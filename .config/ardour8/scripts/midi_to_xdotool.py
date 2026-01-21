#!/usr/bin/env python3
import subprocess
import mido
import sys
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

# Configuration
ARROW_KEY_REPEAT_COUNT = 1
ARROW_RIGHT_SINGLE_PRESS = 1
ARROW_RIGHT_REPEAT_COUNT = 3
MOUSE_SCROLL_REPEAT_COUNT = 1
MOUSE_SCROLL_UP_BUTTON = '4'
MOUSE_SCROLL_DOWN_BUTTON = '5'
REPEAT_DELAY = 0.3  # Initial delay before key repeat starts (seconds)
REPEAT_INTERVAL = 0.01  # Time between repeated keypresses (seconds)
ARDOUR_WINDOW_NAME = 'Ardour'  # Match text that appears in the main window title
MIDI_CHANNEL = 9

# NOTE_* values refer to padKONTROL pad note numbers (control-surface IDs)
NOTE_ZOOM_IN = 49
NOTE_ZOOM_OUT = 51
NOTE_ARROW_LEFT = 68
NOTE_ARROW_RIGHT = 56
NOTE_SCROLL_DOWN = 63
NOTE_SCROLL_UP = 55
NOTE_HOME = 48
NOTE_SPACE = 52

TOUCHPAD_CONTROLLER = 1  # CC controlling vertical movement
TOUCHPAD_X_SENSITIVITY = 0.05  # Pixels per pitch-bend delta unit
TOUCHPAD_Y_SENSITIVITY = 4  # Pixels per CC delta unit
DEBUG_NOTES = False  # Set True to print note_on/off diagnostics

@dataclass(frozen=True)
class Action:
    """Describes how a MIDI note should control Ardour."""
    kind: str  # 'key' or 'mouse'
    value: str  # key name or mouse button id
    immediate_count: int = 1  # how many events to send on press
    hold_repeat_count: Optional[int] = None  # events per repeat cycle when held


NOTE_ACTIONS: Dict[int, Action] = {
    NOTE_ZOOM_IN: Action(kind='key', value='minus'),
    NOTE_ZOOM_OUT: Action(kind='key', value='Escape'),
    NOTE_ARROW_LEFT: Action(
        kind='key',
        value='Left',
        immediate_count=ARROW_KEY_REPEAT_COUNT,
        hold_repeat_count=ARROW_KEY_REPEAT_COUNT,
    ),
    NOTE_ARROW_RIGHT: Action(
        kind='key',
        value='Right',
        immediate_count=ARROW_RIGHT_SINGLE_PRESS,
        hold_repeat_count=ARROW_RIGHT_REPEAT_COUNT,
    ),
    NOTE_SCROLL_DOWN: Action(
        kind='mouse',
        value=MOUSE_SCROLL_DOWN_BUTTON,
        hold_repeat_count=MOUSE_SCROLL_REPEAT_COUNT,
    ),
    NOTE_SCROLL_UP: Action(
        kind='mouse',
        value=MOUSE_SCROLL_UP_BUTTON,
        hold_repeat_count=MOUSE_SCROLL_REPEAT_COUNT,
    ),
    NOTE_HOME: Action(kind='key', value='Home'),
    NOTE_SPACE: Action(kind='key', value='space'),
}

# Auto-find padKONTROL CTRL port
port_name = None
for port in mido.get_input_names():
    if 'padKONTROL' in port and 'CTRL' in port:
        port_name = port
        break

if not port_name:
    print("Error: padKONTROL CTRL port not found!", file=sys.stderr)
    sys.exit(1)

print(f"Listening on {port_name}", file=sys.stderr)

# Track held notes that should trigger repeats; value is the stop event for that note
@dataclass
class RepeaterHandle:
    stop_event: threading.Event
    thread: threading.Thread


held_repeaters: Dict[int, RepeaterHandle] = {}
repeat_lock = threading.Lock()
ardour_window: Optional[str] = None
last_touchpad_cc: Optional[int] = None
last_touchpad_pitch: Optional[int] = None
active_notes: Dict[int, float] = {}

def debug(msg: str) -> None:
    if DEBUG_NOTES:
        print(msg, file=sys.stderr)

def get_ardour_window(force_refresh: bool = False) -> Optional[str]:
    """Find and cache the Ardour main window ID."""
    global ardour_window

    if force_refresh:
        ardour_window = None

    if ardour_window:
        return ardour_window

    try:
        output = subprocess.check_output(
            ['xdotool', 'search', '--onlyvisible', '--name', ARDOUR_WINDOW_NAME],
            stderr=subprocess.DEVNULL,
        )
        ardour_window = output.splitlines()[0].decode().strip()
    except (subprocess.CalledProcessError, IndexError):
        ardour_window = None
    return ardour_window

def _run_with_window(cmd_builder):
    """Run an xdotool command tied to the Ardour window, retrying once if needed."""
    window = get_ardour_window()
    if not window:
        print("Error: Ardour window not found; cannot send events.", file=sys.stderr)
        return False

    for refresh in (False, True):
        cmd = cmd_builder(window)
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if result.returncode == 0:
            return True

        if refresh:
            break
        window = get_ardour_window(force_refresh=True)
        if not window:
            break

    print("Error: Failed to deliver events to Ardour window.", file=sys.stderr)
    return False

def send_key(key: str, count: int = 1) -> None:
    """Send key events directly to the Ardour window."""
    _run_with_window(
        lambda window: [
            'xdotool',
            'key',
            '--window',
            window,
            '--clearmodifiers',
            '--repeat',
            str(count),
            key,
        ]
    )

def click_mouse(button: str, count: int = 1) -> None:
    """Trigger mouse clicks (used for wheel emulation)."""
    _run_with_window(
        lambda window: [
            'xdotool',
            'click',
            '--window',
            window,
            '--repeat',
            str(count),
            button,
        ]
    )

def move_mouse(dx: int = 0, dy: int = 0) -> None:
    """Move mouse relative to current pointer position."""
    if dx == 0 and dy == 0:
        return
    subprocess.run(
        ['xdotool', 'mousemove_relative', '--', str(dx), str(dy)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

def send_action(action: Action, count: Optional[int] = None) -> None:
    """Dispatch the configured action."""
    repetitions = count or action.immediate_count
    if action.kind == 'key':
        send_key(action.value, repetitions)
    elif action.kind == 'mouse':
        click_mouse(action.value, repetitions)
    else:
        print(f"Warning: Unsupported action kind '{action.kind}' for value '{action.value}'", file=sys.stderr)

def start_repeat(note: int, action: Action) -> None:
    """Spawn a repeating sender for the provided note/action."""
    if not action.hold_repeat_count:
        return

    with repeat_lock:
        existing = held_repeaters.get(note)
        if existing and existing.thread.is_alive():
            return

        stop_event = threading.Event()

        def repeater():
            time.sleep(REPEAT_DELAY)
            while not stop_event.is_set():
                send_action(action, action.hold_repeat_count)
                time.sleep(REPEAT_INTERVAL)

        thread = threading.Thread(target=repeater, daemon=True)
        held_repeaters[note] = RepeaterHandle(stop_event=stop_event, thread=thread)
        thread.start()

def stop_repeat(note: int) -> None:
    with repeat_lock:
        handle = held_repeaters.pop(note, None)
    if handle:
        handle.stop_event.set()
    else:
        debug(f"[repeat] stop requested for note {note} but no repeater active")

def handle_touchpad_vertical(value: int) -> None:
    global last_touchpad_cc
    if last_touchpad_cc is None:
        last_touchpad_cc = value
        return
    delta = value - last_touchpad_cc
    last_touchpad_cc = value
    if delta == 0:
        return
    move_mouse(dy=int(delta * TOUCHPAD_Y_SENSITIVITY))

def handle_touchpad_horizontal(pitch_value: int) -> None:
    global last_touchpad_pitch
    if last_touchpad_pitch is None:
        last_touchpad_pitch = pitch_value
        return
    delta = pitch_value - last_touchpad_pitch
    last_touchpad_pitch = pitch_value
    if delta == 0:
        return
    move_mouse(dx=int(delta * TOUCHPAD_X_SENSITIVITY))

def handle_note_on(note: int) -> None:
    active_notes[note] = time.monotonic()
    debug(f"[note] on  {note}")
    action = NOTE_ACTIONS.get(note)
    if not action:
        print(f"Info: Unmapped note_on received for note {note}", file=sys.stderr)
        return
    send_action(action)
    start_repeat(note, action)

def handle_note_off(note: int) -> None:
    removed = active_notes.pop(note, None)
    if removed is None:
        debug(f"[note] off {note} (no matching active note)")
    else:
        debug(f"[note] off {note}")
    stop_repeat(note)

with mido.open_input(port_name) as inport:
    for msg in inport:
        if msg.channel != MIDI_CHANNEL:
            continue

        if msg.type == 'note_on':
            if msg.velocity == 0:
                handle_note_off(msg.note)
            else:
                handle_note_on(msg.note)
        elif msg.type == 'note_off':
            handle_note_off(msg.note)
        elif msg.type == 'control_change' and msg.control == TOUCHPAD_CONTROLLER:
            handle_touchpad_vertical(msg.value)
        elif msg.type == 'pitchwheel':
            handle_touchpad_horizontal(msg.pitch)
        else:
            print(f"Info: Unsupported MIDI message type '{msg.type}' on channel {msg.channel}", file=sys.stderr)

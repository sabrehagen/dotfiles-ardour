#!/usr/bin/env python3
import subprocess
import mido
import sys
import threading
import time

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

# Track held keys and their repeat threads
held_keys = {}
repeat_lock = threading.Lock()
ardour_window = None

def get_ardour_window():
    """Find and cache the Ardour main window ID."""
    global ardour_window

    if ardour_window:
        return ardour_window

    try:
        output = subprocess.check_output(
            ['xdotool', 'search', '--onlyvisible', '--name', ARDOUR_WINDOW_NAME],
            stderr=subprocess.DEVNULL
        )
        # Take the first line returned (top-most matching window)
        ardour_window = output.splitlines()[0].decode().strip()
    except (subprocess.CalledProcessError, IndexError):
        ardour_window = None
    return ardour_window

def press_key(key, count=1):
    """Fast key press using xdotool with repeat"""
    window = get_ardour_window()
    if not window:
        print("Error: Ardour window not found; cannot send key events.", file=sys.stderr)
        return

    subprocess.Popen(['xdotool', 'key', '--window', window, '--clearmodifiers', '--repeat', str(count), key],
                     stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)

def click_mouse(button, count=1):
    """Trigger mouse clicks (used for wheel emulation)"""
    window = get_ardour_window()
    if not window:
        print("Error: Ardour window not found; cannot send mouse events.", file=sys.stderr)
        return

    subprocess.Popen(['xdotool', 'click', '--window', window, '--repeat', str(count), button],
                     stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)

def repeat_key(key, note, repeat_count):
    """Repeat a key while it's held down"""
    time.sleep(REPEAT_DELAY)
    with repeat_lock:
        if note not in held_keys:
            return  # Key was released before repeat started

    while True:
        with repeat_lock:
            if note not in held_keys:
                break
        press_key(key, repeat_count)
        time.sleep(REPEAT_INTERVAL)

def repeat_click(button, note, repeat_count):
    """Repeat a mouse click while the button is held"""
    time.sleep(REPEAT_DELAY)
    with repeat_lock:
        if note not in held_keys:
            return

    while True:
        with repeat_lock:
            if note not in held_keys:
                break
        click_mouse(button, repeat_count)
        time.sleep(REPEAT_INTERVAL)

with mido.open_input(port_name) as inport:
    for msg in inport:
        if msg.channel == MIDI_CHANNEL:
            if msg.type == 'note_on':
                if msg.note == NOTE_ZOOM_IN:
                    press_key('minus')
                elif msg.note == NOTE_ZOOM_OUT:
                    press_key('Escape')
                elif msg.note == NOTE_ARROW_LEFT:
                    press_key('Left', ARROW_KEY_REPEAT_COUNT)
                    if msg.note not in held_keys:
                        thread = threading.Thread(
                            target=repeat_key,
                            args=('Left', msg.note, ARROW_KEY_REPEAT_COUNT),
                            daemon=True
                        )
                        held_keys[msg.note] = thread
                        thread.start()
                elif msg.note == NOTE_ARROW_RIGHT:
                    press_key('Right', ARROW_RIGHT_SINGLE_PRESS)
                    if msg.note not in held_keys:
                        thread = threading.Thread(
                            target=repeat_key,
                            args=('Right', msg.note, ARROW_RIGHT_REPEAT_COUNT),
                            daemon=True
                        )
                        held_keys[msg.note] = thread
                        thread.start()
                elif msg.note == NOTE_SCROLL_DOWN:
                    click_mouse(MOUSE_SCROLL_DOWN_BUTTON)
                    if msg.note not in held_keys:
                        thread = threading.Thread(
                            target=repeat_click,
                            args=(MOUSE_SCROLL_DOWN_BUTTON, msg.note, MOUSE_SCROLL_REPEAT_COUNT),
                            daemon=True
                        )
                        held_keys[msg.note] = thread
                        thread.start()
                elif msg.note == NOTE_SCROLL_UP:
                    click_mouse(MOUSE_SCROLL_UP_BUTTON)
                    if msg.note not in held_keys:
                        thread = threading.Thread(
                            target=repeat_click,
                            args=(MOUSE_SCROLL_UP_BUTTON, msg.note, MOUSE_SCROLL_REPEAT_COUNT),
                            daemon=True
                        )
                        held_keys[msg.note] = thread
                        thread.start()
                elif msg.note == NOTE_HOME:
                    press_key('Home')
                elif msg.note == NOTE_SPACE:
                    press_key('space')
            elif msg.type == 'note_off':
                # Stop repeating when button is released
                with repeat_lock:
                    if msg.note in held_keys:
                        del held_keys[msg.note]

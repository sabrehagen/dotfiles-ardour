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
REPEAT_DELAY = 0.3  # Initial delay before key repeat starts (seconds)
REPEAT_INTERVAL = 0.01  # Time between repeated keypresses (seconds)

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

def press_key(key, count=1):
    """Fast key press using xdotool with repeat"""
    subprocess.Popen(['xdotool', 'key', '--clearmodifiers', '--repeat', str(count), key], 
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

with mido.open_input(port_name) as inport:
    for msg in inport:
        if msg.channel == 9:
            if msg.type == 'note_on':
                if msg.note == 49:  # zoom in
                    press_key('minus')
                elif msg.note == 51:  # zoom out
                    press_key('Escape')
                elif msg.note == 68:  # arrow left
                    press_key('Left', ARROW_KEY_REPEAT_COUNT)
                    if msg.note not in held_keys:
                        thread = threading.Thread(target=repeat_key, args=('Left', msg.note, ARROW_KEY_REPEAT_COUNT), daemon=True)
                        held_keys[msg.note] = thread
                        thread.start()
                elif msg.note == 56:  # arrow right
                    press_key('Right', ARROW_RIGHT_SINGLE_PRESS)
                    if msg.note not in held_keys:
                        thread = threading.Thread(target=repeat_key, args=('Right', msg.note, ARROW_RIGHT_REPEAT_COUNT), daemon=True)
                        held_keys[msg.note] = thread
                        thread.start()
            elif msg.type == 'note_off':
                # Stop repeating when button is released
                with repeat_lock:
                    if msg.note in held_keys:
                        del held_keys[msg.note]

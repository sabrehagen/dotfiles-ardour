#!/usr/bin/env python3
import subprocess
import mido
import sys

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

with mido.open_input(port_name) as inport:
    for msg in inport:
        if msg.type == 'note_on' and msg.channel == 9:
            if msg.note == 51:  # zoom in
                subprocess.run(['xdotool', 'key', 'Escape'])
            elif msg.note == 49:  # zoom out
                subprocess.run(['xdotool', 'key', 'minus'])

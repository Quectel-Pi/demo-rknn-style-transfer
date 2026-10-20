#!/bin/bash
set -euo pipefail

printf '[stop] stopping demo...\n'
PID_FILE=/tmp/m2_demo_youhua.pid
if [ -f "$PID_FILE" ]; then
    PID="$(cat "$PID_FILE")"
    kill "$PID" 2>/dev/null || true
    rm -f "$PID_FILE"
fi
pkill -f '[o]il_painting_cam.py' 2>/dev/null || true
pkill -f '[g]st-launch.*video33' 2>/dev/null || true
sleep 1

if pgrep -f '[o]il_painting_cam.py' >/dev/null; then
    printf '[warn] demo process still running, sending SIGKILL\n'
    pkill -9 -f '[o]il_painting_cam.py' 2>/dev/null || true
else
    printf '[stop] stopped\n'
fi

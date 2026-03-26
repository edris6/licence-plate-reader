#!/bin/bash

cd "$(dirname "$0")"

# Kill gvfs so gphoto2 can claim Nikon if needed
sudo killall gvfs-gphoto2-volume-monitor gvfsd-gphoto2 gvfsd 2>/dev/null
sleep 0.5

IP_ADDR=$(hostname -I | awk '{print $1}')

PYTHON_BIN="python3"

if [ -f "venv/bin/python" ]; then
    if venv/bin/python -c "import flask, cv2, pytesseract" >/dev/null 2>&1; then
        if venv/bin/python -c "from picamera2 import Picamera2" >/dev/null 2>&1; then
            PYTHON_BIN="venv/bin/python"
            echo "Using venv Python (picamera2 available)"
        else
            PYTHON_BIN="python3"
            echo "venv found, but picamera2 is missing there"
            echo "Falling back to system python3 for Pi camera support"
        fi
    else
        PYTHON_BIN="python3"
        echo "venv found, but required Python packages are missing there"
        echo "Falling back to system python3"
    fi
fi

echo "Starting ALPR..."
echo "Dashboard  → http://${IP_ADDR}:5000"
echo "Camera     → http://${IP_ADDR}:5000/camera"
echo "Press Ctrl+C to stop."
echo

"$PYTHON_BIN" plate_detector.py "$@"

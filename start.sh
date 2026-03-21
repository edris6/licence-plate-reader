#!/bin/bash

# ALPR - Start licence plate reader + web server
cd "$(dirname "$0")"

# Kill gvfs so gphoto2 can claim the Nikon
sudo killall gvfs-gphoto2-volume-monitor gvfsd-gphoto2 gvfsd 2>/dev/null
sleep 0.5

source venv/bin/activate

echo "Starting ALPR..."
echo "Dashboard  → http://$(hostname -I | awk '{print $1}'):5000"
echo "Camera     → http://$(hostname -I | awk '{print $1}'):5000/camera"
echo "Press Ctrl+C to stop."
echo ""

venv/bin/python plate_detector.py
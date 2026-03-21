#!/bin/bash

# ALPR - Start the licence plate reader + web server
cd "$(dirname "$0")"

source venv/bin/activate

echo "Starting ALPR..."
echo "Dashboard  → http://$(hostname -I | awk '{print $1}'):5000"
echo "Camera     → http://$(hostname -I | awk '{print $1}'):5000/camera"
echo "Press Ctrl+C to stop."
echo ""

python plate_detector.py
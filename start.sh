#!/bin/bash

# ALPR - Run both plate detector and web server
cd "$(dirname "$0")"

# Activate virtual environment
source venv/bin/activate

echo "Starting ALPR..."
echo "Dashboard will be available at http://$(hostname -I | awk '{print $1}'):5000"
echo "Press Ctrl+C to stop both."
echo ""

# Run both scripts, kill both if either exits
trap 'kill 0' EXIT

python plate_detector.py &
python server.py &

wait
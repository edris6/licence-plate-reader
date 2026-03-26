# 🚘 ALPR — Automatic Licence Plate Recognition System

A real-time Automatic Licence Plate Recognition (ALPR) system designed for Raspberry Pi and Linux environments.

This project captures frames from multiple camera types, detects licence plates, performs OCR, tracks vehicle presence, and exposes a live dashboard with persistent logging.

---

# 📌 Features

* Real-time licence plate detection
* OCR via Tesseract
* Multi-camera support:

  * 📷 Raspberry Pi Camera (Picamera2 / libcamera)
  * 🎥 USB webcam (OpenCV / V4L2)
  * 📸 Nikon DSLR (gphoto2)
* Automatic camera selection (default priority)
* Manual camera selection (`-select`)
* Live MJPEG video stream
* Web dashboard
* SQLite database logging
* JSON log output
* Image capture:

  * full annotated frame
  * cropped plate region
* Vehicle tracking:

  * new arrivals
  * parked vehicles
  * departures

---

# 🧠 System Architecture

```text
Camera → Frame Capture → Preprocessing → Edge Detection
       → Contours → Plate Extraction → OCR → Validation
       → Tracking → Storage → Web Dashboard
```

---

# 🔬 Detection Pipeline

## 1. Frame Capture

Frames are captured depending on selected backend:

* Pi Camera → Picamera2
* USB Camera → OpenCV (`cv2.VideoCapture`)
* Nikon → gphoto2 still capture

---

## 2. Preprocessing

* Convert to grayscale
* Bilateral filtering (noise reduction)

---

## 3. Edge Detection

* Canny edge detection

---

## 4. Contour Detection

* Find largest contours
* Approximate polygons

---

## 5. Plate Filtering

Candidate regions must:

* Have 4 sides
* Aspect ratio between 2:1 and 6:1
* Minimum width threshold

---

## 6. OCR (Text Recognition)

Using Tesseract:

* Whitelist: A–Z, 0–9
* PSM mode: 7 (single text line)
* Confidence estimation from OCR data

---

## 7. Validation

Regex filter:

```python
[A-Z0-9]{2,8}
```

---

## 8. Tracking Logic

Each plate has a state:

| State  | Meaning            |
| ------ | ------------------ |
| NEW    | First time seen    |
| PARKED | Still visible      |
| LEFT   | No longer detected |

Prevents duplicate logging spam.

---

## 9. Persistence

Each detection is saved to:

* SQLite database
* JSON log
* Image files

---

# 📁 Project Structure

```text
plate_detector.py      # Main application (camera + OCR + server)
start.sh               # Startup script (auto-selects Python + camera)
requirements.txt       # Python dependencies

alpr_dashboard.html    # Dashboard UI
camera.html            # Camera view

plates.db              # SQLite DB (auto-created)
plates_log.json        # JSON log (auto-created)
plate_images/          # Saved images
```

---

# 🎥 Camera System

## Supported Camera Types

### 1. Raspberry Pi Camera (Recommended)

* Uses **Picamera2 (libcamera stack)**
* Required for Pi Camera v2 / v3
* Best performance on Raspberry Pi

Test camera:

```bash
rpicam-hello
```

---

### 2. USB Camera

Uses OpenCV:

```python
cv2.VideoCapture(0)
```

Check device:

```bash
ls /dev/video*
```

---

### 3. Nikon DSLR

* Uses `gphoto2`
* Captures full-resolution still frames

Detect camera:

```bash
gphoto2 --auto-detect
```

---

# ⚙️ Installation

## 1. System Dependencies

```bash
sudo apt update
sudo apt install -y \
    tesseract-ocr \
    gphoto2 \
    python3-picamera2
```

---

## 2. Python Dependencies

```bash
pip install -r requirements.txt
```

### requirements.txt

```txt
opencv-python-headless
pytesseract
flask
```

---

# ▶️ Running the System

## Default Mode (Auto Select)

```bash
./start.sh
```

Camera priority:

1. Pi camera
2. USB camera
3. Nikon camera

---

## Manual Selection Mode

```bash
./start.sh -select
```

Prompt:

```
1 → Nikon
2 → USB camera
3 → Pi camera
```

---

## Direct Python

```bash
python plate_detector.py
python plate_detector.py -select
```

---

# ⚠️ IMPORTANT — Raspberry Pi Camera + Virtual Environments

This is the **most common issue on Raspberry Pi**.

Picamera2 is installed via:

```bash
sudo apt install python3-picamera2
```

This installs it **system-wide**, not inside your virtual environment.

### Symptom

```bash
python3 works
venv/bin/python fails with:
ModuleNotFoundError: No module named 'picamera2'
```

### Why

Your venv cannot see system-installed packages.

---

## ✅ Solutions

### Option 1 (Recommended)

Let `start.sh` automatically fall back to system Python.

---

### Option 2

Recreate venv with system packages:

```bash
rm -rf venv
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r requirements.txt
```

---

### Option 3

Run without venv:

```bash
python3 plate_detector.py
```

---

# 🌐 Web Interface

Once running, access:

| Feature   | URL                                 |
| --------- | ----------------------------------- |
| Dashboard | http://<pi-ip>:5000                 |
| Camera    | http://<pi-ip>:5000/camera          |
| Live Feed | http://<pi-ip>:5000/video_feed      |
| JSON Log  | http://<pi-ip>:5000/plates_log.json |

---

# 🗄️ Data Storage

## SQLite Database

File: `plates.db`

```sql
CREATE TABLE plates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plate TEXT,
    timestamp TEXT,
    confidence REAL,
    image_path TEXT,
    event TEXT
);
```

---

## JSON Log

File: `plates_log.json`

```json
{
  "plate": "AB12CDE",
  "timestamp": "2026-03-26T12:00:00",
  "confidence": 0.87,
  "image_full": "plate_images/...",
  "image_crop": "plate_images/...",
  "event": "arrival"
}
```

---

## Image Output

Directory:

```text
plate_images/
```

Each detection saves:

* annotated full frame
* cropped zoomed plate

---

# 🔧 Configuration

Inside `plate_detector.py`:

```python
FRAME_SKIP = 3
PLATE_REGEX = r"[A-Z0-9]{2,8}"
FLASK_PORT = 5000
```

---

# ⚡ Performance Notes

| Camera Type | Speed  | Notes              |
| ----------- | ------ | ------------------ |
| Pi Camera   | Fast   | Best option        |
| USB Camera  | Medium | Stable             |
| Nikon       | Slow   | High quality, slow |

---

# 🧪 Troubleshooting

## ❌ No camera detected

Run:

```bash
./start.sh -select
```

and test manually.

---

## Pi camera works in `rpicam-hello` but not in script

```bash
python3 -c "from picamera2 import Picamera2; print(Picamera2.global_camera_info())"
```

If that works → issue is your Python environment (see section above).

---

## USB camera not detected

```bash
ls /dev/video*
```

---

## Nikon not detected

```bash
gphoto2 --auto-detect
```

If busy:

```bash
sudo killall gvfs-gphoto2-volume-monitor gvfsd-gphoto2 gvfsd
```

---

## OCR inaccurate

* Improve lighting
* Increase contrast
* Ensure plate fills frame
* Avoid motion blur

---

# 🛑 Stopping

Press:

```bash
Ctrl+C
```

---

# 📊 Example Queries

## Most frequent plates

```sql
SELECT plate, COUNT(*) as freq
FROM plates
GROUP BY plate
ORDER BY freq DESC;
```

---

## Latest detections

```sql
SELECT * FROM plates
ORDER BY timestamp DESC
LIMIT 10;
```

---

# 🧩 Future Improvements

* YOLO-based plate detection
* GPU acceleration
* Multi-camera simultaneous support
* REST API
* Cloud sync
* Country-specific plate formats

---

# 📄 License

MIT License

---

# 👤 Author

Original project:
https://github.com/edris6/licence-plate-reader

Extended with:

* Multi-camera support
* Pi camera (Picamera2 integration)
* Improved runtime handling
* Web streaming improvements

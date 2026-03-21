# 🚗 ALPR — Automatic Licence Plate Recognition

## Project Structure
```
plate_detector.py     ← Main script (run this)
alpr_dashboard.html   ← Visual dashboard (open in browser)
plates.db             ← SQLite database (auto-created)
plates_log.json       ← JSON log (auto-created)
```

---

## ⚙️ Installation

```bash
pip install opencv-python easyocr
```

> **Note:** First run downloads the EasyOCR English model (~100MB). This is normal.

---

## ▶️ Run

```bash
python plate_detector.py
```

- A window will open showing your webcam feed
- Detected plates are highlighted in green
- Press **Q** to quit

---

## 📊 View Dashboard

1. Open `alpr_dashboard.html` in any browser
2. Click the upload area and select your `plates_log.json`
3. See live stats, recent detections, and top plates

---

## 🔧 Configuration (top of plate_detector.py)

| Variable | Default | Description |
|---|---|---|
| `FRAME_SKIP` | `5` | Process every Nth frame (lower = slower but more accurate) |
| `MIN_CONF` | `0.4` | Minimum OCR confidence to accept (0.0–1.0) |
| `PLATE_REGEX` | `[A-Z0-9]{2,8}` | Regex to validate plate format |
| `DEDUP_SECONDS` | `10` | Ignore same plate within N seconds |

### 🇵🇹 Portuguese plate format
Plates follow `AA-00-AA` format. You can tighten the regex:
```python
PLATE_REGEX = r"[A-Z]{2}\d{2}[A-Z]{2}|[A-Z]{2}\d{4}|\d{2}\d{2}[A-Z]{2}"
```

---

## 💾 Data

**SQLite** (`plates.db`) — query with any DB viewer:
```sql
SELECT plate, COUNT(*) as freq FROM plates GROUP BY plate ORDER BY freq DESC;
```

**JSON** (`plates_log.json`) — load into the dashboard or any tool.

---

## 🚀 Next Steps
- Add email/SMS alert for specific plates
- Mount a Pi camera for 24/7 outdoor use
- Add a Flask web server to view dashboard remotely

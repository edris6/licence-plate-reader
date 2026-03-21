"""
ALPR - Automatic Licence Plate Recognition
Webcam source | Saves to SQLite + JSON + Images | Displays live feed
Parked car logic: logs each plate once; re-logs only after it disappears
Flask web server included — serves dashboard + live MJPEG stream over WiFi
"""

import cv2
import easyocr
import sqlite3
import json
import re
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, send_from_directory, Response

# ── Config ────────────────────────────────────────────────────────────────────

DB_PATH     = "plates.db"
LOG_PATH    = "plates_log.json"
IMAGES_DIR  = Path("plate_images")
FRAME_SKIP  = 5       # process every Nth frame
MIN_CONF    = 0.4     # minimum OCR confidence
PLATE_REGEX = r"[A-Z0-9]{2,8}"
FLASK_PORT  = 5000

BASE_DIR = str(Path(__file__).parent)

# ── Shared frame (camera → Flask) ────────────────────────────────────────────

_frame_lock   = threading.Lock()
_latest_frame = None   # raw BGR frame, updated every capture loop

def set_latest_frame(frame):
    global _latest_frame
    with _frame_lock:
        _latest_frame = frame.copy()

def get_latest_frame():
    with _frame_lock:
        return _latest_frame.copy() if _latest_frame is not None else None

# ── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(__name__)

@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "alpr_dashboard.html")

@app.route("/plates_log.json")
def plates_log():
    path = Path(LOG_PATH)
    if not path.exists():
        return jsonify([])
    with open(path, encoding="utf-8") as f:
        try:
            return jsonify(json.load(f))
        except json.JSONDecodeError:
            return jsonify([])

def _generate_mjpeg():
    """Yield MJPEG frames from the shared latest frame."""
    while True:
        frame = get_latest_frame()
        if frame is None:
            continue
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + buf.tobytes()
            + b"\r\n"
        )

@app.route("/camera")
def camera():
    return send_from_directory(BASE_DIR, "camera.html")

@app.route("/video_feed")
def video_feed():
    return Response(
        _generate_mjpeg(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

def start_flask():
    """Run Flask in a background daemon thread."""
    app.run(host="0.0.0.0", port=FLASK_PORT, debug=False, use_reloader=False)

# ── Parked car tracker ────────────────────────────────────────────────────────

class ParkedCarTracker:
    def __init__(self):
        self._present_this_frame: set = set()
        self._parked:             set = set()
        self._gone:               set = set()

    def see(self, plate: str) -> bool:
        self._present_this_frame.add(plate)
        if plate in self._gone:
            self._gone.discard(plate)
            self._parked.add(plate)
            return True
        if plate not in self._parked:
            self._parked.add(plate)
            return True
        return False

    def end_frame(self):
        disappeared = self._parked - self._present_this_frame
        for plate in disappeared:
            self._parked.discard(plate)
            self._gone.add(plate)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 👋 {plate} left the street")
        self._present_this_frame.clear()

    def current_parked(self) -> list:
        return sorted(self._parked)

    def count(self) -> int:
        return len(self._parked)

# ── Database ──────────────────────────────────────────────────────────────────

def init_db():
    IMAGES_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS plates (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            plate      TEXT    NOT NULL,
            timestamp  TEXT    NOT NULL,
            confidence REAL,
            image_path TEXT,
            event      TEXT DEFAULT 'arrival'
        )
    """)
    conn.commit()
    return conn

def save_plate(conn, plate, confidence, frame, roi, x, y, w, h):
    ts      = datetime.now().isoformat()
    safe_ts = ts.replace(":", "-").replace(".", "-")

    full_path = IMAGES_DIR / f"{plate}_{safe_ts}_full.jpg"
    crop_path = IMAGES_DIR / f"{plate}_{safe_ts}_crop.jpg"

    annotated = frame.copy()
    cv2.rectangle(annotated, (x, y), (x+w, y+h), (0, 255, 0), 3)
    cv2.putText(annotated, f"{plate} ({confidence:.2f})",
                (x, y - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
    cv2.imwrite(str(full_path), annotated)

    crop_big = cv2.resize(roi, (roi.shape[1]*3, roi.shape[0]*3),
                          interpolation=cv2.INTER_CUBIC)
    cv2.imwrite(str(crop_path), crop_big)

    conn.execute(
        "INSERT INTO plates (plate, timestamp, confidence, image_path) VALUES (?,?,?,?)",
        (plate, ts, confidence, str(full_path))
    )
    conn.commit()

    entry = {
        "plate":      plate,
        "timestamp":  ts,
        "confidence": round(confidence, 3),
        "image_full": str(full_path),
        "image_crop": str(crop_path),
        "event":      "arrival",
    }

    logs = []
    if Path(LOG_PATH).exists():
        with open(LOG_PATH, encoding="utf-8") as f:
            try:
                logs = json.load(f)
            except json.JSONDecodeError:
                logs = []

    logs.append(entry)
    tmp = Path(f"{LOG_PATH}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2)
    tmp.replace(LOG_PATH)

    print(f"[{ts[11:19]}] ✅ NEW ARRIVAL {plate} (conf: {confidence:.2f}) 📸 {full_path.name}")

def get_history(conn, limit=5):
    cur = conn.execute(
        "SELECT plate, timestamp, confidence FROM plates ORDER BY id DESC LIMIT ?",
        (limit,)
    )
    return cur.fetchall()

def get_frequency(conn):
    cur = conn.execute(
        "SELECT plate, COUNT(*) as freq FROM plates GROUP BY plate ORDER BY freq DESC LIMIT 10"
    )
    return cur.fetchall()

# ── Image helpers ─────────────────────────────────────────────────────────────

def preprocess(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.bilateralFilter(gray, 11, 17, 17)

def find_plate_regions(frame):
    proc     = preprocess(frame)
    edges    = cv2.Canny(proc, 30, 200)
    contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:10]

    regions = []
    for c in contours:
        peri  = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.018 * peri, True)
        if len(approx) == 4:
            x, y, w, h = cv2.boundingRect(approx)
            if 2.0 < w / float(h) < 6.0 and w > 60:
                regions.append((x, y, w, h))
    return regions

def is_valid_plate(text: str) -> bool:
    text = text.upper().replace(" ", "")
    return bool(re.match(PLATE_REGEX, text)) and len(text) >= 4

# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    conn    = init_db()
    reader  = easyocr.Reader(["en"], gpu=False)
    cap     = cv2.VideoCapture(0)
    tracker = ParkedCarTracker()

    if not cap.isOpened():
        print("❌ Cannot open webcam.")
        return

    import socket
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        local_ip = "raspberrypi.local"

    # Start Flask in background thread
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    print(f"🚗 ALPR running — press Q to quit")
    print(f"🌐 Dashboard → http://{local_ip}:{FLASK_PORT}")
    print(f"📷 Live feed  → http://{local_ip}:{FLASK_PORT}/video_feed\n")

    frame_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_count += 1
        display = frame.copy()

        if frame_count % FRAME_SKIP == 0:
            regions = find_plate_regions(frame)

            for (x, y, w, h) in regions:
                roi     = frame[y:y+h, x:x+w]
                results = reader.readtext(roi)

                for (_, text, conf) in results:
                    clean = text.upper().replace(" ", "")
                    if conf < MIN_CONF or not is_valid_plate(clean):
                        continue

                    is_new = tracker.see(clean)
                    if is_new:
                        save_plate(conn, clean, conf, frame, roi, x, y, w, h)
                        box_color  = (0, 255, 0)
                        label_text = f"NEW: {clean}"
                    else:
                        box_color  = (200, 200, 0)
                        label_text = f"PARKED: {clean}"

                    cv2.rectangle(display, (x, y), (x+w, y+h), box_color, 2)
                    cv2.putText(display, label_text,
                                (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX,
                                0.65, box_color, 2)

            tracker.end_frame()

        # ── HUD ───────────────────────────────────────────────────────────────
        y_pos = 20
        cv2.putText(display, f"ALPR | parked: {tracker.count()}", (10, y_pos),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)
        y_pos += 25

        for plate, ts, _ in get_history(conn, 5):
            cv2.putText(display, f"{plate} {ts[11:19]}", (10, y_pos),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (180, 180, 180), 1)
            y_pos += 17

        parked_now = tracker.current_parked()
        bottom_y   = display.shape[0] - 10 - len(parked_now) * 17
        for p in parked_now:
            cv2.putText(display, f"● {p}", (10, bottom_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 0), 1)
            bottom_y += 17

        # Push annotated frame to Flask stream
        set_latest_frame(display)

        cv2.imshow("ALPR — Press Q to quit", display)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

    print("\n── Parked cars still present at exit ────")
    for p in tracker.current_parked():
        print(f"  {p}")

    print("\n── Top arrivals ─────────────────────────")
    for plate, freq in get_frequency(conn):
        print(f"  {plate:<12} x{freq} arrival(s)")

    print(f"\n💾 {DB_PATH}  📄 {LOG_PATH}  📸 {IMAGES_DIR}/")
    conn.close()


if __name__ == "__main__":
    main()
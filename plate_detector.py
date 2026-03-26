import argparse
import cv2
import pytesseract
import sqlite3
import json
import re
import threading
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, send_from_directory, Response

try:
    from picamera2 import Picamera2
except Exception:
    Picamera2 = None

DB_PATH = "plates.db"
LOG_PATH = "plates_log.json"
IMAGES_DIR = Path("plate_images")
FRAME_SKIP = 3
PLATE_REGEX = r"[A-Z0-9]{2,8}"
FLASK_PORT = 5000
CAPTURE_PATH = "/tmp/alpr_latest.jpg"
TESS_CONFIG = "--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
BASE_DIR = str(Path(__file__).parent)

_frame_lock = threading.Lock()
_latest_frame = None


def set_latest_frame(frame):
    global _latest_frame
    with _frame_lock:
        _latest_frame = frame.copy()


def get_latest_frame():
    with _frame_lock:
        return _latest_frame.copy() if _latest_frame is not None else None


app = Flask(__name__)


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "alpr_dashboard.html")


@app.route("/camera")
def camera_page():
    return send_from_directory(BASE_DIR, "camera.html")


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


@app.route("/plate_images/<path:filename>")
def plate_image(filename):
    return send_from_directory(str(IMAGES_DIR), filename)


def _generate_mjpeg():
    while True:
        frame = get_latest_frame()
        if frame is None:
            time.sleep(0.05)
            continue

        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
        )


@app.route("/video_feed")
def video_feed():
    return Response(
        _generate_mjpeg(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


def start_flask():
    app.run(host="0.0.0.0", port=FLASK_PORT, debug=False, use_reloader=False)


def detect_nikon():
    try:
        result = subprocess.run(
            ["gphoto2", "--auto-detect"],
            capture_output=True,
            text=True,
            timeout=5
        )
        lines = result.stdout.strip().splitlines()
        for line in lines[2:]:
            if line.strip():
                print(f"Nikon check: detected -> {line.strip()}")
                return True
    except Exception as e:
        print(f"Nikon check failed: {e}")
        return False

    print("Nikon check: not detected")
    return False


def kill_gvfs():
    for proc in ["gvfs-gphoto2-volume-monitor", "gvfsd-gphoto2", "gvfsd"]:
        subprocess.run(
            ["sudo", "killall", proc],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    time.sleep(0.5)


def capture_nikon():
    subprocess.run(
        ["gphoto2", "--set-config", "autofocusdrive=1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(0.55)

    subprocess.run(
        [
            "gphoto2",
            "--capture-image-and-download",
            "--filename", CAPTURE_PATH,
            "--force-overwrite",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    if Path(CAPTURE_PATH).exists():
        return cv2.imread(CAPTURE_PATH)
    return None


def detect_pi_camera():
    if Picamera2 is None:
        print("Pi camera check: picamera2 import failed")
        return False

    try:
        info = Picamera2.global_camera_info()
        print(f"Pi camera check: {info}")
        return bool(info)
    except Exception as e:
        print(f"Pi camera check failed: {e}")
        return False


def build_pi_camera():
    if Picamera2 is None:
        raise RuntimeError("Picamera2 is not installed.")

    picam2 = Picamera2()
    config = picam2.create_preview_configuration(
        main={"size": (1280, 720), "format": "RGB888"}
    )
    picam2.configure(config)
    picam2.start()
    time.sleep(1.0)
    return picam2


def detect_usb_camera(index=0):
    cap = cv2.VideoCapture(index)
    ok = cap.isOpened()
    if ok:
        ret, _ = cap.read()
        ok = bool(ret)
    cap.release()
    print(f"USB camera check (/dev/video{index}): {ok}")
    return ok


def build_usb_camera(index=0):
    cap = cv2.VideoCapture(index)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    cap.set(cv2.CAP_PROP_FPS, 30)

    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"Cannot open USB camera at index {index}.")

    return cap


def auto_select_camera():
    pi_ok = detect_pi_camera()
    usb_ok = detect_usb_camera(0)
    nikon_ok = detect_nikon()

    print(f"Auto-detect results -> pi={pi_ok}, usb={usb_ok}, nikon={nikon_ok}")

    if pi_ok:
        return "pi"
    if usb_ok:
        return "usb"
    if nikon_ok:
        return "nikon"
    return None


def prompt_camera_selection():
    print("\nSelect camera source:")
    print("  1) Nikon (gphoto2)")
    print("  2) USB camera (/dev/video0)")
    print("  3) Pi camera (Picamera2)")

    while True:
        choice = input("Enter 1, 2 or 3: ").strip()
        if choice == "1":
            return "nikon"
        if choice == "2":
            return "usb"
        if choice == "3":
            return "pi"
        print("Invalid choice. Please enter 1, 2 or 3.")


def parse_args():
    parser = argparse.ArgumentParser(description="ALPR camera runner")
    parser.add_argument(
        "-select",
        "--select",
        action="store_true",
        help="Prompt to select camera source instead of auto-selecting Pi -> USB -> Nikon."
    )
    return parser.parse_args()


def choose_camera_source(force_select=False):
    if force_select:
        return prompt_camera_selection()

    selected = auto_select_camera()
    if selected == "pi":
        print("✅ Auto-selected Pi camera")
    elif selected == "usb":
        print("✅ Auto-selected USB camera")
    elif selected == "nikon":
        print("✅ Auto-selected Nikon camera")
    else:
        print("❌ No camera source detected")

    return selected


def open_camera(source):
    if source == "pi":
        if not detect_pi_camera():
            raise RuntimeError("Pi camera not detected or Picamera2 unavailable.")
        picam2 = build_pi_camera()
        return {"source": "pi", "pi": picam2, "cap": None}

    if source == "usb":
        if not detect_usb_camera(0):
            raise RuntimeError("USB camera not detected on index 0.")
        cap = build_usb_camera(0)
        return {"source": "usb", "pi": None, "cap": cap}

    if source == "nikon":
        kill_gvfs()
        if not detect_nikon():
            raise RuntimeError("No Nikon/gphoto2 camera detected.")
        return {"source": "nikon", "pi": None, "cap": None}

    raise RuntimeError(f"Unsupported camera source: {source}")


def read_frame(camera_ctx):
    source = camera_ctx["source"]

    if source == "pi":
        frame = camera_ctx["pi"].capture_array()
        return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    if source == "usb":
        ret, frame = camera_ctx["cap"].read()
        if not ret:
            return None
        return frame

    if source == "nikon":
        return capture_nikon()

    return None


def close_camera(camera_ctx):
    if not camera_ctx:
        return

    try:
        if camera_ctx.get("cap") is not None:
            camera_ctx["cap"].release()
    except Exception:
        pass

    try:
        if camera_ctx.get("pi") is not None:
            camera_ctx["pi"].stop()
    except Exception:
        pass


class ParkedCarTracker:
    def __init__(self):
        self._present_this_frame = set()
        self._parked = set()
        self._gone = set()

    def see(self, plate):
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
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {plate} left the street")

        self._present_this_frame.clear()

    def current_parked(self):
        return sorted(self._parked)

    def count(self):
        return len(self._parked)


def init_db():
    IMAGES_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS plates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            confidence REAL,
            image_path TEXT,
            event TEXT DEFAULT 'arrival'
        )
        """
    )
    conn.commit()
    return conn


def save_plate(conn, plate, confidence, frame, roi, x, y, w, h):
    ts = datetime.now().isoformat()
    safe_ts = ts.replace(":", "-").replace(".", "-")
    full_path = IMAGES_DIR / f"{plate}_{safe_ts}_full.jpg"
    crop_path = IMAGES_DIR / f"{plate}_{safe_ts}_crop.jpg"

    annotated = frame.copy()
    cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 255, 0), 3)
    cv2.putText(
        annotated,
        f"{plate} ({confidence:.2f})",
        (x, y - 12),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (0, 255, 0),
        2,
    )
    cv2.imwrite(str(full_path), annotated)

    crop_big = cv2.resize(
        roi,
        (roi.shape[1] * 3, roi.shape[0] * 3),
        interpolation=cv2.INTER_CUBIC
    )
    cv2.imwrite(str(crop_path), crop_big)

    conn.execute(
        "INSERT INTO plates (plate, timestamp, confidence, image_path) VALUES (?,?,?,?)",
        (plate, ts, confidence, str(full_path)),
    )
    conn.commit()

    entry = {
        "plate": plate,
        "timestamp": ts,
        "confidence": round(confidence, 3),
        "image_full": str(full_path),
        "image_crop": str(crop_path),
        "event": "arrival",
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

    print(f"[{ts[11:19]}] ✅ NEW ARRIVAL {plate} (conf: {confidence:.2f}) {full_path.name}")


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


def preprocess(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.bilateralFilter(gray, 11, 17, 17)


def find_plate_regions(frame):
    proc = preprocess(frame)
    edges = cv2.Canny(proc, 30, 200)
    contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:10]
    regions = []

    for c in contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.018 * peri, True)
        if len(approx) == 4:
            x, y, w, h = cv2.boundingRect(approx)
            if 2.0 < w / float(h) < 6.0 and w > 60:
                regions.append((x, y, w, h))

    return regions


def is_valid_plate(text):
    text = text.upper().replace(" ", "")
    return bool(re.match(PLATE_REGEX, text)) and len(text) >= 4


def ocr_plate(roi):
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(
        gray,
        (gray.shape[1] * 3, gray.shape[0] * 3),
        interpolation=cv2.INTER_CUBIC
    )
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    text = pytesseract.image_to_string(thresh, config=TESS_CONFIG).strip()

    try:
        data = pytesseract.image_to_data(
            thresh,
            config=TESS_CONFIG,
            output_type=pytesseract.Output.DICT
        )
        confs = [
            int(c) for c in data["conf"]
            if str(c).lstrip("-").isdigit() and int(c) >= 0
        ]
        conf = (sum(confs) / len(confs) / 100.0) if confs else 0.0
    except Exception:
        conf = 1.0

    return text.upper().replace(" ", ""), conf


def draw_hud(display, conn, tracker, camera_source):
    y_pos = 20
    cv2.putText(
        display,
        f"ALPR | source: {camera_source} | parked: {tracker.count()}",
        (10, y_pos),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 200, 255),
        2,
    )
    y_pos += 25

    for plate, ts, _ in get_history(conn, 5):
        cv2.putText(
            display,
            f"{plate} {ts[11:19]}",
            (10, y_pos),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (180, 180, 180),
            1,
        )
        y_pos += 17

    parked_now = tracker.current_parked()
    bottom_y = display.shape[0] - 10 - len(parked_now) * 17
    for p in parked_now:
        cv2.putText(
            display,
            f"● {p}",
            (10, bottom_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (200, 200, 0),
            1,
        )
        bottom_y += 17


def main():
    args = parse_args()
    conn = init_db()
    tracker = ParkedCarTracker()

    camera_ctx = None
    selected_source = choose_camera_source(force_select=args.select)
    if selected_source is None:
        print("❌ No usable camera source found.")
        conn.close()
        return

    try:
        camera_ctx = open_camera(selected_source)
    except Exception as e:
        print(f"❌ Failed to open selected camera ({selected_source}): {e}")
        conn.close()
        return

    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        local_ip = "raspberrypi.local"

    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    print("🚘 ALPR running — press Ctrl+C to quit")
    print(f"📡 Camera source → {selected_source}")
    print(f"🌐 Dashboard → http://{local_ip}:{FLASK_PORT}")
    print(f"📷 Camera → http://{local_ip}:{FLASK_PORT}/camera")
    print(f"🎞️  Video feed → http://{local_ip}:{FLASK_PORT}/video_feed\n")

    frame_count = 0

    try:
        while True:
            frame = read_frame(camera_ctx)
            if frame is None:
                print(f"⚠️ {selected_source} frame read failed, retrying...")
                time.sleep(0.1 if selected_source != "nikon" else 0.5)
                continue

            frame_count += 1
            display = frame.copy()

            if frame_count % FRAME_SKIP == 0:
                regions = find_plate_regions(frame)

                for (x, y, w, h) in regions:
                    roi = frame[y:y + h, x:x + w]
                    clean, conf = ocr_plate(roi)

                    if not is_valid_plate(clean):
                        continue

                    is_new = tracker.see(clean)
                    if is_new:
                        save_plate(conn, clean, conf, frame, roi, x, y, w, h)
                        box_color = (0, 255, 0)
                        label_text = f"NEW: {clean}"
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] NEW PLATE → {clean} (conf: {conf:.2f})")
                    else:
                        box_color = (200, 200, 0)
                        label_text = f"PARKED: {clean}"
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ℹ️ STILL PARKED → {clean}")

                    cv2.rectangle(display, (x, y), (x + w, y + h), box_color, 2)
                    cv2.putText(
                        display,
                        label_text,
                        (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.65,
                        box_color,
                        2,
                    )

                tracker.end_frame()

            draw_hud(display, conn, tracker, selected_source)
            set_latest_frame(display)

    except KeyboardInterrupt:
        print("\n🛑 Stopping ALPR...")

    finally:
        close_camera(camera_ctx)

        print("\n── Parked cars still present at exit ────")
        for p in tracker.current_parked():
            print(f"  {p}")

        print("\n── Top arrivals ─────────────────────────")
        for plate, freq in get_frequency(conn):
            print(f"  {plate:<12} x{freq} arrival(s)")

        print(f"\n📁 {DB_PATH} | {LOG_PATH} | {IMAGES_DIR}/")
        conn.close()


if __name__ == "__main__":
    main()

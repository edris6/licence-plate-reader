#source venv/bin/activate
from flask import Flask, jsonify, send_from_directory
import json
import os


app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(BASE_DIR, "plate_images")


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "alpr_dashboard.html")


@app.route("/plates_log.json")
def plates_log():
    path = os.path.join(BASE_DIR, "plates_log.json")
    if not os.path.exists(path):
        response = jsonify([])
        response.headers["Cache-Control"] = "no-store"
        return response

    try:
        with open(path, encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        payload = []

    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/plate_images/<path:filename>")
def plate_images(filename):
    return send_from_directory(IMAGE_DIR, filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

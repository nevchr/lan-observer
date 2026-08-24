from flask import Flask, redirect, render_template, request, url_for

from database import (
    get_devices,
    get_last_scan,
    init_database,
    save_scan,
    set_last_scan,
    update_device
)
from scanner import scan_network
from datetime import datetime

app = Flask(__name__)

init_database()
def format_timestamp(timestamp):
    if not timestamp:
        return "Unknown"

    dt = datetime.fromisoformat(timestamp)
    now = datetime.now()

    if dt.date() == now.date():
        return f"Today at {dt.strftime('%I:%M %p').lstrip('0')}"

    return dt.strftime("%b %d, %Y at %I:%M %p").replace(" 0", " ")
app.jinja_env.filters["pretty_time"] = format_timestamp


@app.route("/device/update", methods=["POST"])
def device_update():
    mac = request.form["mac"]
    nickname = request.form["nickname"].strip()

    known = 1 if request.form.get("known") else 0

    update_device(
        mac,
        nickname,
        known
    )

    return redirect(url_for("index"))

@app.route("/")
def index():
    devices = get_devices()
    last_scan = get_last_scan()
    stats = {
    "online": sum(1 for device in devices if device["online"]),
    "recognized": sum(1 for device in devices if device["known"]),
    "unknown": sum(1 for device in devices if not device["known"]),
    "total": len(devices)
    }

    return render_template(
    "index.html",
    devices=devices,
    stats=stats,
    last_scan=last_scan
)


@app.route("/scan", methods=["POST"])
def scan():
    devices = scan_network()

    save_scan(devices)

    set_last_scan(
        datetime.now().isoformat(timespec="seconds")
    )

    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
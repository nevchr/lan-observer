"""Synthetic UI fixture. Never scans a real network or opens the legacy database."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from waitress import create_server

from lan_observer import create_app

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=5057)
parser.add_argument("--data-dir", type=Path, default=Path(".runtime/demo"))
args = parser.parse_args()
adapter = dict(
    index=7,
    name="Demo Ethernet",
    guid="demo-guid",
    mac="02:00:00:00:00:10",
    ip="192.0.2.10",
    prefix=24,
    profile="Demo home",
    gateway="192.0.2.1",
    key="demo",
)
observations = [
    dict(
        ip="192.0.2.10",
        mac=adapter["mac"],
        hostname="workstation",
        vendor="Example Systems",
        evidence="local",
    ),
    dict(
        ip="192.0.2.20",
        mac="02:00:00:00:00:20",
        hostname="living-room-speaker",
        vendor="Example Audio",
        evidence="response",
    ),
    dict(
        ip="192.0.2.30",
        mac="02:00:00:00:00:30",
        hostname="network-device-" + "x" * 49,
        vendor=None,
        evidence="cache",
    ),
    dict(ip="192.0.2.40", mac=None, hostname=None, vendor=None, evidence="response"),
]


def scan(interface, scope, cancel, progress, **kwargs):
    for completed in range(0, 255, 25):
        if cancel.wait(0.2):
            return dict(status="canceled", observations=[], warnings=[])
        progress("discovering", min(completed, 254))
    progress("enriching", 254)
    return dict(status="completed", observations=observations, warnings=[])


app = create_app(
    {
        "DATA_DIR": args.data_dir,
        "INTERFACE_PROVIDER": lambda: [adapter],
        "SCANNER": scan,
    }
)
store = app.extensions["store"]
if not store.networks():
    network = store.add_network("Home network · demo", adapter, "192.0.2.0/24")
    scan_id = store.create_scan(network, "192.0.2.0/24", 254)
    store.progress(scan_id, "discovering", 254)
    store.finish(
        scan_id, dict(status="completed", observations=observations, warnings=[])
    )
    devices = store.devices()
    store.edit(
        devices[0]["id"], "Workstation", "Primary desk computer", True, True, False
    )
    store.edit(devices[1]["id"], "Kitchen speaker", "#audio", False, False, False)
app.extensions["coordinator"].start_scheduler()
server = create_server(app, host="127.0.0.1", port=args.port)
print(f"Synthetic fixture: http://127.0.0.1:{args.port}", flush=True)
try:
    server.run()
except KeyboardInterrupt:
    pass
finally:
    app.extensions["coordinator"].close()
    server.close()

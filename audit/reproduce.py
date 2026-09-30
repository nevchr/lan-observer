"""Baseline characterization: synthetic data only; never opens the user's DB.

Run with Python + requirements.txt installed. CONFIRMED means the defect is
present, not that the app passed a regression test. --serve runs a safe UI fixture.
"""
import argparse
import asyncio
import contextlib
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if not (ROOT / 'database.py').exists():
    raise SystemExit('Historical baseline harness: use commit d3c662c. For the overhaul run: python -m unittest discover -s tests -v')
import database as db

MAC = "02:00:00:00:00:10"


def device(mac=MAC, ip="192.0.2.10", hostname="fixture-host", vendor="Fixture Vendor"):
    return dict(mac=mac, ip=ip, hostname=hostname, vendor=vendor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=5057)
    args = parser.parse_args()
    original = ROOT / "devices.db"
    before = hashlib.sha256(original.read_bytes()).hexdigest() if original.exists() else None
    results = []
    with tempfile.TemporaryDirectory(prefix="lan-observer-audit-") as tmp:
        db.DB_NAME = str(Path(tmp) / "fixture.db")
        import app as web
        import scanner

        if args.serve:
            @web.app.get("/audit/empty")
            def empty_fixture():
                return web.render_template("index.html", devices=[], stats=dict(online=0, recognized=0, unknown=0, total=0), last_scan=None)

        web.app.config.update(TESTING=True)
        client = web.app.test_client()

        def reset():
            with contextlib.closing(db.get_connection()) as conn:
                conn.execute("DELETE FROM devices")
                conn.execute("CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT)")
                conn.execute("DELETE FROM app_state")
                conn.commit()

        def record(key, observed, **evidence):
            results.append(dict(id=key, outcome="CONFIRMED" if observed else "NOT_REPRODUCED", evidence=evidence))

        def scan_fixture(arp=None, responders=()):
            with patch.object(scanner, "get_local_ip", return_value="192.0.2.10"), \
                 patch.object(scanner, "get_local_mac", return_value=MAC), \
                 patch.object(scanner, "ping_device", side_effect=lambda ip: ip in responders), \
                 patch.object(scanner, "get_arp_table", return_value=arp or {}), \
                 patch.object(scanner, "get_hostname", return_value="fixture-host"), \
                 patch.object(scanner, "get_vendor", return_value="Fixture Vendor"), \
                 contextlib.redirect_stdout(io.StringIO()):
                return scanner.scan_network()

        reset()
        db.save_scan(scan_fixture({"192.0.2.20": "02-00-00-00-00-20"}))
        cached = next(d for d in db.get_devices() if d["ip"] == "192.0.2.20")
        record("B01", cached["online"] == 1, ping_responders=0, cached_device_online=cached["online"])

        reset()
        db.save_scan([device()])
        db.update_device(MAC, "My computer", 1)
        db.save_scan([device(mac=MAC.replace(":", "-"))])
        rows = db.get_devices()
        record("B02", len(rows) == 2, identities=len(rows), recognized_online=sum(d["known"] and d["online"] for d in rows))

        reset()
        found = scan_fixture(responders=("192.0.2.20",))
        db.save_scan(found)
        record("B03", len(found) == 2 and len(db.get_devices()) == 1, discovered=len(found), stored=len(db.get_devices()))

        reset()
        db.save_scan([device()])
        client.post("/device/update", data=dict(mac=MAC, nickname="Kitchen speaker"))
        html = client.get("/").get_data(as_text=True)
        saved = db.get_devices()[0]["nickname"]
        client.post("/device/update", data=dict(mac=MAC, nickname="", known="on"))
        record("B04", saved == "Kitchen speaker" and "Kitchen speaker" not in html and db.get_devices()[0]["nickname"] == "",
               saved_name_hidden="Kitchen speaker" not in html, name_after_recognize=db.get_devices()[0]["nickname"])

        reset()
        db.save_scan([device()])
        db.save_scan([device(mac="02:00:00:00:01:20", ip="198.51.100.20")])
        old = next(d for d in db.get_devices() if d["mac"] == MAC)
        record("B05", old["online"] == 0, other_network_device_forced_offline=old["online"] == 0)

        with patch.object(scanner.socket, "gethostbyaddr", side_effect=socket.timeout("fixture DNS timeout")):
            try:
                scanner.get_hostname("192.0.2.20")
                dns_escaped = False
            except socket.timeout:
                dns_escaped = True
        with patch.object(web, "scan_network", side_effect=socket.timeout("fixture DNS timeout")):
            web.app.config["TESTING"] = False
            with patch.object(web.app.logger, "error"):
                response = client.post("/scan")
            web.app.config["TESTING"] = True
        record("B06", dns_escaped and response.status_code == 500, dns_exception_escaped=dns_escaped, scan_http=response.status_code)

        reset()
        db.save_scan([device(mac="02-00-00-00-00-20", ip="192.0.2.20")])
        with patch.object(scanner.subprocess, "run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="fixture error")):
            failed_arp = scanner.get_arp_table()
        with patch.object(web, "scan_network", return_value=scan_fixture(arp=failed_arp)):
            response = client.post("/scan")
        old = next(d for d in db.get_devices() if d["ip"] == "192.0.2.20")
        record("B07", failed_arp == {} and response.status_code == 302 and old["online"] == 0,
               arp_exit=1, scan_http=response.status_code, last_scan_set=bool(db.get_last_scan()), previous_device_online=old["online"])

        reset()
        started = threading.Event()
        release = threading.Event()
        statuses = []
        errors = []

        def fake_scan():
            if threading.current_thread().name == "older-scan":
                started.set()
                if not release.wait(5):
                    raise TimeoutError("audit synchronization failed")
                return [device(ip="192.0.2.11")]
            return [device(ip="192.0.2.22")]

        def older_request():
            try:
                with web.app.test_client() as other:
                    statuses.append(other.post("/scan").status_code)
            except Exception as exc:
                errors.append(type(exc).__name__)

        with patch.object(web, "scan_network", side_effect=fake_scan):
            thread = threading.Thread(target=older_request, name="older-scan")
            thread.start()
            if not started.wait(5):
                raise TimeoutError("audit thread did not start")
            try:
                statuses.append(client.post("/scan").status_code)
                newer_ip = db.get_devices()[0]["ip"]
            finally:
                release.set()
                thread.join(5)
        final_ip = db.get_devices()[0]["ip"]
        record("B08", not errors and statuses == [302, 302] and final_ip == "192.0.2.11",
               statuses=statuses, newer_scan_ip=newer_ip, final_ip=final_ip, errors=errors)

        reset()
        db.save_scan([device()])
        response = client.post("/device/update", headers={"Origin": "https://example.invalid", "Host": "example.invalid"},
                               data=dict(mac=MAC, nickname="Unexpected edit", known="on"))
        with patch.object(web, "scan_network", return_value=[]):
            scan_response = client.post("/scan", headers={"Origin": "https://example.invalid"})
        record("B09", response.status_code == 302 and db.get_devices()[0]["nickname"] == "Unexpected edit" and scan_response.status_code == 302,
               edit_http=response.status_code, scan_http=scan_response.status_code, note="Server test client only; browser exploit not tested")

        reset()
        db.save_scan([device()])
        previous_path = db.DB_NAME
        with tempfile.TemporaryDirectory(prefix="lan-observer-other-cwd-") as other:
            import os
            previous_cwd = Path.cwd()
            try:
                os.chdir(other)
                db.DB_NAME = "devices.db"
                db.init_database()
                alternate_count = len(db.get_devices())
            finally:
                db.DB_NAME = previous_path
                os.chdir(previous_cwd)
        record("B10", alternate_count == 0 and len(db.get_devices()) == 1, alternate_directory_count=alternate_count, original_fixture_count=len(db.get_devices()))

        reset()
        db.save_scan([device()])
        db.save_scan([device(hostname="Unknown", vendor="Unknown")])
        row = db.get_devices()[0]
        record("B11", row["hostname"] == row["vendor"] == "Unknown", hostname=row["hostname"], vendor=row["vendor"])

        reset()
        db.save_scan([device()])
        with contextlib.closing(db.get_connection()) as conn:
            conn.execute("UPDATE devices SET last_seen='2000-01-01T12:00:00'")
            conn.commit()
        db.set_last_scan("2000-01-01T12:00:00")
        html = client.get("/").get_data(as_text=True)
        record("B12", "ONLINE" in html and db.get_devices()[0]["online"] == 1,
               last_observation="2000-01-01", online_label_still_rendered="ONLINE" in html)

        reset()
        db.set_last_scan("2000-01-01T12:00:00")
        with patch.object(web, "scan_network", return_value=[device()]), \
             patch.object(web, "set_last_scan", side_effect=sqlite3.OperationalError("fixture metadata write failure")):
            try:
                client.post("/scan")
            except sqlite3.OperationalError:
                pass
        record("B13", len(db.get_devices()) == 1 and db.get_last_scan() == "2000-01-01T12:00:00",
               committed_devices=len(db.get_devices()), last_scan=db.get_last_scan())

        from mac_vendor_lookup import AsyncMacLookup
        lookup = AsyncMacLookup()
        mocked_update = AsyncMock()
        with patch.object(lookup, "find_vendors_list", return_value=None), \
             patch.object(lookup, "update_vendors", mocked_update), \
             patch("mac_vendor_lookup.os.makedirs"):
            asyncio.run(lookup.load_vendors())
        record("B14", mocked_update.await_count == 1, automatic_vendor_download_attempts=mocked_update.await_count,
               note="Download mocked; no outbound request performed")

        reset()
        db.save_scan([device()])
        db.update_device(MAC, "<script>alert('fixture')</script>", 1)
        html = client.get("/").get_data(as_text=True)
        positive = {"html_escaped": "&lt;script&gt;" in html and "<script>alert('fixture')</script>" not in html}
        db.update_device(MAC, "Robert'); DROP TABLE devices;--", 1)
        positive["sql_values_parameterized"] = len(db.get_devices()) == 1
        db.save_scan([device(ip="192.0.2.99")])
        row = db.get_devices()[0]
        positive["stable_mac_retains_recognition_and_name"] = row["known"] == 1 and row["nickname"].startswith("Robert") and row["ip"] == "192.0.2.99"
        reset()
        positive["empty_dashboard_http_200"] = client.get("/").status_code == 200

        after = hashlib.sha256(original.read_bytes()).hexdigest() if original.exists() else None
        report = dict(python=sys.version.split()[0], flask=importlib.metadata.version("flask"),
                      mac_vendor_lookup=importlib.metadata.version("mac-vendor-lookup"),
                      user_database_unchanged=before == after, network_scans_performed=0,
                      findings=results, positive_controls=positive)
        (ROOT / "audit" / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)

        if args.serve:
            reset()
            db.save_scan([
                device(hostname="workstation"),
                device(mac="02:00:00:00:00:20", ip="192.0.2.20", hostname="living-room-speaker"),
                device(mac="02:00:00:00:00:30", ip="192.0.2.30", hostname="network-device-" + "x" * 49),
            ])
            db.update_device(MAC, "Workstation", 1)
            db.update_device("02:00:00:00:00:20", "Kitchen speaker", 0)
            db.set_last_scan("2026-09-22T10:00:00")
            web.scan_network = lambda: [device()]

            print(f"Synthetic fixture: http://127.0.0.1:{args.port}", flush=True)
            web.app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)

        if any(r["outcome"] != "CONFIRMED" for r in results) or not all(positive.values()) or before != after:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

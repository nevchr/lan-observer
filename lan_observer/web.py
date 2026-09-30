"""Validated local browser routes; all mutations require a session token."""

import csv
import io
import ipaddress
import json
import secrets
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from flask import (
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from . import __version__
from .domain import display_name, presence, scope_for


def register(app):
    store = app.extensions["store"]
    coordinator = app.extensions["coordinator"]

    @app.before_request
    def protect():
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("Origin")
            # Sandboxed browser views can send an opaque Origin. The session-bound
            # token is mandatory for every POST, including opaque/missing origins.
            if origin and origin != "null":
                parsed = urlsplit(origin)
                if parsed.scheme != request.scheme or parsed.netloc != request.host:
                    abort(403, "This request did not originate from LAN Observer.")
            token = request.form.get("csrf_token") or request.headers.get(
                "X-CSRF-Token", ""
            )
            if not session.get("csrf") or not secrets.compare_digest(
                str(token), session["csrf"]
            ):
                abort(403, "This form expired. Reload the page and try again.")

    @app.after_request
    def headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.context_processor
    def context():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(32)
        return dict(
            csrf_token=session["csrf"],
            version=__version__,
            networks=store.networks(),
            active_scan=store.active(),
        )

    @app.errorhandler(ValueError)
    def invalid(error):
        return render_template(
            "error.html", title="Check your request", message=str(error)
        ), 400

    @app.errorhandler(sqlite3.Error)
    def database_error(error):
        app.logger.error("Database operation failed: %s", type(error).__name__)
        # Do not query a broken database again through the context processor.
        return (
            '<!doctype html><html lang="en"><meta charset="utf-8"><title>Inventory unavailable</title><h1>Inventory unavailable</h1><p>The database could not be read or written. Close other instances and check the data folder permissions. Your files have not been reset.</p><p><a href="/">Try again</a></p></html>',
            503,
        )

    from werkzeug.exceptions import HTTPException, SecurityError

    @app.errorhandler(HTTPException)
    def http_error(error):
        if isinstance(error, SecurityError):
            return "Untrusted host. Open LAN Observer at http://127.0.0.1:5000.", 400
        return render_template(
            "error.html", title=error.name, message=error.description
        ), error.code

    @app.errorhandler(OSError)
    @app.errorhandler(subprocess.TimeoutExpired)
    def operation_error(error):
        app.logger.error("Local operation failed: %s", type(error).__name__)
        return render_template(
            "error.html",
            title="Operation unavailable",
            message="The local operation could not finish. Check adapter availability and file permissions, then try again.",
        ), 503

    def text_field(name, limit):
        value = request.form.get(name, "").strip()
        if len(value) > limit or any(ord(c) < 32 and c not in "\n\t" for c in value):
            raise ValueError(
                f"{name.replace('_', ' ').capitalize()} must be at most {limit} characters without control characters."
            )
        return value

    def checkbox(name):
        value = request.form.get(name)
        if value not in (None, "on"):
            raise ValueError("Invalid checkbox value.")
        return value == "on"

    @app.get("/")
    def index():
        # Keep the user's list context when returning from a device detail page.
        session["inventory_url"] = url_for(
            "index",
            **{
                key: value[:200]
                for key, value in request.args.items()
                if key in {"network", "q", "state", "vendor", "sort", "page"}
            },
        )
        network_id = request.args.get("network", "")
        if network_id:
            store.network(network_id)
        configured_networks = [
            network for network in store.networks() if network["scope"]
        ]
        scan_selected = (
            network_id
            if any(network["id"] == network_id for network in configured_networks)
            else configured_networks[0]["id"]
            if len(configured_networks) == 1
            else ""
        )
        devices = store.devices(network_id or None)
        query = request.args.get("q", "").strip().casefold()
        state = request.args.get("state", "")
        vendor = request.args.get("vendor", "")
        sort = request.args.get("sort", "seen")
        stats = dict(
            total=sum(not d["archived"] for d in devices),
            recognized=sum(d["known"] and not d["archived"] for d in devices),
            review=sum(not d["reviewed"] and not d["archived"] for d in devices),
            responded=sum(
                presence(d) in ("Responded in scan", "This computer")
                and not d["archived"]
                for d in devices
            ),
        )
        vendors = sorted({d["vendor"] for d in devices if d["vendor"]})
        devices = [
            d
            for d in devices
            if (bool(d["archived"]) == (state == "archived"))
            and (state != "review" or not d["reviewed"])
            and (state != "recognized" or d["known"])
            and (
                state != "responded"
                or presence(d) in ("Responded in scan", "This computer")
            )
            and (not vendor or d["vendor"] == vendor)
            and (
                not query
                or query
                in " ".join(
                    str(d.get(k) or "")
                    for k in ("nickname", "hostname", "ip", "mac", "vendor", "notes")
                ).casefold()
            )
        ]

        def ip_key(d):
            try:
                return int(ipaddress.IPv4Address(d["ip"]))
            except (ValueError, TypeError):
                return -1

        devices.sort(
            key=(lambda d: display_name(d).casefold())
            if sort == "name"
            else ip_key
            if sort == "ip"
            else lambda d: d["observed_at"] or "",
            reverse=sort not in ("name", "ip"),
        )
        page = max(1, min(100000, request.args.get("page", 1, type=int) or 1))
        total = len(devices)
        devices = devices[(page - 1) * 50 : page * 50]
        recent = store.query(
            "SELECT s.*,n.name network_name FROM scans s JOIN networks n ON n.id=s.network_id"
            + (" WHERE network_id=?" if network_id else "")
            + " ORDER BY s.id DESC LIMIT 1",
            (network_id,) if network_id else (),
        )
        unidentified = store.query(
            """SELECT o.*,s.network_id FROM observations o JOIN scans s ON s.id=o.scan_id
            WHERE o.device_id IS NULL AND s.id IN (SELECT MAX(id) FROM scans WHERE status IN ('completed','partial') GROUP BY network_id)"""
            + (" AND s.network_id=?" if network_id else "")
            + " ORDER BY o.id DESC LIMIT 50",
            (network_id,) if network_id else (),
        )
        return render_template(
            "index.html",
            devices=devices,
            stats=stats,
            vendors=vendors,
            total=total,
            page=page,
            selected=network_id,
            scan_selected=scan_selected,
            configured_networks=configured_networks,
            latest=recent[0] if recent else None,
            unidentified=unidentified,
        )

    @app.get("/devices/<int:device_id>")
    def device_detail(device_id):
        device = store.device(device_id)
        if not device:
            abort(404)
        events = store.query(
            "SELECT * FROM events WHERE device_id=? ORDER BY id DESC LIMIT 100",
            (device_id,),
        )
        observations = store.query(
            "SELECT * FROM observations WHERE device_id=? ORDER BY id DESC LIMIT 30",
            (device_id,),
        )
        return render_template(
            "device.html", device=device, events=events, observations=observations
        )

    @app.post("/devices/<int:device_id>")
    def device_update(device_id):
        if not store.device(device_id):
            abort(404)
        try:
            store.edit(
                device_id,
                text_field("nickname", 80),
                text_field("notes", 2000),
                checkbox("known"),
                checkbox("reviewed"),
                checkbox("archived"),
            )
        except ValueError as error:
            device = store.device(device_id)
            device.update(
                nickname=request.form.get("nickname", ""),
                notes=request.form.get("notes", ""),
                **{
                    key: request.form.get(key) == "on"
                    for key in ("known", "reviewed", "archived")
                },
            )
            return render_template(
                "device.html",
                device=device,
                events=[],
                observations=[],
                form_error=str(error),
            ), 400
        flash("Device saved. Naming, recognition and review are independent.")
        return redirect(url_for("device_detail", device_id=device_id), code=303)

    @app.post("/scans")
    def start_scan():
        scan_id, created = coordinator.start(request.form.get("network_id", ""))
        if request.accept_mimetypes.best == "application/json":
            return jsonify(
                id=scan_id, url=url_for("scan_detail", scan_id=scan_id)
            ), 202 if created else 200
        if not created:
            flash("A scan is already running. Showing its progress.")
        return redirect(url_for("scan_detail", scan_id=scan_id), code=303)

    @app.post("/devices/<int:device_id>/assign")
    def assign_legacy(device_id):
        with coordinator.lock, store.lock:
            if store.active():
                raise ValueError(
                    "Wait for the scan to finish before linking an imported device."
                )
            linked_id = store.assign_legacy(
                device_id, request.form.get("network_id", "")
            )
        flash(
            "Imported device linked. Existing identity conflicts are retained in the timeline and original archive for review."
        )
        return redirect(url_for("device_detail", device_id=linked_id), code=303)

    @app.get("/scans/<int:scan_id>")
    def scan_detail(scan_id):
        rows = store.query(
            "SELECT s.*,n.name network_name FROM scans s JOIN networks n ON n.id=s.network_id WHERE s.id=?",
            (scan_id,),
        )
        if not rows:
            abort(404)
        run = rows[0]
        run["warnings"] = json.loads(run["warnings"])
        if request.args.get("format") == "json":
            return jsonify(run)
        observations = store.query(
            "SELECT o.*,d.nickname FROM observations o LEFT JOIN devices d ON d.id=o.device_id WHERE o.scan_id=? ORDER BY o.id LIMIT 1024",
            (scan_id,),
        )
        changes = store.query(
            """SELECT e.*,d.nickname,d.hostname,d.ip FROM events e
            LEFT JOIN devices d ON d.id=e.device_id WHERE e.scan_id=? ORDER BY e.id""",
            (scan_id,),
        )
        previous = store.query(
            "SELECT id FROM scans WHERE network_id=? AND id<? AND status='completed' ORDER BY id DESC LIMIT 1",
            (run["network_id"], scan_id),
        )
        not_observed = []
        if previous and run["status"] == "completed":
            prior = store.query(
                "SELECT o.*,d.nickname FROM observations o LEFT JOIN devices d ON d.id=o.device_id WHERE o.scan_id=? AND o.evidence IN ('response','local')",
                (previous[0]["id"],),
            )
            confirmed = {
                o["mac"] or o["ip"]
                for o in observations
                if o["evidence"] in ("response", "local")
            }
            coverage = ipaddress.IPv4Network(run["scope"])
            not_observed = [
                o
                for o in prior
                if ipaddress.IPv4Address(o["ip"]) in coverage
                and (o["mac"] or o["ip"]) not in confirmed
            ]
        return render_template(
            "scan.html",
            run=run,
            observations=observations,
            changes=changes,
            previous=previous[0] if previous else None,
            not_observed=not_observed,
        )

    @app.post("/scans/<int:scan_id>/cancel")
    def cancel_scan(scan_id):
        coordinator.cancel(scan_id)
        return redirect(url_for("scan_detail", scan_id=scan_id), code=303)

    @app.get("/history")
    def history():
        page = max(1, request.args.get("page", 1, type=int) or 1)
        runs = store.query(
            "SELECT s.*,n.name network_name FROM scans s JOIN networks n ON n.id=s.network_id ORDER BY id DESC LIMIT 50 OFFSET ?",
            ((page - 1) * 50,),
        )
        return render_template("history.html", runs=runs, page=page)

    @app.get("/settings")
    def settings():
        error = None
        try:
            adapters = coordinator.provider()
        except (OSError, ValueError, subprocess.TimeoutExpired):
            adapters, error = (
                [],
                "Adapter information is unavailable. Check that you are connected on Windows and refresh this page.",
            )
        return render_template(
            "settings.html",
            adapters=adapters,
            adapter_error=error,
            data_path=str(store.path.parent),
            settings={
                key: store.setting(key, default)
                for key, default in [
                    ("schedule_minutes", "0"),
                    ("schedule_network", ""),
                    ("resolve_names", "1"),
                    ("retention_days", "90"),
                    ("schedule_error", ""),
                ]
            },
            vendor_updated=store.setting("vendor_updated"),
            legacy_path=str(Path(__file__).resolve().parents[1] / "devices.db"),
        )

    @app.post("/networks")
    def add_network():
        name = text_field("network_name", 80)
        if not name:
            raise ValueError("Give this network a name.")
        interface = next(
            (
                i
                for i in coordinator.provider()
                if i["key"] == request.form.get("interface_key")
            ),
            None,
        )
        if not interface:
            raise ValueError("Adapter changed. Refresh Settings and choose it again.")
        scope = scope_for(interface, request.form.get("scope") or None)
        network_id = store.add_network(name, interface, str(scope))
        flash(
            "Network saved. Each saved network has a separate inventory; scan only networks you are authorized to inspect."
        )
        return redirect(url_for("index", network=network_id), code=303)

    @app.post("/settings")
    def save_settings():
        interval = request.form.get("schedule_minutes", "0")
        retention = request.form.get("retention_days", "90")
        if interval not in {"0", "5", "15", "30", "60"} or retention not in {
            "30",
            "90",
            "365",
        }:
            raise ValueError(
                "Choose one of the supported scheduling and retention options."
            )
        network_id = request.form.get("schedule_network", "")
        if interval != "0":
            network = store.network(network_id)
            if not network["scope"]:
                raise ValueError("Select a configured network for scheduling.")
        store.set_settings(
            dict(
                schedule_minutes=interval,
                retention_days=retention,
                schedule_network=network_id,
                resolve_names=int(checkbox("resolve_names")),
                schedule_error="",
            )
        )
        flash(
            "Settings saved. Scheduled scans run only while this app is open; missed intervals are not replayed."
        )
        return redirect(url_for("settings"), code=303)

    @app.post("/data/import-legacy")
    def import_legacy():
        with coordinator.lock, store.lock:
            if store.active():
                raise ValueError("Finish or cancel the current scan before importing.")
            result = store.import_legacy(text_field("legacy_path", 1000))
        flash(
            f"Imported {result['rows']} legacy records; {result['merged']} duplicate identities need review. The original database is unchanged."
        )
        return redirect(url_for("index"), code=303)

    @app.post("/data/backup")
    def backup():
        return send_file(
            store.backup(), as_attachment=True, download_name="lan-observer-backup.db"
        )

    @app.post("/data/restore")
    def restore():
        upload = request.files.get("backup")
        if not upload or request.form.get("confirmation") != "RESTORE":
            raise ValueError(
                "Choose a backup and type RESTORE. A backup of your current inventory is made first."
            )
        with tempfile.TemporaryDirectory(dir=store.path.parent) as directory:
            path = Path(directory) / "restore.db"
            upload.save(path)
            with coordinator.lock:
                store.restore(path)
        session.clear()
        flash(
            "Backup restored. Scheduling has been disabled; review your settings before enabling it."
        )
        return redirect(url_for("index"), code=303)

    @app.post("/data/export")
    def export():
        content = {
            "version": __version__,
            "devices": store.devices(),
            "networks": store.networks(),
        }
        return send_file(
            io.BytesIO(json.dumps(content, indent=2).encode()),
            mimetype="application/json",
            as_attachment=True,
            download_name="lan-observer-inventory.json",
        )

    @app.post("/data/vendors")
    def import_vendors():
        upload = request.files.get("vendors")
        if not upload:
            raise ValueError("Choose an IEEE OUI CSV file.")
        text = upload.read(10 * 1024 * 1024 + 1)
        if len(text) > 10 * 1024 * 1024:
            raise ValueError("Vendor list must be under 10 MB.")
        try:
            rows = csv.DictReader(io.StringIO(text.decode("utf-8-sig")))
            vendors = {}
            for row in rows:
                prefix = row.get("Assignment", "").replace("-", "").upper()
                name = row.get("Organization Name", "").strip()
                if (
                    len(prefix) == 6
                    and all(c in "0123456789ABCDEF" for c in prefix)
                    and name
                ):
                    vendors[prefix] = name[:200]
            if not vendors:
                raise ValueError(
                    "No valid Assignment / Organization Name records found."
                )
        except UnicodeError:
            raise ValueError("Choose a UTF-8 IEEE OUI CSV file.") from None
        path = store.path.parent / "vendors.json"
        temp = path.with_suffix(".tmp")
        with store.lock:
            temp.write_text(json.dumps(vendors), encoding="utf-8")
            temp.replace(path)
            from .domain import now

            store.set_settings({"vendor_updated": now()})
        flash(
            f"Imported {len(vendors)} vendor prefixes. Used locally on subsequent scans; no automatic downloads occur."
        )
        return redirect(url_for("settings"), code=303)

    @app.get("/diagnostics")
    def diagnostics():
        # Deliberately exclude inventory, paths, network names, IPs, MACs and logs.
        return jsonify(
            version=__version__,
            schema=store.setting("schema"),
            scan_counts=store.query(
                "SELECT status,count(*) count FROM scans GROUP BY status"
            ),
            scheduling_enabled=store.setting("schedule_minutes", "0") != "0",
            active=bool(store.active()),
        )

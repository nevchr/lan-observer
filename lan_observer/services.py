"""One bounded background scan coordinator per running application."""

import json
import logging
import sqlite3
import threading
import time

from . import discovery
from .domain import scope_for


class Coordinator:
    def __init__(self, store, provider=discovery.interfaces, scanner=discovery.scan):
        self.store, self.provider, self.scanner = store, provider, scanner
        self.cancel_event = threading.Event()
        self.stop_event = threading.Event()
        self.worker = None
        self.scheduler = None
        self.lock = threading.RLock()

    def start(self, network_id):
        with self.lock, self.store.lock:
            if self.stop_event.is_set():
                raise ValueError("The app is shutting down.")
            active = self.store.active()
            if active:
                return active["id"], False
            network = self.store.network(network_id)
            saved = network["interface"]
            current = next(
                (i for i in self.provider() if i["key"] == saved.get("key")), None
            )
            if not current:
                raise ValueError(
                    "The saved adapter/network is unavailable or has changed. Create or select the correct network."
                )
            scope = scope_for(current, network["scope"])
            try:
                scan_id = self.store.create_scan(
                    network_id, str(scope), len(list(scope.hosts()))
                )
            except sqlite3.IntegrityError:
                return self.store.active()["id"], False
            self.cancel_event = threading.Event()
            self.worker = threading.Thread(
                target=self._run,
                args=(scan_id, current, str(scope)),
                name="LANObserver-scan",
                daemon=True,
            )
            self.worker.start()
            return scan_id, True

    def _run(self, scan_id, interface, scope):
        try:
            vendors_path = self.store.path.parent / "vendors.json"
            try:
                vendors = (
                    json.loads(vendors_path.read_text(encoding="utf-8"))
                    if vendors_path.exists()
                    else {}
                )
            except (ValueError, OSError):
                vendors = {}
            result = self.scanner(
                interface,
                scope,
                self.cancel_event,
                lambda phase, completed: self.store.progress(scan_id, phase, completed),
                vendors=vendors,
                resolve_names=self.store.setting("resolve_names", "1") == "1",
            )
            self.store.finish(scan_id, result)
            self.store.prune(int(self.store.setting("retention_days", "90")))
        except Exception:
            logging.getLogger("lan_observer").exception("Scan job %s failed", scan_id)
            try:
                self.store.finish(
                    scan_id,
                    dict(
                        status="failed",
                        observations=[],
                        warnings=[
                            "The scan could not finish. Previous observations are preserved. Check Diagnostics and try again."
                        ],
                    ),
                )
            except Exception:
                logging.getLogger("lan_observer").exception(
                    "Could not record scan failure"
                )

    def cancel(self, scan_id):
        with self.lock:
            active = self.store.active()
            if not active or active["id"] != scan_id:
                raise ValueError("This scan is no longer active.")
            self.store.progress(scan_id, "canceling", active["completed"])
            self.cancel_event.set()

    def start_scheduler(self):
        self.store.recover()  # Only the launcher holding the process lock calls this.
        self.scheduler = threading.Thread(
            target=self._schedule, name="LANObserver-schedule", daemon=True
        )
        self.scheduler.start()

    def _schedule(self):
        due = None
        previous = None
        while not self.stop_event.wait(1):
            try:
                config = (
                    self.store.setting("schedule_minutes", "0"),
                    self.store.setting("schedule_network", ""),
                )
                interval = int(config[0]) * 60
                if config != previous:
                    due = time.monotonic() + interval if interval else None
                    previous = config
                if due is not None and time.monotonic() >= due:
                    due = (
                        time.monotonic() + interval
                    )  # Never replay missed intervals after sleep.
                    if not self.store.active():
                        try:
                            self.start(config[1])
                            self.store.set_settings({"schedule_error": ""})
                        except (ValueError, OSError):
                            self.store.set_settings(
                                {
                                    "schedule_error": "Scheduled network unavailable. Select the adapter/network again in Settings."
                                }
                            )
            except Exception:
                logging.getLogger("lan_observer").exception(
                    "Scheduler iteration failed"
                )

    def close(self):
        self.stop_event.set()
        self.cancel_event.set()
        if self.scheduler:
            self.scheduler.join(2)
        if self.worker:
            self.worker.join(15)

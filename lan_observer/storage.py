"""Transactional, network-scoped inventory; never modifies a legacy database."""

import hashlib
import ipaddress
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .domain import canonical_mac, friendly_edit_detail, meaningful, now, stamp

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS networks(id TEXT PRIMARY KEY, name TEXT NOT NULL, interface TEXT NOT NULL, scope TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scans(id INTEGER PRIMARY KEY, network_id TEXT NOT NULL REFERENCES networks(id),
 scope TEXT NOT NULL, started TEXT NOT NULL, finished TEXT, status TEXT NOT NULL,
 completed INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0, warnings TEXT NOT NULL DEFAULT '[]');
CREATE UNIQUE INDEX IF NOT EXISTS one_active_scan ON scans((1)) WHERE status IN ('queued','discovering','enriching','canceling');
CREATE TABLE IF NOT EXISTS devices(id INTEGER PRIMARY KEY, network_id TEXT NOT NULL REFERENCES networks(id),
 mac TEXT, ip TEXT, hostname TEXT, vendor TEXT, nickname TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
 known INTEGER NOT NULL DEFAULT 0, reviewed INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
 first_seen TEXT, last_confirmed TEXT, observed_at TEXT, evidence TEXT NOT NULL DEFAULT 'legacy', scan_id INTEGER REFERENCES scans(id),
 UNIQUE(network_id,mac));
CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY, scan_id INTEGER NOT NULL REFERENCES scans(id),
 device_id INTEGER REFERENCES devices(id), ip TEXT NOT NULL, mac TEXT, hostname TEXT, vendor TEXT,
 evidence TEXT NOT NULL, observed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, device_id INTEGER REFERENCES devices(id),
 scan_id INTEGER REFERENCES scans(id), at TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS legacy_records(id INTEGER PRIMARY KEY, source TEXT NOT NULL, raw TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS device_network ON devices(network_id,archived,observed_at);
CREATE INDEX IF NOT EXISTS observation_device ON observations(device_id,id);
CREATE INDEX IF NOT EXISTS event_device ON events(device_id,id);
"""
ACTIVE = ("queued", "discovering", "enriching", "canceling")


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connection() as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if tables and "meta" not in tables:
                raise ValueError(
                    "This is a legacy database. Choose a new data directory and import it in Settings."
                )
            if "meta" in tables:
                row = conn.execute(
                    "SELECT value FROM meta WHERE key='schema'"
                ).fetchone()
                if not row or row[0] != "1":
                    raise ValueError(
                        "Unsupported database version. Keep the file and use the matching app version."
                    )
            conn.executescript(SCHEMA)
            conn.execute("INSERT OR IGNORE INTO meta VALUES ('schema','1')")

    @contextmanager
    def connection(self):
        with self.lock:
            conn = sqlite3.connect(self.path, timeout=5)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            try:
                with conn:
                    yield conn
            finally:
                conn.close()

    def query(self, sql, values=()):
        with self.connection() as conn:
            return [dict(r) for r in conn.execute(sql, values)]

    def setting(self, key, default=None):
        rows = self.query("SELECT value FROM meta WHERE key=?", (key,))
        return rows[0]["value"] if rows else default

    def set_settings(self, values):
        with self.connection() as conn:
            conn.executemany(
                "INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                [(k, str(v)) for k, v in values.items()],
            )

    def networks(self):
        return self.query("SELECT * FROM networks ORDER BY name")

    def add_network(self, name, interface, scope):
        network_id = uuid.uuid4().hex
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO networks VALUES (?,?,?,?)",
                (network_id, name, json.dumps(interface), scope),
            )
        return network_id

    def network(self, network_id):
        rows = self.query("SELECT * FROM networks WHERE id=?", (network_id,))
        if not rows:
            raise ValueError("Network not found.")
        result = rows[0]
        result["interface"] = json.loads(result["interface"])
        return result

    def devices(self, network_id=None):
        return self.query(
            "SELECT d.*,n.name network_name FROM devices d JOIN networks n ON n.id=d.network_id"
            + (" WHERE network_id=?" if network_id else ""),
            (network_id,) if network_id else (),
        )

    def device(self, device_id):
        rows = self.query(
            "SELECT d.*,n.name network_name FROM devices d JOIN networks n ON n.id=d.network_id WHERE d.id=?",
            (device_id,),
        )
        return rows[0] if rows else None

    def edit(self, device_id, nickname, notes, known, reviewed, archived):
        with self.connection() as conn:
            old = conn.execute(
                "SELECT * FROM devices WHERE id=?", (device_id,)
            ).fetchone()
            if not old:
                raise ValueError("Device not found.")
            conn.execute(
                "UPDATE devices SET nickname=?,notes=?,known=?,reviewed=?,archived=? WHERE id=?",
                (nickname, notes, known, reviewed, archived, device_id),
            )
            changes = [
                key
                for key, value in dict(
                    nickname=nickname,
                    notes=notes,
                    known=known,
                    reviewed=reviewed,
                    archived=archived,
                ).items()
                if old[key] != value
            ]
            if changes:
                self.event(
                    conn,
                    device_id,
                    None,
                    "Edited",
                    friendly_edit_detail("Changed: " + ", ".join(changes)),
                )

    def assign_legacy(self, device_id, network_id):
        """Move an imported identity without guessing its network or deleting conflicts."""
        target = self.network(network_id)
        if not target["scope"]:
            raise ValueError("Choose a configured scan network.")
        with self.connection() as conn:
            source = conn.execute(
                "SELECT d.*,n.scope FROM devices d JOIN networks n ON n.id=d.network_id WHERE d.id=?",
                (device_id,),
            ).fetchone()
            if not source or source["scope"]:
                raise ValueError("Only unassigned legacy devices can be linked here.")
            existing = (
                conn.execute(
                    "SELECT * FROM devices WHERE network_id=? AND mac=?",
                    (network_id, source["mac"]),
                ).fetchone()
                if source["mac"]
                else None
            )
            if existing:
                # Keep the source row archived as a complete copy of the user's original decisions.
                conflict = (
                    bool(
                        existing["nickname"]
                        and source["nickname"]
                        and existing["nickname"] != source["nickname"]
                    )
                    or existing["known"] != source["known"]
                )
                notes = existing["notes"]
                if source["notes"]:
                    notes += "\nImported notes: " + source["notes"]
                if conflict:
                    self.event(
                        conn,
                        existing["id"],
                        None,
                        "Import conflict",
                        f"Linked legacy device #{device_id}. Original name: {source['nickname'] or '(empty)'}. Original recognition: {bool(source['known'])}. Review both records.",
                    )
                conn.execute(
                    "UPDATE devices SET nickname=CASE WHEN nickname='' THEN ? ELSE nickname END,notes=?,known=?,reviewed=0,first_seen=? WHERE id=?",
                    (
                        source["nickname"],
                        notes,
                        min(existing["known"], source["known"])
                        if conflict
                        else source["known"],
                        min(
                            t
                            for t in [existing["first_seen"], source["first_seen"]]
                            if t
                        )
                        if existing["first_seen"] or source["first_seen"]
                        else None,
                        existing["id"],
                    ),
                )
                conn.execute("UPDATE devices SET archived=1 WHERE id=?", (device_id,))
                self.event(
                    conn,
                    device_id,
                    None,
                    "Linked to network",
                    f"Original preserved in archive. Current identity is device #{existing['id']}.",
                )
                return existing["id"]
            conn.execute(
                "UPDATE devices SET network_id=? WHERE id=?", (network_id, device_id)
            )
            self.event(
                conn,
                device_id,
                None,
                "Network assigned",
                f"Assigned to {target['name']}. Historical presence is not treated as a fresh response.",
            )
            return device_id

    @staticmethod
    def event(conn, device_id, scan_id, kind, detail):
        conn.execute(
            "INSERT INTO events(device_id,scan_id,at,kind,detail) VALUES (?,?,?,?,?)",
            (device_id, scan_id, now(), kind, detail),
        )

    def active(self):
        rows = self.query(
            "SELECT * FROM scans WHERE status IN ('queued','discovering','enriching','canceling') ORDER BY id DESC LIMIT 1"
        )
        return rows[0] if rows else None

    def create_scan(self, network_id, scope, total):
        with self.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO scans(network_id,scope,started,status,total) VALUES (?,?,?,'queued',?)",
                (network_id, scope, now(), total),
            )
            return cursor.lastrowid

    def progress(self, scan_id, phase, completed):
        with self.connection() as conn:
            conn.execute(
                "UPDATE scans SET status=CASE WHEN status='canceling' THEN status ELSE ? END,completed=? WHERE id=? AND status IN ('queued','discovering','enriching','canceling')",
                (phase, completed, scan_id),
            )

    def recover(self):
        with self.connection() as conn:
            conn.execute(
                "UPDATE scans SET status='interrupted',finished=?,warnings=? WHERE status IN ('queued','discovering','enriching','canceling')",
                (
                    now(),
                    json.dumps(
                        ["The app stopped before this scan finished. Start a new scan."]
                    ),
                ),
            )

    def finish(self, scan_id, result):
        """Publish evidence + completion together. Failed/canceled scans never reconcile."""
        with self.connection() as conn:
            run = conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
            if not run or run["status"] not in ACTIVE:
                raise ValueError("Scan is no longer active.")
            status = result["status"]
            if status not in {"completed", "partial", "failed", "canceled"}:
                raise ValueError("Invalid scan outcome.")
            if run["status"] == "canceling":
                status = "canceled"
            if status in {"completed", "partial"}:
                coverage = ipaddress.IPv4Network(run["scope"])
                seen = set()
                for observation in result.get("observations", []):
                    ip = str(ipaddress.IPv4Address(observation["ip"]))
                    if ipaddress.IPv4Address(ip) not in coverage:
                        raise ValueError("Observation outside scan scope.")
                    mac = canonical_mac(observation.get("mac"))
                    evidence = observation["evidence"]
                    if evidence not in {"response", "local", "cache"}:
                        raise ValueError("Invalid evidence source.")
                    observed_at = now()
                    hostname, vendor = (
                        meaningful(observation.get("hostname")),
                        meaningful(observation.get("vendor")),
                    )
                    old = (
                        conn.execute(
                            "SELECT * FROM devices WHERE network_id=? AND mac=?",
                            (run["network_id"], mac),
                        ).fetchone()
                        if mac
                        else None
                    )
                    confirmed = (
                        observed_at if evidence in {"response", "local"} else None
                    )
                    if old:
                        device_id = old["id"]
                        if old["ip"] != ip:
                            self.event(
                                conn,
                                device_id,
                                scan_id,
                                "Address changed",
                                f"{old['ip']} → {ip}",
                            )
                        if hostname and old["hostname"] and old["hostname"] != hostname:
                            self.event(
                                conn,
                                device_id,
                                scan_id,
                                "Hostname changed",
                                f"{old['hostname']} → {hostname}",
                            )
                        if old["archived"]:
                            self.event(
                                conn,
                                device_id,
                                scan_id,
                                "Reappeared",
                                "Restored to inventory; needs review.",
                            )
                        conn.execute(
                            """UPDATE devices SET ip=?,hostname=COALESCE(?,hostname),vendor=COALESCE(?,vendor),
                            last_confirmed=COALESCE(?,last_confirmed),observed_at=?,evidence=?,scan_id=?,
                            reviewed=CASE WHEN archived=1 THEN 0 ELSE reviewed END,archived=0 WHERE id=?""",
                            (
                                ip,
                                hostname,
                                vendor,
                                confirmed,
                                observed_at,
                                evidence,
                                scan_id,
                                device_id,
                            ),
                        )
                    elif mac:
                        cursor = conn.execute(
                            """INSERT INTO devices(network_id,mac,ip,hostname,vendor,first_seen,last_confirmed,observed_at,evidence,scan_id)
                            VALUES (?,?,?,?,?,?,?,?,?,?)""",
                            (
                                run["network_id"],
                                mac,
                                ip,
                                hostname,
                                vendor,
                                observed_at,
                                confirmed,
                                observed_at,
                                evidence,
                                scan_id,
                            ),
                        )
                        device_id = cursor.lastrowid
                        self.event(
                            conn,
                            device_id,
                            scan_id,
                            "First observed",
                            "A new identity was recorded on this network.",
                        )
                    else:
                        device_id = None  # IP-only observations are visible, never permanent identities.
                    if device_id:
                        seen.add(device_id)
                    conn.execute(
                        "INSERT INTO observations(scan_id,device_id,ip,mac,hostname,vendor,evidence,observed_at) VALUES (?,?,?,?,?,?,?,?)",
                        (
                            scan_id,
                            device_id,
                            ip,
                            mac,
                            hostname,
                            vendor,
                            evidence,
                            observed_at,
                        ),
                    )
                if status == "completed":
                    for row in conn.execute(
                        "SELECT id,ip FROM devices WHERE network_id=?",
                        (run["network_id"],),
                    ).fetchall():
                        try:
                            covered = ipaddress.IPv4Address(row["ip"]) in coverage
                        except (ValueError, TypeError):
                            covered = False
                        if covered and row["id"] not in seen:
                            conn.execute(
                                "UPDATE devices SET evidence='not_seen',observed_at=?,scan_id=? WHERE id=?",
                                (now(), scan_id, row["id"]),
                            )
            conn.execute(
                "UPDATE scans SET status=?,finished=?,warnings=? WHERE id=?",
                (status, now(), json.dumps(result.get("warnings", [])), scan_id),
            )

    def backup(self, destination=None):
        target = (
            Path(destination)
            if destination
            else self.path.parent / "backups" / f"inventory-{uuid.uuid4().hex}.db"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as source:
            dest = sqlite3.connect(target)
            try:
                source.backup(dest)
            finally:
                dest.close()
        return target

    def import_legacy(self, source):
        source = Path(source).resolve()
        if source == self.path or not source.is_file():
            raise ValueError("Choose the existing legacy devices.db file.")
        key = "legacy:" + hashlib.sha256(str(source).encode()).hexdigest()
        with self.lock:
            if self.setting(key):
                raise ValueError(
                    "This legacy file has already been imported. Its original records are retained."
                )
            self.backup()
            legacy = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
            legacy.row_factory = sqlite3.Row
            try:
                if legacy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Legacy database failed its integrity check.")
                tables = {
                    r[0]
                    for r in legacy.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if "devices" not in tables or "meta" in tables:
                    raise ValueError("This is not a supported legacy inventory.")
                rows = [dict(r) for r in legacy.execute("SELECT * FROM devices")]
                if (
                    rows
                    and not {"mac", "ip", "first_seen", "last_seen", "known"}
                    <= rows[0].keys()
                ):
                    raise ValueError("Unsupported legacy schema.")
                target = self.path.parent / "backups" / f"legacy-{uuid.uuid4().hex}.db"
                dest = sqlite3.connect(target)
                try:
                    legacy.backup(dest)
                finally:
                    dest.close()
            finally:
                legacy.close()
            with self.connection() as conn:
                network_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO networks VALUES (?,?,?,?)",
                    (network_id, "Legacy inventory · unassigned", "{}", ""),
                )
                merged = 0
                for raw in rows:
                    conn.execute(
                        "INSERT INTO legacy_records(source,raw) VALUES (?,?)",
                        (str(source), json.dumps(raw)),
                    )
                    try:
                        mac = canonical_mac(raw.get("mac"))
                    except ValueError:
                        mac = None
                    old = (
                        conn.execute(
                            "SELECT * FROM devices WHERE network_id=? AND mac=?",
                            (network_id, mac),
                        ).fetchone()
                        if mac
                        else None
                    )
                    first = stamp(raw.get("first_seen"))
                    last = stamp(raw.get("last_seen"))
                    first, last = (
                        first.isoformat() if first else None,
                        last.isoformat() if last else None,
                    )
                    if old:
                        merged += 1
                        # Preserve all conflicting originals; conservatively require review.
                        detail = f"Imported duplicate MAC. Original name: {raw.get('nickname') or '(empty)'}. Recognition: {bool(raw.get('known'))}."
                        self.event(conn, old["id"], None, "Import conflict", detail)
                        times = [t for t in (old["first_seen"], first) if t]
                        lasts = [t for t in (old["observed_at"], last) if t]
                        conn.execute(
                            "UPDATE devices SET first_seen=?,observed_at=?,reviewed=0,known=MIN(known,?),nickname=CASE WHEN nickname='' THEN ? ELSE nickname END WHERE id=?",
                            (
                                min(times) if times else None,
                                max(lasts) if lasts else None,
                                bool(raw.get("known")),
                                raw.get("nickname") or "",
                                old["id"],
                            ),
                        )
                    else:
                        conn.execute(
                            "INSERT INTO devices(network_id,mac,ip,hostname,vendor,nickname,known,reviewed,first_seen,observed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (
                                network_id,
                                mac,
                                raw.get("ip"),
                                meaningful(raw.get("hostname")),
                                meaningful(raw.get("vendor")),
                                raw.get("nickname") or "",
                                bool(raw.get("known")),
                                not raw.get("is_new", 1),
                                first,
                                last,
                            ),
                        )
                conn.execute(
                    "INSERT INTO meta VALUES (?,?)",
                    (
                        key,
                        json.dumps({"rows": len(rows), "merged": merged, "at": now()}),
                    ),
                )
            return {"rows": len(rows), "merged": merged}

    def restore(self, source):
        with self.lock:
            if self.active():
                raise ValueError("Wait for the active scan to finish before restoring.")
            incoming = sqlite3.connect(
                Path(source).resolve().as_uri() + "?mode=ro", uri=True
            )
            try:
                if incoming.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Backup integrity check failed.")
                if incoming.execute(
                    "SELECT value FROM meta WHERE key='schema'"
                ).fetchone() != ("1",):
                    raise ValueError("Unsupported backup version.")
                if incoming.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type IN ('trigger','view')"
                ).fetchone()[0]:
                    raise ValueError("Unexpected database objects in backup.")
                with self.connection() as current:
                    for table in (
                        "networks",
                        "scans",
                        "devices",
                        "observations",
                        "events",
                        "legacy_records",
                        "meta",
                    ):
                        expected = [
                            (r[1], r[2])
                            for r in current.execute(f"PRAGMA table_info({table})")
                        ]
                        actual = [
                            (r[1], r[2])
                            for r in incoming.execute(f"PRAGMA table_info({table})")
                        ]
                        if actual != expected:
                            raise ValueError(
                                "Backup schema does not match this version."
                            )
                if incoming.execute("PRAGMA foreign_key_check").fetchone():
                    raise ValueError("Backup contains broken references.")
                self.backup()
                with self.connection() as current:
                    incoming.backup(current)
                self.recover()
                self.set_settings({"schedule_minutes": 0})
            finally:
                incoming.close()

    def prune(self, days):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM observations WHERE observed_at<? AND scan_id NOT IN (SELECT MAX(id) FROM scans WHERE status IN ('completed','partial') GROUP BY network_id)",
                (cutoff,),
            )
            # Device summaries and scan totals survive observation retention.

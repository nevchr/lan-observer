import hashlib
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from lan_observer import create_app, discovery
from lan_observer.__main__ import InstanceLock, create_local_server
from lan_observer.domain import canonical_mac, presence, scope_for

ADAPTER = dict(
    index=7,
    name="Test Ethernet",
    guid="test-guid",
    mac="02:00:00:00:00:10",
    ip="192.0.2.10",
    prefix=24,
    profile="Fixture",
    gateway="192.0.2.1",
    key="test-network",
)


def observation(
    ip="192.0.2.20", mac="02:00:00:00:00:20", evidence="response", **fields
):
    return dict(ip=ip, mac=mac, evidence=evidence, **fields)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.app = create_app(
            {
                "TESTING": True,
                "DATA_DIR": self.directory,
                "SECRET_KEY": "fixture-secret",
                "INTERFACE_PROVIDER": lambda: [ADAPTER],
            }
        )
        self.store = self.app.extensions["store"]
        self.coordinator = self.app.extensions["coordinator"]
        self.network = self.store.add_network("Test network", ADAPTER, "192.0.2.0/24")
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["csrf"] = "fixture-token"

    def tearDown(self):
        self.coordinator.close()
        self.temp.cleanup()

    def post(self, url, data=None, **kwargs):
        return self.client.post(
            url, data=dict(csrf_token="fixture-token", **(data or {})), **kwargs
        )

    def save(self, observations, status="completed", network=None):
        network_id = network or self.network
        scan_id = self.store.create_scan(
            network_id, self.store.network(network_id)["scope"], 254
        )
        self.store.finish(
            scan_id, dict(status=status, observations=observations, warnings=[])
        )
        return scan_id

    def test_all_main_pages_render_and_security_headers(self):
        for url in ["/", "/settings", "/history", "/diagnostics"]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                self.assertIn(
                    "frame-ancestors 'none'",
                    response.headers["Content-Security-Policy"],
                )

    def test_first_run_prioritizes_network_setup(self):
        with self.store.connection() as conn:
            conn.execute("DELETE FROM networks")
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Set up a network", html)
        self.assertNotIn('class="scan-action"', html)
        self.assertNotIn('id="inventory-title"', html)

    def test_single_saved_network_is_ready_to_scan(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn(
            f'value="{self.network}" data-name="Test network" data-scope="192.0.2.0/24" selected',
            html,
        )
        self.assertIn("Selected: Test network · 192.0.2.0/24", html)
        self.assertIn("Recently confirmed", html)

    def test_scan_changes_identify_devices_and_translate_evidence(self):
        scan_id = self.save(
            [
                observation(hostname="speaker"),
                observation(
                    ip="192.0.2.30",
                    mac="02:00:00:00:00:30",
                    evidence="cache",
                    hostname="printer",
                ),
            ]
        )
        html = self.client.get(f"/scans/{scan_id}").get_data(as_text=True)
        changes = html.split("Changes in this scan", 1)[1].split("Observations", 1)[0]
        self.assertIn("speaker", changes)
        self.assertIn("printer", changes)
        self.assertIn("Responded in scan", html)
        self.assertIn("Cached · uncertain", html)

    def test_old_edit_event_uses_friendly_field_names(self):
        self.save([observation()])
        device_id = self.store.devices()[0]["id"]
        with self.store.connection() as conn:
            self.store.event(
                conn, device_id, None, "Edited", "Changed: nickname, known"
            )
        html = self.client.get(f"/devices/{device_id}").get_data(as_text=True)
        self.assertIn("Updated device name and recognition.", html)
        self.assertNotIn("Changed: nickname", html)

    def test_b01_cache_not_confirmed_presence(self):
        self.save([observation(evidence="cache")])
        row = self.store.devices()[0]
        self.assertIsNone(row["last_confirmed"])
        self.assertEqual(presence(row), "Cached · uncertain")

    def test_b02_canonical_mac_preserves_recognition_name(self):
        self.save([observation()])
        row = self.store.devices()[0]
        self.store.edit(row["id"], "Kitchen speaker", "notes", True, True, False)
        self.save([observation(mac="02-00-00-00-00-20", ip="192.0.2.50")])
        self.assertEqual(len(self.store.devices()), 1)
        self.assertEqual(self.store.devices()[0]["nickname"], "Kitchen speaker")
        self.assertEqual(self.store.devices()[0]["known"], 1)

    def test_b03_ip_only_observation_is_visible(self):
        self.save([observation(mac=None)])
        self.assertEqual(len(self.store.devices()), 0)
        self.assertEqual(len(self.store.query("SELECT * FROM observations")), 1)
        self.assertIn(b"192.0.2.20", self.client.get("/").data)

    def test_b04_name_roundtrip_independent_of_recognition(self):
        self.save([observation()])
        row = self.store.devices()[0]
        self.assertEqual(
            self.post(
                f"/devices/{row['id']}", {"nickname": "Kitchen speaker"}
            ).status_code,
            303,
        )
        html = self.client.get(f"/devices/{row['id']}").get_data(as_text=True)
        self.assertIn('value="Kitchen speaker"', html)
        self.post(
            f"/devices/{row['id']}", {"nickname": "Kitchen speaker", "known": "on"}
        )
        self.assertEqual(self.store.devices()[0]["nickname"], "Kitchen speaker")

    def test_b05_other_network_not_modified(self):
        self.save([observation()])
        previous = self.store.devices()[0]
        network = self.store.add_network("Other network", ADAPTER, "198.51.100.0/24")
        self.save([], network=network)
        self.assertEqual(self.store.device(previous["id"]), previous)

    def test_b05_partial_scope_not_reconciled_outside_coverage(self):
        self.save([observation(ip="192.0.2.200")])
        with self.store.connection() as conn:
            conn.execute(
                "UPDATE networks SET scope=? WHERE id=?", ("192.0.2.0/25", self.network)
            )
        self.save([])
        self.assertEqual(self.store.devices()[0]["evidence"], "response")

    def test_b06_hostname_failure_is_optional(self):
        with patch.object(discovery, "powershell", side_effect=OSError("DNS failed")):
            self.assertIsNone(discovery.hostname("192.0.2.20"))

    def test_b06_worker_exception_records_failure(self):
        self.coordinator.scanner = lambda *a, **k: (_ for _ in ()).throw(
            OSError("fixture failure")
        )
        scan_id, created = self.coordinator.start(self.network)
        self.coordinator.worker.join(5)
        self.assertEqual(
            self.store.query("SELECT status FROM scans WHERE id=?", (scan_id,))[0][
                "status"
            ],
            "failed",
        )

    def test_b07_failed_scan_preserves_snapshot(self):
        self.save([observation()])
        before = self.store.devices()
        self.save([], status="failed")
        self.assertEqual(self.store.devices(), before)

    def test_b07_neighbor_failure_not_success(self):
        with (
            patch.object(discovery, "probe", return_value=False),
            patch.object(discovery, "neighbors", side_effect=OSError("fixture")),
        ):
            result = discovery.scan(
                ADAPTER,
                "192.0.2.10/32",
                threading.Event(),
                lambda *a: None,
                resolve_names=False,
            )
        self.assertEqual(result["status"], "failed")

    def test_b08_single_flight(self):
        entered, release = threading.Event(), threading.Event()

        def scanning(*args, **kwargs):
            entered.set()
            release.wait(5)
            return dict(status="completed", observations=[], warnings=[])

        self.coordinator.scanner = scanning
        first, created = self.coordinator.start(self.network)
        try:
            self.assertTrue(entered.wait(2))
            second, created_again = self.coordinator.start(self.network)
            self.assertEqual(first, second)
            self.assertFalse(created_again)
        finally:
            release.set()
            self.coordinator.worker.join(5)

    def test_b08_database_enforces_single_active_scan(self):
        self.store.create_scan(self.network, "192.0.2.0/24", 254)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.create_scan(self.network, "192.0.2.0/24", 254)

    def test_b09_missing_token_rejected(self):
        self.assertEqual(
            self.client.post("/scans", data={"network_id": self.network}).status_code,
            403,
        )
        self.assertIsNone(self.store.active())

    def test_b09_wrong_origin_rejected(self):
        self.assertEqual(
            self.post(
                "/scans",
                {"network_id": self.network},
                headers={"Origin": "https://example.invalid"},
            ).status_code,
            403,
        )

    def test_b09_opaque_browser_origin_still_requires_session_token(self):
        self.assertEqual(
            self.client.post("/data/export", headers={"Origin": "null"}).status_code,
            403,
        )
        self.assertEqual(
            self.post("/data/export", headers={"Origin": "null"}).status_code, 200
        )

    def test_b09_wrong_host_rejected(self):
        self.assertEqual(
            self.client.get("/", headers={"Host": "example.invalid"}).status_code, 400
        )

    def test_b10_path_absolute(self):
        self.assertTrue(self.store.path.is_absolute())
        self.assertEqual(self.store.path.parent, self.directory.resolve())

    def test_b11_enrichment_failure_preserves_previous_values(self):
        self.save([observation(hostname="speaker", vendor="Example")])
        self.save([observation(hostname="Unknown", vendor=None)])
        row = self.store.devices()[0]
        self.assertEqual((row["hostname"], row["vendor"]), ("speaker", "Example"))

    def test_b12_stale_snapshot_labeled(self):
        self.assertEqual(
            presence(
                dict(evidence="response", observed_at="2000-01-01T00:00:00+00:00")
            ),
            "Stale observation",
        )

    def test_b13_completion_failure_rolls_back_devices_and_evidence(self):
        scan_id = self.store.create_scan(self.network, "192.0.2.0/24", 254)
        with self.store.connection() as conn:
            conn.execute(
                "CREATE TRIGGER fail_completion BEFORE UPDATE OF finished ON scans BEGIN SELECT RAISE(ABORT,'fixture failure'); END"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.finish(
                scan_id,
                dict(status="completed", observations=[observation()], warnings=[]),
            )
        self.assertEqual(self.store.devices(), [])
        self.assertEqual(self.store.query("SELECT * FROM observations"), [])
        self.assertEqual(self.store.active()["id"], scan_id)

    def test_b14_empty_vendor_list_scans_offline(self):
        with (
            patch.object(discovery, "probe", return_value=True),
            patch.object(discovery, "neighbors", return_value={}),
            patch(
                "socket.create_connection",
                side_effect=AssertionError("Unexpected egress"),
            ),
        ):
            result = discovery.scan(
                ADAPTER,
                "192.0.2.10/32",
                threading.Event(),
                lambda *a: None,
                resolve_names=False,
            )
        self.assertIsNone(result["observations"][0]["vendor"])

    def test_b16_visible_name_label(self):
        self.save([observation()])
        html = self.client.get(f"/devices/{self.store.devices()[0]['id']}").get_data(
            as_text=True
        )
        self.assertIn('<label for="nickname">Device name</label>', html)

    def test_b17_debug_disabled(self):
        self.assertFalse(self.app.debug)

    def test_b18_prefix_ranges_and_bounds(self):
        self.assertEqual(len(list(scope_for(dict(ADAPTER, prefix=23)).hosts())), 510)
        self.assertEqual(len(list(scope_for(dict(ADAPTER, prefix=25)).hosts())), 126)
        with self.assertRaises(ValueError):
            scope_for(ADAPTER, "198.51.100.0/24")
        with self.assertRaises(ValueError):
            scope_for(dict(ADAPTER, prefix=16))

    def test_b18_changed_network_refused(self):
        self.coordinator.provider = lambda: [dict(ADAPTER, key="different-network")]
        with self.assertRaises(ValueError):
            self.coordinator.start(self.network)

    def test_mac_validation_and_multicast(self):
        self.assertEqual(canonical_mac("AA-BB-CC-DD-EE-FF"), "aa:bb:cc:dd:ee:ff")
        self.assertIsNone(canonical_mac("ff:ff:ff:ff:ff:ff"))
        with self.assertRaises(ValueError):
            canonical_mac("not a mac")

    def test_out_of_scope_result_rejected_atomically(self):
        with self.assertRaises(ValueError):
            self.save([observation(ip="198.51.100.10")])
        self.assertEqual(self.store.devices(), [])

    def test_partial_result_does_not_infer_absence(self):
        self.save([observation()])
        before = self.store.devices()
        self.save([], status="partial")
        self.assertEqual(self.store.devices(), before)

    def test_repeated_completion_rejected(self):
        scan_id = self.save([observation()])
        with self.assertRaises(ValueError):
            self.store.finish(
                scan_id, dict(status="completed", observations=[], warnings=[])
            )

    def test_cancel_does_not_publish_observations(self):
        scan_id = self.store.create_scan(self.network, "192.0.2.0/24", 254)
        self.store.progress(scan_id, "canceling", 2)
        self.store.finish(
            scan_id, dict(status="completed", observations=[observation()], warnings=[])
        )
        self.assertEqual(self.store.devices(), [])
        self.assertEqual(
            self.store.query("SELECT status FROM scans")[0]["status"], "canceled"
        )

    def test_search_and_numeric_ip_sort(self):
        self.save(
            [
                observation(ip="192.0.2.100"),
                observation(ip="192.0.2.9", mac="02:00:00:00:00:09"),
            ]
        )
        html = self.client.get("/?sort=ip").get_data(as_text=True)
        self.assertLess(html.index("192.0.2.9"), html.index("192.0.2.100"))
        self.assertNotIn(
            "192.0.2.9</span>",
            self.client.get("/?q=192.0.2.100").get_data(as_text=True),
        )

    def test_html_escape_and_sql_values(self):
        self.save([observation()])
        row = self.store.devices()[0]
        self.post(
            f"/devices/{row['id']}",
            {
                "nickname": "<script>alert(1)</script>",
                "notes": "'); DROP TABLE devices;--",
            },
        )
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("&lt;script&gt;", html)
        self.assertEqual(len(self.store.devices()), 1)

    def test_validation_keeps_submitted_name(self):
        self.save([observation()])
        row = self.store.devices()[0]
        result = self.post(
            f"/devices/{row['id']}", {"nickname": "retain input", "notes": "x" * 2001}
        )
        self.assertEqual(result.status_code, 400)
        self.assertIn(b'value="retain input"', result.data)
        self.assertEqual(self.post("/devices/9999").status_code, 404)

    def test_archive_and_reappearance(self):
        self.save([observation()])
        row = self.store.devices()[0]
        self.store.edit(row["id"], "Name", "", True, True, True)
        self.assertNotIn(b">Name</a>", self.client.get("/").data)
        self.assertIn(b">Name</a>", self.client.get("/?state=archived").data)
        self.save([observation()])
        self.assertEqual(self.store.devices()[0]["archived"], 0)
        self.assertEqual(self.store.devices()[0]["reviewed"], 0)

    def test_backup_restore_and_rollback_copy(self):
        self.save([observation()])
        backup = self.store.backup()
        row = self.store.devices()[0]
        self.store.edit(row["id"], "Later edit", "", False, False, False)
        self.store.restore(backup)
        self.assertEqual(self.store.devices()[0]["nickname"], "")
        self.assertEqual(self.store.setting("schedule_minutes"), "0")
        self.assertGreaterEqual(len(list((self.directory / "backups").glob("*.db"))), 2)

    def test_restore_while_scanning_rejected(self):
        backup = self.store.backup()
        self.store.create_scan(self.network, "192.0.2.0/24", 254)
        with self.assertRaises(ValueError):
            self.store.restore(backup)

    def test_legacy_import_is_readonly_deduplicated_and_repeat_safe(self):
        source = self.directory / "old.db"
        with sqlite3.connect(source) as conn:
            conn.execute(
                "CREATE TABLE devices(mac TEXT,ip TEXT,first_seen TEXT,last_seen TEXT,known INTEGER,nickname TEXT)"
            )
            conn.executemany(
                "INSERT INTO devices VALUES (?,?,?,?,?,?)",
                [
                    (
                        "02:00:00:00:00:20",
                        "192.0.2.20",
                        "2020-01-01",
                        "2021-01-01",
                        1,
                        "Speaker",
                    ),
                    (
                        "02-00-00-00-00-20",
                        "192.0.2.21",
                        "2019-01-01",
                        "2022-01-01",
                        0,
                        "Conflict",
                    ),
                ],
            )
        conn.close()
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        result = self.store.import_legacy(source)
        self.assertEqual(result, {"rows": 2, "merged": 1})
        self.assertEqual(len(self.store.devices()), 1)
        self.assertEqual(self.store.devices()[0]["known"], 0)
        self.assertEqual(len(self.store.query("SELECT * FROM legacy_records")), 2)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        self.assertIsNone(self.store.devices()[0]["last_confirmed"])
        with self.assertRaises(ValueError):
            self.store.import_legacy(source)

    def test_recovery_marks_interrupted(self):
        self.store.create_scan(self.network, "192.0.2.0/24", 254)
        self.store.recover()
        self.assertIsNone(self.store.active())
        self.assertEqual(
            self.store.query("SELECT status FROM scans")[0]["status"], "interrupted"
        )

    def test_legacy_assignment_retains_identity_and_user_name(self):
        legacy_network = self.store.add_network("Legacy", {}, "")
        with self.store.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO devices(network_id,mac,nickname,known) VALUES (?,?,?,1)",
                (legacy_network, "02:00:00:00:00:20", "Imported speaker"),
            )
            device_id = cursor.lastrowid
        self.store.assign_legacy(device_id, self.network)
        self.save([observation()])
        self.assertEqual(self.store.devices()[0]["nickname"], "Imported speaker")
        self.assertEqual(self.store.devices()[0]["known"], 1)

    def test_legacy_assignment_conflict_preserves_original(self):
        self.save([observation()])
        existing_id = self.store.devices()[0]["id"]
        self.store.edit(existing_id, "Current name", "", False, False, False)
        legacy_network = self.store.add_network("Legacy", {}, "")
        with self.store.connection() as conn:
            device_id = conn.execute(
                "INSERT INTO devices(network_id,mac,nickname,known) VALUES (?,?,?,1)",
                (legacy_network, "02:00:00:00:00:20", "Original name"),
            ).lastrowid
        self.assertEqual(self.store.assign_legacy(device_id, self.network), existing_id)
        self.assertEqual(self.store.device(device_id)["nickname"], "Original name")
        self.assertEqual(self.store.device(device_id)["archived"], 1)
        self.assertEqual(self.store.device(existing_id)["nickname"], "Current name")

    def test_scan_comparison_reports_absence_only_after_completion(self):
        self.save([observation()])
        failed = self.save([], status="failed")
        self.assertNotIn(
            b"No fresh response in this scan", self.client.get(f"/scans/{failed}").data
        )
        completed = self.save([])
        self.assertIn(
            b"No fresh response in this scan",
            self.client.get(f"/scans/{completed}").data,
        )

    def test_scheduler_runs_once_after_missed_interval(self):
        self.store.set_settings(
            {"schedule_minutes": 5, "schedule_network": self.network}
        )
        with (
            patch.object(
                self.coordinator.stop_event, "wait", side_effect=[False, False, True]
            ),
            patch("lan_observer.services.time.monotonic", side_effect=[0, 0, 301, 301]),
            patch.object(self.coordinator, "start") as start,
        ):
            self.coordinator._schedule()
        start.assert_called_once_with(self.network)

    def test_observation_retention_keeps_latest_network_snapshot(self):
        first = self.save([observation()])
        self.save([observation()])
        with self.store.connection() as conn:
            conn.execute(
                "UPDATE observations SET observed_at='2000-01-01T00:00:00+00:00'"
            )
        self.store.prune(90)
        rows = self.store.query("SELECT scan_id FROM observations")
        self.assertEqual(len(rows), 1)
        self.assertNotEqual(rows[0]["scan_id"], first)

    def test_vendor_csv_local_import(self):
        content = b"Assignment,Organization Name\nAABBCC,Example Vendor\n"
        result = self.post(
            "/data/vendors", {"vendors": (io.BytesIO(content), "oui.csv")}
        )
        self.assertEqual(result.status_code, 303)
        self.assertEqual(
            json.loads((self.directory / "vendors.json").read_text()),
            {"AABBCC": "Example Vendor"},
        )

    def test_diagnostics_redacts_identifiers(self):
        self.save([observation()])
        result = self.client.get("/diagnostics").data
        self.assertNotIn(b"192.0.2", result)
        self.assertNotIn(b"Test network", result)

    def test_instance_lock_prevents_second_launcher(self):
        with InstanceLock(self.directory / "app.lock"):
            with self.assertRaises(RuntimeError):
                with InstanceLock(self.directory / "app.lock"):
                    pass

    def test_launcher_rejects_second_listener_on_same_port(self):
        server = create_local_server(self.app, 0)
        port = server.socket.getsockname()[1]
        try:
            with self.assertRaises(OSError):
                create_local_server(self.app, port)
        finally:
            server.task_dispatcher.shutdown()
            server.close()


if __name__ == "__main__":
    unittest.main()

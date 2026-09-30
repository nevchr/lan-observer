# LAN Observer overhaul status

Updated 2026-09-22. This is the implementation status for version 0.2.0. [AUDIT.md](AUDIT.md), [BUG_LOG.md](BUG_LOG.md), and [OVERHAUL_PLAN.md](OVERHAUL_PLAN.md) document the original `d3c662c` prototype and the intended scope; their original findings are historical.

## Implemented

All 18 original bug findings have corresponding code changes and targeted regression coverage in `tests/test_app.py` (B15 also has browser-width verification). The new app uses network-scoped timestamped evidence, canonical MAC identities, explicit scan outcomes and single-flight ownership, bounded Windows discovery, atomic result writes, independent user names/recognition, a stable local data directory, local request protection, and a debug-off Waitress launcher. Cached neighbors and old snapshots are visibly uncertain, and scan failures do not publish absence.

The planned product additions are also implemented: first-run network selection; searchable, filterable inventory; device detail/editing; scan progress and cancellation; history and change review; archive/restore; opt-in scheduling; configurable detail retention; JSON export; SQLite backup/restore; read-only legacy import; local CSV manufacturer lookup; redacted diagnostics; responsive UI; source and Windows folder/ZIP packaging.

The old `devices.db` is never overwritten automatically. Import places its records in an unassigned legacy network for explicit linking. The old database and its backup remain usable for rollback; restore of the new schema creates a pre-restore backup.

## Verification completed

- 52 focused regression tests passed on local Windows Python 3.12, including all B01–B18 paths, migration conflicts, backup/restore, scheduling recovery, launcher/port guards, and the follow-up visual fixes. The isolated fresh Python environment passed the earlier suite before the final tests were added.
- A six-row import of the actual legacy database into isolated temporary app data retained all six raw records and left the source checksum unchanged. This did not switch or modify the user's active data.
- Synthetic browser journeys covered first run, network setup, device rename/recognition, scan progress/cancel, Settings, and long hostnames at 320, 390, 768, and 1280 CSS pixels, without horizontal overflow. The follow-up [visual audit](VISUAL_AUDIT.md) records eight resolved findings and the remaining zoom/screen-reader limits. Current screenshots are in `screenshots/`.
- A bounded local probe to this computer's own LAN address succeeded, and the Windows provider listed usable adapters. A full LAN sweep was intentionally not run.
- A clean local Python 3.12 install and package builds succeeded. An earlier dependency advisory check reported no known vulnerabilities; a later repeat could not reach PyPI under the sandbox network policy, so current advisory status still needs a connected CI check. Synthetic inventory load testing at 1,000 devices recorded median 20.45 ms and p95 26.9 ms across 20 page requests; see `audit/overhaul-data-checks.json`.
- The Windows folder/ZIP package was exercised by `scripts/smoke_package.py`: six HTTP endpoints returned 200 with security headers, and duplicate-instance and occupied-port attempts were rejected. Results are saved to `audit/overhaul-package-checks.json`.

## Remaining release validation

This is a local beta, not a production-certified release. A controlled live-device matrix is still needed for sleeping and ICMP-blocking devices, Wi-Fi/Ethernet/VPN changes, duplicate address ranges, and multi-adapter routing. A long scheduled run and sleep/resume cycle have not been measured. Browser verification did not establish 200% zoom, screen-reader operation, physical-device behavior, or a complete accessibility audit. A separate clean Windows machine, Python 3.13 CI run, upgrade/uninstall lifecycle, signed installer, and package-signing review remain open. The repository has no chosen license; a license decision is needed before a public open-source release. No CI run or public release is claimed from local checks alone.

No GitHub issues, pull request, push, or public release was created as part of this local implementation.

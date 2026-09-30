# LAN Observer audit

Audit date: 2026-09-22. Baseline: `d3c662cc48abec5858899d74208e7c34bffe8122` on local and GitHub `main`.

**Historical baseline:** The findings below describe the original prototype. The 0.2.0 implementation and current limits are tracked in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). The baseline statements about open bugs and missing tooling are not descriptions of the current working tree.

LAN Observer is a useful prototype with a simple, understandable implementation. Its largest problem is the reliability of the information it presents: “online,” device identity, scan completion, and saved names can all be misleading. I would fix these foundations before adding automated monitoring or redesigning the dashboard.

The recommended overhaul keeps Python, Flask, SQLite, and a local browser interface. The product should answer three questions clearly: **What was seen on this network? What changed? How recent and reliable is that observation?**

## Deliverables

- [Bug log](BUG_LOG.md): 18 open findings with severity, evidence, reproduction, and acceptance criteria.
- [Overhaul plan](OVERHAUL_PLAN.md): product scope, screen design, architecture, migration strategy, milestones, and release gates.
- [Reproduction harness](audit/reproduce.py): 14 isolated backend/dependency reproductions and four positive controls.
- [Recorded results](audit/results.json), [environment checks](audit/environment-checks.json), and [browser measurements](audit/browser-checks.json).
- Synthetic screenshots: [desktop](audit/desktop-baseline.png) and [390px mobile](audit/mobile-baseline.png).

Bugs are logged locally in this repository. No GitHub issues were created, no code was pushed, and no application fixes were made during this planning audit.

## Most consequential findings

| Priority | Finding | Consequence |
| --- | --- | --- |
| P1 | B01: ARP cache entries become online observations | A cached entry can keep an absent device “online” and advance its last-seen timestamp. |
| P1 | B02: MAC addresses are not normalized | One physical device can get a second identity and appear unrecognized. |
| P1 | B03: devices without a MAC are discarded | A responding device may disappear from the dashboard entirely. |
| P1 | B05–B08: scan scope, errors, and concurrent results are unsafe | Failed or older scans can change current device state incorrectly. |
| P1 | B09: state-changing routes accept unrelated origins and hosts | The server lacks protections expected for a browser-accessible local service. Browser exploitability was not tested. |
| P2 | B04: names on unrecognized devices are hidden and can be erased | Saving a name appears ineffective; later recognizing the device can delete it. |
| P2 | B12: old snapshots continue to say online | The display implies current presence even when its evidence is old. |

Other logged work covers data location, metadata preservation, transaction boundaries, vendor-download disclosure, mobile overflow, accessibility, the debug launcher, and interface selection.

P1 means fix before relying on regular monitoring or distributing an overhaul. P2 means a meaningful reliability, usability, or release defect. No P0 finding was established. These are project priorities, not CVSS scores.

## What was verified

- Read every application source file, template, stylesheet, dependency manifest, README, and ignore rules; checked Git status and remote metadata.
- GitHub's default branch matched the local commit. The GitHub issue search returned no existing issues at audit time.
- Reproduced B01–B14 with synthetic network observations, controlled faults, Flask test clients, and temporary SQLite databases. B08 used two overlapping requests and a controlled completion order.
- All four positive controls passed: HTML escaping, SQL values treated as data, recognition/name persistence with a stable MAC across an IP change, and an empty dashboard returning HTTP 200.
- Syntax compilation succeeded for the three app modules and audit harness. All 19 installed distribution versions matched the manifest pins. This is not a dependency vulnerability scan or a clean-install test.
- Reviewed the actual template and CSS in a local browser, served with synthetic devices. Inspected desktop, 390×844 populated, and 320×800 empty layouts. Measured overflow and label structure; no browser warning/error logs were returned during the inspected pages.
- The real `devices.db` checksum was unchanged during the isolated backend checks. The fixture server redirected database access to a temporary path before importing the app. No live subnet scan or vendor download was performed.

The existing `.venv` launcher failed with an access-denied error for its Microsoft Store Python path. Tests used bundled Python 3.12.14 with the existing project packages through `PYTHONPATH`, including Flask 3.1.3 and mac-vendor-lookup 0.1.15. This proves the recorded test behavior in that environment; it does not certify the original Python 3.13 launcher or native dependency compatibility on a clean machine.

## What remains unverified

- Actual discovery precision/recall against a controlled live network, including sleeping and ICMP-blocking devices.
- Windows Wi-Fi/Ethernet/VPN routing, multiple adapters, duplicate private address ranges, and real subnet masks.
- Long-running scanning, sleep/resume, host reboot, SQLite contention under sustained use, and resource consumption.
- Real browser cross-origin/local-network request restrictions and DNS-rebinding behavior. B09 verifies missing server checks, not a demonstrated browser exploit.
- Screen-reader operation, complete keyboard flows, 200% zoom, physical mobile devices, and a full WCAG audit.
- Clean dependency installation, dependency CVEs, macOS/Linux behavior, installer lifecycle, signing, release packaging, and backup restoration.

## Product and maintenance assessment

**Keep:** the restrained dark visual direction, readable code, loopback binding, parameterized queries, automatic template escaping, local persistence, and explicit recognized/unrecognized distinction. The current code is small enough to evolve without a wholesale framework replacement.

**Improve:** replace the binary live-status implication with timestamped observations; treat identity and network scope explicitly; give scans lifecycle states; preserve existing data on failure; and separate editable names from discovery metadata. A unified inventory will scale better than two groups of large cards with a form on every card.

**Missing product behavior:** first-run guidance, interface/range visibility, search/filter/sort, device details, save feedback, scan progress/retry/cancel, history, archive/restore, backup/export, and explicit new-device acknowledgment. These are planned enhancements, not all existing bugs. “NEW DEVICE” currently persists until recognition; define it as “Needs review” or introduce a separate review state rather than assuming time-based semantics.

**Maintenance gaps:** no pre-existing tests, CI, versioned migrations, supported-runtime declaration, clean-install verification, structured logs, packaging, or license file was found in the tracked baseline. Dependencies are a flat pinned environment export, and `requirements.txt` uses UTF-16 with a BOM. Normalize source/manifests to UTF-8 during tooling work; this encoding alone is not established as a pip installation bug. Choose an intended license before distributing the overhaul; do not assume one from the repository being public.

## Recommended next implementation slice

Start with milestone M1 in the [overhaul plan](OVERHAUL_PLAN.md): regression tests, stable database location and reversible migrations, canonical identities, reliable name editing, local request protection, and a supported debug-off launcher. Then implement the scanner lifecycle and evidence model before scheduling scans. UI work should follow those contracts so the redesigned dashboard displays trustworthy data.

Supporting primary references: [Flask security guidance](https://flask.palletsprojects.com/en/stable/web-security/), [Flask deployment guidance](https://flask.palletsprojects.com/en/stable/deploying/), [Waitress on Windows](https://flask.palletsprojects.com/en/stable/deploying/waitress/), [Python UUID behavior](https://docs.python.org/3/library/uuid.html#uuid.getnode), [W3C form labeling](https://www.w3.org/WAI/tutorials/forms/labels/), and [W3C contrast requirements](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).

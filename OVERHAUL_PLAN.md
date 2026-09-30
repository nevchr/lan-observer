# LAN Observer overhaul plan

Prepared 2026-09-22 from the [audit](AUDIT.md) of commit `d3c662c`. This is the original design plan. The 0.2.0 implementation covers the planned product and engineering work; [current status](IMPLEMENTATION_STATUS.md) records what was verified and which release gates remain open. Estimates and milestone wording below are historical planning material.

## Product direction

Build a dependable Windows-first local network inventory and observation dashboard for one person managing a home or small lab network. The user should be able to choose a network, discover devices, give them meaningful names, review new observations, and understand changes without confusing a failed scan with a disconnected device.

Keep Python, Flask, SQLite, and a browser UI. Prefer server-rendered HTML with small JavaScript modules for scan progress, filtering, and device editing. The current scope does not require React, Electron, Redis, a cloud backend, or a paid service. Reconsider a framework only when a concrete product requirement justifies its maintenance cost.

The first supported release targets Windows with IPv4 network discovery. macOS/Linux scanner backends, IPv6 discovery, remote multi-user access, SNMP integrations, and router APIs are later scope. Do not present discovery as traffic monitoring, bandwidth measurement, vulnerability detection, or proof that a device is safe.

## User journeys and screen design

### 1. First launch and network selection

Show a short explanation of what is observed and where the inventory is stored. List usable adapters with friendly name, local IPv4 address, prefix/range, and connectivity. Preselect a suitable active LAN adapter only when unambiguous; keep the selection editable. Show an explicit range and host count before scanning.

Offer a clear “Scan this network” action. A disconnected machine gets a useful empty state and Refresh adapters action. A VPN or unusually large range gets an explanation and a deliberate range selection, not an automatic sweep of guessed addresses. Default scanning remains limited to an approved directly attached network; add a bounded subrange when the attached network is too large.

Use human-friendly data location and privacy copy, with separate vendor-list update controls. Never display a successful scan simply because the host computer could be included.

### 2. Overview

The header contains the selected network, interface, last successful observation time, and Scan action. Beneath it, a scan status region shows idle, queued, discovering, enriching, completed, partial, failed, canceled, or interrupted state. Progress shows completed probes out of planned probes; enrichment is a separate phase. Do not invent a percentage for work whose total is unknown.

Place network-wide statistics above the inventory, not inside “Recognized Devices.” Suggested metrics:

- Seen in latest successful scan.
- Needs review.
- Recognized devices on this network.
- Total recorded on this network.

Show the age of the snapshot next to these counts. Filters and metric clicks share the same scope. A stale or partial snapshot gets a visible, non-alarming explanation. No automatic “live” label without continuous evidence.

### 3. Device inventory

Use one searchable inventory with filters for presence, review state, recognition, and vendor. Search covers name, hostname, IP, MAC, and notes. Support numeric IP sorting, last-seen sorting, name sorting, clear filters, result counts, and a predictable default order. Keep query state in the URL so a detail view or reload does not lose context.

On desktop, use compact rows with columns for display name, observation status/time, IP, vendor, recognition, and details. On narrow screens, use a compact stacked row/card with the same essential data and one Details action. Put editing controls in the detail view instead of a full form on every device. Include pagination or measured incremental rendering for a large historical inventory; do not render thousands of full forms.

Default display name precedence: user name, meaningful hostname, vendor plus short identifier, then “Unidentified device.” Missing information uses null/typed state internally; distinguish “Not available,” “Lookup failed,” and “Not yet checked” where it helps the user.

Recognized means the user recognizes the device. Needs review means an observation has not been acknowledged. Neither label asserts security or ownership. Use a neutral or amber review treatment; reserve red for failures requiring attention.

### 4. Device details

Provide editable name, optional notes/tags, recognition toggle, and separate Mark reviewed action. Name fields have visible labels, clear length limits, and save success/error feedback. Keep unsaved input through recoverable errors and warn before navigation discards it.

Show the current and previous addresses, canonical MAC if known, whether it is locally administered, vendor with provenance, first seen, latest confirmed response, most recent observation, and associated networks. Explain uncertainty around private/randomized MACs. Provide copy controls for useful identifiers and ensure the confirmation is announced accessibly.

Display a timeline of observed changes: first observed, seen again, address/hostname changed, recognition/review edited, archived/restored. Connection intervals and uptime are estimates bounded by scans; do not imply that every connection or disconnection was observed.

Archive obsolete devices while retaining history. Provide restore. Treat deletion as an explicit separate data-management action with clear consequences. A newly seen archived identity should get a defined reappearance state rather than silently disappearing from view.

### 5. Scan history

Each scan records its network/range, start/end times, status, discovery counts, warnings, and evidence coverage. A detail page distinguishes newly observed devices, meaningful metadata changes, and devices not seen this time. A failed scan cannot generate mass-disconnection events.

History should support comparing successive successful scans. Explain that “not observed” can mean asleep, blocked probes, or unavailable evidence. Provide a Retry action from a failure and keep the previous successful inventory visible while retrying.

### 6. Settings and diagnostics

Group settings into Network, Scanning, Data, and About/Diagnostics. Support scan interval with scheduling off initially, bounded timeouts/ranges, observation retention, vendor-list updates, backup/restore, export, version, and data location. Support logs with rotation and a redacted diagnostic export; include device identifiers only when the user deliberately selects that data.

Do not introduce autostart or a background service silently. The first scheduled mode runs only while the app process is running. Clearly explain sleep/resume behavior. A later tray/background mode is a separate lifecycle feature.

## Visual and accessibility requirements

Preserve the restrained dark direction, but establish spacing, typography, surface, border, status, and focus tokens. Use a small, consistent set of icons with text labels for essential actions. Avoid decorative traffic graphs that have no underlying measurements.

- Design and test at 320, 390, 768, and 1280px, plus 200% zoom. Stack the mobile header and wrap long names and identifiers without page overflow.
- Target WCAG 2.2 AA: normal-text contrast at least 4.5:1, visible focus, semantic forms/tables/headings, and status conveyed with text as well as color. Validate non-text contrast and pointer target criteria where applicable.
- Every editable control has a persistent visible label and field-level error association. Repeated actions include device context in their accessible names.
- Scan/save feedback uses an appropriate live region without announcing every probe. A detail dialog, if used, handles initial focus, keyboard dismissal, and return focus correctly; a normal details page is an acceptable simpler default.
- Provide deliberate first-run, zero-results, empty-history, stale-data, scanning, partial, failed, disconnected, database-unavailable, and successful-save states.
- Check long names, missing fields, duplicate display names, 1,000 historical devices, keyboard-only operation, and NVDA on Windows. Screenshot review alone does not establish accessibility.

## Architecture

Keep a single local application process for the first release, with a supported WSGI server and one scanner coordinator. Use bounded worker execution for network work, not Flask request threads. Start the coordinator in explicit application startup, never as an import side effect. The development reloader must not create duplicate scan workers.

Suggested module structure:

```text
lan_observer/
  __init__.py             # create_app(config)
  config.py              # paths, local host policy, limits
  web/                   # page/API routes, validation, forms
  domain/                # device identity, observations, status rules
  storage/               # repositories, transactions, migrations
  discovery/
    interfaces.py        # adapter/route abstraction
    windows.py           # Windows discovery implementation
    probes.py            # bounded commands and evidence parsing
    enrichment.py        # DNS and vendor resolution
  services/
    scans.py             # job coordinator and reconciliation
    scheduler.py         # interval ownership and restart policy
    events.py            # meaningful changes, review state
  templates/             # shared device components
  static/                # CSS tokens, small JS modules
tests/
  unit/                  # parsing, identity, state semantics
  integration/           # storage, routes, jobs, migrations
  browser/               # main user journeys
```

Proposed HTTP contracts:

| Route | Behavior |
| --- | --- |
| `GET /` | Network overview and inventory, useful before JavaScript loads |
| `GET /devices/<id>` | Details and history by internal ID |
| `POST /devices/<id>` | Validated name/recognition/review edits with CSRF protection |
| `POST /scans` | Validate selected scope; return 202 with job ID or current active job |
| `GET /scans/<id>` | Page or structured status, counts, warnings, completion state |
| `POST /scans/<id>/cancel` | Request cancellation; remain truthful until work has stopped |
| `GET /history` | Paginated scan and observation history |
| `GET /settings` | Configuration and data-management controls |

Prefer short polling for the active scan initially; it is simple and fits the existing stack. Stop polling on completion/navigation and back off on errors. Preserve a usable HTML fallback. Add streaming only when a measured need justifies it.

### Data model

| Entity | Main responsibility |
| --- | --- |
| `networks` | Stable user-visible network ID, selected interface association, prefix/range, friendly name; subnet text alone is not identity |
| `devices` | Internal ID, user name, notes, recognition, reviewed time, archive state, creation metadata |
| `device_identifiers` | Canonical identifier/type/network association with confidence and validity times; preserve raw observed values |
| `scan_runs` | Network, requested scope, coverage, start/end, status, warnings, worker ownership/lease |
| `observations` | Scan ID, network/interface, IP/MAC, evidence source, observed time, response/enrichment outcomes; may initially have no device ID |
| `device_events` | Derived changes with source observation/scan IDs; explicit user-edit events |
| `schema_migrations` and settings | Applied migrations, stable configuration, retention policy |

Use timezone-aware UTC timestamps internally and format in the user's local time with an absolute-time option. Add indexes for network/latest scan, canonical identifiers, device/time, and review/archive filtering. Enable foreign keys per connection, short transactions, bounded lock waits, and exception-safe connection cleanup. Evaluate WAL with tests and keep the database in local app data outside the OneDrive source tree; document that SQLite files should not be used as a multi-host sync mechanism.

Do not persist ambiguous “Unknown” strings as identity keys. MAC normalization is necessary but not sufficient: randomized addresses, duplicates, virtual interfaces, and spoofing exist. Do not auto-merge devices based only on hostname, vendor, or a reused IP. Expose ambiguous merges for deliberate review.

### Scanner contract and presence semantics

Discovery returns a structured result containing network/interface identity, exact scope, observations, timestamps, warnings, and outcome. A plain list of devices cannot express partial failure sufficiently.

1. Resolve and validate the selected adapter, route and actual prefix; apply a host-count/time budget. Make exclusions and partial ranges explicit.
2. Collect current neighbor state for that interface, retaining evidence type and distinguishing cache records from fresh responses.
3. Perform bounded platform-specific probes. Use argument lists, subprocess timeouts, limited concurrency, and explicit return/output interpretation. Terminate lingering child work on cancellation.
4. Enrich observations with bounded DNS/vendor lookups. Enrichment can finish partially without invalidating discovery. Avoid an event loop shared unsafely across request threads.
5. Persist observations and successful completion metadata atomically. Reconcile only the scanned network and covered scope, with scan ordering enforced.

Suggested display rules:

| Evidence | Display | State consequence |
| --- | --- | --- |
| Fresh positive response | Seen in scan, with response time | Advances latest confirmed response |
| ARP/cache hint without fresh evidence | Cached observation / presence uncertain | Does not advance confirmed presence |
| Not seen in complete scan | Not observed in this scan | Preserve last-confirmed time; do not claim exact disconnection time |
| Failed or partial scan | Previous snapshot plus coverage warning | Do not infer absence outside successful coverage |
| Old snapshot or network no longer selected | Stale observation, with timestamp | Do not continue an unqualified online claim |
| IP response without stable identity | Unidentified observation | Visible and reviewable, without a fabricated permanent identity |

Set freshness thresholds as documented policy and test boundary times. Derive events from successful observations, with debounce for repeated absences if “likely offline” is later introduced. A scan of a different network never establishes that a device went offline on the previous one.

### Local security and privacy

Keep explicit loopback binding and debug off. Use trusted-host validation and CSRF-protected state changes backed by a persistent local secret stored outside the repo. Add validated field/body limits and useful bad-request/not-found responses. Protect export/restore actions as well as scans and edits. Add appropriate content-type/frame protections and a CSP compatible with local assets; avoid copying public-HTTPS policies blindly onto a loopback-only HTTP app.

Use Waitress as the initial Windows server candidate; Flask's documentation confirms native Windows support. Validate its configuration and version during implementation. No remote-access mode is part of the first release. Any future LAN exposure requires a separate authentication, TLS, authorization, and threat-model decision.

Make vendor-list updates explicit, bounded, and documented. Prefer a usable offline baseline with a data provenance/license review before redistribution. Record update age separately from vendor lookup success. Verify actual outbound activity in an offline/network-capture test; do not claim that dependency configuration alone proves no egress.

## Existing-data migration and rollback

Preserving the current `devices.db` is a release requirement.

1. Locate the legacy database deliberately and show its path/count summary. Never infer that an empty database means the user has no inventory.
2. Create a consistent SQLite backup through the backup API before mutation; store migration version and integrity results. Do not copy an actively written database file as the backup strategy.
3. Import into a new versioned schema in the stable app-data directory. Keep the original file unchanged until import and verification succeed.
4. Normalize MAC formats and detect duplicates. Preserve earliest first-seen and latest last-seen values. If merged rows disagree on user-entered names or recognition, keep the conflicting originals and produce a review item; do not discard a user decision silently.
5. Import legacy data into a clearly labeled legacy/unassigned network until the user maps it to the correct network. Existing rows do not contain sufficient evidence to infer network identity reliably.
6. Import online bits as historical snapshot data, never fresh presence. Keep nickname/recognition/new-state provenance. Do not invent scan history or exact connection intervals from first/last-seen fields.
7. Validate counts, canonical IDs, retained fields, constraints, and sample records against the backup. Record any merges and unresolved records in a local migration report.
8. Switch the configured path only after success. Keep an explicit rollback path to the untouched old app/data, test interrupted migration and repeated launch, and provide backup restore verification.

Legacy `app_state` may be absent or malformed. Migration must handle known baseline schema variants and report unsupported/corrupt cases clearly. Do not treat all SQLite `OperationalError` exceptions as harmless duplicate columns.

## Delivery milestones

Effort below is an initial engineering estimate for one experienced developer, including targeted tests. It is not a delivery promise. Live network behavior, Windows packaging, and migration edge cases can expand it. Re-estimate after M1 and M2. Each milestone should be a reviewable PR or small PR sequence, with user data preserved.

| Milestone | Scope and dependency | Acceptance gate | Estimate |
| --- | --- | --- | --- |
| M0: audit baseline | This audit, bug log, reproductions, synthetic screenshots | Findings and limits recorded; no app behavior changed | Completed |
| M1: safe foundation | App factory/config, stable data path, migration/backup foundation, MAC canonicalization, shared name editing fix, local request protection, atomic save contract, debug-off launcher, dependency/tooling baseline. B02/B04/B09/B10/B13/B17; B14 disclosure. | Existing names/recognition survive migration and rollback; forged requests rejected; launch from arbitrary cwd; regression tests pass | 4–6 days |
| M2: reliable discovery | Adapter/range provider, scoped observations, job ownership/order, bounded probes/enrichment, partial/failure semantics, current-versus-cached presence. Depends on M1. B01/B03/B05/B06/B07/B08/B11/B12/B14/B18. | Controlled network fixtures and live Windows matrix prove selected scope, no stale-cache online claims, no state loss on failure, finite cancellation/deadlines | 5–8 days |
| M3: usable interface | Overview, one searchable/filterable inventory, detail editing, first-run/error/stale states, scan progress, responsive/accessibility work. Depends on M2 data/API contract; design can begin during M1. B15/B16 and B12 presentation. | Main user journeys work at specified widths/zoom with keyboard and NVDA; long values do not overflow; feedback is clear | 4–6 days |
| M4: useful history and monitoring | Scan/device timeline, archive/restore, review semantics, opt-in schedules, in-app meaningful-change notifications, retention and exports. Depends on M2/M3. | No alerts from failed scans; no duplicate jobs after sleep/resume; retention/export behavior verified; scheduling limits visible | 3–5 days |
| M5: release hardening | Clean-install CI, packaged Windows launch, port/restart/shutdown handling, backup/restore UI, redacted diagnostics, documentation/license, installer/release validation. Depends on M1–M4. | Clean Windows install/upgrade/rollback/uninstall tests; preserved data; debug off; offline first-use behavior; measured resource limits | 3–5 days |

Total planning range: **19–30 engineering days**, roughly 4–6 focused work weeks before contingency. A useful first beta can stop after M3 and release hardening relevant to that scope; history and scheduling can follow. Do not add scheduling before discovery semantics are reliable—it would automate misleading results.

### Suggested implementation order within M1

1. Convert the audit reproductions into normal regression tests that assert the corrected behavior; retain baseline evidence separately.
2. Introduce app factory/configuration and temporary-database test fixtures. Declare the supported Python version and establish CI.
3. Add versioned schema migration and backup/import foundation with normalized identifiers and a stable data path.
4. Correct name rendering/edit semantics and move to internal device IDs for mutation routes.
5. Add host/token/field validation and explicit startup configuration; run the app without debug/reloader for normal use.
6. Unify snapshot/completion writes under one transaction. Establish scan IDs/outcomes for M2 without prematurely implementing scheduling.

## Verification strategy and release gates

### Automated checks

- Unit tests: canonical MACs, invalid/private identifiers, IPv4 range limits, interface parsing, per-platform probe interpretation, evidence state rules, freshness boundaries, missing enrichment, and event derivation.
- Database tests: legacy schema variants, duplicate/conflicting records, interrupted/repeated migrations, backup restore, transaction rollback, locked/read-only paths, scoped reconciliation, and ordering of concurrent jobs.
- Web tests: valid/invalid forms, unexpected hosts/origins, CSRF tokens, field lengths, unknown IDs, escaping, job conflict/status/cancel, and useful errors.
- Browser tests: first scan, rename before recognition, recognition changes, search/filter/sort preservation, details/history, retry after failure, archive/restore, focus, labels, live-region output, and no overflow.
- CI: formatting/lint, Python unit/integration tests, Windows backend tests plus synthetic browser tests, clean dependency install, advisory scan, and artifact packaging smoke test. Use separate direct-dependency declarations and a reproducible resolved lock; review updates rather than freezing indefinitely.

### Controlled live Windows matrix

Use a known inventory that the tester is authorized to scan. Record expected devices and compare actual results; do not use a successful process exit as discovery accuracy evidence.

| Scenario | Evidence required |
| --- | --- |
| Wi-Fi and Ethernet, each selected explicitly | Correct IP/MAC/interface/prefix and scoped neighbors |
| VPN/virtual adapters plus normal LAN | No silent target switching or unrelated sweeps |
| `/24`, `/23`, `/25`, oversized ranges | Correct host coverage or an explicit bounded range requirement |
| Awake responder, sleeping device, ICMP-blocking device, stale neighbor entry | Honest differentiation of presence evidence and uncertainty |
| DHCP IP change, missing MAC, randomized MAC, duplicate hostnames | No lost observation or unsafe identity merge |
| Disconnected adapter, command failure, DNS stall | Useful failure/partial result and previous inventory preserved |
| Two browser tabs, scheduled/manual overlap, restart during a scan | Single ownership, finite cleanup, no result regression |
| Offline first launch and later vendor update | Useful inventory without network dependency; update behavior matches privacy copy |

### Performance and lifecycle targets

Treat these as proposed targets to measure, not achieved benchmarks:

- Overview/details remain responsive during a scan. A second Scan action returns the active job/conflict promptly instead of spawning another sweep.
- A normal `/24` discovery finishes within a documented total deadline, initially targeting 30 seconds for discovery plus a separately bounded enrichment window. Tune after real Windows measurements and preserve correctness over an artificial timing target.
- Cancellation stops new probes immediately and terminates active work within its configured per-operation deadline; UI distinguishes cancel requested from canceled.
- Search/filter on 1,000 historical device records feels immediate, with a proposed p95 response target below 300ms on the reference machine. Measure and record that machine and dataset.
- An eight-hour scheduled run and a sleep/resume/restart test show no orphan processes, duplicate scan ownership, continually growing queues, or uncontrolled log/database growth.
- Fresh install, upgrade from legacy DB, failed migration, rollback, and uninstall behavior are exercised on a clean Windows environment. User inventory survives an ordinary upgrade and remains available for deliberate removal/export.

### Definition of done

All P1 findings are fixed and verified. P2 findings in the chosen release scope are closed with evidence or explicitly documented and deferred. The app truthfully presents scan coverage and data age; actual live discovery tests have run; backup/restore and migration rollback work; the normal launcher has debug disabled; responsive and accessibility checks pass; dependency and package checks are current; and documentation accurately states platform support, network behavior, and scheduling limitations.

Commit/PR notes should identify exact checks and remaining limitations. Passing synthetic tests alone must never be described as verified live-network monitoring or a production-ready release.

## Decisions to settle when implementation reaches them

These do not block the recommended starting work:

- Whether the user wants a portable Windows folder/launcher first or an installer/tray experience immediately. Default proposal: portable launcher for beta, installer after lifecycle verification.
- Which open-source license is intended, and whether any vendor database redistribution terms permit bundling.
- Default observation retention and scheduling interval. Default proposal: scheduling off, 90 days of detailed observations, compact historical summaries; show estimates and allow adjustment.
- Whether remote access, mobile access to a hosted LAN service, router integrations, or non-Windows support is actually required. Those expand the security/support scope and should be separate milestones.

Technical references: [Flask deployment](https://flask.palletsprojects.com/en/stable/deploying/), [Waitress](https://flask.palletsprojects.com/en/stable/deploying/waitress/), [Flask security](https://flask.palletsprojects.com/en/stable/web-security/), [Python UUID](https://docs.python.org/3/library/uuid.html#uuid.getnode), and [W3C contrast guidance](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).

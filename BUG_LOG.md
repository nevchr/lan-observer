# Bug log

Baseline: `d3c662cc48abec5858899d74208e7c34bffe8122`, audited 2026-09-22. Locations and reproductions refer to that baseline. All 18 findings have implementation fixes and regression coverage in the 0.2.0 working tree; see [current status and remaining validation](IMPLEMENTATION_STATUS.md). Historical descriptions below are retained as the original evidence, not claims that those bugs remain open.

Evidence types: **Reproduced** means an isolated execution demonstrated the behavior; **Browser verified** means the actual template/CSS was inspected with synthetic data; **Source verified** means the implementation is conclusive but the operational scenario was not exercised. Harness results are characterization evidence, not passing regression tests for correct behavior.

## Index

| ID | Priority | Finding | Evidence | Milestone |
| --- | --- | --- | --- | --- |
| B01 | P1 | Cached ARP entries are treated as current presence | Reproduced | M2 |
| B02 | MAC formatting splits one device into multiple identities | Reproduced | M1 |
| B03 | Responding devices without a MAC are discarded | Reproduced | M2 |
| B04 | Unrecognized-device names are hidden and later erased | Reproduced | M1 |
| B05 | Scans change presence for devices outside their network | Reproduced | M2 |
| B06 | DNS errors abort the entire scan; work is not deadline-bounded | Reproduced error / source timing gap | M2 |
| B07 | ARP command failure is recorded as a successful scan | Reproduced | M2 |
| B08 | Overlapping scans allow older observations to overwrite newer ones | Reproduced | M2 |
| B09 | Untrusted-origin mutations and arbitrary Host values are accepted | Reproduced at server boundary | M1 |
| B10 | Database location changes with working directory | Reproduced | M1 |
| B11 | Temporary enrichment failure erases useful metadata | Reproduced | M2 |
| B12 | Old scan snapshots continue to claim devices are online | Reproduced | M2/M3 |
| B13 | Scan data and scan timestamp are committed separately | Reproduced with fault injection | M1 |
| B14 | Vendor lookup can make an undisclosed first-use network download | Reproduced dependency branch | M1/M2 |
| B15 | Long device hostnames overflow cards and the mobile page | Browser verified | M3 |
| B16 | Name controls lack labels and scan timestamp contrast is too low | Browser verified / measured | M3 |
| B17 | The documented launcher always enables Flask debug mode | Source verified | M1 |
| B18 | Scan target and local MAC are not tied to a selected interface | Source verified | M2 |

## B01 — ARP cache entries falsely establish current presence

**P1 · Reproduced.** [scanner.py:100](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/scanner.py#L100), [database.py:139](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/database.py#L139).

- Reproduction: make every ping return false and supply one in-range ARP cache entry; run discovery and save it. Harness `B01` reports that cached device as online.
- Actual: any matching cached entry is added to discovery; saving it sets `online=1` and advances `last_seen`, regardless of active evidence or cache age.
- Expected: retain a cached neighbor as a discovery hint with its evidence source. Do not interpret an arbitrary ARP-cache record as a fresh response. Absence of a ping response also does not prove that a device is offline.
- Fix: typed observations with source, timestamp, network/interface, and confidence; explicit current-response versus cache-only states.
- Acceptance: stale/cache-only fixtures never advance the latest confirmed response time; an actively responding fixture does. A sleeping device with a cached entry remains distinguishable from a confirmed responder.

## B02 — MAC formatting splits identity and recognition

**P1 · Reproduced.** [scanner.py:15](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/scanner.py#L15), [scanner.py:69](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/scanner.py#L69), [database.py:128](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/database.py#L128).

- Reproduction: save `02:00:00:00:00:10`, recognize/name it, then save `02-00-00-00-00-10`. Harness `B02` produces two rows; the newly online row is unrecognized.
- Actual: the local-MAC function returns colon formatting, the ARP parser preserves hyphens, and SQLite identity comparison uses the literal string. Case variations can also create distinct rows.
- Expected: equivalent valid MAC encodings resolve to the same canonical identity within the chosen identity policy.
- Fix: validate/normalize at ingestion and mutation boundaries, migrate existing duplicates with a conflict report, and use an internal device ID for UI edits.
- Acceptance: colon/hyphen/case variants retain one device's first-seen time, name, and recognition; conflicting user names are surfaced rather than silently discarded.

## B03 — Responding devices disappear when no MAC is available

**P1 · Reproduced.** [database.py:130](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/database.py#L130).

- Reproduction: a non-local IP responds to ping but has no ARP entry. Harness `B03` discovers two IPs including the fixture host, but stores only one.
- Actual: `mac == "Unknown"` causes the device to be skipped completely.
- Expected: show the response with “MAC unavailable” and limited identity confidence.
- Fix: store observations independently of persistent device identity. Keep an IP-only observation scoped to its network and scan; do not permanently treat an IP as a device ID.
- Acceptance: a responding IP remains visible without a MAC; later learning a MAC can link evidence without merging unrelated devices after DHCP reuse.

## B04 — Naming an unrecognized device appears broken and can lose data

**P2 · Reproduced.** [templates/index.html:161](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/templates/index.html#L161), [templates/index.html:204](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/templates/index.html#L204).

- Reproduction: save “Kitchen speaker” without checking recognition, reload, then check recognition and press Save without retyping the name. Harness `B04` verifies the stored name is absent from the page and becomes an empty string after the second save.
- Actual: the unknown-card heading ignores `nickname`, and its name input does not render the saved value.
- Expected: naming and recognition are independent; both sections display the same saved data.
- Fix: share one device rendering component, bind the name value consistently, and provide explicit save feedback.
- Acceptance: save, reload, recognize/unrecognize, and save again preserves the name; deliberately clearing a name still works.

## B05 — Scanning a different network rewrites unrelated presence

**P1 · Reproduced.** [database.py:119](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/database.py#L119), [database.py:82](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/database.py#L82).

- Reproduction: save a device observed on network A, then save a scan containing only a device on network B. Harness `B05` shows A's device set offline.
- Actual: each scan first marks every row offline; there is no network or scan-scope key in storage.
- Expected: only observations within a completed scan's network and coverage can affect that network's status. Leaving a network means its snapshot is stale, not that every device disconnected.
- Fix: explicit network IDs, scan coverage, and per-network observations. Scope identity associations and reconciliation; avoid subnet text as the sole network ID.
- Acceptance: switching networks or scanning a subset does not make unscanned devices offline. Overlapping private ranges remain separate.

## B06 — Enrichment failure aborts scans; operations lack deadlines

**P1 · Reproduced error path; source-verified timing gap.** [scanner.py:34](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/scanner.py#L34), [scanner.py:45](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/scanner.py#L45), [scanner.py:117](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/scanner.py#L117), [app.py:65](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/app.py#L65).

- Reproduction: have reverse DNS raise `socket.timeout`. Harness `B06` verifies it escapes `get_hostname()` and a scan failure produces HTTP 500.
- Actual: only `socket.herror` is handled. Hostname lookups occur serially, and ping/ARP subprocess calls have no Python `timeout`; `/scan` waits for the entire operation in the request.
- Expected: optional enrichment failure preserves discoveries and becomes a warning. Every scan phase has a finite budget and actionable completion/failure state.
- Fix: platform-aware error handling, isolated bounded enrichment, subprocess deadlines, scan-job lifecycle, and useful retry/cancel UX. Canceling a Future does not interrupt an already blocked resolver; choose a mechanism that actually bounds it.
- Acceptance: injected DNS/OS errors do not erase observations; hung-command and resolver tests terminate within configured deadlines. A failed scan returns the user to usable app UI instead of a generic 500 page.

## B07 — Failed ARP command silently becomes a successful scan

**P1 · Reproduced.** [scanner.py:53](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/scanner.py#L53), [app.py:67](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/app.py#L67).

- Reproduction: return exit code 1 and empty stdout from `arp -a`, with no ping responses. Harness `B07` shows a success redirect, an updated last-scan timestamp, and a previously stored peer marked offline.
- Actual: the ARP exit code and stderr are ignored. The local computer is always included, so discovery may look superficially successful.
- Expected: distinguish command failure, partial coverage, valid empty results, and no active network. Preserve the previous successful snapshot on failure.
- Fix: structured scan outcomes and explicit command-result validation before reconciliation.
- Acceptance: permission/missing-command/parse failures produce a failed or partial scan with diagnostics; they do not count as evidence of absence or replace a successful snapshot.

## B08 — Older concurrent scans overwrite newer observations

**P1 · Reproduced with two request threads.** [app.py:65](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/app.py#L65), [scanner.py:93](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/scanner.py#L93).

- Reproduction: hold the first scan's result, complete a second scan reporting `.22`, then release the first reporting `.11`. Harness `B08` gets two success redirects and the final stored IP is `.11`.
- Actual: there is no server scan lock/job identity. Disabling a single browser button does not stop another tab or client. Each request starts its own 20-worker pool.
- Expected: single-flight scanning or revision-aware reconciliation with bounded resource usage.
- Fix: one scanner coordinator for the local app instance, a database lease or equivalent cross-request ownership, scan IDs, and ordered observation times. Protect vendor lookup state from concurrent access as well.
- Acceptance: concurrent scan requests reuse the active job or return a useful conflict; older jobs cannot regress a newer committed snapshot; restart clears or expires abandoned ownership safely.

## B09 — Server accepts mutations from unrelated origins and hosts

**P1 · Reproduced at the server boundary.** [app.py:14](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/app.py#L14), [app.py:31](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/app.py#L31), [app.py:65](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/app.py#L65).

- Reproduction: send a form POST with `Origin: https://example.invalid` and `Host: example.invalid` to the test client. Harness `B09` confirms a name change and a successful scan POST without a session/token.
- Actual: neither mutation route verifies a form token/origin; the app has no trusted-host configuration or local-session capability.
- Expected: a local browser service accepts mutations only from an authorized app interaction. Loopback binding is useful but is not a request-authenticity check.
- Fix: trusted local hosts, per-session CSRF protection, a persisted local secret, origin checking as defense in depth, body/name limits, and no permissive CORS. Keep loopback binding. Define stronger authentication before any optional LAN access mode.
- Acceptance: valid app forms work; forged origin, invalid/missing token, and unexpected Host cases are rejected before scanning or updating data. Add browser tests covering current local-network access rules.
- Limit: no remote access, practical browser CSRF exploit, or DNS-rebinding exploit was demonstrated. Modern browser restrictions can affect reachability. See [Flask security guidance](https://flask.palletsprojects.com/en/stable/web-security/).

## B10 — Working directory determines which database opens

**P2 · Reproduced.** [database.py:4](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/database.py#L4), [app.py:16](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/app.py#L16).

- Reproduction: initialize with `DB_NAME="devices.db"` from a different temporary working directory. Harness `B10` sees zero devices there and the original fixture still has one.
- Actual: shortcuts, service launchers, and scripts can silently create an unrelated empty database or fail in an unwritable directory.
- Expected: a stable configurable application data path, independent of launch location.
- Fix: explicit configuration/app factory and an absolute user-data path; offer a deliberate legacy-database migration with backup and provenance.
- Acceptance: launches from two directories use the same configured inventory; a wrong/unwritable path shows a diagnostic and does not silently reset the user's data.

## B11 — Temporary hostname/vendor failure destroys prior metadata

**P2 · Reproduced.** [database.py:140](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/database.py#L140).

- Reproduction: save a meaningful hostname/vendor, then save the same MAC with `Unknown` values. Harness `B11` confirms both useful values are overwritten.
- Actual: unsuccessful enrichment replaces existing metadata with the string sentinel.
- Expected: preserve last-known metadata and separately show the latest lookup's outcome/age.
- Fix: typed nullable values and per-field observation timestamps/source; distinguish “lookup failed,” “not found,” and an actual changed value.
- Acceptance: transient failures retain prior labels; a successful changed hostname updates it; an intentional user name remains separate.

## B12 — Old snapshot status is presented as current online status

**P2 · Reproduced.** [app.py:50](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/app.py#L50), [templates/index.html:98](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/templates/index.html#L98), [templates/index.html:178](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/templates/index.html#L178).

- Reproduction: set the last observation and last-scan time to 2000 while keeping the row's online bit. Harness `B12` still renders ONLINE and counts it as online.
- Actual: the status never expires. Unknown cards show first-seen but omit last-seen; no stale-snapshot state exists.
- Expected: clearly label “Seen in last scan” and its time, or derive a freshness-aware status. Do not silently convert lack of fresh evidence into offline either.
- Fix: separate observation presence from freshness, show time on every device, and surface stale/partial network snapshots.
- Acceptance: old observations render a stale/last-seen state; recent successful responses render their evidence time; aggregate labels match the selected network and period.

## B13 — Device snapshot and last-scan timestamp are not atomic

**P2 · Reproduced with fault injection.** [app.py:69](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/app.py#L69), [database.py:12](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/database.py#L12), [database.py:178](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/database.py#L178).

- Reproduction: allow `save_scan()` to commit, then inject failure into `set_last_scan()`. Harness `B13` has the new device data but the previous scan timestamp.
- Actual: a request can fail after committing results; the UI cannot identify which scan produced its data.
- Expected: snapshot observations and successful completion metadata commit as one transaction.
- Fix: persisted scan IDs and one transaction for results plus completion; use exception-safe connection cleanup and record failure separately.
- Acceptance: a failure during completion leaves no partially published successful snapshot; retry does not duplicate history or lose prior successful state.

## B14 — Vendor lookup has an undisclosed automatic download path

**P2 · Reproduced dependency branch; no real request sent.** [scanner.py:8](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/scanner.py#L8), [scanner.py:137](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/scanner.py#L137), README Privacy section; installed mac-vendor-lookup 0.1.15 `AsyncMacLookup.load_vendors()`.

- Reproduction: simulate no vendor cache and replace `update_vendors()` with an async spy. Harness `B14` confirms first-use loading invokes the download method automatically.
- Actual: the dependency retrieves the IEEE OUI list when no cache exists. The README only says scanning/device information remains local and does not explain this external connection or an offline startup dependency.
- Expected: disclose vendor-list network activity and let users understand/control refresh. A completely offline first scan should remain useful.
- Fix: a bundled or explicitly managed vendor database with visible last-updated state and a bounded optional update command; verify redistribution terms before bundling data. Explain that DNS lookup behavior also follows the host's resolver configuration.
- Acceptance: offline startup and scanning are tested; updates are explicit and time-bounded; no device MAC/hostname is included in download requests.
- Limit: this is a transparency/offline-behavior defect, not evidence that inventory is uploaded. Inspected code downloads a complete vendor list rather than querying a service with each MAC.

## B15 — Long hostnames overflow cards and create mobile horizontal scroll

**P2 · Browser verified.** [static/style.css:49](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/static/style.css#L49), [static/style.css:62](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/static/style.css#L62), [static/style.css:67](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/static/style.css#L67).

- Reproduction: render a valid 63-character label (`network-device-` plus 49 `x` characters) in the synthetic dashboard.
- Actual: at the desktop viewport, one card's content width was 530px within a 354px client width. At a 390px viewport, the page scroll width was 546px with a 375px client width (scrollbar excluded).
- Expected: long discovery strings cannot escape card bounds or widen the document.
- Fix: shrinkable grid tracks and wrapping/overflow handling for names and metadata, plus an explicit stacked mobile header. Keep full values available in device details/copy controls.
- Acceptance: no document horizontal overflow at 320, 390, 768, and 1280px with realistic maximum hostnames, MACs, localized timestamps, and user-name limits. Normal and 200% zoom flows remain usable.

## B16 — Name controls lack persistent labels; scan time fails contrast target

**P2 · Browser verified and measured.** [templates/index.html:119](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/templates/index.html#L119), [templates/index.html:204](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/templates/index.html#L204), [static/style.css:187](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/static/style.css#L187).

- Reproduction: inspect all three synthetic name inputs. Each has zero associated labels and no `aria-label`; the accessibility tree exposes unlabeled text fields. Inspect the last-scan style.
- Actual: placeholders are the only name-field prompts. `#666666` text on `#0b0d10` at 12px has approximately 3.389:1 contrast, below the 4.5:1 normal-text target.
- Expected: visible associated labels and sufficient contrast; screen-reader users can identify each device's editing controls.
- Fix: unique input IDs and visible labels, context for repeated actions, accessible success/error/progress announcements, and tested semantic color tokens.
- Acceptance: automated label/contrast checks pass and keyboard plus NVDA save/scan flows are manually verified. See [W3C labels](https://www.w3.org/WAI/tutorials/forms/labels/) and [contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).

## B17 — Normal launch enables the debug server

**P2 · Source verified.** [app.py:78](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/app.py#L78), README running instructions.

- Reproduction by inspection: the documented `python app.py` path calls `app.run(..., debug=True)` unconditionally.
- Actual: everyday use enables the development debugger/reloader. Loopback binding reduces exposure but does not make this a supported packaged runtime.
- Expected: debug is explicit development-only configuration; normal use runs a supported server without the reloader.
- Fix: a debug-off launcher using Waitress, bind explicitly to loopback, and provide a separate documented developer command.
- Acceptance: normal startup has debug/reloader disabled, one scanner coordinator, clear port-conflict handling, and graceful shutdown. [Flask deployment guidance](https://flask.palletsprojects.com/en/stable/deploying/) applies to private/local deployed use too.

## B18 — Network selection is guessed and local IP/MAC may not correspond

**P1 · Source verified; live multi-adapter behavior untested.** [scanner.py:10](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/scanner.py#L10), [scanner.py:15](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/scanner.py#L15), [scanner.py:25](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/scanner.py#L25), [scanner.py:53](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/scanner.py#L53), [scanner.py:78](https://github.com/nevchr/lan-observer/blob/d3c662cc48abec5858899d74208e7c34bffe8122/scanner.py#L78).

- Reproduction setup for follow-up: a Windows machine with Wi-Fi plus VPN/virtual adapters, or a `/25`/`/23` network. Compare the chosen IP/MAC/range against the selected adapter and route.
- Actual by inspection: hostname resolution supplies one IP, `uuid.getnode()` independently supplies a MAC, the first three octets determine a fixed `.1`–`.254` sweep, and the ARP parser discards interface headers. There is no user-visible interface choice, actual mask handling, or validation that the chosen address is a usable LAN interface.
- Expected: the user sees which interface/network will be scanned; IP, MAC, prefix and neighbor data all belong to it. Unsupported networks are diagnosed rather than guessed.
- Fix: a Windows adapter/route provider with prefix-aware address generation and scan-size bounds; retain interface identity while reading neighbors. Follow the selected interface if it changes or disappears.
- Acceptance: controlled Wi-Fi/Ethernet/VPN, `/23`, `/25`, disconnected, loopback-only, and overlapping-subnet fixtures select the right scope or fail clearly. Local-device MAC matches that adapter. The README already discloses the `/24` limitation; the broader interface-association risk remains important even on `/24` LANs. [Python documents](https://docs.python.org/3/library/uuid.html#uuid.getnode) that `getnode()` selects among interfaces and can fall back to a generated value; it does not promise the MAC for an independently resolved IP.

## Follow-up investigations and enhancements (not additional confirmed bugs)

- Test Windows ping output/exit behavior for destination-unreachable responses; establish what constitutes positive reachability evidence on each supported backend.
- Test concurrent use of the shared mac-vendor-lookup event loop. Its implementation retains a single loop, while scans can overlap; vendor lookup exceptions are broadly swallowed today.
- Exercise locked/corrupt/read-only databases and migration errors. `init_database()` suppresses every `OperationalError` from ALTER TABLE, not only duplicate-column errors; exception cleanup is not systematic.
- Define input limits, canonical boolean parsing, and useful missing/unknown-device responses. No explicit nickname length limit or nonexistent-MAC feedback exists.
- Decide “new” acknowledgment versus recognition, archive/restore, device notes/tags, search, filter/sort, scan history, scheduling, notification retention, and export semantics in the product plan.
- Test clean installation on a declared Python version, native dependency compatibility, manifest encoding handling, and a current advisory scan. Installed version matches are not security certification.

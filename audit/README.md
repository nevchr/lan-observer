# Audit evidence and reproduction

See [the audit](../AUDIT.md), [bug log](../BUG_LOG.md), and [overhaul plan](../OVERHAUL_PLAN.md).

This folder preserves the original `d3c662c` audit evidence alongside 0.2.0 check results. The original `reproduce.py` imports removed prototype modules and is **not runnable against the overhauled working tree**. Use `python -m unittest discover -s tests -v` for current regression checks and `python scripts/smoke_package.py` after a Windows package build. The commands below document how the baseline was originally captured; run them only in an isolated checkout of `d3c662c` with its original dependencies.

`reproduce.py` is a baseline characterization harness. Its `CONFIRMED` output means a defect is still present. Its successful exit is **not** an application quality gate; a fixed defect should cause its baseline expectation to change/fail. During implementation, replace these characterizations with regression tests that assert correct behavior and retain the dated JSON as historical evidence.

## Normal reproduction

Use a working Python environment with the project's requirements installed:

```powershell
python audit/reproduce.py
```

The harness overrides the database path before importing `app`, uses only synthetic identifiers in documentation address ranges, mocks all subnet discovery and vendor-download work, and writes `audit/results.json`. Temporary fixture databases are cleaned up when the process exits normally. The real database is only read to compare its checksum before/after; its content is not printed or included in reports.

For browser inspection with the same synthetic fixtures:

```powershell
python audit/reproduce.py --serve --port 5057
```

Open `http://127.0.0.1:5057/`. `/audit/empty` renders the empty first-run template. The Scan button uses a synthetic replacement rather than real network discovery. The server binds only to loopback with debug and reloader disabled. Stop it after inspection with Ctrl+C. This is an audit fixture, not a production launcher.

## Environment used for this audit

The saved `.venv` launcher could not start in this session because its Microsoft Store Python target returned access denied. The following session-local fallback ran the existing packages on bundled Python 3.12.14, without replacing `.venv`:

```powershell
$env:PYTHONPATH = "$PWD\.venv\Lib\site-packages"
& 'C:\Users\chris\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' audit\reproduce.py
```

This absolute runtime path is machine-specific. A supported fresh environment is the appropriate choice for subsequent project CI and release work. No clean-install or original-launcher success is implied by the fallback.

## Evidence files

| File | What it proves |
| --- | --- |
| `results.json` | 14 observed backend/dependency defects, four positive controls, environment versions, unchanged user database during tests |
| `environment-checks.json` | Syntax compile result, installed-version matches, and computed timestamp contrast; not dependency security or fresh installation |
| `browser-checks.json` | Measurements from actual template/CSS rendered with synthetic devices; browser viewport emulation only |
| `desktop-baseline.png` | Full-page synthetic baseline at normal desktop width |
| `mobile-baseline.png` | Full-page synthetic baseline at 390px, including long-hostname overflow |
| `overhaul-data-checks.json` | Isolated legacy import preservation and synthetic 1,000-device page timing |
| `overhaul-package-checks.json` | Built Windows executable HTTP, duplicate-instance, port, and working-directory smoke checks |

The baseline screenshots include a 63-character hostname to expose wrapping behavior and a saved unrecognized nickname that the current template does not render. They contain no actual LAN inventory.

"""Launch the built executable in isolated data folders and check its HTTP surface."""

import json
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    executable = root / "dist" / "LANObserver" / "LANObserver.exe"
    with tempfile.TemporaryDirectory(
        dir=root / ".runtime", prefix="package-smoke-"
    ) as directory:
        base = Path(directory)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        arguments = [
            str(executable),
            "--data-dir",
            str(base / "data"),
            "--port",
            str(port),
            "--no-browser",
        ]
        process = subprocess.Popen(
            arguments,
            cwd=base,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(
                        process.communicate()[1].decode(errors="replace")
                    )
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/", timeout=2
                    ) as response:
                        assert response.status == 200
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise TimeoutError("Packaged server did not start")
            checks = {}
            for path in [
                "/",
                "/history",
                "/settings",
                "/diagnostics",
                "/static/app.css",
                "/static/app.js",
            ]:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}{path}", timeout=20
                ) as response:
                    checks[path] = response.status
                    assert response.status == 200
                    assert response.headers.get("X-Frame-Options") == "DENY"
            duplicate = subprocess.run(
                arguments,
                cwd=base,
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            assert duplicate.returncode == 1 and b"already running" in duplicate.stderr
            conflict = subprocess.run(
                [
                    str(executable),
                    "--data-dir",
                    str(base / "other"),
                    "--port",
                    str(port),
                    "--no-browser",
                ],
                cwd=base,
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            assert conflict.returncode == 1
            report = dict(
                http=checks,
                duplicate_instance_rejected=True,
                occupied_port_rejected=True,
                arbitrary_working_directory=True,
                limitation="Process termination exercised; clean-machine, signed-installer and long-duration tests not performed",
            )
            (root / "audit" / "overhaul-package-checks.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
            print(json.dumps(report, indent=2))
        finally:
            process.terminate()
            process.communicate(timeout=10)


if __name__ == "__main__":
    main()

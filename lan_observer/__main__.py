import argparse
import logging
import os
import socket
import sys
import threading
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import create_app, data_directory


def create_local_server(app, port):
    from waitress import create_server

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", port))
        return create_server(
            app, sockets=[listener], threads=4, max_request_body_size=20 * 1024 * 1024
        )
    except Exception:
        listener.close()
        raise


class InstanceLock:
    """OS lock, released even after a crash; no stale PID heuristics."""

    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        try:
            self.handle.seek(0, 2)
            if self.handle.tell() == 0:
                self.handle.write(b"0")
                self.handle.flush()
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise RuntimeError(
                "LAN Observer is already running with this data folder."
            ) from None
        return self

    def __exit__(self, *args):
        if self.handle:
            self.handle.close()


def main():
    parser = argparse.ArgumentParser(
        description="LAN Observer — local Windows IPv4 inventory"
    )
    parser.add_argument("--data-dir", type=Path, default=data_directory())
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port from 1024 to 65535.")
    try:
        with InstanceLock(args.data_dir / "app.lock"):
            handler = RotatingFileHandler(
                args.data_dir / "app.log",
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
            )
            logging.basicConfig(
                level=logging.INFO, handlers=[handler, logging.StreamHandler()]
            )
            app = create_app({"DATA_DIR": args.data_dir})
            server = create_local_server(app, args.port)
            coordinator = app.extensions["coordinator"]
            coordinator.start_scheduler()
            print(
                f"LAN Observer: http://127.0.0.1:{args.port}\nData: {args.data_dir.resolve()}\nPress Ctrl+C to stop.",
                flush=True,
            )
            if not args.no_browser:
                threading.Timer(
                    0.5, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")
                ).start()
            try:
                server.run()
            except KeyboardInterrupt:
                pass
            finally:
                coordinator.close()
                server.close()
                handler.close()
    except (OSError, RuntimeError, ValueError) as error:
        print(
            f"Unable to start LAN Observer: {error}\nTry another --port or check the data-folder permissions.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

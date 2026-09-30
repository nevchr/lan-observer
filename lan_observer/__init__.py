"""LAN Observer app factory; importing this package does not open a database."""

import os
import secrets
from pathlib import Path

from flask import Flask

from .domain import (
    display_name,
    evidence_label,
    friendly_edit_detail,
    presence,
    pretty_time,
)
from .services import Coordinator
from .storage import Store

__version__ = "0.2.0"


def data_directory():
    override = os.environ.get("LAN_OBSERVER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (
        Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
        / "LANObserver"
    )


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        DATA_DIR=data_directory(),
        TRUSTED_HOSTS=["127.0.0.1", "localhost", "[::1]"],
        MAX_CONTENT_LENGTH=20 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        FRESH_SECONDS=900,
    )
    app.config.update(config or {})
    directory = Path(app.config["DATA_DIR"]).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if not app.config.get("SECRET_KEY"):
        secret_file = directory / "session.key"
        try:
            with secret_file.open("x", encoding="utf-8") as handle:
                handle.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        app.config["SECRET_KEY"] = secret_file.read_text(encoding="utf-8").strip()
        if len(app.config["SECRET_KEY"]) < 32:
            raise ValueError(
                "Invalid session key. Restore the key or move it aside while the app is stopped."
            )
    store = Store(directory / "inventory.db")
    app.extensions["store"] = store
    overrides = {}
    if app.config.get("INTERFACE_PROVIDER"):
        overrides["provider"] = app.config["INTERFACE_PROVIDER"]
    if app.config.get("SCANNER"):
        overrides["scanner"] = app.config["SCANNER"]
    app.extensions["coordinator"] = Coordinator(store, **overrides)
    app.jinja_env.filters.update(
        pretty_time=pretty_time,
        display_name=display_name,
        presence=presence,
        evidence_label=evidence_label,
        friendly_edit_detail=friendly_edit_detail,
    )
    from .web import register

    register(app)
    return app

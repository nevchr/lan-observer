"""Compatibility entry point: python app.py. No database or worker at import time."""

from lan_observer import create_app as create_app
from lan_observer.__main__ import main

if __name__ == "__main__":
    main()

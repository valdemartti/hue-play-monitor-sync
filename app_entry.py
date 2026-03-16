"""Entry point for the macOS .app bundle."""

import logging
import sys
import os

# Ensure the bundled package is importable
if getattr(sys, "frozen", False):
    # Running as a py2app bundle
    bundle_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, bundle_dir)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

from ui.tray_app import run_tray_app

run_tray_app()

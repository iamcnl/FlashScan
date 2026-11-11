"""
main.py — FlashScan entry point

Launches the pywebview window with the HTML GUI.
"""

from __future__ import annotations

import logging
import platform
import sys
import threading
from importlib import metadata
from pathlib import Path

# Add parent to sys.path for imports
sys.path.insert(0, str(Path(__file__).parent))

import logger

logger.setup()

import window_state

import webview

from ui.api import API
from version import __version__

log = logging.getLogger(__name__)

UI_DIR  = Path(__file__).parent / "ui"
UI_HTML = UI_DIR / "index.html"
ICON    = Path(__file__).parent / "assets" / "FlashScan.ico"
APP_ID  = "FlashScan.App"

REVEAL_TIMEOUT_S = 3.0


def _pywebview_version() -> str:
    try:
        return metadata.version("pywebview")
    except metadata.PackageNotFoundError:
        return "unknown"


def _set_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    import ctypes

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def main():
    _set_app_user_model_id()
    log.info(
        "FlashScan %s starting: python %s, %s, pywebview %s",
        __version__, platform.python_version(), platform.platform(), _pywebview_version(),
    )
    # window_ref_holder: list with one element, populated after create_window
    window_ref: list = []
    api = API(window_ref)

    options = window_state.startup_options(window_state.current_screens())
    window = webview.create_window(
        title      = "FlashScan",
        url        = str(UI_HTML),
        js_api     = api,
        min_size   = window_state.MIN_SIZE,
        resizable  = True,
        frameless  = False,  # True = hide native titlebar (GUI has its own drag bar)
        hidden     = True,
        **options,
    )
    tracker = window_state.Tracker(options["maximized"], window_state.saved_bounds())
    tracker.attach(window.events)
    window_ref.append(window)

    def on_started():
        reveal_timer = threading.Timer(REVEAL_TIMEOUT_S, api.reveal)
        reveal_timer.daemon = True
        reveal_timer.start()

    webview.start(on_started, debug=False, icon=str(ICON))
    tracker.flush()
    log.info("FlashScan closed")


if __name__ == "__main__":
    main()
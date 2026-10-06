"""
main.py — FlashScan entry point

Launches the pywebview window with the HTML GUI.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import webview

# Add parent to sys.path for imports
sys.path.insert(0, str(Path(__file__).parent))

from ui.api import API

UI_DIR  = Path(__file__).parent / "ui"
UI_HTML = UI_DIR / "index.html"

REVEAL_TIMEOUT_S = 3.0


def main():
    # window_ref_holder: list with one element, populated after create_window
    window_ref: list = []
    api = API(window_ref)

    window = webview.create_window(
        title      = "FlashScan",
        url        = str(UI_HTML),
        js_api     = api,
        width      = 1000,
        height     = 680,
        min_size   = (760, 520),
        resizable  = True,
        frameless  = False,  # True = hide native titlebar (GUI has its own drag bar)
        hidden     = True,
    )
    window_ref.append(window)

    def on_started():
        reveal_timer = threading.Timer(REVEAL_TIMEOUT_S, api.reveal)
        reveal_timer.daemon = True
        reveal_timer.start()

    webview.start(on_started, debug=False)


if __name__ == "__main__":
    main()
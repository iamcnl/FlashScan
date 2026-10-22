"""
logger.py — centralised logging for FlashScan

One rotating log file shared by all Python modules and by JS errors forwarded
through the API bridge (ui/js/log.js -> API.log_js).

Log location: %APPDATA%/FlashScan/flashscan.log
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_NAME     = "flashscan.log"
MAX_BYTES    = 1_000_000
BACKUP_COUNT = 3

JS_MAX_MESSAGE_CHARS = 4000
JS_MAX_PER_WINDOW    = 50
JS_WINDOW_SECONDS    = 60

_FORMAT = "%(asctime)s [%(levelname)s] %(threadName)s %(name)s: %(message)s"

_lock = threading.Lock()
_log_file: Path | None = None
_configured = False

_js_log = logging.getLogger("js")
_js_levels = {"error": logging.ERROR, "warn": logging.WARNING, "info": logging.INFO}
_js_window_start = 0.0
_js_window_count = 0
_js_suppressed = 0


def _default_dir() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    return base / "FlashScan"


def _open_handler(directories: list[Path]) -> RotatingFileHandler | None:
    for directory in directories:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            return RotatingFileHandler(
                directory / LOG_NAME,
                maxBytes=MAX_BYTES,
                backupCount=BACKUP_COUNT,
                encoding="utf-8",
            )
        except OSError:
            continue
    return None


def _install_excepthooks() -> None:
    crash = logging.getLogger("crash")

    def on_main_thread(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        crash.critical("Uncaught exception", exc_info=(exc_type, exc, tb))

    def on_other_thread(args):
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread else "?"
        crash.critical(
            "Uncaught exception in thread %s", name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = on_main_thread
    threading.excepthook = on_other_thread


def setup(directory: Path | None = None) -> Path | None:
    """
    Call once from main.py before anything else. Returns the log file path,
    or None when no writable location exists (logging then goes to stderr only).
    """
    global _log_file, _configured
    with _lock:
        if _configured:
            return _log_file

        directories = [directory or _default_dir(), Path(tempfile.gettempdir()) / "FlashScan"]
        handler = _open_handler(directories)

        root = logging.getLogger()
        root.setLevel(logging.INFO)
        formatter = logging.Formatter(_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

        if handler is not None:
            handler.setFormatter(formatter)
            root.addHandler(handler)
            _log_file = Path(handler.baseFilename)

        if sys.stderr is not None:
            console = logging.StreamHandler()
            console.setLevel(logging.WARNING)
            console.setFormatter(formatter)
            root.addHandler(console)

        _install_excepthooks()
        _configured = True

    log = logging.getLogger(__name__)
    if _log_file is None:
        log.warning("No writable log location found; file logging is disabled")
    else:
        log.info("Log file: %s", _log_file)
    return _log_file


def log_file() -> Path | None:
    return _log_file


def log_js(level: str, message: str, source: str = "") -> None:
    """Writes an entry sent from JS. Rate-limited so a render loop cannot flood the file."""
    global _js_window_start, _js_window_count, _js_suppressed

    now = time.monotonic()
    with _lock:
        if now - _js_window_start > JS_WINDOW_SECONDS:
            suppressed = _js_suppressed
            _js_window_start, _js_window_count, _js_suppressed = now, 0, 0
        else:
            suppressed = 0
        if _js_window_count >= JS_MAX_PER_WINDOW:
            _js_suppressed += 1
            return
        _js_window_count += 1

    if suppressed:
        _js_log.warning("%d JS log entries were dropped by the rate limit", suppressed)

    text = str(message)
    if len(text) > JS_MAX_MESSAGE_CHARS:
        text = text[:JS_MAX_MESSAGE_CHARS] + "… [truncated]"
    prefix = f"[{str(source)[:60]}] " if source else ""
    _js_log.log(_js_levels.get(str(level), logging.ERROR), "%s%s", prefix, text)
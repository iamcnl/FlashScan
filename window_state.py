"""
window_state.py — remembers whether the window is maximized and, when it is not, its size and position

Stored in the global settings as windowMaximized and windowBounds {x, y, width, height}.
Bounds are the normal (restored) rectangle in logical pixels, the same units pywebview reports.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable

import settings

log = logging.getLogger(__name__)

DEFAULT_SIZE = (1000, 680)
MIN_SIZE = (760, 520)
SAVE_DELAY_S = 0.5
TOLERANCE = 2
MIN_VISIBLE_WIDTH = 120
MIN_VISIBLE_HEIGHT = 60
OFFSCREEN = -30000
BOUNDS_KEYS = ("x", "y", "width", "height")

Screen = tuple[int, int, int, int]


def _integer(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def window_maximized() -> bool:
    value = settings.load().get("windowMaximized", settings.DEFAULTS["windowMaximized"])
    return value if isinstance(value, bool) else settings.DEFAULTS["windowMaximized"]


def saved_bounds() -> dict:
    raw = settings.load().get("windowBounds")
    if not isinstance(raw, dict):
        return {}
    return {key: raw[key] for key in BOUNDS_KEYS if _integer(raw.get(key)) is not None}


def current_screens() -> list[Screen]:
    try:
        import webview

        return [(s.x, s.y, s.width, s.height) for s in webview.screens]
    except Exception:
        log.warning("Cannot read the screen layout; the saved window position is ignored", exc_info=True)
        return []


def _fit_size(width: int, height: int, screens: list[Screen]) -> tuple[int, int]:
    if screens:
        width = min(width, max(screen[2] for screen in screens))
        height = min(height, max(screen[3] for screen in screens))
    return max(width, MIN_SIZE[0]), max(height, MIN_SIZE[1])


def _is_reachable(x: int, y: int, width: int, screens: list[Screen]) -> bool:
    for left, top, screen_width, screen_height in screens:
        overlap = min(x + width, left + screen_width) - max(x, left)
        if overlap >= MIN_VISIBLE_WIDTH and top <= y <= top + screen_height - MIN_VISIBLE_HEIGHT:
            return True
    return False


def startup_options(screens: Iterable[Screen]) -> dict:
    screens = list(screens)
    bounds = saved_bounds()
    width, height = DEFAULT_SIZE
    if "width" in bounds and "height" in bounds:
        width, height = _fit_size(bounds["width"], bounds["height"], screens)

    options = {"maximized": window_maximized(), "width": width, "height": height}
    if "x" in bounds and "y" in bounds and _is_reachable(bounds["x"], bounds["y"], width, screens):
        options.update(x=bounds["x"], y=bounds["y"])
    return options


class Tracker:
    """
    pywebview runs every event handler on its own thread, so a resize caused by maximizing can be
    handled before the maximized event. Bounds are therefore collected first and written after a
    quiet period, and a state change throws away whatever was collected just before it.
    """

    def __init__(self, maximized: bool, bounds: dict | None = None, delay: float = SAVE_DELAY_S):
        self._lock = threading.Lock()
        self._delay = delay
        self._maximized = maximized
        self._minimized = False
        self._committed = dict(bounds or {})
        self._pending: dict = {}
        self._timer: threading.Timer | None = None

    def attach(self, events) -> None:
        events.maximized += self.on_maximized
        events.minimized += self.on_minimized
        events.restored += self.on_restored
        events.resized += self.on_resized
        events.moved += self.on_moved
        events.closed += self.flush

    def on_maximized(self) -> None:
        self._set_maximized(True)

    def on_restored(self) -> None:
        self._set_maximized(False)

    def on_minimized(self) -> None:
        with self._lock:
            self._minimized = True
            self._pending.clear()

    def on_resized(self, width: int, height: int) -> None:
        if width < MIN_SIZE[0] - TOLERANCE or height < MIN_SIZE[1] - TOLERANCE:
            return
        self._record(width=width, height=height)

    def on_moved(self, x: int, y: int) -> None:
        if x <= OFFSCREEN or y <= OFFSCREEN:
            return
        self._record(x=x, y=y)

    def flush(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            pending, self._pending = self._pending, {}
            if not pending or self._maximized or self._minimized:
                return
            merged = {**self._committed, **pending}
            if not self._differs(merged):
                return
            self._committed = merged
        settings.save({"windowBounds": dict(merged)})

    def _differs(self, merged: dict) -> bool:
        return any(
            key not in self._committed or abs(merged[key] - self._committed[key]) > TOLERANCE
            for key in merged
        )

    def _set_maximized(self, maximized: bool) -> None:
        with self._lock:
            changed = maximized != self._maximized
            self._maximized = maximized
            self._minimized = False
            self._pending.clear()
        if changed:
            settings.save({"windowMaximized": maximized})

    def _record(self, **values: int) -> None:
        with self._lock:
            if self._maximized or self._minimized:
                return
            self._pending.update(values)
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._delay, self.flush)
            self._timer.daemon = True
            self._timer.start()
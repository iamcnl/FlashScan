"""
settings.py — persistent application settings and per-drive profiles

Global settings: ~/.flashscan_settings.json
Drive profiles:  ~/.flashscan_profiles/<hash of volume id>.json
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger(__name__)

SETTINGS_FILE   = Path.home() / ".flashscan_settings.json"
PROFILES_DIR    = Path.home() / ".flashscan_profiles"
MAX_PROFILES    = 50
PROFILE_VERSION = 1

DEFAULTS: dict = {
    "lastPath":    "",
    "lastOutput":  "",
    "lastFormats": ["MD"],
    "lastDepth":   10,
    "inclHidden":  False,
    "inclSystem":  False,
    "customExts":  [],
    "exportIncludeSize": True,
    "exportIncludeDate": True,
    "theme":       "light",
    "sortCol":     "name",
    "sortDir":     "asc",
}

_lock = threading.RLock()


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _load_unlocked() -> dict:
    try:
        if SETTINGS_FILE.exists():
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return {**DEFAULTS, **data}
    except Exception as e:
        log.warning("Cannot load settings from %s: %s", SETTINGS_FILE, e)
    return dict(DEFAULTS)


def load() -> dict:
    with _lock:
        return _load_unlocked()


def save(settings: dict) -> None:
    try:
        with _lock:
            merged = {**_load_unlocked(), **settings}
            _write_atomic(
                SETTINGS_FILE,
                json.dumps(merged, ensure_ascii=False, indent=2),
            )
    except Exception as e:
        log.warning("Cannot save settings to %s: %s", SETTINGS_FILE, e)


# ── Drive profiles ────────────────────────────────────────────────

def _profile_path(volume_id: str) -> Path:
    digest = hashlib.sha256(volume_id.encode("utf-8")).hexdigest()[:16]
    return PROFILES_DIR / f"{digest}.json"


def load_profile(volume_id: str) -> dict | None:
    if not volume_id:
        return None
    path = _profile_path(volume_id)
    try:
        with _lock:
            if not path.exists():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            os.utime(path)
        if data.get("version") != PROFILE_VERSION or data.get("volumeId") != volume_id:
            return None
        return data
    except Exception as e:
        log.warning("Cannot load profile %s: %s", path, e)
        return None


def save_profile(volume_id: str, data: dict) -> None:
    if not volume_id or not isinstance(data, dict):
        return
    payload = {**data, "version": PROFILE_VERSION, "volumeId": volume_id}
    path = _profile_path(volume_id)
    try:
        with _lock:
            _write_atomic(
                path,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            )
            _evict_old_profiles()
    except Exception as e:
        log.warning("Cannot save profile %s: %s", path, e)


def _evict_old_profiles() -> None:
    profiles = sorted(
        PROFILES_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in profiles[MAX_PROFILES:]:
        stale.unlink(missing_ok=True)
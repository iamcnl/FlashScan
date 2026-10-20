"""
api.py — pywebview JS API

Methods of this class are callable from JS as:
  window.pywebview.api.method_name(args)

Responsible for:
  - scanning (runs scanner.py in a thread) and keeping the scanned tree
  - export (runs exporter.py in a thread from the tree and the UI's selection)
  - dialogs (browse_directory)
  - settings (get/save) and per-drive profiles
  - window reveal once the UI has applied its settings
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import threading
from datetime import datetime
from pathlib import Path

import json
import logging
import time

import webview  # pywebview

import logger
import settings

log = logging.getLogger(__name__)

MAX_LOGGED_UNREADABLE = 20
MAX_LOGGED_LINKS = 20

_SYSTEM = platform.system()  # 'Windows' | 'Darwin' | 'Linux'

_INVALID_NAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_DENIED = {"error": "Path is outside the scanned folders."}
_EXPORT_EXTS = {"MD": ".md", "TXT": ".txt", "JSON": ".json", "HTML": ".html"}


def _reserve_unique(path: Path) -> Path:
    """
    Creates an empty file at path, or at "name (2).ext", "name (3).ext", ...
    when the name is taken, so an existing file is never overwritten.
    """
    for n in range(1, 10_000):
        candidate = path if n == 1 else path.with_name(f"{path.stem} ({n}){path.suffix}")
        try:
            with open(candidate, "x"):
                pass
            return candidate
        except FileExistsError:
            continue
    raise OSError(f"No free file name for {path.name}")


def _safe_stem(stem: str, fallback: str) -> str:
    cleaned = _INVALID_NAME_CHARS.sub("", str(stem)).strip().strip(".")
    return cleaned[:150] or fallback


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


class API:
    def __init__(self, window_ref_holder: list):
        # window_ref_holder is [window] — populated after window creation
        self._win = window_ref_holder
        self._reveal_lock = threading.Lock()
        self._revealed = False
        self._scan_lock = threading.Lock()
        self._scan_cancel: threading.Event | None = None
        self._scan_seq = 0
        self._scan_data: dict | None = None
        self._export_lock = threading.Lock()
        self._exporting = False
        self._trust_lock = threading.Lock()
        self._trusted_roots: set[str] = set()
        self._trusted_files: set[str] = set()

    def _trust_root(self, path: str) -> None:
        with self._trust_lock:
            self._trusted_roots.add(_norm(path))

    def _trust_file(self, path: str) -> None:
        with self._trust_lock:
            self._trusted_files.add(_norm(path))

    def _is_trusted(self, path: str) -> bool:
        target = _norm(path)
        with self._trust_lock:
            if target in self._trusted_files:
                return True
            roots = list(self._trusted_roots)
        for root in roots:
            try:
                if os.path.commonpath([root, target]) == root:
                    return True
            except ValueError:
                continue
        return False

    @property
    def _window(self):
        return self._win[0] if self._win else None

    def _notify(self, js_call: str) -> None:
        win = self._window
        if win is None:
            return
        try:
            win.evaluate_js(js_call)
        except Exception:
            log.warning("evaluate_js failed for %s", js_call.split("(", 1)[0], exc_info=True)

    # ── Settings ───────────────────────────────────────────────────

    def get_settings(self) -> dict:
        return settings.load()

    def save_settings(self, data: dict) -> None:
        settings.save(data)

    def get_custom_exts(self) -> list:
        return settings.load().get("customExts", [])

    def save_custom_exts(self, exts: list) -> None:
        settings.save({"customExts": exts})

    def get_profile(self, volume_id: str) -> dict | None:
        return settings.load_profile(volume_id)

    def save_profile(self, volume_id: str, data: dict) -> None:
        settings.save_profile(volume_id, data)

    def delete_profile(self, volume_id: str) -> None:
        settings.delete_profile(volume_id)

    # ── Logging ───────────────────────────────────────────────────

    def log_js(self, level: str, message: str, source: str = "") -> None:
        logger.log_js(level, message, source)

    def open_log_folder(self) -> dict:
        path = logger.log_file()
        if path is None:
            return {"error": "No log file is available."}
        self._trust_file(str(path))
        return self.reveal_in_explorer(str(path))

    # ── Window ────────────────────────────────────────────────────

    def ui_ready(self) -> None:
        self.reveal(ui_reported=True)

    def reveal(self, ui_reported: bool = False) -> None:
        with self._reveal_lock:
            if self._revealed:
                return
            self._revealed = True
        if not ui_reported:
            log.warning("UI did not report ready in time; revealing the window anyway")
        win = self._window
        if win:
            win.maximize()
            win.show()

    # ── Dialogs ───────────────────────────────────────────────────

    def browse_directory(self) -> str | None:
        try:
            dialog = webview.FileDialog.FOLDER
        except AttributeError:
            # fallback for older pywebview versions
            dialog = webview.FOLDER_DIALOG  # type: ignore
        result = self._window.create_file_dialog(dialog)
        if result and len(result) > 0:
            return result[0]
        return None

    # ── File / folder operations ──────────────────────────────────

    def open_path(self, path: str) -> dict:
        """Opens a file or folder with the OS default application."""
        try:
            if not self._is_trusted(path):
                return _DENIED
            p = Path(path)
            if not p.exists():
                return {"error": "Path does not exist."}
            if _SYSTEM == "Windows":
                os.startfile(str(p))
            elif _SYSTEM == "Darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def reveal_in_explorer(self, path: str) -> dict:
        """Reveals a file/folder in the native file manager."""
        try:
            if not self._is_trusted(path):
                return _DENIED
            p = Path(path)
            if not p.exists():
                return {"error": "Path does not exist."}
            if _SYSTEM == "Windows":
                # /select highlights the specific file in Explorer
                subprocess.Popen(["explorer", "/select,", str(p)])
            elif _SYSTEM == "Darwin":
                subprocess.Popen(["open", "-R", str(p)])
            else:
                # On Linux, open the parent folder
                parent = str(p.parent) if p.is_file() else str(p)
                subprocess.Popen(["xdg-open", parent])
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def open_properties(self, path: str) -> dict:
        """Opens the file/folder properties dialog (Windows) or returns metadata."""
        try:
            if not self._is_trusted(path):
                return _DENIED
            p = Path(path)
            if not p.exists():
                return {"error": "Path does not exist."}
            if _SYSTEM == "Windows":
                import ctypes
                import ctypes.wintypes

                class SHELLEXECUTEINFOW(ctypes.Structure):
                    _fields_ = [
                        ("cbSize",       ctypes.wintypes.DWORD),
                        ("fMask",        ctypes.wintypes.ULONG),
                        ("hwnd",         ctypes.wintypes.HWND),
                        ("lpVerb",       ctypes.wintypes.LPCWSTR),
                        ("lpFile",       ctypes.wintypes.LPCWSTR),
                        ("lpParameters", ctypes.wintypes.LPCWSTR),
                        ("lpDirectory",  ctypes.wintypes.LPCWSTR),
                        ("nShow",        ctypes.c_int),
                        ("hInstApp",     ctypes.wintypes.HINSTANCE),
                        ("lpIDList",     ctypes.c_void_p),
                        ("lpClass",      ctypes.wintypes.LPCWSTR),
                        ("hkeyClass",    ctypes.wintypes.HKEY),
                        ("dwHotKey",     ctypes.wintypes.DWORD),
                        ("hIconOrMonitor", ctypes.wintypes.HANDLE),
                        ("hProcess",     ctypes.wintypes.HANDLE),
                    ]

                SEE_MASK_INVOKEIDLIST = 0x0000000C
                SW_SHOW = 5

                sei = SHELLEXECUTEINFOW()
                sei.cbSize       = ctypes.sizeof(sei)
                sei.fMask        = SEE_MASK_INVOKEIDLIST
                sei.hwnd         = None
                sei.lpVerb       = "properties"
                sei.lpFile       = str(p)
                sei.lpParameters = None
                sei.lpDirectory  = None
                sei.nShow        = SW_SHOW

                ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei))  # type: ignore[attr-defined]
                return {"ok": True}
            elif _SYSTEM == "Darwin":
                # Escape \ and " in path — both characters are legal in macOS names
                # and would cause injection into the AppleScript string.
                safe_p = str(p).replace("\\", "\\\\").replace('"', '\\"')
                subprocess.Popen(["osascript", "-e",
                    f'tell application "Finder" to open information window of (POSIX file "{safe_p}" as alias)'])
                return {"ok": True}
            else:
                # Linux — return metadata, JS will show a toast
                stat = p.stat()
                return {
                    "ok": True,
                    "meta": True,
                    "name": p.name,
                    "path": str(p),
                    "size": stat.st_size,
                    "mtime": int(stat.st_mtime),
                    "is_dir": p.is_dir(),
                }
        except Exception as e:
            return {"error": str(e)}

    # ── Scanning ──────────────────────────────────────────────────

    def scan(self, params: dict) -> dict:
        """
        Scans a folder in a separate thread — UI will not freeze.
        Sends the result/error back via evaluate_js('onScanDone(...)'),
        or 'onScanCancelled()' if cancel_scan() was called.

        Only one scan runs at a time; a second call returns {"busy": True}.

        params: { path, depth, incl_hidden, incl_system }
        """
        import scanner  # lazy

        path        = params.get("path", "")
        depth       = int(params.get("depth", 10))
        incl_hidden = bool(params.get("incl_hidden", False))
        incl_system = bool(params.get("incl_system", False))

        errors = []
        if not (1 <= depth <= 50):
            errors.append("Invalid scan depth (allowed: 1–50).")
        if not Path(path).exists():
            errors.append("Path does not exist.")
        if errors:
            log.warning("Scan rejected: %s (path=%r)", "; ".join(errors), path)
            return {"errors": errors}

        with self._scan_lock:
            if self._scan_cancel is not None:
                log.info("Scan rejected: another scan is running")
                return {"busy": True}
            cancel = threading.Event()
            self._scan_cancel = cancel
            self._scan_seq += 1
            scan_id = self._scan_seq

        self._trust_root(path)
        log.info(
            "Scan started: id=%d path=%r depth=%d hidden=%s system=%s",
            scan_id, path, depth, incl_hidden, incl_system,
        )

        def progress_cb(count: int):
            win = self._window
            if win is None or cancel.is_set():
                return
            try:
                win.evaluate_js(f"onScanProgress({count})")
            except Exception:
                pass

        def _run():
            scan_data = None
            started = time.monotonic()
            try:
                result = scanner.scan_path(
                    path, depth, incl_hidden, incl_system, progress_cb, cancel
                )
                if cancel.is_set():
                    raise scanner.ScanCancelled
                settings.save({"lastPath": path})
                result["depth"] = depth
                result["scan_id"] = scan_id
                scan_data = {
                    "id":           scan_id,
                    "tree":         result["tree"],
                    "path":         path,
                    "volume_label": result.get("volume_label", ""),
                }
                call = f"onScanDone({json.dumps(result, ensure_ascii=False)})"
                self._log_scan_result(scan_id, result, time.monotonic() - started)
            except scanner.ScanCancelled:
                log.info("Scan cancelled: id=%d after %.1fs", scan_id, time.monotonic() - started)
                call = "onScanCancelled()"
            except Exception as e:
                log.exception("Scan failed: id=%d path=%r", scan_id, path)
                call = f"onScanDone({json.dumps({'error': str(e)}, ensure_ascii=False)})"

            # Release before notifying JS so a scan started from the callback is accepted.
            # A cancelled or failed scan keeps the previous tree, which the UI still shows.
            with self._scan_lock:
                if scan_data is not None:
                    self._scan_data = scan_data
                self._scan_cancel = None
            self._notify(call)

        threading.Thread(target=_run, daemon=True).start()
        return {"async": True}

    @staticmethod
    def _log_scan_result(scan_id: int, result: dict, seconds: float) -> None:
        log.info(
            "Scan finished: id=%d files=%d folders=%d skipped=%d unreadable=%d beyond_depth=%d links=%d in %.1fs",
            scan_id, result["file_count"], result["folder_count"], result["skipped"],
            result["unreadable_count"], result["beyond_depth"], result["links_skipped"], seconds,
        )
        shown = result["unreadable"][:MAX_LOGGED_UNREADABLE]
        for entry in shown:
            log.warning("Unreadable %s: %s (%s)", entry["kind"], entry["path"], entry["reason"])
        hidden = result["unreadable_count"] - len(shown)
        if hidden > 0:
            log.warning("... and %d more unreadable entries", hidden)
        listed_links = result["links"][:MAX_LOGGED_LINKS]
        for link in listed_links:
            log.info("Link not followed (%s): %s -> %s", link["kind"], link["path"], link["target"])
        more_links = result["links_skipped"] - len(listed_links)
        if more_links > 0:
            log.info("... and %d more links", more_links)

    def cancel_scan(self) -> dict:
        """Asks the running scan to stop. Returns {"ok": False} if none is running."""
        with self._scan_lock:
            cancel = self._scan_cancel
        if cancel is None:
            return {"ok": False}
        cancel.set()
        return {"ok": True}

    # ── Export ────────────────────────────────────────────────────

    def export(self, params: dict) -> dict:
        """
        Validates the request, then writes the files in a separate thread.
        Progress goes to evaluate_js('onExportProgress(done, total, fmt)'), the outcome to
        evaluate_js('onExportDone({success, saved, errors} | {success: false, error})').

        Only one export runs at a time; a second call returns {"busy": True}.

        The scanned tree stays in Python (see scan()); the UI sends only the selection:
        params: { scan_id, formats, output_dir, custom_names, include_size, include_date,
                  date_pattern (strftime layout of %d %m %Y; invalid values fall back to the default),
                  selection: { all_except | only: [file paths],
                               folder_states: {path: state} (folders that are not "full"),
                               folder_notes, active_exts: [ext] | null } }
        """
        out_path = Path(params.get("output_dir", ""))
        if not out_path.exists():
            return self._refuse_export("Output folder does not exist.", out_path)
        if not os.access(out_path, os.W_OK):
            return self._refuse_export("Cannot write to output folder (permission denied).", out_path)

        with self._scan_lock:
            scan = self._scan_data
        if scan is None or params.get("scan_id") != scan["id"]:
            return self._refuse_export("Scan data is out of date. Run the scan again.", out_path)

        selection = params.get("selection")
        if not isinstance(selection, dict):
            return self._refuse_export("Selection is missing.", out_path)

        with self._export_lock:
            if self._exporting:
                log.info("Export rejected: another export is running")
                return {"busy": True}
            self._exporting = True

        threading.Thread(
            target=self._run_export, args=(scan, selection, params, out_path), daemon=True
        ).start()
        return {"async": True}

    @staticmethod
    def _refuse_export(message: str, out_path: Path) -> dict:
        log.warning("Export rejected: %s (output=%r)", message, str(out_path))
        return {"success": False, "error": message}

    def _run_export(self, scan: dict, selection: dict, params: dict, out_path: Path) -> None:
        try:
            result = self._write_exports(scan, selection, params, out_path)
        except Exception as e:
            log.exception("Export failed unexpectedly (output=%r)", str(out_path))
            result = {"success": False, "error": str(e)}
        with self._export_lock:
            self._exporting = False
        self._notify(f"onExportDone({json.dumps(result, ensure_ascii=False)})")

    def _write_exports(self, scan: dict, selection: dict, params: dict, out_path: Path) -> dict:
        import exporter  # lazy

        formats      = params.get("formats", [])
        include_size = params.get("include_size", True)
        include_date = params.get("include_date", True)
        date_pattern = exporter.normalize_date_pattern(params.get("date_pattern"))
        custom_names = params.get("custom_names", {})
        folder_notes = selection.get("folder_notes", {})
        raw_exts     = selection.get("active_exts")
        active_exts  = set(raw_exts) if raw_exts is not None else None
        tree         = scan["tree"]

        items = list(exporter.iter_export(
            tree, selection.get("folder_states", {}),
            self._selected_files(tree, selection), active_exts,
        ))
        meta = self._build_meta(items, scan, date_pattern)

        total       = len(items)
        valid       = [f for f in formats if f in exporter.WRITERS]
        grand_total = total * len(valid)
        started     = time.monotonic()
        log.info("Export started: formats=%s items=%d output=%r", formats, total, str(out_path))
        if valid:
            self._emit_export_progress(0, grand_total, valid[0])

        ts    = datetime.now().strftime("%Y-%m-%d_%H-%M")
        saved = []
        errors = []
        finished = 0

        for fmt in formats:
            writer = exporter.WRITERS.get(fmt)
            if not writer:
                log.warning("Export skipped unknown format: %r", fmt)
                errors.append(f"Unknown format: {fmt}")
                continue
            stem     = _safe_stem(
                custom_names.get(fmt) or f"LIST_{meta['disk_name']}_{ts}",
                f"LIST_{ts}",
            )
            target   = out_path / f"{stem}{_EXPORT_EXTS[fmt]}"
            out_file = None
            tmp_file = None

            def report(written: int, fmt=fmt, base=finished * total) -> None:
                self._emit_export_progress(base + written, grand_total, fmt)

            try:
                out_file = _reserve_unique(target)
                tmp_file = out_file.with_name(out_file.name + ".part")
                with open(tmp_file, "w", encoding="utf-8") as fh:
                    writer(fh, items, meta, include_size=include_size, include_date=include_date,
                           date_pattern=date_pattern, folder_notes=folder_notes, progress=report)
                os.replace(tmp_file, out_file)
            except Exception as e:
                log.exception("Export failed: format=%s target=%s", fmt, out_file or target)
                for ours in (tmp_file, out_file):
                    if ours is not None:
                        try:
                            ours.unlink(missing_ok=True)
                        except OSError:
                            pass
                errors.append(f"{fmt}: {e}")
            else:
                self._trust_file(str(out_file))
                saved.append(str(out_file))
                log.info("Export saved: %s", out_file)
            finished += 1

        settings.save({
            "lastOutput":  str(out_path),
            "lastFormats": formats,
        })
        log.info(
            "Export finished: saved=%d errors=%d in %.1fs",
            len(saved), len(errors), time.monotonic() - started,
        )

        return {
            "success": len(saved) > 0,
            "saved":   saved,
            "errors":  errors,
        }

    def _emit_export_progress(self, done: int, total: int, fmt: str) -> None:
        self._notify(f"onExportProgress({done}, {total}, {json.dumps(fmt)})")

    @staticmethod
    def _selected_files(tree: list, selection: dict) -> set:
        if "only" in selection:
            return set(selection["only"])
        all_files = {item["path"] for item in tree if item["type"] == "file"}
        return all_files.difference(selection.get("all_except", ()))

    def _build_meta(self, items: list, scan: dict, date_pattern: str) -> dict:
        import exporter  # lazy
        path = scan["path"]
        volume_label = scan["volume_label"]
        disk_name = (
            volume_label
            or Path(path).name
            or path.replace(":", "").replace("\\", "").replace("/", "")
            or "DISK"
        )

        file_count   = 0
        folder_count = 0
        total        = 0
        name_only    = 0
        for item in items:
            if item[1] == "file":
                file_count += 1
                total += item[4]
            else:
                if item[0] > 0:
                    folder_count += 1
                if item[6] == "name":
                    name_only += 1

        return {
            "disk_name":        disk_name,
            "volume_label":     volume_label,
            "path":             path,
            "timestamp":        datetime.now().strftime(f"{date_pattern} %H:%M"),
            "file_count":       file_count,
            "folder_count":     folder_count,
            "total_size":       exporter.fmt_size(total),
            "name_only_count":  name_only,
            "generated_by":     "flashscan",
        }
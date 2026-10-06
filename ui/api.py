"""
api.py — pywebview JS API

Methods of this class are callable from JS as:
  window.pywebview.api.method_name(args)

Responsible for:
  - scanning (runs scanner.py in a thread)
  - export (calls exporter.py)
  - dialogs (browse_directory)
  - settings (get/save)
"""

from __future__ import annotations

import os
import platform
import subprocess
import threading
from datetime import datetime
from pathlib import Path

import json

import webview  # pywebview

import settings

_SYSTEM = platform.system()  # 'Windows' | 'Darwin' | 'Linux'


class API:
    def __init__(self, window_ref_holder: list):
        # window_ref_holder is [window] — populated after window creation
        self._win = window_ref_holder

    @property
    def _window(self):
        return self._win[0] if self._win else None

    # ── Settings ───────────────────────────────────────────────────

    def get_settings(self) -> dict:
        return settings.load()

    def save_settings(self, data: dict) -> None:
        settings.save(data)

    def get_custom_exts(self) -> list:
        return settings.load().get("customExts", [])

    def save_custom_exts(self, exts: list) -> None:
        settings.save({"customExts": exts})

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
        Sends the result/error back via evaluate_js('onScanDone(...)').

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
            return {"errors": errors}

        def progress_cb(count: int):
            win = self._window
            if win is None:
                return
            try:
                win.evaluate_js(f"onScanProgress({count})")
            except Exception:
                pass

        def _run():
            win = self._window
            try:
                result = scanner.scan_path(
                    path, depth, incl_hidden, incl_system, progress_cb
                )
                settings.save({"lastPath": path})
                payload = json.dumps(result, ensure_ascii=False)
                if win:
                    win.evaluate_js(f"onScanDone({payload})")
            except Exception as e:
                payload = json.dumps({"error": str(e)}, ensure_ascii=False)
                if win:
                    win.evaluate_js(f"onScanDone({payload})")

        threading.Thread(target=_run, daemon=True).start()
        return {"async": True}

    # ── Export ────────────────────────────────────────────────────

    def export(self, params: dict) -> dict:
        import exporter  # lazy

        formats        = params.get("formats", [])
        output_dir     = params.get("output_dir", "")
        folder_states  = params.get("folder_states", {})
        folder_notes   = params.get("folder_notes", {})
        selected_files = set(params.get("selected_files", []))
        # active_exts: null = all, list = allowed extensions
        raw_exts   = params.get("active_exts", None)
        active_exts = set(raw_exts) if raw_exts is not None else None
        include_size = params.get("include_size", True)
        include_date = params.get("include_date", True)

        out_path = Path(output_dir)
        if not out_path.exists():
            return {"success": False, "error": "Output folder does not exist."}
        if not os.access(out_path, os.W_OK):
            return {"success": False, "error": "Cannot write to output folder (permission denied)."}

        tree = params.get("tree", [])
        if not tree:
            return {"success": False, "error": "No data to export (tree is missing)."}

        meta = self._build_meta(tree, folder_states, selected_files, params, active_exts)

        builders = {
            "MD":   exporter.build_md,
            "TXT":  exporter.build_txt,
            "JSON": exporter.build_json,
            "HTML": exporter.build_html,
        }
        exts = {"MD": ".md", "TXT": ".txt", "JSON": ".json", "HTML": ".html"}
        custom_names = params.get("custom_names", {})

        ts    = datetime.now().strftime("%Y-%m-%d_%H-%M")
        saved = []
        errors = []

        for fmt in formats:
            builder = builders.get(fmt)
            if not builder:
                errors.append(f"Unknown format: {fmt}")
                continue
            stem     = custom_names.get(fmt) or f"LIST_{meta['disk_name']}_{ts}"
            fname    = f"{stem}{exts[fmt]}"
            out_file = out_path / fname
            try:
                content = builder(tree, folder_states, selected_files, meta, active_exts,
                                 include_size=include_size, include_date=include_date,
                                 folder_notes=folder_notes)
                out_file.write_text(content, encoding="utf-8")
                saved.append(str(out_file))
            except Exception as e:
                errors.append(f"{fmt}: {e}")

        settings.save({
            "lastOutput":  output_dir,
            "lastFormats": formats,
        })

        return {
            "success": len(saved) > 0,
            "saved":   saved,
            "errors":  errors,
        }

    def _build_meta(self, tree, folder_states, selected_files, params, active_exts=None) -> dict:
        import exporter  # lazy
        path = params.get("path", "")
        volume_label = params.get("volume_label", "")
        disk_name = (
            volume_label
            or Path(path).name
            or path.replace(":", "").replace("\\", "").replace("/", "")
            or "DISK"
        )

        files: list = []
        name_only = 0
        for item in exporter.iter_export(tree, folder_states, selected_files, active_exts):
            if item[1] == "file":
                files.append(item)
            elif item[1] == "folder" and item[6] == "name":
                name_only += 1
        total         = sum(f[4] for f in files)
        folders_total = sum(1 for item in tree if item["type"] == "folder")

        return {
            "disk_name":        disk_name,
            "volume_label":     volume_label,
            "path":             path,
            "timestamp":        datetime.now().strftime("%d. %m. %Y %H:%M"),
            "file_count":       len(files),
            "folder_count":     folders_total,
            "total_size":       exporter.fmt_size(total),
            "name_only_count":  name_only,
            "generated_by":     "flashscan",
        }
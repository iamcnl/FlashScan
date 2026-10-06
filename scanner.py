"""
scanner.py — file system scanner

No UI dependencies. Testable standalone.
Returns a flat list of dict items compatible with JS State.reset().
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from datetime import datetime

try:
    import ctypes
    _HAS_CTYPES = True
except ImportError:
    _HAS_CTYPES = False

# ── Windows system folders (skip if incl_system=False) ──
WIN_SYSTEM_DIRS = {
    "$recycle.bin", "system volume information", "$windows.~bt",
    "$windows.~ws", "recovery", "boot", "bootmgr",
}


# ── Windows attributes ────────────────────────────────────────────

def _win_attrs(path: str) -> int:
    if not _HAS_CTYPES:
        return 0
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
        return 0 if attrs == -1 else attrs
    except Exception:
        return 0


def is_hidden(path: Path) -> bool:
    name = path.name
    if name.startswith("."):
        return True
    if _HAS_CTYPES:
        return bool(_win_attrs(str(path)) & 0x2)
    return False


def is_system(path: Path) -> bool:
    if not _HAS_CTYPES:
        return False
    return bool(_win_attrs(str(path)) & 0x4)


# ── Volume label ─────────────────────────────────────────────────

def get_volume_info(path: str) -> dict:
    """Returns {'label': str, 'serial': int | None} for the drive that holds path."""
    label, serial = "", None
    try:
        if _HAS_CTYPES and hasattr(ctypes, 'windll'):
            # Windows: GetVolumeInformationW
            root = str(Path(path).anchor)  # e.g. "D:\"
            buf = ctypes.create_unicode_buffer(256)
            serial_no = ctypes.c_uint32(0)
            ok = ctypes.windll.kernel32.GetVolumeInformationW(
                root, buf, len(buf),
                ctypes.byref(serial_no), None, None, None, 0
            )
            if ok:
                label = buf.value
                serial = serial_no.value or None
        else:
            # macOS/Linux: try via diskutil or /proc/mounts
            anchor = str(Path(path).anchor)
            try:
                out = subprocess.check_output(
                    ["diskutil", "info", anchor],
                    stderr=subprocess.DEVNULL, timeout=3
                ).decode(errors="ignore")
                for line in out.splitlines():
                    if "Volume Name" in line:
                        label = line.split(":", 1)[-1].strip()
                        break
            except Exception:
                pass
    except Exception:
        pass
    return {"label": label, "serial": serial}


def get_volume_label(path: str) -> str:
    """Returns the volume label of the drive, or an empty string if unavailable."""
    return get_volume_info(path)["label"]


def make_volume_id(info: dict, root_path: str) -> str:
    """Stable drive identity: volume serial where available, else the scan path."""
    if info["serial"]:
        return f"serial:{info['serial']:08X}"
    return f"path:{os.path.normcase(os.path.abspath(root_path))}"


# ── Main scan ─────────────────────────────────────────────────────

def scan_path(
    root_path: str,
    max_depth: int = 10,
    incl_hidden: bool = False,
    incl_system: bool = False,
    progress_cb=None,
) -> dict:
    """
    Scans root_path and returns a dict:
    {
        'tree':         [{ lvl, type, name, path, size, mtime }, ...],
        'file_count':   int,
        'folder_count': int,
        'skipped':      int,
        'volume_label': str,
        'volume_id':    str,   # serial:XXXXXXXX or path:<normalized scan path>
        'volume_root':  str,   # drive root; profile keys are relative to it
    }

    tree is a flat list in DFS order (folder, then its contents).
    Directly compatible with JS State.reset(tree).
    """
    root = Path(root_path)
    tree: list[dict] = []
    file_count   = 0
    folder_count = 0
    skipped      = 0

    path_to_idx: dict[str, int] = {}
    for dirpath, dirs, files in os.walk(root, onerror=lambda e: None):
        try:
            rel   = Path(dirpath).relative_to(root)
            depth = len(rel.parts)
        except ValueError:
            depth = 0

        if depth > max_depth:
            dirs.clear()
            continue

        # Filter subdirectories
        filtered_dirs = []
        for d in sorted(dirs):
            dpath = Path(dirpath) / d
            if not incl_system and d.lower() in WIN_SYSTEM_DIRS:
                skipped += 1
                continue
            if not incl_hidden and is_hidden(dpath):
                skipped += 1
                continue
            if not incl_system and is_system(dpath):
                skipped += 1
                continue
            filtered_dirs.append(d)
        dirs[:] = filtered_dirs

        folder_count += 1
        folder_name = Path(dirpath).name or root.name

        # Folder modification date from OS
        try:
            fst    = Path(dirpath).stat()
            fmtime = fst.st_mtime
        except OSError:
            fmtime = 0

        folder_entry = {
            "lvl":   depth,
            "type":  "folder",
            "name":  folder_name,
            "path":  str(dirpath),
            "size":  0,       # will be accumulated below
            "mtime": fmtime,
        }
        tree.append(folder_entry)
        path_to_idx[str(dirpath)] = len(tree) - 1

        folder_size = 0
        for fname in sorted(files):
            fpath = Path(dirpath) / fname
            if not incl_hidden and is_hidden(fpath):
                skipped += 1
                continue
            if not incl_system and is_system(fpath):
                skipped += 1
                continue
            try:
                st    = fpath.stat()
                size  = st.st_size
                mtime = st.st_mtime
            except OSError:
                skipped += 1
                continue

            tree.append({
                "lvl":   depth + 1,
                "type":  "file",
                "name":  fname,
                "path":  str(fpath),
                "size":  size,
                "mtime": mtime,
            })
            folder_size += size
            file_count += 1
            if progress_cb and file_count % 100 == 0:
                progress_cb(file_count)

        folder_entry["size"] = folder_size
        # Add direct files of this folder to all ancestors
        ancestor = Path(dirpath).parent
        while ancestor != Path(dirpath) and str(ancestor) in path_to_idx:
            tree[path_to_idx[str(ancestor)]]["size"] += folder_size
            if ancestor == root:
                break
            ancestor = ancestor.parent

    volume = get_volume_info(root_path)
    return {
        "tree":         tree,
        "file_count":   file_count,
        "folder_count": folder_count,
        "skipped":      skipped,
        "volume_label": volume["label"],
        "volume_id":    make_volume_id(volume, root_path),
        "volume_root":  str(root.anchor),
    }

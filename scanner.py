"""
scanner.py — file system scanner

No UI dependencies. Testable standalone.
Returns a flat list of dict items compatible with JS State.reset().
"""

from __future__ import annotations

import os
import stat
import subprocess
import threading
from pathlib import Path

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


def make_volume_id(info: dict, root_path: str) -> str:
    """Stable drive identity: volume serial where available, else the scan path."""
    if info["serial"]:
        return f"serial:{info['serial']:08X}"
    return f"path:{os.path.normcase(os.path.abspath(root_path))}"


# ── Main scan ─────────────────────────────────────────────────────

class ScanCancelled(Exception):
    """Raised by scan_path when cancel_event is set."""


MAX_UNREADABLE_DETAILS = 200
MAX_LINK_DETAILS = 200

IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003


def _reason(error: OSError) -> str:
    return error.strerror or type(error).__name__


def _is_link(st: os.stat_result) -> bool:
    return stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) == IO_REPARSE_TAG_MOUNT_POINT


def scan_path(
    root_path: str,
    max_depth: int = 10,
    incl_hidden: bool = False,
    incl_system: bool = False,
    progress_cb=None,
    cancel_event: threading.Event | None = None,
) -> dict:
    """
    Scans root_path and returns a dict:
    {
        'tree':         [{ lvl, type, name, path, size, mtime }, ...],
        'file_count':   int,
        'folder_count': int,
        'skipped':      int,   # hidden/system entries left out by the options, not errors
        'unreadable_count': int,
        'unreadable':   [{ path, kind: 'folder' | 'file' | 'date', reason }, ...],  # first 200
        'beyond_depth': int,   # folders just below max_depth that were not scanned
        'links_skipped': int,  # symlinks and junctions that were not followed
        'links':        [{ path, kind: 'folder' | 'file', target }, ...],  # first 200
        'volume_label': str,
        'volume_id':    str,   # serial:XXXXXXXX or path:<normalized scan path>
        'volume_root':  str,   # drive root; profile keys are relative to it
    }

    tree is a flat list in DFS order (folder, then its contents).
    Directly compatible with JS State.reset(tree).

    Symlinks and NTFS junctions are never followed or listed, so a link can neither
    loop the scan nor count the same files twice. root_path itself may be a link.

    Raises ScanCancelled if cancel_event is set while scanning, and OSError if
    root_path itself cannot be read.
    """
    def check_cancelled():
        if cancel_event is not None and cancel_event.is_set():
            raise ScanCancelled

    root = Path(root_path)
    tree: list[dict] = []
    file_count   = 0
    folder_count = 0
    skipped      = 0
    unreadable: list[dict] = []
    unreadable_count = 0
    beyond_depth = 0
    links: list[dict] = []
    links_skipped = 0

    def note_unreadable(path, kind: str, error: OSError) -> None:
        nonlocal unreadable_count
        unreadable_count += 1
        if len(unreadable) < MAX_UNREADABLE_DETAILS:
            unreadable.append({"path": str(path), "kind": kind, "reason": _reason(error)})

    def note_link(path, kind: str) -> None:
        nonlocal links_skipped
        links_skipped += 1
        if len(links) < MAX_LINK_DETAILS:
            try:
                target = os.readlink(path)
            except OSError:
                target = ""
            links.append({"path": str(path), "kind": kind, "target": target})

    def on_walk_error(error: OSError) -> None:
        path = str(error.filename) if error.filename else "?"
        if path == str(root):
            raise OSError(f"Cannot read {root}: {_reason(error)}") from error
        note_unreadable(path, "folder", error)

    path_to_idx: dict[str, int] = {}
    for dirpath, dirs, files in os.walk(root, onerror=on_walk_error):
        check_cancelled()
        try:
            rel   = Path(dirpath).relative_to(root)
            depth = len(rel.parts)
        except ValueError:
            depth = 0

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
            try:
                dir_is_link = _is_link(os.lstat(dpath))
            except OSError:
                dir_is_link = False  # os.walk reports an unreadable folder itself
            if dir_is_link:
                note_link(dpath, "folder")
                continue
            filtered_dirs.append(d)

        if depth >= max_depth:
            beyond_depth += len(filtered_dirs)
            dirs.clear()
        else:
            dirs[:] = filtered_dirs

        folder_count += 1
        folder_name = Path(dirpath).name or root.name

        # Folder modification date from OS
        try:
            fst    = Path(dirpath).stat()
            fmtime = fst.st_mtime
        except OSError as e:
            fmtime = 0
            note_unreadable(dirpath, "date", e)

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
            check_cancelled()
            fpath = Path(dirpath) / fname
            if not incl_hidden and is_hidden(fpath):
                skipped += 1
                continue
            if not incl_system and is_system(fpath):
                skipped += 1
                continue
            try:
                st = os.lstat(fpath)
            except OSError as e:
                note_unreadable(fpath, "file", e)
                continue
            if _is_link(st):
                note_link(fpath, "file")
                continue
            size  = st.st_size
            mtime = st.st_mtime

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

    check_cancelled()
    volume = get_volume_info(root_path)
    return {
        "tree":         tree,
        "file_count":   file_count,
        "folder_count": folder_count,
        "skipped":      skipped,
        "unreadable_count": unreadable_count,
        "unreadable":   unreadable,
        "beyond_depth": beyond_depth,
        "links_skipped": links_skipped,
        "links":        links,
        "volume_label": volume["label"],
        "volume_id":    make_volume_id(volume, root_path),
        "volume_root":  str(root.anchor),
    }
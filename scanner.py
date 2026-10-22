"""
scanner.py — file system scanner

No UI dependencies. Testable standalone.
Returns a flat list of dict items compatible with JS State.reset().
"""

from __future__ import annotations

import operator
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

_IS_WINDOWS = os.name == "nt"

_by_name = operator.attrgetter("name")


def _reason(error: OSError) -> str:
    return error.strerror or type(error).__name__


def _is_link(st: os.stat_result) -> bool:
    return stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) == IO_REPARSE_TAG_MOUNT_POINT


def _lstat(entry: os.DirEntry) -> os.stat_result:
    return entry.stat(follow_symlinks=False)


def _file_attributes(entry: os.DirEntry, st: os.stat_result) -> int:
    return getattr(st, "st_file_attributes", 0)


def _is_dir(entry: os.DirEntry) -> bool:
    try:
        return entry.is_dir()
    except OSError:
        return False


def _link_target(path) -> str:
    try:
        target = os.readlink(path)
    except OSError:
        return ""
    if _IS_WINDOWS:
        if target.startswith("\\\\?\\UNC\\"):
            return "\\\\" + target[8:]
        if target.startswith("\\\\?\\"):
            return target[4:]
    return target


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
            links.append({"path": str(path), "kind": kind, "target": _link_target(path)})

    hidden_bit = stat.FILE_ATTRIBUTE_HIDDEN
    system_bit = stat.FILE_ATTRIBUTE_SYSTEM
    parent_of: dict[int, int | None] = {}
    stack = [(str(root), root.name, 0, None, None, None)]

    while stack:
        check_cancelled()
        dirpath, folder_name, depth, parent_idx, dir_st, dir_err = stack.pop()

        try:
            with os.scandir(dirpath) as it:
                entries = sorted(it, key=_by_name)
        except OSError as e:
            if parent_idx is None:
                raise OSError(f"Cannot read {root}: {_reason(e)}") from e
            note_unreadable(dirpath, "folder", e)
            continue

        if parent_idx is None:
            try:
                dir_st = os.stat(dirpath)
            except OSError as e:
                dir_err = e
        if dir_st is not None:
            fmtime = dir_st.st_mtime
        else:
            fmtime = 0
            note_unreadable(dirpath, "date", dir_err)

        folder_idx = len(tree)
        folder_entry = {
            "lvl":   depth,
            "type":  "folder",
            "name":  folder_name,
            "path":  dirpath,
            "size":  0,
            "mtime": fmtime,
        }
        tree.append(folder_entry)
        parent_of[folder_idx] = parent_idx
        folder_count += 1

        subdirs = []
        folder_size = 0
        for entry in entries:
            check_cancelled()
            name = entry.name
            try:
                st, err = _lstat(entry), None
            except OSError as e:
                st, err = None, e

            link = st is not None and _is_link(st)
            if st is None or link:
                is_dir = _is_dir(entry)
            else:
                is_dir = stat.S_ISDIR(st.st_mode)
            attrs = _file_attributes(entry, st) if st is not None else 0

            if is_dir and not incl_system and name.lower() in WIN_SYSTEM_DIRS:
                skipped += 1
                continue
            if not incl_hidden and (name.startswith(".") or attrs & hidden_bit):
                skipped += 1
                continue
            if not incl_system and attrs & system_bit:
                skipped += 1
                continue
            if link:
                note_link(entry.path, "folder" if is_dir else "file")
                continue

            if is_dir:
                subdirs.append((entry.path, name, depth + 1, folder_idx, st, err))
                continue
            if st is None:
                note_unreadable(entry.path, "file", err)
                continue

            size = st.st_size
            tree.append({
                "lvl":   depth + 1,
                "type":  "file",
                "name":  name,
                "path":  entry.path,
                "size":  size,
                "mtime": st.st_mtime,
            })
            folder_size += size
            file_count += 1
            if progress_cb and file_count % 100 == 0:
                progress_cb(file_count)

        if depth >= max_depth:
            beyond_depth += len(subdirs)
        else:
            stack.extend(reversed(subdirs))

        folder_entry["size"] = folder_size
        ancestor = parent_idx
        while ancestor is not None:
            tree[ancestor]["size"] += folder_size
            ancestor = parent_of[ancestor]

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
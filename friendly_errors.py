"""Plain-language messages for exceptions that would otherwise reach the UI."""

from __future__ import annotations

import errno

GENERIC_ERROR = "Something went wrong. Details are in the log."
NOT_A_FOLDER = "That location is a file, not a folder."
PATH_TOO_LONG = "That path is too long."
DISK_FULL = "Not enough free space there."
NO_ASSOCIATION = "No app is set up to open that file."
NO_PERMISSION = {
    "read": "No permission to read there.",
    "write": "No permission to write there.",
}

ERROR_ACCESS_DENIED = 5
ERROR_WRITE_PROTECT = 19
ERROR_HANDLE_DISK_FULL = 39
ERROR_DISK_FULL = 112
ERROR_NO_ASSOCIATION = 1155
ERROR_FILENAME_EXCED_RANGE = 206
ERROR_DIRECTORY = 267


def _errnos(*names: str) -> frozenset:
    return frozenset(getattr(errno, name) for name in names if hasattr(errno, name))


_TOO_LONG = (_errnos("ENAMETOOLONG"), frozenset({ERROR_FILENAME_EXCED_RANGE}))
_NOT_A_DIR = (_errnos("ENOTDIR"), frozenset({ERROR_DIRECTORY}))
_DENIED = (_errnos("EACCES", "EPERM", "EROFS"), frozenset({ERROR_ACCESS_DENIED, ERROR_WRITE_PROTECT}))
_NO_SPACE = (_errnos("ENOSPC", "EDQUOT"), frozenset({ERROR_HANDLE_DISK_FULL, ERROR_DISK_FULL}))


def describe_error(exc: BaseException, action: str = "read") -> str:
    """Returns a sentence for the user. The exception itself belongs in the log."""
    if not isinstance(exc, OSError):
        return GENERIC_ERROR

    code = exc.errno
    win = getattr(exc, "winerror", None)

    def matches(codes: tuple) -> bool:
        return code in codes[0] or win in codes[1]

    if win == ERROR_NO_ASSOCIATION:
        return NO_ASSOCIATION
    # Windows reports an over-long path as FileNotFoundError, so this check comes first
    if matches(_TOO_LONG):
        return PATH_TOO_LONG
    if matches(_NOT_A_DIR) or isinstance(exc, NotADirectoryError):
        return NOT_A_FOLDER
    if matches(_DENIED) or isinstance(exc, PermissionError):
        return NO_PERMISSION[action]
    if matches(_NO_SPACE):
        return DISK_FULL
    return GENERIC_ERROR
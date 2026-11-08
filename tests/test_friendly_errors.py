import errno

import pytest

from friendly_errors import (
    DISK_FULL, GENERIC_ERROR, NO_ASSOCIATION, NO_PERMISSION, NOT_A_FOLDER, PATH_TOO_LONG,
    describe_error,
)


def os_error(code, winerror=None, kind=OSError):
    exc = kind(code, "raw detail")
    if winerror is not None:
        exc.winerror = winerror
    return exc


@pytest.mark.parametrize("exc, message", [
    (os_error(errno.ENAMETOOLONG), PATH_TOO_LONG),
    (os_error(errno.ENOENT, winerror=206, kind=FileNotFoundError), PATH_TOO_LONG),
    (os_error(errno.ENOTDIR), NOT_A_FOLDER),
    (os_error(errno.ENOENT, winerror=267, kind=NotADirectoryError), NOT_A_FOLDER),
    (NotADirectoryError("raw detail"), NOT_A_FOLDER),
    (os_error(errno.ENOSPC), DISK_FULL),
    (os_error(errno.EIO, winerror=112), DISK_FULL),
    (os_error(errno.EIO, winerror=39), DISK_FULL),
    (os_error(errno.EIO, winerror=1155), NO_ASSOCIATION),
    (os_error(errno.EIO), GENERIC_ERROR),
    (RuntimeError("raw detail"), GENERIC_ERROR),
    (ValueError("embedded null byte"), GENERIC_ERROR),
])
def test_errors_become_plain_sentences(exc, message):
    assert describe_error(exc) == message
    assert "raw detail" not in describe_error(exc)


@pytest.mark.parametrize("exc", [
    os_error(errno.EACCES),
    os_error(errno.EPERM),
    os_error(errno.EROFS),
    os_error(errno.EIO, winerror=5),
    os_error(errno.EIO, winerror=19),
    PermissionError("raw detail"),
])
@pytest.mark.parametrize("action", ["read", "write"])
def test_permission_errors_name_what_was_being_attempted(exc, action):
    assert describe_error(exc, action) == NO_PERMISSION[action]


def test_reading_is_the_default_action():
    assert describe_error(PermissionError()) == NO_PERMISSION["read"]
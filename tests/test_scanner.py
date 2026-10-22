import os
import pathlib
import stat
import threading
import types

import pytest

import scanner


def build(root, files):
    for rel, size in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)


def scan(root, **kwargs):
    return scanner.scan_path(str(root), **kwargs)


def names(result, kind):
    return [i["name"] for i in result["tree"] if i["type"] == kind]


def item(result, name):
    return next(i for i in result["tree"] if i["name"] == name)


def link(root, name, target, directory=False):
    try:
        os.symlink(target, root / name, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")


@pytest.fixture
def root(tmp_path):
    drive = tmp_path / "drive"
    drive.mkdir()
    return drive


@pytest.fixture(autouse=True)
def no_volume_lookup(monkeypatch):
    monkeypatch.setattr(scanner, "get_volume_info", lambda path: {"label": "", "serial": None})


@pytest.fixture
def unreadable_file(monkeypatch):
    real_lstat = scanner._lstat
    denied = set()

    def lstat(entry):
        if entry.name in denied:
            raise PermissionError(13, "Permission denied", entry.path)
        return real_lstat(entry)

    monkeypatch.setattr(scanner, "_lstat", lstat)
    return denied.add


# ── Result shape ─────────────────────────────────────────────────

def test_result_has_all_keys_the_ui_expects(root):
    assert set(scan(root)) == {
        "tree", "file_count", "folder_count", "skipped", "unreadable_count",
        "unreadable", "beyond_depth", "links_skipped", "links",
        "volume_label", "volume_id", "volume_root",
    }


def test_flat_folder(root):
    build(root, {"b.txt": 3, "a.txt": 5})
    r = scan(root)

    assert r["file_count"] == 2
    assert r["folder_count"] == 1
    assert r["tree"][0] == {
        "lvl": 0, "type": "folder", "name": "drive",
        "path": str(root), "size": 8, "mtime": r["tree"][0]["mtime"],
    }
    assert names(r, "file") == ["a.txt", "b.txt"]
    assert all(i["lvl"] == 1 for i in r["tree"][1:])


def test_tree_order_is_depth_first_with_files_before_subfolders(root):
    build(root, {"a/one.txt": 1, "a/b/two.txt": 1, "z.txt": 1})
    r = scan(root)

    assert [(i["lvl"], i["type"], i["name"]) for i in r["tree"]] == [
        (0, "folder", "drive"),
        (1, "file", "z.txt"),
        (1, "folder", "a"),
        (2, "file", "one.txt"),
        (2, "folder", "b"),
        (3, "file", "two.txt"),
    ]


def test_siblings_are_sorted(root):
    build(root, {"c/x": 1, "a/x": 1, "b/x": 1, "z.txt": 1, "m.txt": 1})
    r = scan(root)

    assert names(r, "folder") == ["drive", "a", "b", "c"]
    assert names(r, "file")[:2] == ["m.txt", "z.txt"]


def test_file_size_and_mtime_come_from_the_file(root):
    build(root, {"f.bin": 42})
    os.utime(root / "f.bin", (1_700_000_000, 1_700_000_000))

    f = item(scan(root), "f.bin")

    assert f["size"] == 42
    assert f["mtime"] == 1_700_000_000
    assert f["path"] == str(root / "f.bin")


def test_empty_folder_is_listed_with_zero_size(root):
    (root / "empty").mkdir()
    r = scan(root)

    assert item(r, "empty")["size"] == 0
    assert r["folder_count"] == 2
    assert r["file_count"] == 0


def test_odd_but_portable_names_round_trip(root):
    odd = [
        "naïve ☃ 日本語.txt",
        "a & b.txt",
        "it's #1 [x] {y}.txt",
        "multi.dot.name.tar.gz",
        "no_extension",
        "dir with spaces/üñí.txt",
    ]
    build(root, {name: 1 for name in odd})
    r = scan(root)

    assert set(names(r, "file")) == {"naïve ☃ 日本語.txt", "a & b.txt", "it's #1 [x] {y}.txt",
                                     "multi.dot.name.tar.gz", "no_extension", "üñí.txt"}
    assert "dir with spaces" in names(r, "folder")
    assert all(os.path.exists(i["path"]) for i in r["tree"])


# ── Sizes ────────────────────────────────────────────────────────

def test_folder_size_is_recursive_sum(root):
    build(root, {"a/x.bin": 10, "a/b/y.bin": 20})
    r = scan(root)

    assert item(r, "b")["size"] == 20
    assert item(r, "a")["size"] == 30
    assert item(r, "drive")["size"] == 30


def test_size_reaches_every_ancestor(root):
    build(root, {"r.bin": 1, "a/a.bin": 2, "a/b/b.bin": 4, "a/b/c/c.bin": 8})
    r = scan(root)

    assert [item(r, n)["size"] for n in ("drive", "a", "b", "c")] == [15, 14, 12, 8]


def test_skipped_files_do_not_add_to_sizes(root):
    build(root, {".hidden": 100, "shown.bin": 5})

    assert item(scan(root), "drive")["size"] == 5
    assert item(scan(root, incl_hidden=True), "drive")["size"] == 105


# ── Depth ────────────────────────────────────────────────────────

def test_max_depth_stops_descent(root):
    build(root, {"a/b/c/deep.txt": 1, "a/b/at_limit.txt": 1})
    r = scan(root, max_depth=2)

    assert names(r, "folder") == ["drive", "a", "b"]
    assert "deep.txt" not in names(r, "file")
    assert item(r, "at_limit.txt")["lvl"] == 3
    assert r["beyond_depth"] == 1


def test_beyond_depth_counts_each_folder_just_below_the_limit(root):
    build(root, {"a/c1/x": 1, "a/c2/y": 1, "a/c1/deeper/z": 1})
    r = scan(root, max_depth=1)

    assert names(r, "folder") == ["drive", "a"]
    assert r["beyond_depth"] == 2


def test_max_depth_zero_scans_only_the_root(root):
    build(root, {"top.txt": 1, "sub/inner.txt": 1})
    r = scan(root, max_depth=0)

    assert names(r, "folder") == ["drive"]
    assert names(r, "file") == ["top.txt"]
    assert r["beyond_depth"] == 1


def test_folders_below_the_depth_limit_are_never_listed(root, monkeypatch):
    build(root, {"a/b/c/deep.txt": 1})
    listed = []
    real_scandir = os.scandir

    def spy(path):
        listed.append(os.path.basename(os.fspath(path)))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", spy)
    scan(root, max_depth=2)

    assert "c" not in listed


def test_nothing_is_beyond_depth_when_everything_fits(root):
    build(root, {"a/b/c.txt": 1})

    assert scan(root, max_depth=10)["beyond_depth"] == 0


# ── Hidden and system filters ────────────────────────────────────

def test_hidden_entries_are_skipped_and_counted(root):
    build(root, {".secret": 1, ".hid/inside.txt": 1, "vis.txt": 1})
    r = scan(root)

    assert names(r, "file") == ["vis.txt"]
    assert names(r, "folder") == ["drive"]
    assert r["skipped"] == 2
    assert r["file_count"] == 1


def test_incl_hidden_brings_them_back(root):
    build(root, {".secret": 1, ".hid/inside.txt": 1, "vis.txt": 1})
    r = scan(root, incl_hidden=True)

    assert set(names(r, "file")) == {".secret", "inside.txt", "vis.txt"}
    assert ".hid" in names(r, "folder")
    assert r["skipped"] == 0


@pytest.mark.parametrize("system_dir", ["$RECYCLE.BIN", "System Volume Information", "recovery"])
def test_windows_system_folders_are_skipped_regardless_of_case(root, system_dir):
    build(root, {f"{system_dir}/x.bin": 1, "keep/y.bin": 1})
    r = scan(root)

    assert names(r, "folder") == ["drive", "keep"]
    assert r["skipped"] == 1


def test_incl_system_keeps_windows_system_folders(root):
    build(root, {"$RECYCLE.BIN/x.bin": 1, "keep/y.bin": 1})
    r = scan(root, incl_system=True)

    assert names(r, "folder") == ["drive", "$RECYCLE.BIN", "keep"]
    assert r["skipped"] == 0


@pytest.fixture
def win_attrs(monkeypatch):
    attrs = {"secret.txt": 0x2, "sys.txt": 0x4, "hid_dir": 0x2}
    monkeypatch.setattr(scanner, "_file_attributes", lambda entry, st: attrs.get(entry.name, 0))


def test_hidden_attribute_hides_files(root, win_attrs):
    build(root, {"secret.txt": 1, "sys.txt": 1, "normal.txt": 1})

    r = scan(root, incl_system=True)
    assert names(r, "file") == ["normal.txt", "sys.txt"]
    assert r["skipped"] == 1

    r = scan(root, incl_hidden=True, incl_system=True)
    assert names(r, "file") == ["normal.txt", "secret.txt", "sys.txt"]
    assert r["skipped"] == 0


def test_system_attribute_hides_files(root, win_attrs):
    build(root, {"secret.txt": 1, "sys.txt": 1, "normal.txt": 1})

    r = scan(root, incl_hidden=True)

    assert names(r, "file") == ["normal.txt", "secret.txt"]
    assert r["skipped"] == 1


def test_hidden_attribute_skips_a_folder_and_its_contents(root, win_attrs):
    build(root, {"hid_dir/inside.txt": 1, "normal.txt": 1})
    r = scan(root)

    assert names(r, "folder") == ["drive"]
    assert names(r, "file") == ["normal.txt"]
    assert r["skipped"] == 1


def test_attributes_come_from_the_listing_stat(root, monkeypatch):
    build(root, {"secret.txt": 3, "sys.txt": 3, "normal.txt": 3})
    real_lstat = scanner._lstat
    flags = {"secret.txt": stat.FILE_ATTRIBUTE_HIDDEN, "sys.txt": stat.FILE_ATTRIBUTE_SYSTEM}

    def lstat(entry):
        st = real_lstat(entry)
        return types.SimpleNamespace(
            st_mode=st.st_mode, st_size=st.st_size, st_mtime=st.st_mtime,
            st_file_attributes=flags.get(entry.name, 0),
        )

    monkeypatch.setattr(scanner, "_lstat", lstat)

    assert names(scan(root), "file") == ["normal.txt"]
    assert names(scan(root, incl_hidden=True, incl_system=True), "file") == [
        "normal.txt", "secret.txt", "sys.txt",
    ]


def test_missing_attributes_mean_no_flags():
    assert scanner._file_attributes(None, types.SimpleNamespace()) == 0


def test_files_are_never_stat_ed_individually(root, monkeypatch):
    build(root, {"a.txt": 1, "sub/b.txt": 1})

    def forbidden(*args, **kwargs):
        raise AssertionError("per-file stat call")

    monkeypatch.setattr(os, "lstat", forbidden)
    monkeypatch.setattr(pathlib.Path, "stat", forbidden)
    r = scan(root)

    assert names(r, "file") == ["a.txt", "b.txt"]


# ── Progress and cancellation ────────────────────────────────────

def test_progress_is_reported_every_100_files(root):
    build(root, {f"f{i:03}.txt": 1 for i in range(250)})
    seen = []

    scan(root, progress_cb=seen.append)

    assert seen == [100, 200]


def test_scan_cancelled_before_start_raises(root):
    build(root, {"a.txt": 1})
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(scanner.ScanCancelled):
        scan(root, cancel_event=cancel)


def test_scan_can_be_cancelled_from_the_progress_callback(root):
    build(root, {f"f{i:03}.txt": 1 for i in range(250)})
    cancel = threading.Event()

    with pytest.raises(scanner.ScanCancelled):
        scan(root, progress_cb=lambda n: cancel.set(), cancel_event=cancel)


def test_unset_cancel_event_does_not_interfere(root):
    build(root, {"a.txt": 1})

    assert scan(root, cancel_event=threading.Event())["file_count"] == 1


# ── Errors are reported, not swallowed ───────────────────────────

@pytest.mark.parametrize("target", ["missing", "a_file.txt"])
def test_unreadable_root_raises(root, target):
    build(root, {"a_file.txt": 1})

    with pytest.raises(OSError):
        scan(root / target)


def test_unreadable_file_is_reported_not_swallowed(root, unreadable_file):
    build(root, {"ok.txt": 4, "denied.txt": 4})
    unreadable_file("denied.txt")
    r = scan(root)

    assert r["unreadable_count"] == 1
    entry = r["unreadable"][0]
    assert entry["kind"] == "file"
    assert entry["path"].endswith("denied.txt")
    assert entry["reason"] == "Permission denied"
    assert names(r, "file") == ["ok.txt"]
    assert r["file_count"] == 1
    assert r["skipped"] == 0


def test_unreadable_details_are_capped_but_count_is_true(root, monkeypatch, unreadable_file):
    monkeypatch.setattr(scanner, "MAX_UNREADABLE_DETAILS", 2)
    for n in range(3):
        build(root, {f"denied{n}.txt": 1})
        unreadable_file(f"denied{n}.txt")
    r = scan(root)

    assert r["unreadable_count"] == 3
    assert len(r["unreadable"]) == 2


@pytest.fixture
def locked_folder(monkeypatch):
    real_scandir = os.scandir

    def scandir(path="."):
        if os.path.basename(os.fspath(path)) == "locked":
            raise PermissionError(13, "Permission denied", os.fspath(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)


def test_unreadable_folder_is_reported(root, locked_folder):
    build(root, {"locked/inner.txt": 1, "ok.txt": 1})
    r = scan(root)

    assert r["unreadable_count"] == 1
    entry = r["unreadable"][0]
    assert entry["kind"] == "folder"
    assert entry["path"].endswith("locked")
    assert entry["reason"] == "Permission denied"
    assert "inner.txt" not in names(r, "file")
    assert names(r, "file") == ["ok.txt"]


def test_unreadable_folder_past_the_depth_limit_is_not_reported(root, locked_folder):
    build(root, {"a/locked/inner.txt": 1})
    r = scan(root, max_depth=1)

    assert r["unreadable_count"] == 0


def test_unreadable_folder_date_is_reported_and_zeroed(root, monkeypatch):
    build(root, {"weird/x.txt": 1})
    real_lstat = scanner._lstat

    def lstat(entry):
        if entry.name == "weird":
            raise OSError(5, "Input/output error")
        return real_lstat(entry)

    monkeypatch.setattr(scanner, "_lstat", lstat)
    r = scan(root)

    assert item(r, "weird")["mtime"] == 0
    assert r["unreadable"] == [
        {"path": str(root / "weird"), "kind": "date", "reason": "Input/output error"},
    ]
    assert names(r, "file") == ["x.txt"]


# ── Symlinks and junctions ───────────────────────────────────────

def test_file_link_is_counted_not_listed(root):
    build(root, {"real.txt": 5})
    link(root, "alias.txt", root / "real.txt")
    r = scan(root)

    assert names(r, "file") == ["real.txt"]
    assert r["file_count"] == 1
    assert item(r, "drive")["size"] == 5
    assert r["links_skipped"] == 1
    assert r["links"] == [
        {"path": str(root / "alias.txt"), "kind": "file", "target": str(root / "real.txt")},
    ]


def test_folder_link_is_not_followed_or_listed(root):
    build(root, {"real/inner.txt": 3})
    link(root, "alias", root / "real", directory=True)
    r = scan(root)

    assert names(r, "folder") == ["drive", "real"]
    assert names(r, "file") == ["inner.txt"]
    assert r["folder_count"] == 2
    assert item(r, "drive")["size"] == 3
    assert r["links_skipped"] == 1
    assert r["links"][0]["kind"] == "folder"
    assert r["links"][0]["target"] == str(root / "real")


def test_link_back_to_an_ancestor_cannot_loop_the_scan(root):
    build(root, {"a/f.txt": 1})
    link(root, "a/up", root, directory=True)
    r = scan(root)

    assert names(r, "file") == ["f.txt"]
    assert r["links_skipped"] == 1


def test_broken_link_is_a_link_not_an_unreadable_file(root):
    build(root, {"ok.txt": 1})
    link(root, "broken.lnk", root / "missing-target")
    r = scan(root)

    assert r["links_skipped"] == 1
    assert r["unreadable_count"] == 0
    assert names(r, "file") == ["ok.txt"]


def test_link_details_are_capped_but_count_is_true(root, monkeypatch):
    monkeypatch.setattr(scanner, "MAX_LINK_DETAILS", 2)
    for n in range(3):
        link(root, f"l{n}", root / "missing-target")
    r = scan(root)

    assert r["links_skipped"] == 3
    assert len(r["links"]) == 2


def test_hidden_link_counts_as_hidden_unless_hidden_entries_are_included(root):
    link(root, ".hidden-link", root / "missing-target")

    r = scan(root)
    assert (r["skipped"], r["links_skipped"]) == (1, 0)

    r = scan(root, incl_hidden=True)
    assert (r["skipped"], r["links_skipped"]) == (0, 1)


def test_scan_root_may_itself_be_a_link(tmp_path):
    real = tmp_path / "real"
    build(real, {"f.txt": 2})
    alias = tmp_path / "alias"
    link(tmp_path, "alias", real, directory=True)
    r = scan(alias)

    assert names(r, "file") == ["f.txt"]
    assert r["links_skipped"] == 0


def test_is_link_recognises_symlinks_and_junctions_but_not_other_reparse_points():
    symlink  = types.SimpleNamespace(st_mode=stat.S_IFLNK | 0o777)
    junction = types.SimpleNamespace(
        st_mode=stat.S_IFDIR | 0o777, st_reparse_tag=scanner.IO_REPARSE_TAG_MOUNT_POINT
    )
    cloud    = types.SimpleNamespace(st_mode=stat.S_IFDIR | 0o777, st_reparse_tag=0x9000001A)
    plain    = types.SimpleNamespace(st_mode=stat.S_IFREG | 0o644)

    assert scanner._is_link(symlink)
    assert scanner._is_link(junction)
    assert not scanner._is_link(cloud)
    assert not scanner._is_link(plain)


@pytest.mark.parametrize("raw, expected", [
    ("\\\\?\\C:\\drive\\real", "C:\\drive\\real"),
    ("\\\\?\\UNC\\server\\share\\real", "\\\\server\\share\\real"),
    ("C:\\drive\\real", "C:\\drive\\real"),
    ("..\\real", "..\\real"),
])
def test_link_targets_lose_the_windows_extended_path_prefix(monkeypatch, raw, expected):
    monkeypatch.setattr(os, "readlink", lambda path: raw)

    assert scanner._link_target("any") == expected


def test_link_target_is_empty_when_it_cannot_be_read(monkeypatch):
    def unreadable(path):
        raise OSError("not a link")

    monkeypatch.setattr(os, "readlink", unreadable)

    assert scanner._link_target("any") == ""


def test_junction_is_skipped_like_a_symlink(root, monkeypatch):
    build(root, {"real/inner.txt": 1, "junction/inner.txt": 1})
    real_lstat = scanner._lstat

    def lstat(entry):
        st = real_lstat(entry)
        if entry.name == "junction":
            return types.SimpleNamespace(
                st_mode=st.st_mode, st_reparse_tag=scanner.IO_REPARSE_TAG_MOUNT_POINT
            )
        return st

    monkeypatch.setattr(scanner, "_lstat", lstat)
    r = scan(root)

    assert names(r, "folder") == ["drive", "real"]
    assert names(r, "file") == ["inner.txt"]
    assert r["links"] == [{"path": str(root / "junction"), "kind": "folder", "target": ""}]


# ── Volume identity ──────────────────────────────────────────────

def test_volume_id_prefers_the_serial_number():
    info = {"label": "USB", "serial": 0xABCD}

    assert scanner.make_volume_id(info, "/anywhere") == "serial:0000ABCD"


def test_volume_id_falls_back_to_the_normalised_path(tmp_path):
    info = {"label": "", "serial": None}

    assert scanner.make_volume_id(info, str(tmp_path)) == (
        "path:" + os.path.normcase(os.path.abspath(tmp_path))
    )


def test_scan_reports_volume_details(root, monkeypatch):
    monkeypatch.setattr(scanner, "get_volume_info", lambda path: {"label": "MY USB", "serial": None})
    r = scan(root)

    assert r["volume_label"] == "MY USB"
    assert r["volume_id"] == scanner.make_volume_id({"serial": None}, str(root))
    assert r["volume_root"] == str(root.anchor)
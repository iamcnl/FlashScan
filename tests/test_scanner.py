import os
import pathlib
import threading

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


def broken_link(root, name):
    try:
        os.symlink(root / "missing-target", root / name)
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


# ── Result shape ─────────────────────────────────────────────────

def test_result_has_all_keys_the_ui_expects(root):
    assert set(scan(root)) == {
        "tree", "file_count", "folder_count", "skipped", "unreadable_count",
        "unreadable", "beyond_depth", "volume_label", "volume_id", "volume_root",
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
    monkeypatch.setattr(scanner, "_win_attrs", lambda p: attrs.get(os.path.basename(p), 0))


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


def test_unreadable_file_is_reported_not_swallowed(root):
    build(root, {"ok.txt": 4})
    broken_link(root, "broken.lnk")
    r = scan(root)

    assert r["unreadable_count"] == 1
    entry = r["unreadable"][0]
    assert entry["kind"] == "file"
    assert entry["path"].endswith("broken.lnk")
    assert entry["reason"]
    assert names(r, "file") == ["ok.txt"]
    assert r["file_count"] == 1
    assert r["skipped"] == 0


def test_unreadable_details_are_capped_but_count_is_true(root, monkeypatch):
    monkeypatch.setattr(scanner, "MAX_UNREADABLE_DETAILS", 2)
    for n in range(3):
        broken_link(root, f"broken{n}.lnk")
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
    real_stat = pathlib.Path.stat

    def stat(self, *args, **kwargs):
        if self.name == "weird":
            raise OSError(5, "Input/output error")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "stat", stat)
    r = scan(root)

    assert item(r, "weird")["mtime"] == 0
    assert r["unreadable"] == [
        {"path": str(root / "weird"), "kind": "date", "reason": "Input/output error"},
    ]
    assert names(r, "file") == ["x.txt"]


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
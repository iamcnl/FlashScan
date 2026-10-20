import json
import logging
import os
import re
import threading
import time
import types
from pathlib import Path

import pytest

import exporter
import scanner
import settings
from ui import api


class FakeWindow:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.maximized = 0
        self.shown = 0
        self.dialog_result = None
        self.dialog_args = []
        self._cond = threading.Condition()

    def evaluate_js(self, code):
        with self._cond:
            self.calls.append(code)
            self._cond.notify_all()
        if self.fail:
            raise RuntimeError("window closed")

    def take(self, prefix, timeout=5.0):
        with self._cond:
            found = self._cond.wait_for(
                lambda: any(c.startswith(prefix) for c in self.calls), timeout
            )
            assert found, f"timed out waiting for {prefix}; last calls: {self.calls[-3:]}"
            for index, call in enumerate(self.calls):
                if call.startswith(prefix):
                    return self.calls.pop(index)

    def take_json(self, prefix, timeout=5.0):
        return json.loads(self.take(prefix, timeout)[len(prefix) + 1:-1])

    def starting(self, prefix):
        with self._cond:
            return [c for c in self.calls if c.startswith(prefix)]

    def maximize(self):
        self.maximized += 1

    def show(self):
        self.shown += 1

    def create_file_dialog(self, dialog):
        self.dialog_args.append(dialog)
        return self.dialog_result


def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail("timed out waiting for a condition")


def make_drive(root, files):
    for rel, size in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
    return root


def symlink_or_skip(target, link, directory=False):
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    store = tmp_path / "store"
    monkeypatch.setattr(settings, "SETTINGS_FILE", store / "settings.json")
    monkeypatch.setattr(settings, "PROFILES_DIR", store / "profiles")
    monkeypatch.setattr(scanner, "get_volume_info", lambda path: {"label": "", "serial": None})
    monkeypatch.setattr(api, "_SYSTEM", "Linux")


@pytest.fixture
def window():
    return FakeWindow()


@pytest.fixture
def app(window):
    return api.API([window])


@pytest.fixture
def drive(tmp_path):
    return make_drive(
        tmp_path / "drive",
        {"a.txt": 3, "b.log": 4, "docs/n.md": 6, "photos/p.png": 5},
    )


@pytest.fixture
def out(tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


@pytest.fixture
def popen(monkeypatch):
    calls = []
    monkeypatch.setattr(api.subprocess, "Popen", lambda args, *a, **k: calls.append(list(args)))
    return calls


@pytest.fixture
def gate(monkeypatch):
    started, release = threading.Event(), threading.Event()
    real = scanner.scan_path

    def scan_path(path, depth, incl_hidden, incl_system, progress_cb, cancel):
        started.set()
        assert release.wait(5)
        return real(path, depth, incl_hidden, incl_system, progress_cb, cancel)

    monkeypatch.setattr(scanner, "scan_path", scan_path)
    yield started, release
    release.set()


def scan_params(path, **extra):
    return {"path": str(path), "depth": 5, **extra}


def run_scan(app, window, path, **extra):
    assert app.scan(scan_params(path, **extra)) == {"async": True}
    return window.take_json("onScanDone")


def run_export(app, window, scan_id, out, formats=("MD",), selection=None, **extra):
    params = {
        "scan_id": scan_id,
        "formats": list(formats),
        "output_dir": str(out),
        "selection": {"all_except": []} if selection is None else selection,
        **extra,
    }
    assert app.export(params) == {"async": True}
    return window.take_json("onExportDone")


def exported_names(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    files = sorted(f["name"] for folder in data["folders"] for f in folder["files"])
    folders = sorted(folder["name"] for folder in data["folders"])
    return files, folders


# ── File names ───────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("report", "report"),
    ("a/b\\c", "abc"),
    ("../../etc/passwd", "etcpasswd"),
    ('na:me*?"<>|', "name"),
    ("  spaced  ", "spaced"),
    (".hidden.", "hidden"),
    ("a\x00b\x1fc", "abc"),
    ("x" * 300, "x" * 150),
    ("...", "fallback"),
    (" . ", "fallback"),
    ("", "fallback"),
])
def test_safe_stem_cannot_escape_the_output_folder(raw, expected):
    assert api._safe_stem(raw, "fallback") == expected


def test_reserve_unique_numbers_taken_names_and_never_overwrites(tmp_path):
    (tmp_path / "list.md").write_text("mine")

    second = api._reserve_unique(tmp_path / "list.md")
    third = api._reserve_unique(tmp_path / "list.md")

    assert second.name == "list (2).md"
    assert third.name == "list (3).md"
    assert (tmp_path / "list.md").read_text() == "mine"
    assert second.read_text() == third.read_text() == ""


def test_reserve_unique_gives_up_instead_of_looping_forever(tmp_path, monkeypatch):
    def always_taken(*args, **kwargs):
        raise FileExistsError

    monkeypatch.setattr(api, "open", always_taken, raising=False)

    with pytest.raises(OSError, match="No free file name"):
        api._reserve_unique(tmp_path / "list.md")


# ── Path allowlist ───────────────────────────────────────────────

def test_nothing_is_trusted_by_default(app, tmp_path):
    assert not app._is_trusted(str(tmp_path))


def test_trusted_root_covers_itself_and_everything_below(app, tmp_path):
    root = tmp_path / "drive"
    app._trust_root(str(root))

    assert app._is_trusted(str(root))
    assert app._is_trusted(str(root / "a" / "b.txt"))


def test_trusted_root_does_not_cover_siblings_parents_or_traversal(app, tmp_path):
    root = tmp_path / "drive"
    app._trust_root(str(root))

    assert not app._is_trusted(str(tmp_path / "drive-evil"))
    assert not app._is_trusted(str(tmp_path))
    assert not app._is_trusted(str(root / ".." / "other"))


def test_trusted_file_does_not_cover_its_siblings(app, tmp_path):
    app._trust_file(str(tmp_path / "out" / "list.md"))

    assert app._is_trusted(str(tmp_path / "out" / "list.md"))
    assert not app._is_trusted(str(tmp_path / "out" / "other.md"))


def test_link_inside_a_trusted_root_cannot_lead_outside(app, tmp_path):
    root = tmp_path / "drive"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    symlink_or_skip(secret, root / "alias.txt")
    app._trust_root(str(root))

    assert not app._is_trusted(str(root / "alias.txt"))


def test_paths_on_another_drive_are_not_trusted(app, tmp_path, monkeypatch):
    app._trust_root(str(tmp_path))

    def other_drive(paths):
        raise ValueError("Paths don't have the same drive")

    monkeypatch.setattr(api.os.path, "commonpath", other_drive)

    assert not app._is_trusted(str(tmp_path / "x"))


def test_scanning_trusts_the_scanned_folder_only(app, window, drive, tmp_path, popen):
    run_scan(app, window, drive)
    outside = tmp_path / "outside.txt"
    outside.write_text("x")

    assert app.open_path(str(drive / "a.txt")) == {"ok": True}
    assert app.open_path(str(outside)) == api._DENIED


# ── Open / reveal / properties ───────────────────────────────────

@pytest.mark.parametrize("operation", ["open_path", "reveal_in_explorer", "open_properties"])
def test_untrusted_paths_are_refused_and_nothing_is_launched(app, tmp_path, popen, operation):
    target = tmp_path / "file.txt"
    target.write_text("x")

    assert getattr(app, operation)(str(target)) == api._DENIED
    assert popen == []


@pytest.mark.parametrize("operation", ["open_path", "reveal_in_explorer", "open_properties"])
def test_trusted_but_missing_paths_report_it(app, tmp_path, popen, operation):
    app._trust_root(str(tmp_path))

    assert getattr(app, operation)(str(tmp_path / "gone.txt")) == {"error": "Path does not exist."}
    assert popen == []


@pytest.mark.parametrize("system, expected", [
    ("Linux", lambda p: ["xdg-open", p]),
    ("Darwin", lambda p: ["open", p]),
])
def test_open_path_uses_the_platform_opener(app, tmp_path, popen, monkeypatch, system, expected):
    monkeypatch.setattr(api, "_SYSTEM", system)
    target = tmp_path / "file.txt"
    target.write_text("x")
    app._trust_root(str(tmp_path))

    assert app.open_path(str(target)) == {"ok": True}
    assert popen == [expected(str(target))]


def test_open_path_uses_startfile_on_windows(app, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(api, "_SYSTEM", "Windows")
    monkeypatch.setattr(api.os, "startfile", opened.append, raising=False)
    target = tmp_path / "file.txt"
    target.write_text("x")
    app._trust_root(str(tmp_path))

    assert app.open_path(str(target)) == {"ok": True}
    assert opened == [str(target)]


def test_open_path_returns_launcher_failures_as_errors(app, tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise FileNotFoundError("xdg-open not found")

    monkeypatch.setattr(api.subprocess, "Popen", broken)
    target = tmp_path / "file.txt"
    target.write_text("x")
    app._trust_root(str(tmp_path))

    assert app.open_path(str(target)) == {"error": "xdg-open not found"}


@pytest.mark.parametrize("system, as_folder, expected", [
    ("Linux", False, lambda f, d: ["xdg-open", str(f.parent)]),
    ("Linux", True, lambda f, d: ["xdg-open", str(d)]),
    ("Darwin", False, lambda f, d: ["open", "-R", str(f)]),
    ("Windows", False, lambda f, d: ["explorer", "/select,", str(f)]),
])
def test_reveal_selects_in_the_platform_file_manager(
    app, tmp_path, popen, monkeypatch, system, as_folder, expected
):
    monkeypatch.setattr(api, "_SYSTEM", system)
    folder = tmp_path / "docs"
    folder.mkdir()
    file = folder / "file.txt"
    file.write_text("x")
    app._trust_root(str(tmp_path))

    assert app.reveal_in_explorer(str(folder if as_folder else file)) == {"ok": True}
    assert popen == [expected(file, folder)]


def test_properties_return_metadata_on_linux(app, tmp_path):
    target = tmp_path / "file.txt"
    target.write_bytes(b"12345")
    app._trust_root(str(tmp_path))

    meta = app.open_properties(str(target))

    assert meta == {
        "ok": True, "meta": True, "name": "file.txt", "path": str(target),
        "size": 5, "mtime": int(target.stat().st_mtime), "is_dir": False,
    }


def test_properties_on_macos_escape_the_path_for_applescript(app, tmp_path, popen, monkeypatch):
    monkeypatch.setattr(api, "_SYSTEM", "Darwin")
    target = tmp_path / 'we"ird\\name.txt'
    try:
        target.write_text("x")
    except OSError:
        pytest.skip("file system does not allow quotes or backslashes in names")
    app._trust_root(str(tmp_path))

    assert app.open_properties(str(target)) == {"ok": True}
    script = popen[0][2]
    assert 'we\\"ird\\\\name.txt' in script
    assert script.endswith('" as alias)')


def test_open_log_folder_reveals_the_log_even_outside_scanned_folders(
    app, tmp_path, popen, monkeypatch
):
    log_file = tmp_path / "logs" / "flashscan.log"
    log_file.parent.mkdir()
    log_file.write_text("x")
    monkeypatch.setattr(api.logger, "log_file", lambda: log_file)

    assert app.open_log_folder() == {"ok": True}
    assert popen == [["xdg-open", str(log_file.parent)]]


def test_open_log_folder_reports_a_missing_log(app, monkeypatch):
    monkeypatch.setattr(api.logger, "log_file", lambda: None)

    assert app.open_log_folder() == {"error": "No log file is available."}


# ── Scanning ─────────────────────────────────────────────────────

@pytest.mark.parametrize("depth", [0, 51, -1])
def test_scan_rejects_depth_outside_the_allowed_range(app, window, drive, depth):
    reply = app.scan(scan_params(drive, depth=depth))

    assert reply == {"errors": ["Invalid scan depth (allowed: 1–50)."]}
    assert window.calls == []


def test_scan_rejects_a_missing_path(app, window, tmp_path):
    assert app.scan(scan_params(tmp_path / "nope")) == {"errors": ["Path does not exist."]}


def test_scan_reports_every_validation_error_at_once(app, tmp_path):
    reply = app.scan(scan_params(tmp_path / "nope", depth=0))

    assert len(reply["errors"]) == 2


def test_scan_runs_in_the_background_and_reports_the_result(app, window, drive):
    result = run_scan(app, window, drive)

    assert result["scan_id"] == 1
    assert result["depth"] == 5
    assert result["file_count"] == 4
    assert app._scan_data["id"] == 1
    assert app._scan_data["path"] == str(drive)
    assert len(app._scan_data["tree"]) == len(result["tree"]) == 7
    assert settings.load()["lastPath"] == str(drive)


def test_scan_forwards_the_options(app, window, drive, monkeypatch):
    seen = []
    real = scanner.scan_path

    def spy(path, depth, incl_hidden, incl_system, progress_cb, cancel):
        seen.append((depth, incl_hidden, incl_system))
        return real(path, depth, incl_hidden, incl_system, progress_cb, cancel)

    monkeypatch.setattr(scanner, "scan_path", spy)
    run_scan(app, window, drive, depth=3, incl_hidden=True, incl_system=True)

    assert seen == [(3, True, True)]


def test_scan_ids_increase_with_every_scan(app, window, drive):
    assert run_scan(app, window, drive)["scan_id"] == 1
    assert run_scan(app, window, drive)["scan_id"] == 2


def test_second_scan_while_one_runs_is_busy_and_does_not_disturb_it(app, window, drive, gate):
    started, release = gate
    assert app.scan(scan_params(drive)) == {"async": True}
    assert started.wait(5)

    assert app.scan(scan_params(drive)) == {"busy": True}

    release.set()
    assert window.take_json("onScanDone")["scan_id"] == 1
    assert app.scan(scan_params(drive)) == {"async": True}
    assert window.take_json("onScanDone")["scan_id"] == 2


def test_a_scan_can_be_started_from_the_done_callback(app, window, drive):
    replies = []

    class Chained(FakeWindow):
        chained = False

        def evaluate_js(self, code):
            super().evaluate_js(code)
            if code.startswith("onScanDone") and not self.chained:
                self.chained = True
                replies.append(app.scan(scan_params(drive)))

    chained = Chained()
    app._win[0] = chained

    assert app.scan(scan_params(drive)) == {"async": True}
    chained.take_json("onScanDone")
    chained.take_json("onScanDone")

    wait_until(lambda: replies)
    assert replies == [{"async": True}]


def test_cancel_scan_without_a_running_scan_does_nothing(app):
    assert app.cancel_scan() == {"ok": False}


def test_cancelling_a_scan_notifies_the_ui_and_frees_the_slot(app, window, drive, monkeypatch):
    started = threading.Event()

    def cancellable(path, depth, incl_hidden, incl_system, progress_cb, cancel):
        started.set()
        assert cancel.wait(5)
        raise scanner.ScanCancelled

    monkeypatch.setattr(scanner, "scan_path", cancellable)
    assert app.scan(scan_params(drive)) == {"async": True}
    assert started.wait(5)

    assert app.cancel_scan() == {"ok": True}
    window.take("onScanCancelled")

    assert app.cancel_scan() == {"ok": False}
    assert app._scan_data is None
    monkeypatch.undo()
    assert run_scan(app, window, drive)["scan_id"] == 2


def test_cancelling_keeps_the_previous_scan_for_export(app, window, drive, out, monkeypatch):
    first = run_scan(app, window, drive)
    started = threading.Event()

    def cancellable(path, depth, incl_hidden, incl_system, progress_cb, cancel):
        started.set()
        assert cancel.wait(5)
        raise scanner.ScanCancelled

    monkeypatch.setattr(scanner, "scan_path", cancellable)
    app.scan(scan_params(drive))
    assert started.wait(5)
    app.cancel_scan()
    window.take("onScanCancelled")

    assert app._scan_data["id"] == first["scan_id"]
    assert run_export(app, window, first["scan_id"], out)["success"] is True


def test_a_scan_that_finishes_after_cancel_was_requested_is_discarded(
    app, window, drive, monkeypatch
):
    started = threading.Event()
    real = scanner.scan_path

    def finishes_anyway(path, depth, incl_hidden, incl_system, progress_cb, cancel):
        started.set()
        assert cancel.wait(5)
        return real(path, depth, incl_hidden, incl_system, progress_cb, None)

    monkeypatch.setattr(scanner, "scan_path", finishes_anyway)
    app.scan(scan_params(drive))
    assert started.wait(5)
    app.cancel_scan()

    window.take("onScanCancelled")
    assert app._scan_data is None
    assert settings.load()["lastPath"] == ""


def test_scan_progress_is_forwarded_until_cancel(app, window, drive, monkeypatch):
    def noisy(path, depth, incl_hidden, incl_system, progress_cb, cancel):
        progress_cb(1)
        cancel.set()
        progress_cb(2)
        raise scanner.ScanCancelled

    monkeypatch.setattr(scanner, "scan_path", noisy)
    app.scan(scan_params(drive))
    window.take("onScanCancelled")

    assert window.starting("onScanProgress") == ["onScanProgress(1)"]


def test_a_failing_scan_reports_the_error_and_frees_the_slot(app, window, drive, monkeypatch):
    first = run_scan(app, window, drive)
    real = scanner.scan_path

    def broken(*args):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(scanner, "scan_path", broken)
    app.scan(scan_params(drive))
    assert window.take_json("onScanDone") == {"error": "disk on fire"}

    monkeypatch.setattr(scanner, "scan_path", real)
    assert app._scan_data["id"] == first["scan_id"]
    assert run_scan(app, window, drive)["scan_id"] == 3


def test_scan_without_a_window_still_completes(drive):
    app = api.API([])

    assert app.scan(scan_params(drive)) == {"async": True}

    wait_until(lambda: app._scan_data is not None and app._scan_cancel is None)
    assert app._scan_data["id"] == 1


def test_scan_survives_a_window_that_rejects_javascript(app, window, drive):
    window.fail = True

    assert app.scan(scan_params(drive)) == {"async": True}
    wait_until(lambda: app._scan_data is not None and app._scan_cancel is None)

    window.take("onScanDone")
    window.fail = False
    assert run_scan(app, window, drive)["scan_id"] == 2


# ── Export validation ────────────────────────────────────────────

def seed_scan(app, tmp_path, scan_id=1):
    app._scan_data = {"id": scan_id, "tree": [], "path": str(tmp_path), "volume_label": ""}


def test_export_needs_an_existing_output_folder(app, tmp_path):
    seed_scan(app, tmp_path)
    reply = app.export({"scan_id": 1, "output_dir": str(tmp_path / "nope"), "selection": {}})

    assert reply == {"success": False, "error": "Output folder does not exist."}


def test_export_needs_a_writable_output_folder(app, tmp_path, out, monkeypatch):
    seed_scan(app, tmp_path)
    monkeypatch.setattr(api.os, "access", lambda path, mode: False)
    reply = app.export({"scan_id": 1, "output_dir": str(out), "selection": {}})

    assert reply["success"] is False
    assert "permission denied" in reply["error"]


@pytest.mark.parametrize("scan_id", [None, 0, 2, "1"])
def test_export_refuses_a_scan_id_that_is_not_the_current_one(app, tmp_path, out, scan_id):
    seed_scan(app, tmp_path)
    reply = app.export({"scan_id": scan_id, "output_dir": str(out), "selection": {}})

    assert reply == {"success": False, "error": "Scan data is out of date. Run the scan again."}


def test_export_refuses_when_nothing_was_scanned(app, out):
    reply = app.export({"scan_id": 1, "output_dir": str(out), "selection": {}})

    assert reply["error"] == "Scan data is out of date. Run the scan again."


def test_export_refuses_the_scan_id_of_a_replaced_scan(app, window, drive, out):
    first = run_scan(app, window, drive)
    run_scan(app, window, drive)
    reply = app.export({"scan_id": first["scan_id"], "output_dir": str(out), "selection": {}})

    assert reply["error"] == "Scan data is out of date. Run the scan again."


@pytest.mark.parametrize("selection", [None, [], "all", 5])
def test_export_needs_a_selection_object(app, tmp_path, out, selection):
    seed_scan(app, tmp_path)
    reply = app.export({"scan_id": 1, "output_dir": str(out), "selection": selection})

    assert reply == {"success": False, "error": "Selection is missing."}


def test_second_export_while_one_runs_is_busy(app, tmp_path, out):
    seed_scan(app, tmp_path)
    app._exporting = True
    reply = app.export({"scan_id": 1, "output_dir": str(out), "selection": {}})

    assert reply == {"busy": True}
    assert app._exporting is True


# ── Export results ───────────────────────────────────────────────

def test_export_writes_every_format_with_a_dated_name(app, window, drive, out):
    scan = run_scan(app, window, drive)
    result = run_export(app, window, scan["scan_id"], out, ["MD", "TXT", "JSON", "HTML"])

    assert result["success"] is True
    assert result["errors"] == []
    names = sorted(Path(p).name for p in result["saved"])
    assert len(names) == 4
    pattern = r"LIST_drive_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}\.(md|txt|json|html)"
    assert all(re.fullmatch(pattern, n) for n in names)
    assert sorted(os.listdir(out)) == names


def test_export_reports_progress_across_formats(app, window, drive, out):
    scan = run_scan(app, window, drive)
    run_export(app, window, scan["scan_id"], out, ["MD", "JSON"])

    items = len(scan["tree"])
    calls = window.starting("onExportProgress")
    assert calls[0] == f'onExportProgress(0, {items * 2}, "MD")'
    assert calls[-1] == f'onExportProgress({items * 2}, {items * 2}, "JSON")'


def test_export_remembers_the_output_folder_and_formats(app, window, drive, out):
    scan = run_scan(app, window, drive)
    run_export(app, window, scan["scan_id"], out, ["TXT", "MD"])

    saved = settings.load()
    assert saved["lastOutput"] == str(out)
    assert saved["lastFormats"] == ["TXT", "MD"]


def test_export_can_be_repeated_once_the_first_one_is_done(app, window, drive, out):
    scan = run_scan(app, window, drive)
    run_export(app, window, scan["scan_id"], out)

    assert app._exporting is False
    assert run_export(app, window, scan["scan_id"], out)["success"] is True


def test_export_uses_the_scan_taken_when_it_was_requested(app, window, drive, out):
    scan = run_scan(app, window, drive)
    (drive / "late.txt").write_text("added after the scan")
    result = run_export(app, window, scan["scan_id"], out, ["JSON"])

    files, _ = exported_names(result["saved"][0])
    assert "late.txt" not in files


@pytest.mark.parametrize("selection, files", [
    ({"all_except": []}, ["a.txt", "b.log", "n.md", "p.png"]),
    ({}, ["a.txt", "b.log", "n.md", "p.png"]),
    ({"all_except": ["B"]}, ["a.txt", "n.md", "p.png"]),
    ({"only": ["A", "N"]}, ["a.txt", "n.md"]),
    ({"only": []}, []),
])
def test_export_follows_the_file_selection(app, window, drive, out, selection, files):
    scan = run_scan(app, window, drive)
    paths = {
        "A": str(drive / "a.txt"), "B": str(drive / "b.log"), "N": str(drive / "docs" / "n.md"),
    }
    chosen = {
        key: [paths[p] for p in value] if isinstance(value, list) else value
        for key, value in selection.items()
    }
    result = run_export(app, window, scan["scan_id"], out, ["JSON"], chosen)

    assert exported_names(result["saved"][0])[0] == files


def test_export_applies_folder_states_extension_filter_and_notes(app, window, drive, out):
    scan = run_scan(app, window, drive)
    selection = {
        "all_except": [],
        "folder_states": {str(drive / "photos"): "skip", str(drive / "docs"): "name"},
        "folder_notes": {str(drive): "backup of 2024"},
        "active_exts": ["txt", "md"],
    }
    result = run_export(app, window, scan["scan_id"], out, ["JSON"], selection)

    files, folders = exported_names(result["saved"][0])
    assert files == ["a.txt"]
    assert folders == ["docs", "drive"]
    data = json.loads(Path(result["saved"][0]).read_text(encoding="utf-8"))
    assert {f["name"]: f.get("note") for f in data["folders"]}["drive"] == "backup of 2024"


def test_export_forwards_the_options_to_the_writer(app, window, drive, out, monkeypatch):
    seen = {}

    def writer(handle, items, meta, **kwargs):
        seen.update(kwargs, meta=meta)
        handle.write("x")

    monkeypatch.setitem(exporter.WRITERS, "MD", writer)
    scan = run_scan(app, window, drive)
    run_export(
        app, window, scan["scan_id"], out, include_size=False, include_date=False,
        date_pattern="%Y-%m-%d", selection={"folder_notes": {"n": "note"}},
    )

    assert seen["include_size"] is False
    assert seen["include_date"] is False
    assert seen["date_pattern"] == "%Y-%m-%d"
    assert seen["folder_notes"] == {"n": "note"}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", seen["meta"]["timestamp"])


def test_export_falls_back_to_the_default_date_layout_for_a_bad_pattern(
    app, window, drive, out, monkeypatch
):
    seen = {}
    monkeypatch.setitem(
        exporter.WRITERS, "MD", lambda handle, items, meta, **kw: seen.update(kw) or handle.write("x")
    )
    scan = run_scan(app, window, drive)
    run_export(app, window, scan["scan_id"], out, date_pattern="bogus")

    assert seen["date_pattern"] == exporter.DEFAULT_DATE_PATTERN


def test_custom_file_names_cannot_leave_the_output_folder(app, window, drive, out):
    scan = run_scan(app, window, drive)
    result = run_export(
        app, window, scan["scan_id"], out, custom_names={"MD": "../../evil/na:me"},
    )

    saved = Path(result["saved"][0])
    assert saved.parent == out
    assert saved.name == "evilname.md"


def test_unusable_custom_names_fall_back_to_a_dated_name(app, window, drive, out):
    scan = run_scan(app, window, drive)
    result = run_export(app, window, scan["scan_id"], out, custom_names={"MD": "..."})

    assert re.fullmatch(r"LIST_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}\.md", Path(result["saved"][0]).name)


def test_export_never_overwrites_an_existing_file(app, window, drive, out):
    (out / "inventory.md").write_text("mine")
    scan = run_scan(app, window, drive)
    names = {"MD": "inventory"}
    first = run_export(app, window, scan["scan_id"], out, custom_names=names)
    second = run_export(app, window, scan["scan_id"], out, custom_names=names)

    assert Path(first["saved"][0]).name == "inventory (2).md"
    assert Path(second["saved"][0]).name == "inventory (3).md"
    assert (out / "inventory.md").read_text() == "mine"


def test_export_leaves_no_temporary_files_behind(app, window, drive, out):
    scan = run_scan(app, window, drive)
    run_export(app, window, scan["scan_id"], out, ["MD", "TXT", "JSON", "HTML"])

    assert not [n for n in os.listdir(out) if n.endswith(".part")]


def test_a_failing_writer_removes_its_files_and_does_not_stop_the_others(
    app, window, drive, out, monkeypatch
):
    def failing(handle, items, meta, **kwargs):
        handle.write("partial")
        raise RuntimeError("boom")

    monkeypatch.setitem(exporter.WRITERS, "MD", failing)
    scan = run_scan(app, window, drive)
    result = run_export(
        app, window, scan["scan_id"], out, ["MD", "JSON"],
        custom_names={"MD": "list", "JSON": "list"},
    )

    assert result["success"] is True
    assert result["errors"] == ["MD: boom"]
    assert os.listdir(out) == ["list.json"]


def test_export_fails_when_every_writer_fails(app, window, drive, out, monkeypatch):
    def failing(handle, items, meta, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setitem(exporter.WRITERS, "MD", failing)
    scan = run_scan(app, window, drive)
    result = run_export(app, window, scan["scan_id"], out, ["MD"])

    assert result == {"success": False, "saved": [], "errors": ["MD: boom"]}
    assert os.listdir(out) == []


def test_unknown_formats_are_reported_and_skipped(app, window, drive, out):
    scan = run_scan(app, window, drive)
    result = run_export(app, window, scan["scan_id"], out, ["PDF", "MD"])

    assert result["success"] is True
    assert result["errors"] == ["Unknown format: PDF"]
    assert len(result["saved"]) == 1


def test_export_without_formats_saves_nothing(app, window, drive, out):
    scan = run_scan(app, window, drive)
    result = run_export(app, window, scan["scan_id"], out, [])

    assert result == {"success": False, "saved": [], "errors": []}
    assert window.starting("onExportProgress") == []


def test_an_unexpected_export_error_is_reported_and_frees_the_slot(
    app, window, drive, out, monkeypatch
):
    scan = run_scan(app, window, drive)

    def boom(*args):
        raise RuntimeError("boom")

    with monkeypatch.context() as patched:
        patched.setattr(app, "_write_exports", boom)
        assert app.export({
            "scan_id": scan["scan_id"], "output_dir": str(out), "selection": {},
        }) == {"async": True}
        assert window.take_json("onExportDone") == {"success": False, "error": "boom"}

    assert app._exporting is False
    assert run_export(app, window, scan["scan_id"], out)["success"] is True


def test_exported_files_can_be_opened_but_their_neighbours_cannot(
    app, window, drive, out, popen
):
    scan = run_scan(app, window, drive)
    result = run_export(app, window, scan["scan_id"], out)
    neighbour = out / "other.txt"
    neighbour.write_text("x")

    assert app.open_path(result["saved"][0]) == {"ok": True}
    assert app.open_path(str(neighbour)) == api._DENIED


# ── Selection and metadata helpers ───────────────────────────────

TREE = [
    {"lvl": 0, "type": "folder", "name": "d", "path": "/d", "size": 9, "mtime": 0},
    {"lvl": 1, "type": "file", "name": "a.txt", "path": "/d/a.txt", "size": 4, "mtime": 0},
    {"lvl": 1, "type": "folder", "name": "sub", "path": "/d/sub", "size": 5, "mtime": 0},
    {"lvl": 2, "type": "file", "name": "b.txt", "path": "/d/sub/b.txt", "size": 5, "mtime": 0},
]


def test_selected_files_defaults_to_every_file():
    assert api.API._selected_files(TREE, {}) == {"/d/a.txt", "/d/sub/b.txt"}


def test_selected_files_subtracts_all_except():
    assert api.API._selected_files(TREE, {"all_except": ["/d/a.txt", "/nowhere"]}) == {"/d/sub/b.txt"}


def test_selected_files_only_wins_over_everything_else():
    selection = {"only": ["/d/a.txt"], "all_except": ["/d/a.txt"]}

    assert api.API._selected_files(TREE, selection) == {"/d/a.txt"}


def build_meta(app, scan, states=None):
    items = list(exporter.iter_export(TREE, states or {}, {"/d/a.txt", "/d/sub/b.txt"}, None))
    return app._build_meta(items, scan, "%d. %m. %Y")


def test_meta_counts_exported_items_only(app):
    meta = build_meta(app, {"path": "/d", "volume_label": ""}, {"/d/sub": "name"})

    assert meta["file_count"] == 1
    assert meta["folder_count"] == 1
    assert meta["name_only_count"] == 1
    assert meta["total_size"] == exporter.fmt_size(4)
    assert meta["generated_by"] == "flashscan"


@pytest.mark.parametrize("scan, expected", [
    ({"path": "/mnt/usb", "volume_label": "MY USB"}, "MY USB"),
    ({"path": "/mnt/usb", "volume_label": ""}, "usb"),
    ({"path": "/", "volume_label": ""}, "DISK"),
])
def test_meta_names_the_disk_from_label_then_folder_then_a_fallback(app, scan, expected):
    assert build_meta(app, scan)["disk_name"] == expected


# ── Window, dialogs and pass-throughs ────────────────────────────

def test_reveal_shows_the_window_once(app, window):
    app.reveal(ui_reported=True)
    app.reveal(ui_reported=True)

    assert (window.maximized, window.shown) == (1, 1)


def test_ui_ready_reveals_without_a_warning(app, window, caplog):
    with caplog.at_level(logging.WARNING, logger=api.log.name):
        app.ui_ready()

    assert window.shown == 1
    assert "did not report ready" not in caplog.text


def test_a_late_ui_still_gets_a_revealed_window_and_a_warning(app, window, caplog):
    with caplog.at_level(logging.WARNING, logger=api.log.name):
        app.reveal()
        app.ui_ready()

    assert window.shown == 1
    assert caplog.text.count("did not report ready") == 1


def test_reveal_without_a_window_does_nothing():
    api.API([]).reveal(ui_reported=True)


@pytest.mark.parametrize("picked, expected", [(["E:\\Photos", "ignored"], "E:\\Photos"), ([], None), (None, None)])
def test_browse_returns_the_first_folder_or_none(app, window, monkeypatch, picked, expected):
    monkeypatch.setattr(api.webview, "FileDialog", types.SimpleNamespace(FOLDER="folder"), raising=False)
    window.dialog_result = picked

    assert app.browse_directory() == expected
    assert window.dialog_args == ["folder"]


def test_browse_supports_older_pywebview(app, window, monkeypatch):
    monkeypatch.delattr(api.webview, "FileDialog", raising=False)
    monkeypatch.setattr(api.webview, "FOLDER_DIALOG", "legacy", raising=False)
    window.dialog_result = ["x"]

    assert app.browse_directory() == "x"
    assert window.dialog_args == ["legacy"]


def test_settings_round_trip_through_the_api(app):
    app.save_settings({"theme": "dark"})
    assert app.get_settings()["theme"] == "dark"

    assert app.get_custom_exts() == []
    app.save_custom_exts(["abc", "xyz"])
    assert app.get_custom_exts() == ["abc", "xyz"]


def test_profiles_round_trip_through_the_api(app):
    assert app.get_profile("vol-1") is None

    app.save_profile("vol-1", {"notes": {"/d": "keep"}})
    profile = app.get_profile("vol-1")
    assert profile["notes"] == {"/d": "keep"}
    assert profile["volumeId"] == "vol-1"

    app.delete_profile("vol-1")
    assert app.get_profile("vol-1") is None


def test_js_log_entries_reach_the_logger(app, monkeypatch):
    seen = []
    monkeypatch.setattr(api.logger, "log_js", lambda *args: seen.append(args))

    app.log_js("warn", "something odd", "tree.js")

    assert seen == [("warn", "something odd", "tree.js")]


def test_scan_log_summarises_issues_and_caps_the_details(caplog, monkeypatch):
    monkeypatch.setattr(api, "MAX_LOGGED_UNREADABLE", 1)
    monkeypatch.setattr(api, "MAX_LOGGED_LINKS", 1)
    result = {
        "file_count": 10, "folder_count": 2, "skipped": 1, "beyond_depth": 4,
        "unreadable_count": 3,
        "unreadable": [
            {"kind": "file", "path": "/d/a", "reason": "Permission denied"},
            {"kind": "folder", "path": "/d/b", "reason": "Permission denied"},
        ],
        "links_skipped": 2,
        "links": [
            {"kind": "folder", "path": "/d/l1", "target": "/t1"},
            {"kind": "file", "path": "/d/l2", "target": "/t2"},
        ],
    }

    with caplog.at_level(logging.INFO, logger=api.log.name):
        api.API._log_scan_result(7, result, 1.5)

    text = caplog.text
    assert "id=7 files=10 folders=2 skipped=1 unreadable=3 beyond_depth=4 links=2" in text
    assert "Unreadable file: /d/a (Permission denied)" in text
    assert "/d/b" not in text
    assert "... and 2 more unreadable entries" in text
    assert "Link not followed (folder): /d/l1 -> /t1" in text
    assert "/d/l2" not in text
    assert "... and 1 more links" in text
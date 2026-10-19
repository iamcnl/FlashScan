import logging

import pytest

import logger


@pytest.fixture
def fresh_logging(monkeypatch):
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    monkeypatch.setattr(logger, "_configured", False)
    monkeypatch.setattr(logger, "_log_file", None)
    monkeypatch.setattr(logger, "_js_window_start", 0.0)
    monkeypatch.setattr(logger, "_js_window_count", 0)
    monkeypatch.setattr(logger, "_js_suppressed", 0)
    monkeypatch.setattr("sys.excepthook", __import__("sys").excepthook)
    monkeypatch.setattr("threading.excepthook", __import__("threading").excepthook)
    yield
    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


def flush():
    for handler in logging.getLogger().handlers:
        handler.flush()


def test_setup_creates_log_file(tmp_path, fresh_logging):
    path = logger.setup(tmp_path)
    flush()
    assert path == tmp_path / logger.LOG_NAME
    assert "Log file:" in path.read_text(encoding="utf-8")


def test_setup_is_idempotent(tmp_path, fresh_logging):
    first = logger.setup(tmp_path)
    handlers = len(logging.getLogger().handlers)
    assert logger.setup(tmp_path / "other") == first
    assert len(logging.getLogger().handlers) == handlers


def test_falls_back_when_directory_unusable(tmp_path, fresh_logging, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(logger.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    path = logger.setup(blocker / "sub")
    assert path == tmp_path / "tmp" / "FlashScan" / logger.LOG_NAME


def test_rotates_and_keeps_backups(tmp_path, fresh_logging, monkeypatch):
    monkeypatch.setattr(logger, "MAX_BYTES", 2000)
    logger.setup(tmp_path)
    log = logging.getLogger("rotation")
    for i in range(200):
        log.info("line %d %s", i, "x" * 50)
    flush()
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == [f"{logger.LOG_NAME}{s}" for s in ("", ".1", ".2", ".3")]


def test_log_js_writes_level_and_source(tmp_path, fresh_logging):
    path = logger.setup(tmp_path)
    logger.log_js("error", "boom", "window.onerror")
    logger.log_js("warn", "careful")
    flush()
    text = path.read_text(encoding="utf-8")
    assert "[ERROR]" in text and "[window.onerror] boom" in text
    assert "[WARNING]" in text and "careful" in text


def test_log_js_truncates_long_messages(tmp_path, fresh_logging):
    path = logger.setup(tmp_path)
    logger.log_js("error", "y" * 10_000)
    flush()
    assert "[truncated]" in path.read_text(encoding="utf-8")


def test_log_js_rate_limit(tmp_path, fresh_logging):
    path = logger.setup(tmp_path)
    for i in range(logger.JS_MAX_PER_WINDOW + 25):
        logger.log_js("error", f"entry {i}")
    flush()
    text = path.read_text(encoding="utf-8")
    assert f"entry {logger.JS_MAX_PER_WINDOW - 1}\n" in text
    assert f"entry {logger.JS_MAX_PER_WINDOW}\n" not in text


def test_uncaught_thread_exception_is_logged(tmp_path, fresh_logging):
    import threading

    path = logger.setup(tmp_path)

    def fail():
        raise RuntimeError("thread blew up")

    t = threading.Thread(target=fail, name="worker-x")
    t.start()
    t.join()
    flush()
    text = path.read_text(encoding="utf-8")
    assert "Uncaught exception in thread worker-x" in text
    assert "RuntimeError: thread blew up" in text
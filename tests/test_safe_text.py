import json

import safe_text
from settings import load_profile, save_profile

LONE = "bad\udc80name"


def test_printable_escapes_only_what_cannot_be_encoded():
    assert safe_text.printable(LONE) == "bad\\udc80name"
    assert safe_text.printable("naïve ☃ 日本語") == "naïve ☃ 日本語"


def test_dumps_keeps_readable_text_when_it_can_be_encoded():
    assert safe_text.dumps({"a": "日本語"}) == '{"a": "日本語"}'


def test_dumps_escapes_a_lone_surrogate_and_it_reads_back_unchanged():
    text = safe_text.dumps({"path": LONE})

    text.encode("utf-8")
    assert json.loads(text) == {"path": LONE}


def test_a_profile_with_a_lone_surrogate_path_is_saved_and_loaded(tmp_path, monkeypatch):
    import settings
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(settings, "_profile_path", lambda vid: tmp_path / f"{vid}.json")

    save_profile("vol", {"selection": {LONE: "skip"}})

    assert load_profile("vol")["selection"] == {LONE: "skip"}
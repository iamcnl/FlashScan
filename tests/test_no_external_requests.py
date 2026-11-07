import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCANNED = [*ROOT.glob("ui/**/*.html"), *ROOT.glob("ui/**/*.css"), *ROOT.glob("export_templates/*.css")]
EXTERNAL = re.compile(
    r"""@import\s+(?:url\()?\s*['"]?https?://|url\(\s*['"]?https?://|(?:src|href)\s*=\s*['"]https?://""",
    re.IGNORECASE,
)


def test_ui_and_export_assets_make_no_external_requests():
    offenders = [str(p.relative_to(ROOT)) for p in SCANNED if EXTERNAL.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_bundled_font_files_exist_for_every_font_face():
    css = (ROOT / "ui" / "css" / "fonts.css").read_text(encoding="utf-8")
    files = re.findall(r"url\('\.\./fonts/([^']+)'\)", css)
    assert files
    assert all((ROOT / "ui" / "fonts" / f).is_file() for f in files)

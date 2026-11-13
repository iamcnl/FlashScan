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


def test_the_page_has_a_csp_and_no_inline_script_or_handlers():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    policy = re.search(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', html).group(1)

    assert "script-src 'self'" in policy
    assert "'unsafe-inline'" not in policy.split("style-src")[0]
    assert "'unsafe-eval'" not in policy
    assert not re.search(r"<script(?![^>]*\ssrc=)", html)
    assert not re.search(r"\son[a-z]+\s*=", html, re.IGNORECASE)
    assert "javascript:" not in html.lower()
import io
import json
import os
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

import pytest

import exporter
import scanner

ROOT = os.path.abspath(os.sep + "drive")
STAMP = datetime(2024, 3, 5, 12, 0).timestamp()
DATE = "05. 03. 2024"

META = {
    "disk_name": "E:",
    "volume_label": "MY USB",
    "timestamp": "2024-03-05 12:00",
    "path": "E:\\",
    "file_count": 2,
    "folder_count": 3,
    "total_size": "2.0 KB",
}


def path_of(rel):
    return os.path.join(ROOT, *rel.split("/")) if rel else ROOT


def make_tree(*entries, size=10, mtime=STAMP):
    tree = [{"lvl": 0, "type": "folder", "name": "drive", "path": ROOT, "size": 0, "mtime": mtime}]
    for entry in entries:
        rel = entry.rstrip("/")
        is_folder = entry.endswith("/")
        tree.append({
            "lvl": rel.count("/") + 1,
            "type": "folder" if is_folder else "file",
            "name": rel.rsplit("/", 1)[-1],
            "path": path_of(rel),
            "size": 0 if is_folder else size,
            "mtime": mtime,
        })
    for node in tree:
        if node["type"] == "folder":
            prefix = node["path"] + os.sep
            node["size"] = sum(
                n["size"] for n in tree if n["type"] == "file" and n["path"].startswith(prefix)
            )
    return tree


def all_files(tree):
    return {n["path"] for n in tree if n["type"] == "file"}


def export(tree, states=None, files=None, hidden=None):
    chosen = all_files(tree) if files is None else files
    return list(exporter.iter_export(tree, states or {}, chosen, hidden))


def labels(items):
    out = []
    for _lvl, typ, _name, path, _size, _mtime, _state in items:
        if path == ROOT:
            out.append("drive/")
            continue
        rel = path[len(ROOT) + 1:].replace(os.sep, "/")
        out.append(rel + ("/" if typ == "folder" else ""))
    return out


def row(lvl, typ, name, rel, size, state="full", mtime=STAMP):
    return (lvl, typ, name, path_of(rel), size, mtime, state)


GOLDEN_ITEMS = [
    row(0, "folder", "drive", "", 2058),
    row(1, "file", "z.txt", "z.txt", 10),
    row(1, "folder", "a", "a", 2048),
    row(2, "file", "one.txt", "a/one.txt", 2048),
    row(2, "folder", "deep", "a/deep", 0, "name"),
]
GOLDEN_NOTES = {path_of("a"): "holiday pics"}


def render(writer, items, meta=None, **kwargs):
    out = io.StringIO()
    writer(out, list(items), meta or META, **kwargs)
    return out.getvalue()


# ── Formatting helpers ───────────────────────────────────────────

@pytest.mark.parametrize("size, expected", [
    (0, "0 B"),
    (1023, "1023 B"),
    (1024, "1.0 KB"),
    (1536, "1.5 KB"),
    (1_048_576, "1.0 MB"),
    (5 * 1_048_576, "5.0 MB"),
    (1_073_741_824, "1.00 GB"),
    (5 * 1_073_741_824, "5.00 GB"),
])
def test_fmt_size(size, expected):
    assert exporter.fmt_size(size) == expected


def test_fmt_date():
    assert exporter.fmt_date(STAMP) == DATE
    assert exporter.fmt_date(0) == ""


def test_fmt_date_uses_the_given_pattern():
    assert exporter.fmt_date(STAMP, "%Y-%m-%d") == "2024-03-05"
    assert exporter.fmt_date(STAMP, "%m/%d/%Y") == "03/05/2024"
    assert exporter.fmt_date(0, "%Y-%m-%d") == ""


@pytest.mark.parametrize("pattern", [
    "%d. %m. %Y", "%m/%d/%Y", "%Y-%m-%d", "%Y. %m. %d.", "%d.%m.%Y",
])
def test_normalize_date_pattern_keeps_day_month_year_layouts(pattern):
    assert exporter.normalize_date_pattern(pattern) == pattern


@pytest.mark.parametrize("pattern", [
    None, 5, "", "%d", "%d %m", "%d %m %Y %H", "%d %m %Y %Y",
    "%%d %m %Y", "%d %m %Y%", "%d %m %Y\n", "%c", "x" * 40,
])
def test_normalize_date_pattern_falls_back_to_the_default(pattern):
    assert exporter.normalize_date_pattern(pattern) == exporter.DEFAULT_DATE_PATTERN


def test_esc_escapes_everything_that_can_break_html():
    assert exporter._esc("<a href=\"x\" onclick='y'>&") == (
        "&lt;a href=&quot;x&quot; onclick=&#x27;y&#x27;&gt;&amp;"
    )
    assert exporter._esc(5) == "5"


def test_lines_are_joined_without_a_trailing_newline():
    out = io.StringIO()
    emit = exporter._Lines(out).add

    emit("a")
    emit("b")
    emit("")
    emit("c")

    assert out.getvalue() == "a\nb\n\nc"


def test_extension_categories():
    assert exporter._ext_category("jpg") == ("Images", "#85b7eb")
    assert exporter._ext_category("JPG") == ("Images", "#85b7eb")
    assert exporter._ext_category("zip")[0] == "Archives"
    assert exporter._ext_category("zzz") == ("Other", "#c8c5bc")
    assert exporter._ext_category("") == ("Other", "#c8c5bc")


def test_extension_listed_in_two_groups_goes_to_the_later_one():
    assert exporter._ext_category("ts")[0] == "Code & Data"


def test_export_css_template_is_found():
    assert exporter._load_export_css().strip()


def test_all_four_formats_are_registered():
    assert set(exporter.WRITERS) == {"MD", "TXT", "JSON", "HTML"}
    assert exporter.WRITERS["MD"] is exporter.write_md


# ── iter_export ──────────────────────────────────────────────────

TREE = make_tree(
    "z.txt",
    "a/", "a/one.txt", "a/b/", "a/b/two.txt",
    "ab/", "ab/other.txt",
    "c/", "c/three.txt",
)
EVERYTHING = [
    "drive/", "z.txt",
    "a/", "a/one.txt", "a/b/", "a/b/two.txt",
    "ab/", "ab/other.txt",
    "c/", "c/three.txt",
]


def test_everything_is_exported_by_default():
    items = export(TREE)

    assert labels(items) == EVERYTHING
    assert items[0] == (0, "folder", "drive", ROOT, TREE[0]["size"], STAMP, "full")
    assert items[1] == (1, "file", "z.txt", path_of("z.txt"), 10, STAMP, "full")


def test_explicit_full_state_changes_nothing():
    assert labels(export(TREE, {path_of("a"): "full"})) == EVERYTHING


def test_skip_drops_the_folder_and_everything_under_it():
    got = labels(export(TREE, {path_of("a"): "skip"}))

    assert got == ["drive/", "z.txt", "ab/", "ab/other.txt", "c/", "c/three.txt"]


def test_skip_does_not_leak_into_a_sibling_sharing_the_name_prefix():
    got = labels(export(TREE, {path_of("a"): "skip"}))

    assert "ab/" in got and "ab/other.txt" in got


def test_name_keeps_the_folder_but_hides_its_contents():
    items = export(TREE, {path_of("a"): "name"})

    assert labels(items) == ["drive/", "z.txt", "a/", "ab/", "ab/other.txt", "c/", "c/three.txt"]
    assert [i[6] for i in items if i[3] == path_of("a")] == ["name"]


def test_nested_skip_only_affects_that_branch():
    got = labels(export(TREE, {path_of("a/b"): "skip"}))

    assert "a/one.txt" in got
    assert "a/b/" not in got and "a/b/two.txt" not in got


def test_nested_name_keeps_only_the_nested_folder():
    items = export(TREE, {path_of("a/b"): "name"})

    assert "a/b/" in labels(items)
    assert "a/b/two.txt" not in labels(items)
    assert [i[6] for i in items if i[3] == path_of("a/b")] == ["name"]


def test_a_child_cannot_undo_a_blocked_parent():
    got = labels(export(TREE, {path_of("a"): "skip", path_of("a/b"): "full"}))

    assert "a/b/" not in got and "a/b/two.txt" not in got


def test_skip_inside_a_name_only_folder_changes_nothing_visible():
    got = labels(export(TREE, {path_of("a"): "name", path_of("a/b"): "skip"}))

    assert got == ["drive/", "z.txt", "a/", "ab/", "ab/other.txt", "c/", "c/three.txt"]


def test_states_for_unknown_paths_are_ignored():
    assert labels(export(TREE, {path_of("nope"): "skip"})) == EVERYTHING


def test_deselected_files_are_left_out_but_their_folder_stays():
    chosen = all_files(TREE) - {path_of("a/one.txt"), path_of("a/b/two.txt")}
    got = labels(export(TREE, files=chosen))

    assert "a/one.txt" not in got and "a/b/two.txt" not in got
    assert "a/" in got and "a/b/" in got


def test_with_nothing_selected_only_folders_remain():
    got = labels(export(TREE, files=set()))

    assert got == ["drive/", "a/", "a/b/", "ab/", "c/"]


def test_selected_paths_missing_from_the_tree_are_ignored():
    chosen = all_files(TREE) | {path_of("ghost.txt")}

    assert labels(export(TREE, files=chosen)) == EVERYTHING


EXT_TREE = make_tree(
    "photo.JPG", "song.mp3", "notes", "archive.", "readme.md", ".gitignore", "x.tar.gz",
    "sub/", "sub/pic.jpg",
)


def test_no_hidden_extensions_keeps_every_file():
    assert len(export(EXT_TREE, hidden=None)) == len(EXT_TREE)
    assert len(export(EXT_TREE, hidden=set())) == len(EXT_TREE)


def test_hidden_extensions_match_the_file_name_case_insensitively():
    got = labels(export(EXT_TREE, hidden={"jpg"}))

    assert "photo.JPG" not in got and "sub/pic.jpg" not in got
    assert "song.mp3" in got and "readme.md" in got


def test_extensions_that_are_not_hidden_stay_in_even_when_unlisted():
    got = labels(export(EXT_TREE, hidden={"mp3"}))

    assert "song.mp3" not in got
    assert "x.tar.gz" in got and ".gitignore" in got and "readme.md" in got


def test_extensionless_files_are_never_hidden():
    got = labels(export(EXT_TREE, hidden={"jpg", "mp3", "md", "gz", "gitignore"}))

    assert got == ["drive/", "notes", "archive.", "sub/"]


def test_hiding_extensions_never_hides_folders():
    got = labels(export(EXT_TREE, hidden={"jpg", "mp3"}))

    assert "sub/" in got


def test_hidden_extensions_and_selection_both_apply():
    chosen = all_files(EXT_TREE) - {path_of("song.mp3")}
    got = labels(export(EXT_TREE, files=chosen, hidden={"jpg"}))

    assert "song.mp3" not in got and "photo.JPG" not in got
    assert "readme.md" in got


def test_paths_from_a_real_scan_match_folder_state_keys(tmp_path):
    drive = tmp_path / "drive"
    for rel in ("top.txt", "keep/a.jpg", "skip_me/x.txt", "name_only/y.txt"):
        target = drive / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
    tree = scanner.scan_path(str(drive))["tree"]
    states = {str(drive / "skip_me"): "skip", str(drive / "name_only"): "name"}

    items = list(exporter.iter_export(tree, states, {i["path"] for i in tree if i["type"] == "file"}))

    assert [i[2] for i in items] == ["drive", "top.txt", "keep", "a.jpg", "name_only"]


DRIVE_ROOT = os.path.abspath(os.sep)

SELECTION_CASES = json.loads(
    (Path(__file__).parent / "selection_cases.json").read_text(encoding="utf-8")
)


def drive_path(rel):
    return os.path.join(DRIVE_ROOT, *rel.split("/")) if rel else DRIVE_ROOT


def drive_tree(entries):
    return [
        {
            "lvl": rel.count("/") + 1 if rel else 0,
            "type": entry["type"],
            "name": rel.rsplit("/", 1)[-1] if rel else "drive",
            "path": drive_path(rel),
            "size": entry.get("size", 0),
            "mtime": STAMP,
        }
        for entry in entries
        for rel in [entry["path"]]
    ]


def run_case(case):
    tree = drive_tree(SELECTION_CASES["tree"])
    states = {drive_path(k): v for k, v in case.get("states", {}).items()}
    chosen = all_files(tree) - {drive_path(p) for p in case.get("deselected", [])}
    hidden = set(case["hidden_exts"]) if case.get("hidden_exts") is not None else None
    return list(exporter.iter_export(tree, states, chosen, hidden))


@pytest.mark.parametrize("case", SELECTION_CASES["cases"], ids=lambda c: c["name"])
def test_selection_cases_shared_with_the_ui(case):
    items = run_case(case)
    files = [i for i in items if i[1] == "file"]

    assert len(files) == case["files"]
    assert sum(i[4] for i in files) == case["size"]
    assert sum(1 for i in items if i[6] == "name") == case["name_only"]


def test_names_only_on_a_drive_root_hides_every_subfolder():
    tree = drive_tree(SELECTION_CASES["tree"])

    items = list(exporter.iter_export(tree, {DRIVE_ROOT: "name"}, all_files(tree)))

    assert [i[3] for i in items] == [DRIVE_ROOT]


def test_a_partial_folder_chain_exports_a_re_ticked_file_under_a_drive_root():
    tree = drive_tree(SELECTION_CASES["tree"])
    states = {drive_path("a"): "partial", drive_path("a/b"): "partial", DRIVE_ROOT: "partial"}
    chosen = {drive_path("a/b/two.log")}

    items = list(exporter.iter_export(tree, states, chosen))

    assert [i[2] for i in items if i[1] == "file"] == ["two.log"]


# ── Markdown ─────────────────────────────────────────────────────

def assert_valid_nesting(md):
    previous = None
    for line in md.split("\n"):
        item = re.match(r"^( *)- ", line)
        if item is None:
            assert not line.startswith(" "), line
            previous = None
            continue
        indent = len(item.group(1))
        assert indent % 4 == 0, line
        assert indent <= (0 if previous is None else previous + 4), line
        previous = indent


def test_markdown_golden_output():
    out = render(exporter.write_md_list, GOLDEN_ITEMS, folder_notes=GOLDEN_NOTES)

    assert out == "\n".join([
        "# MY USB (E:) — file list",
        "",
        "- **Exported:** 2024-03-05 12:00",
        "- **Path:** `E:\\`",
        "- **Contents:** 2 files · 3 folders · 2.0 KB",
        "",
        "---",
        "",
        f"- z.txt · 10 B · {DATE}",
        "",
        "## a",
        "",
        "> holiday pics",
        "",
        "*1 file · 2.0 KB*",
        "",
        f"- one.txt · 2.0 KB · {DATE}",
        "- **deep/** · names only",
        "",
    ])


def test_markdown_title_without_a_volume_label():
    out = render(exporter.write_md_list, [], {**META, "volume_label": ""})

    assert out.startswith("# E: — file list")


def test_markdown_output_ends_with_exactly_one_newline():
    for items in ([], GOLDEN_ITEMS, [row(0, "folder", "drive", "", 0), row(1, "folder", "e", "e", 0)]):
        out = render(exporter.write_md_list, items)

        assert out.endswith("\n") and not out.endswith("\n\n")


def test_folder_totals_follow_the_tree_levels_not_the_item_order():
    tree = make_tree("a/", "a/b/", "a/b/c/", "a/b/c/x.bin", "a/b/y.bin", "a/z.bin", "top.bin")
    counts, sizes = exporter._folder_totals(export(tree))

    assert counts[path_of("a/b/c")] == 1
    assert counts[path_of("a/b")] == 2
    assert counts[path_of("a")] == 3
    assert sizes[path_of("a")] == 30
    assert counts[ROOT] == 4


def test_markdown_lists_never_become_code_blocks():
    tree = make_tree("a/", "a/b/", "a/b/c/", "a/b/c/x.bin", "a/b/y.bin", "a/z.bin", "top.bin", "top2.bin")
    out = render(exporter.write_md_list, export(tree))

    assert_valid_nesting(out)
    assert "\n    - x.bin" not in out
    assert "    - **c/** · 1 file · 10 B\n        - x.bin" in out


def test_markdown_has_no_heading_for_the_root_and_lists_root_files_first():
    tree = make_tree("top.bin", "a/", "a/x.bin")
    out = render(exporter.write_md_list, export(tree))

    assert "## drive" not in out
    assert out.index("- top.bin") < out.index("## a")
    assert "---\n\n- top.bin" in out


def test_markdown_header_is_a_list_with_singular_counts():
    meta = {**META, "file_count": 1, "folder_count": 1, "name_only_count": 2}
    out = render(exporter.write_md_list, [], meta)

    assert "- **Exported:** 2024-03-05 12:00\n- **Path:** `E:\\`\n" in out
    assert "- **Contents:** 1 file · 1 folder · 2.0 KB · 2 names only\n" in out
    assert "  \n" not in out


def test_markdown_folder_heading_shows_note_count_and_size():
    tree = make_tree("a/", "a/x.bin", "a/y.bin")
    items = export(tree)
    out = render(exporter.write_md_list, items, folder_notes={path_of("a"): "hello"})

    assert "## a\n\n> hello\n\n*2 files · 20 B*\n\n" in out
    bare = render(exporter.write_md_list, items, include_size=False)
    assert "*2 files*" in bare and "20 B" not in bare


def test_markdown_folder_size_counts_only_exported_files():
    tree = make_tree("a/", "a/x.bin", "a/y.bin")
    items = export(tree, files={path_of("a/x.bin")})

    assert "*1 file · 10 B*" in render(exporter.write_md_list, items)


def test_markdown_marks_names_only_and_empty_folders():
    tree = make_tree("n/", "n/z.bin", "e/", "t/", "t/e2/")
    items = export(tree, states={path_of("n"): "name"})
    out = render(exporter.write_md_list, items)

    assert "## n\n\n*names only · 10 B*\n" in out
    assert "## e\n\n*empty*\n" in out
    assert "- **e2/** · empty" in out
    assert "*names only*\n" in render(exporter.write_md_list, items, include_size=False)


def test_markdown_deeper_folder_with_a_note_is_a_bullet():
    items = [row(0, "folder", "drive", "", 0), row(2, "folder", "b", "a/b", 0)]
    out = render(exporter.write_md_list, items, folder_notes={path_of("a/b"): "n"})

    assert out.endswith("- **b/** · empty — *n*\n")


def test_markdown_omits_date_when_empty_and_sizes_when_asked():
    items = [
        row(0, "folder", "drive", "", 0),
        row(1, "file", "full.txt", "full.txt", 10),
        row(1, "file", "empty.txt", "empty.txt", 0),
        row(1, "file", "undated.txt", "undated.txt", 10, mtime=0),
    ]
    out = render(exporter.write_md_list, items)

    assert f"- full.txt · 10 B · {DATE}\n" in out
    assert f"- empty.txt · 0 B · {DATE}\n" in out
    assert "- undated.txt · 10 B\n" in out

    bare = render(exporter.write_md_list, items, include_size=False, include_date=False)
    assert "\n- full.txt\n" in bare
    assert " B" not in bare.split("---")[1]
    assert DATE not in bare


def test_markdown_escapes_special_characters_in_file_names():
    items = [row(0, "folder", "drive", "", 0), row(1, "file", "*star* #hash `tick`.txt", "x", 1)]

    assert "- \\*star\\* \\#hash \\`tick\\`.txt" in render(exporter.write_md_list, items)


@pytest.mark.parametrize("name, escaped", [
    ("[click](http://example.com).txt", "\\[click\\](http://example.com).txt"),
    ("<script>alert(1)</script>", "\\<script\\>alert(1)\\</script\\>"),
    ("my_file_name.txt", "my\\_file\\_name.txt"),
    ("a|b~c&amp;d", "a\\|b\\~c\\&amp;d"),
    ("back\\slash.txt", "back\\\\slash.txt"),
    ("1. intro.txt", "1\\. intro.txt"),
    ("- dash.txt", "\\- dash.txt"),
    ("two\nlines.txt", "two lines.txt"),
])
def test_markdown_escapes_each_kind_of_markup(name, escaped):
    items = [row(0, "folder", "drive", "", 0), row(1, "file", name, "x", 1)]

    assert f"\n- {escaped} · 1 B" in render(exporter.write_md_list, items)


def test_markdown_leaves_plain_names_untouched():
    items = [row(0, "folder", "drive", "", 0), row(1, "file", "Report (final) v2.0 - copy.txt", "x", 1)]

    assert "- Report (final) v2.0 - copy.txt" in render(exporter.write_md_list, items)


def test_markdown_escapes_folder_names_in_headings_and_bold_bullets():
    items = [
        row(0, "folder", "drive", "", 0),
        row(1, "folder", "a*b", "a", 0),
        row(2, "folder", "c**d", "a/c", 0),
    ]
    out = render(exporter.write_md_list, items)

    assert "## a\\*b" in out
    assert "- **c\\*\\*d/** · empty" in out


def test_markdown_escapes_folder_notes():
    items = [row(0, "folder", "drive", "", 0), row(1, "folder", "a", "a", 0), row(2, "folder", "b", "a/b", 0)]
    notes = {path_of("a"): "see [this](http://x) *now*", path_of("a/b"): "# not a heading"}
    out = render(exporter.write_md_list, items, folder_notes=notes)

    assert "> see \\[this\\](http://x) \\*now\\*" in out
    assert "- **b/** · empty — *\\# not a heading*" in out


def test_markdown_escapes_title_and_keeps_path_in_a_code_span():
    meta = {**META, "volume_label": "My_USB *1*", "path": "/mnt/odd`name"}
    out = render(exporter.write_md_list, [], meta)

    assert out.startswith("# My\\_USB \\*1\\* (E:) — file list")
    assert "- **Path:** ``/mnt/odd`name``\n" in out


# ── Markdown: toggles and tables ─────────────────────────────────

def test_markdown_toggles_golden_output():
    out = render(exporter.write_md_toggles, GOLDEN_ITEMS, folder_notes=GOLDEN_NOTES)

    assert out == "\n".join([
        "# MY USB (E:) — file list",
        "",
        "- **Exported:** 2024-03-05 12:00",
        "- **Path:** `E:\\`",
        "- **Contents:** 2 files · 3 folders · 2.0 KB",
        "",
        "---",
        "",
        "| Name | Size | Modified |",
        "|---|--:|---|",
        f"| z.txt | 10 B | {DATE} |",
        "",
        "<details open>",
        "<summary><b>a/</b> · 1 file · 2.0 KB</summary>",
        "",
        "> holiday pics",
        "",
        "| Name | Size | Modified |",
        "|---|--:|---|",
        f"| one.txt | 2.0 KB | {DATE} |",
        "",
        "**deep/** · names only",
        "",
        "</details>",
        "",
    ])


def test_markdown_defaults_to_toggles_and_can_switch_to_the_list():
    assert exporter.WRITERS["MD"] is exporter.write_md
    items = export(make_tree("a/", "a/x.bin"))

    assert render(exporter.write_md, items) == render(exporter.write_md_toggles, items)
    assert render(exporter.write_md, items, md_toggles=False) == render(exporter.write_md_list, items)
    assert "| Name | Modified |" in render(exporter.write_md, items, include_size=False)
    assert "- x.bin · 10 B" in render(exporter.write_md, items, md_toggles=False)


def test_markdown_toggles_are_balanced_and_only_top_level_ones_start_open():
    tree = make_tree("a/", "a/b/", "a/b/x.bin", "c/", "c/y.bin")
    out = render(exporter.write_md_toggles, export(tree))

    assert out.count("<details") == out.count("</details>") == 3
    assert out.count("<details open>") == 2
    assert out.index("<details open>\n<summary><b>a/</b>") < out.index("<details>\n<summary><b>b/</b>")


def test_markdown_toggles_never_indent_lines():
    tree = make_tree("a/", "a/b/", "a/b/c/", "a/b/c/x.bin", "a/b/y.bin", "top.bin")
    out = render(exporter.write_md_toggles, export(tree))

    assert not [line for line in out.split("\n") if line.startswith(" ")]


def test_markdown_toggles_put_each_folders_files_in_its_own_table():
    tree = make_tree("top.bin", "a/", "a/x.bin", "a/b/", "a/b/y.bin")
    out = render(exporter.write_md_toggles, export(tree))

    assert out.count("| Name | Size | Modified |") == 3
    assert out.index("| top.bin") < out.index("<summary><b>a/</b>") < out.index("| x.bin") < out.index("<summary><b>b/</b>")
    assert "| y.bin | 10 B |" in out


def test_markdown_toggles_table_columns_follow_the_options():
    items = [
        row(0, "folder", "drive", "", 0),
        row(1, "file", "full.txt", "full.txt", 10),
        row(1, "file", "undated.txt", "undated.txt", 10, mtime=0),
    ]
    both = render(exporter.write_md_toggles, items)
    assert f"| full.txt | 10 B | {DATE} |" in both
    assert "| undated.txt | 10 B |  |" in both

    no_size = render(exporter.write_md_toggles, items, include_size=False)
    assert "| Name | Modified |\n|---|---|" in no_size
    assert f"| full.txt | {DATE} |" in no_size

    no_date = render(exporter.write_md_toggles, items, include_date=False)
    assert "| Name | Size |\n|---|--:|" in no_date
    assert "| full.txt | 10 B |\n" in no_date

    neither = render(exporter.write_md_toggles, items, include_size=False, include_date=False)
    assert "| Name |\n|---|" in neither
    assert "| full.txt |\n" in neither


def test_markdown_toggles_summary_and_cells_are_escaped_for_their_context():
    items = [
        row(0, "folder", "drive", "", 0),
        row(1, "folder", "<b>&x", "a", 20),
        row(2, "file", "a|b *c*.txt", "a/f", 20),
    ]
    out = render(exporter.write_md_toggles, items)

    assert "<summary><b>&lt;b&gt;&amp;x/</b> · 1 file · 20 B</summary>" in out
    assert "| a\\|b \\*c\\*.txt | 20 B |" in out


def test_markdown_toggles_show_folders_without_contents_as_plain_lines():
    tree = make_tree("a/", "a/x.bin", "a/n/", "e/")
    items = export(tree, states={path_of("a/n"): "name"})
    out = render(exporter.write_md_toggles, items, folder_notes={path_of("e"): "hi"})

    assert f"| x.bin | 10 B | {DATE} |\n\n**n/** · names only\n\n</details>" in out
    assert "**e/** · empty — *hi*\n" in out
    assert out.count("<details") == 1


def test_markdown_toggles_folder_size_counts_only_exported_files():
    tree = make_tree("a/", "a/x.bin", "a/y.bin")
    items = export(tree, files={path_of("a/x.bin")})

    assert "<summary><b>a/</b> · 1 file · 10 B</summary>" in render(exporter.write_md_toggles, items)


def test_markdown_toggles_close_open_toggles_before_a_file_that_follows_them():
    items = [
        row(0, "folder", "drive", "", 0),
        row(1, "folder", "a", "a", 20),
        row(2, "folder", "b", "a/b", 10),
        row(3, "file", "y.bin", "a/b/y.bin", 10),
        row(2, "file", "x.bin", "a/x.bin", 10),
    ]
    out = render(exporter.write_md_toggles, items)

    assert out.index("| y.bin") < out.index("</details>") < out.index("| x.bin")
    assert out.count("<details") == out.count("</details>") == 2


def test_markdown_toggles_output_ends_with_exactly_one_newline():
    for items in ([], GOLDEN_ITEMS, [row(0, "folder", "drive", "", 0), row(1, "folder", "e", "e", 0)]):
        out = render(exporter.write_md_toggles, items)

        assert out.endswith("\n") and not out.endswith("\n\n")


def test_markdown_toggles_report_progress():
    seen = []
    render(exporter.write_md_toggles, GOLDEN_ITEMS, progress=seen.append)

    assert seen[-1] == len(GOLDEN_ITEMS)


# ── TXT ──────────────────────────────────────────────────────────

def test_txt_golden_output():
    out = render(exporter.write_txt, GOLDEN_ITEMS, folder_notes=GOLDEN_NOTES)

    assert out == "\n".join([
        "=" * 60,
        "  MY USB (E:) — file list",
        "  Exported 2024-03-05 12:00  |  E:\\",
        "  2 files  |  3 folders  |  2.0 KB",
        "=" * 60,
        "",
        f"{'z.txt':<9}  {'10 B':>6}  {DATE}",
        "",
        "[a/]  1 file · 2.0 KB",
        "  > holiday pics",
        f"{'  one.txt':<9}  {'2.0 KB':>6}  {DATE}",
        "",
        "  [deep/]  names only",
        "",
    ])


def test_txt_title_keeps_its_case_and_works_without_a_volume_label():
    assert render(exporter.write_txt, [], META).splitlines()[1] == "  MY USB (E:) — file list"
    assert render(exporter.write_txt, [], {**META, "volume_label": ""}).splitlines()[1] == "  E: — file list"


def test_txt_header_counts_use_singular_and_names_only():
    meta = {**META, "file_count": 1, "folder_count": 1, "name_only_count": 2}

    assert "  1 file  |  1 folder  |  2.0 KB  |  2 names only" in render(exporter.write_txt, [], meta)


def test_txt_has_no_line_for_the_root_folder_and_starts_with_its_files():
    tree = make_tree("top.bin", "a/", "a/x.bin")
    out = render(exporter.write_txt, export(tree))

    assert "[drive/]" not in out and "/]" in out
    assert any(line.startswith("top.bin") for line in out.splitlines())
    assert "\n[a/]  1 file · 10 B\n" in out


def test_txt_folder_lines_show_count_size_and_state():
    tree = make_tree("a/", "a/x.bin", "a/y.bin", "n/", "n/z.bin", "e/")
    out = render(exporter.write_txt, export(tree, states={path_of("n"): "name"}))

    assert "[a/]  2 files · 20 B" in out
    assert "[n/]  names only · 10 B" in out
    assert "[e/]  empty" in out
    assert "names only" in render(exporter.write_txt, export(tree, states={path_of("n"): "name"}), include_size=False)
    assert "10 B" not in render(exporter.write_txt, export(tree, states={path_of("n"): "name"}), include_size=False)


def test_txt_folder_size_counts_only_exported_files():
    tree = make_tree("a/", "a/x.bin", "a/y.bin")
    out = render(exporter.write_txt, export(tree, files={path_of("a/x.bin")}))

    assert "[a/]  1 file · 10 B" in out


def test_txt_columns_line_up_across_depths_and_sizes():
    items = [
        row(0, "folder", "drive", "", 0),
        row(1, "file", "a.txt", "a.txt", 5),
        row(1, "folder", "d", "d", 0),
        row(2, "file", "a-much-longer-name.txt", "d/b", 1_500_000),
    ]
    lines = [line for line in render(exporter.write_txt, items).splitlines() if DATE in line]

    assert len({line.index(DATE) for line in lines}) == 1
    assert len({line.index(DATE) - 2 for line in lines}) == 1
    assert lines[0].rstrip().endswith(DATE) and "5 B" in lines[0] and "1.4 MB" in lines[1]
    assert lines[0].index("5 B") + 3 == lines[1].index("1.4 MB") + 6


def test_txt_long_names_do_not_push_the_columns_past_the_cap():
    items = [
        row(0, "folder", "drive", "", 0),
        row(1, "file", "short.txt", "s", 1),
        row(1, "file", "x" * 90 + ".txt", "l", 1),
    ]
    short, long = [line for line in render(exporter.write_txt, items).splitlines() if DATE in line]

    assert "x" * 90 in long
    assert short.index(DATE) == 56 + 2 + len("1 B") + 2


def test_txt_omits_size_and_date_when_asked():
    out = render(exporter.write_txt, GOLDEN_ITEMS, include_size=False, include_date=False)

    assert "\nz.txt\n" in out
    assert "10 B" not in out and DATE not in out
    assert f"{'z.txt':<9}  {DATE}" in render(exporter.write_txt, GOLDEN_ITEMS, include_size=False)


def test_txt_shows_zero_byte_files_and_skips_missing_dates():
    items = [
        row(0, "folder", "drive", "", 0),
        row(1, "file", "empty.txt", "e", 0, mtime=0),
    ]

    assert "empty.txt  0 B\n" in render(exporter.write_txt, items)


def test_txt_keeps_consecutive_folder_lines_together():
    tree = make_tree("a/", "a/b/", "a/b/c/", "a/b/c/x.bin")
    out = render(exporter.write_txt, export(tree))

    assert "[a/]  1 file · 10 B\n  [b/]  1 file · 10 B\n    [c/]  1 file · 10 B\n" in out


def test_txt_separates_sibling_folders_with_a_blank_line():
    tree = make_tree("a/", "a/b/", "c/")
    out = render(exporter.write_txt, export(tree))

    assert "  [b/]  empty\n\n[c/]  empty\n" in out
    assert "[a/]  empty\n  [b/]  empty\n" in out


def test_txt_puts_notes_under_their_folder_on_one_line():
    tree = make_tree("a/", "a/x.bin")
    out = render(exporter.write_txt, export(tree), folder_notes={path_of("a"): "first\nsecond"})

    assert "[a/]  1 file · 10 B\n  > first second\n" in out


def test_txt_flattens_line_breaks_in_names():
    items = [row(0, "folder", "drive", "", 0), row(1, "file", "two\nlines.txt", "x", 1)]

    assert "two lines.txt" in render(exporter.write_txt, items)


def test_txt_output_ends_with_exactly_one_newline():
    for items in ([], GOLDEN_ITEMS, [row(0, "folder", "drive", "", 0), row(1, "folder", "e", "e", 0)]):
        out = render(exporter.write_txt, items)

        assert out.endswith("\n") and not out.endswith("\n\n")


def test_txt_reports_progress():
    seen = []
    render(exporter.write_txt, GOLDEN_ITEMS, progress=seen.append)

    assert seen[-1] == len(GOLDEN_ITEMS)


# ── JSON ─────────────────────────────────────────────────────────

def golden_json_object():
    def file_entry(name, rel, size, size_fmt):
        return {"name": name, "path": path_of(rel), "size": size, "size_fmt": size_fmt, "date": DATE}

    return {
        "meta": META,
        "folders": [
            {"name": "drive", "path": ROOT, "level": 0, "mode": "full",
             "files": [file_entry("z.txt", "z.txt", 10, "10 B")]},
            {"name": "a", "path": path_of("a"), "level": 1, "mode": "full",
             "files": [file_entry("one.txt", "a/one.txt", 2048, "2.0 KB")],
             "note": "holiday pics"},
            {"name": "deep", "path": path_of("a/deep"), "level": 2, "mode": "name", "files": []},
        ],
    }


def test_json_streams_exactly_what_json_dumps_would_write():
    out = render(exporter.write_json, GOLDEN_ITEMS, folder_notes=GOLDEN_NOTES)

    expected = golden_json_object()
    assert out == json.dumps(expected, ensure_ascii=False, indent=2)
    assert json.loads(out) == expected


def test_json_with_no_items_is_still_valid():
    out = render(exporter.write_json, [])

    assert out == json.dumps({"meta": META, "folders": []}, ensure_ascii=False, indent=2)


def test_json_omits_size_and_date_fields_when_asked():
    out = json.loads(render(exporter.write_json, GOLDEN_ITEMS, include_size=False, include_date=False))
    file_entry = out["folders"][0]["files"][0]

    assert file_entry == {"name": "z.txt", "path": path_of("z.txt")}


def test_json_keeps_unicode_readable_and_escapes_awkward_names():
    awkward = ['naïve ☃ 日本語.txt', 'say "hi".txt', "back\\slash.txt", "line\nbreak.txt", "tab\there.txt"]
    items = [row(0, "folder", "drive", "", 0)] + [
        row(1, "file", name, f"f{n}", 1) for n, name in enumerate(awkward)
    ]
    out = render(exporter.write_json, items)

    assert "naïve ☃ 日本語.txt" in out
    assert [f["name"] for f in json.loads(out)["folders"][0]["files"]] == awkward


# ── HTML ─────────────────────────────────────────────────────────

VOID = {"meta", "link", "br", "img", "input", "hr", "area", "base", "col", "embed", "source", "track", "wbr"}


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.stack = []
        self.unbalanced = []
        self.seen = []
        self.files = []
        self.title = ""
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag not in VOID:
            self.stack.append((tag, attrs.get("class") or ""))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()
        else:
            self.unbalanced.append(tag)

    def handle_data(self, data):
        if not self.stack:
            return
        tag, cls = self.stack[-1]
        if tag == "title":
            self.title += data
        for token in cls.split():
            self.seen.append((token, data))
        if "fn" in cls.split():
            self.files.append((data, sum(1 for t, _ in self.stack if t == "details")))

    def texts(self, cls):
        return [text for token, text in self.seen if token == cls]

    def attr(self, cls, name):
        return [a.get(name) for _, a in self.tags if cls in (a.get("class") or "").split()]

    def tag_names(self):
        return [tag for tag, _ in self.tags]

    def attr_names(self):
        return {key for _, a in self.tags for key in a}

    def count(self, tag):
        return self.tag_names().count(tag)

    @property
    def balanced(self):
        return not self.unbalanced and not self.stack


def html_of(items, meta=None, **kwargs):
    out = render(exporter.write_html, items, meta, **kwargs)
    return out, Page(out)


HOSTILE_FILES = [
    "<script>alert(1);.txt",
    '"><img src=x onerror=alert(1)>.txt',
    'x" onmouseover="alert(1).txt',
    "'><svg onload=alert(1)>.txt",
    "a&amp;b<b>bold.txt",
    "&lt;already escaped&gt;.txt",
]
HOSTILE_FOLDER = "<i>folder<"
HOSTILE_NOTES = {HOSTILE_FOLDER: "<script>x", "other": '" onclick="x'}
FORBIDDEN_TAGS = {"img", "i", "u", "em", "s"}
FORBIDDEN_ATTRS = {"onerror", "onload", "onmouseover", "onfocus"}


def hostile_items():
    tree = make_tree(
        *HOSTILE_FILES,
        f"{HOSTILE_FOLDER}/", f"{HOSTILE_FOLDER}/inner.txt",
        "other/", "other/inner2.txt",
    )
    return export(tree)


def hostile_notes():
    return {path_of(name): note for name, note in HOSTILE_NOTES.items()}


def test_hostile_file_names_cannot_inject_markup():
    _html, page = html_of(hostile_items())

    expected = sorted(HOSTILE_FILES + ["inner.txt", "inner2.txt"])
    assert sorted(page.texts("fn")) == expected
    assert sorted(page.attr("fn", "title")) == expected
    assert not FORBIDDEN_TAGS & set(page.tag_names())
    assert not FORBIDDEN_ATTRS & page.attr_names()
    assert page.count("script") == 1
    assert page.balanced


def test_hostile_folder_names_and_notes_cannot_inject_markup():
    _html, page = html_of(hostile_items(), folder_notes=hostile_notes())

    assert HOSTILE_FOLDER + "/" in page.texts("fname")
    assert HOSTILE_FOLDER + "/" in page.attr("fname", "title")
    assert sorted(page.texts("fnote-text")) == sorted(HOSTILE_NOTES.values())
    assert sorted(page.attr("fnote-inline", "title")) == sorted(HOSTILE_NOTES.values())
    assert not FORBIDDEN_TAGS & set(page.tag_names())
    assert not FORBIDDEN_ATTRS & page.attr_names()
    assert "onclick" not in {k for t, a in page.tags if t == "span" for k in a}
    assert page.count("script") == 1
    assert page.balanced


def test_hostile_name_only_folder_names_cannot_inject_markup():
    tree = make_tree(f"{HOSTILE_FOLDER}/", f"{HOSTILE_FOLDER}/inner.txt")
    items = export(tree, {path_of(HOSTILE_FOLDER): "name"})
    _html, page = html_of(items)

    assert page.texts("fname-muted") == [HOSTILE_FOLDER + "/"]
    assert page.attr("fname-muted", "title") == [HOSTILE_FOLDER + "/"]
    assert not FORBIDDEN_TAGS & set(page.tag_names())
    assert not FORBIDDEN_ATTRS & page.attr_names()
    assert page.balanced


def test_hostile_header_fields_cannot_inject_markup():
    meta = {
        **META,
        "disk_name": "<u>disk",
        "volume_label": '"><img src=x onerror=alert(1)>',
        "path": "E:\\<b>",
        "timestamp": "<s>t",
        "total_size": "<em>1 GB",
    }
    _html, page = html_of(GOLDEN_ITEMS[:2], meta)

    assert page.texts("disk-name") == [meta["volume_label"]]
    assert page.texts("disk-path") == [f"{meta['path']} — {meta['disk_name']}"]
    assert page.texts("disk-date") == ["exported <s>t"]
    assert meta["total_size"] in page.texts("meta-n")
    assert meta["volume_label"] in page.title
    assert not FORBIDDEN_TAGS & set(page.tag_names())
    assert "b" not in page.tag_names()
    assert not FORBIDDEN_ATTRS & page.attr_names()
    assert page.count("script") == 1


def test_header_with_a_volume_label():
    _html, page = html_of(GOLDEN_ITEMS[:2])

    assert page.texts("disk-name") == ["MY USB"]
    assert page.texts("disk-path") == ["E:\\ — E:"]
    assert page.texts("disk-date") == ["exported 2024-03-05 12:00"]
    assert page.title == "MY USB — 2 files"


def test_header_without_a_volume_label():
    _html, page = html_of(GOLDEN_ITEMS[:2], {**META, "volume_label": ""})

    assert page.texts("disk-name") == ["E:"]
    assert page.texts("disk-path") == ["E:\\"]
    assert page.title == "E: — 2 files"


def test_summary_numbers():
    _html, page = html_of(GOLDEN_ITEMS[:2])

    assert page.texts("meta-n") == ["2", "2.0 KB", "3"]


def test_name_only_count_appears_only_when_set():
    _html, page = html_of(GOLDEN_ITEMS[:2], {**META, "name_only_count": 4})
    assert page.texts("meta-n") == ["2", "2.0 KB", "3", "4"]

    _html, page = html_of(GOLDEN_ITEMS[:2], {**META, "name_only_count": 0})
    assert page.texts("meta-n") == ["2", "2.0 KB", "3"]


def test_page_is_one_self_contained_document():
    html, page = html_of(GOLDEN_ITEMS)

    assert html.startswith("<!DOCTYPE html>")
    assert html.rstrip().endswith("</html>")
    assert exporter._load_export_css() in html
    assert page.count("script") == 1
    assert page.count("link") == 0
    assert not {"src", "href"} & page.attr_names()
    assert page.balanced


def test_folders_come_before_files_and_files_nest_correctly():
    tree = make_tree("z.txt", "a/", "a/one.txt")
    _html, page = html_of(export(tree))

    assert [(c, t) for c, t in page.seen if c in ("fname", "fn")] == [
        ("fname", "a/"), ("fn", "one.txt"), ("fn", "z.txt"),
    ]
    assert page.files == [("one.txt", 1), ("z.txt", 0)]
    fi_classes = [a["class"] for _, a in page.tags if "fi" in a.get("class", "").split()]
    assert fi_classes == ["fi", "fi fi-root"]


def test_deep_nesting_closes_the_right_number_of_levels():
    tree = make_tree("root.txt", "a/", "a/side.txt", "a/b/", "a/b/c/", "a/b/c/deep.txt")
    _html, page = html_of(export(tree))

    assert page.files == [("deep.txt", 3), ("side.txt", 1), ("root.txt", 0)]
    assert page.balanced


def test_root_folder_is_not_rendered_and_top_level_folders_start_open():
    tree = make_tree("a/", "a/x.bin", "a/inner/", "a/inner/z.bin", "b/", "b/y.bin")
    html, page = html_of(export(tree))

    assert page.texts("fname") == ["a/", "inner/", "b/"]
    assert [("open" in a) for t, a in page.tags if t == "details"] == [True, False, True]
    assert "drive" not in page.texts("fname")


def test_folder_meta_shows_size_and_recursive_file_count():
    tree = make_tree("a/", "a/x.bin", "a/b/", "a/b/y.bin", "a/b/z.bin", "empty/")
    html, _page = html_of(export(tree))

    assert '<span class="fcnt"><b>3 files</b></span><span class="fsz">30 B</span><span class="fdt"></span>' in html
    assert '<span class="fcnt"><b>2 files</b></span><span class="fsz">20 B</span><span class="fdt"></span>' in html
    assert '<span class="fcnt">empty</span><span class="fsz"></span><span class="fdt"></span>' in html


def test_folder_meta_without_sizes():
    tree = make_tree("a/", "a/x.bin", "a/y.bin")
    html, _page = html_of(export(tree), include_size=False)

    assert '<span class="fcnt"><b>2 files</b></span><span class="fdt"></span>' in html
    assert 'class="fsz"' not in html


def test_name_only_folder_has_no_contents_and_is_marked():
    tree = make_tree("z.txt", "a/", "a/x.bin", "a/y.bin")
    items = export(tree, {path_of("a"): "name"})
    html, page = html_of(items, {**META, "name_only_count": 1})

    assert page.count("details") == 0
    assert page.texts("fname-muted") == ["a/"]
    assert page.texts("fcnt") == ["names only"]
    assert page.texts("fsz") == ["20 B", "10 B"]
    assert page.texts("fn") == ["z.txt"]
    assert page.balanced


def test_file_columns_respect_the_toggles_and_empty_values():
    tree = make_tree("a.txt")
    html, _page = html_of(export(tree))
    assert f'<span class="fsz">10 B</span><span class="fdt">{DATE}</span>' in html

    html, _page = html_of(export(tree), include_size=False, include_date=False)
    assert 'class="fsz"' not in html and 'class="fdt"' not in html
    assert '<span class="fn" title="a.txt">a.txt</span></div>' in html

    empty = [row(0, "folder", "drive", "", 0), row(1, "file", "e.txt", "e.txt", 0, mtime=0)]
    html, _page = html_of(empty)
    assert '<span class="fsz">0 B</span><span class="fdt"></span>' in html


def test_each_column_is_written_only_when_its_option_is_on():
    tree = make_tree("a/", "a/x.bin")

    html, page = html_of(export(tree), include_date=False)
    assert page.count("fsz") == 0 and 'class="fdt"' not in html
    assert page.texts("fsz") == ["10 B", "10 B"]
    assert '<span class="fmeta"><span class="fcnt"><b>1 file</b></span><span class="fsz">10 B</span></span>' in html

    html, page = html_of(export(tree), include_size=False)
    assert 'class="fsz"' not in html
    assert html.count('class="fdt"') == 2

    html, _page = html_of(export(tree), include_size=False, include_date=False)
    assert '<span class="fmeta"><span class="fcnt"><b>1 file</b></span></span>' in html


def test_narrow_screen_rules_stack_details_under_the_name():
    html, _page = html_of(GOLDEN_ITEMS)
    block = re.search(r"@media \(max-width: 600px\) \{(.*?)\n\}", html, re.S).group(1)

    assert ".tree-toolbar { flex-wrap: wrap;" in block
    assert "font-size: 16px" in block
    assert ".fn { flex: 1 1 calc(100% - 18px); white-space: normal;" in block
    assert ".fname { flex: 1 1 calc(100% - 24px); white-space: normal;" in block
    assert ".fmeta { flex: 1 1 100%;" in block
    assert ".fnote-text { max-width: none; opacity: 1;" in block


def test_folder_note_is_rendered_as_icon_plus_text():
    tree = make_tree("a/", "a/x.bin")
    html, page = html_of(export(tree), folder_notes={path_of("a"): "holiday pics"})

    assert page.texts("fnote-text") == ["holiday pics"]
    assert page.attr("fnote-inline", "title") == ["holiday pics"]
    assert page.count("svg") == 1


def test_name_only_folder_keeps_its_note():
    tree = make_tree("a/", "a/x.bin")
    html, page = html_of(export(tree, {path_of("a"): "name"}), folder_notes={path_of("a"): "originals on the NAS"})

    assert page.texts("fnote-text") == ["originals on the NAS"]
    assert page.attr("fnote-inline", "title") == ["originals on the NAS"]
    assert page.texts("fcnt") == ["names only"]
    assert page.texts("fsz") == ["10 B"]
    assert page.balanced


def test_folder_rows_end_in_the_same_size_and_date_columns_as_file_rows():
    tree = make_tree("a/", "a/x.bin", "a/b/", "a/b/y.bin", "n/", "n/z.bin", "top.bin")
    html, page = html_of(export(tree, {path_of("n"): "name"}))

    folder_rows = re.findall(
        r'<span class="fcnt">[^<]*(?:<b>[^<]*</b>)?</span><span class="fsz">[^<]*</span><span class="fdt"></span></span>', html)
    assert len(folder_rows) == page.count("details") + page.texts("fcnt").count("names only")
    assert page.count("details") == 2
    assert len(page.texts("fsz")) == 6


def test_folder_size_counts_only_exported_files():
    tree = make_tree("a/", "a/x.bin", "a/y.bin")
    selected = {path_of("a/x.bin")}
    items = list(exporter.iter_export(tree, {}, selected))
    html, _page = html_of(items)

    assert '<span class="fcnt"><b>1 file</b></span><span class="fsz">10 B</span>' in html
    assert "20 B" not in html


def test_counts_use_singular_for_one():
    tree = make_tree("a/", "a/x.bin")
    html, page = html_of(export(tree), {**META, "file_count": 1, "folder_count": 1})

    assert "<b>1 file</b>" in html
    assert "1 files" not in html and "1 folders" not in html
    assert page.title.endswith("— 1 file")


def test_page_has_a_filter_box_and_print_rules():
    html, page = html_of(GOLDEN_ITEMS)

    assert page.attr("tb-search", "type") == ["search"]
    assert page.attr("tb-search", "aria-label") == ["Filter by name"]
    assert "@media print" in html
    assert "[hidden] { display: none !important; }" in html


def test_filter_box_has_a_live_status_region():
    html, page = html_of(GOLDEN_ITEMS)

    assert page.attr("tb-status", "role") == ["status"]
    assert page.attr("tb-status", "id") == ["filter-status"]


def test_theme_script_runs_in_the_head_and_follows_the_system_setting():
    html, page = html_of(GOLDEN_ITEMS)

    assert html.index("<script>") < html.index("<style>") < html.index("<body>")
    assert "prefers-color-scheme: dark" in html
    assert page.count("script") == 1


def test_missing_export_css_is_logged(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(exporter, "__file__", str(tmp_path / "exporter.py"))

    with caplog.at_level("WARNING", logger="exporter"):
        assert exporter._load_export_css() == ""

    assert "Export CSS could not be loaded" in caplog.text


def test_legend_lists_only_used_categories_in_a_fixed_order():
    tree = make_tree("song.zip", "pic.jpg", "noext", "sub/", "sub/b.jpg")
    html, page = html_of(export(tree))

    assert page.texts("leg-item") == ["Images", "Archives", "Other"]
    assert "background:#85b7eb" in html


def test_no_legend_when_there_are_no_files():
    html, _page = html_of(GOLDEN_ITEMS[:1])

    assert 'class="legend"' not in html


# ── All writers ──────────────────────────────────────────────────

@pytest.mark.parametrize("fmt", sorted(exporter.WRITERS))
def test_every_writer_accepts_an_empty_export(fmt):
    assert render(exporter.WRITERS[fmt], [])


@pytest.mark.parametrize("fmt", sorted(exporter.WRITERS))
def test_every_writer_reports_progress_in_steps_and_finishes_at_the_total(fmt):
    items = [row(0, "folder", "drive", "", 0)] + [
        row(1, "file", f"f{n}.txt", f"f{n}.txt", 1) for n in range(2499)
    ]
    calls = []

    render(exporter.WRITERS[fmt], items, progress=calls.append)

    assert calls == [1000, 2000, 2500]


@pytest.mark.parametrize("fmt", sorted(exporter.WRITERS))
def test_every_writer_works_without_a_progress_callback(fmt):
    assert render(exporter.WRITERS[fmt], GOLDEN_ITEMS, progress=None)


@pytest.mark.parametrize("fmt", sorted(exporter.WRITERS))
def test_every_writer_formats_dates_with_the_given_pattern(fmt):
    out = render(exporter.WRITERS[fmt], export(make_tree("a.txt")), date_pattern="%m/%d/%Y")

    assert "03/05/2024" in out
    assert DATE not in out


def test_txt_writer_keeps_unicode_and_punctuation_names():
    names = ["naïve ☃ 日本語.txt", "a & b.txt", "it's #1 [x] {y}.txt", "say \"hi\".txt"]
    items = [row(0, "folder", "drive", "", 0)] + [row(1, "file", n, f"f{i}", 1) for i, n in enumerate(names)]
    out = render(exporter.write_txt, items)

    assert all(name in out for name in names)


def test_markdown_writer_keeps_unicode_and_escapes_punctuation_names():
    names = ["naïve ☃ 日本語.txt", "a & b.txt", "it's #1 [x] {y}.txt", "say \"hi\".txt"]
    items = [row(0, "folder", "drive", "", 0)] + [row(1, "file", n, f"f{i}", 1) for i, n in enumerate(names)]
    out = render(exporter.write_md_list, items)

    assert "naïve ☃ 日本語.txt" in out
    assert "a \\& b.txt" in out
    assert "it's \\#1 \\[x\\] {y}.txt" in out
    assert "say \"hi\".txt" in out


def test_html_keeps_unicode_and_punctuation_names():
    names = ["naïve ☃ 日本語.txt", "a & b.txt", "it's #1 [x] {y}.txt", "say \"hi\".txt"]
    items = [row(0, "folder", "drive", "", 0)] + [row(1, "file", n, f"f{i}", 1) for i, n in enumerate(names)]
    _html, page = html_of(items)

    assert page.texts("fn") == names


def test_scanned_drive_exports_to_every_format(tmp_path):
    drive = tmp_path / "drive"
    for rel in ("top.txt", "keep/a.jpg", "skip_me/x.txt", "name_only/y.txt", "keep/deep/b.zip"):
        target = drive / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * 5)
    tree = scanner.scan_path(str(drive))["tree"]
    states = {str(drive / "skip_me"): "skip", str(drive / "name_only"): "name"}
    notes = {str(drive / "keep"): "keep me"}
    items = list(exporter.iter_export(tree, states, {i["path"] for i in tree if i["type"] == "file"}))

    md = render(exporter.write_md_list, items, folder_notes=notes)
    txt = render(exporter.write_txt, items, folder_notes=notes)
    data = json.loads(render(exporter.write_json, items, folder_notes=notes))
    _html, page = html_of(items, folder_notes=notes)

    for text in (md, txt):
        assert "a.jpg" in text and "b.zip" in text and "x.txt" not in text and "y.txt" not in text
    assert [f["name"] for folder in data["folders"] for f in folder["files"]] == ["top.txt", "a.jpg", "b.zip"]
    assert sorted(page.texts("fn")) == ["a.jpg", "b.zip", "top.txt"]
    assert page.texts("fnote-text") == ["keep me"]
    assert page.balanced


def test_dates_that_cannot_be_formatted_are_left_blank():
    assert exporter.fmt_date(1e18) == ""
    assert exporter.fmt_date(-1e18) == ""
    assert exporter.fmt_date(float("inf")) == ""


def test_a_zero_filetime_date_is_written_even_where_the_platform_refuses_it(monkeypatch):
    class NoNegativeTimestamps(exporter.datetime):
        @classmethod
        def fromtimestamp(cls, ts, tz=None):
            raise OSError(22, "Invalid argument")

    monkeypatch.setattr(exporter, "datetime", NoNegativeTimestamps)

    assert exporter.fmt_date(-11644473600) == "01. 01. 1601"


@pytest.mark.parametrize("fmt", sorted(exporter.WRITERS))
def test_every_writer_survives_an_unformattable_date(fmt):
    items = [row(0, "folder", "drive", "", 10, mtime=1e18), row(1, "file", "f.txt", "f.txt", 10, mtime=-1e18)]

    assert "f.txt" in render(exporter.WRITERS[fmt], items)
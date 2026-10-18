import io
import json
import os
from datetime import datetime
from html.parser import HTMLParser

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


def export(tree, states=None, files=None, exts=None):
    chosen = all_files(tree) if files is None else files
    return list(exporter.iter_export(tree, states or {}, chosen, exts))


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


def test_no_extension_filter_keeps_every_file():
    assert len(export(EXT_TREE, exts=None)) == len(EXT_TREE)


def test_extension_filter_is_case_insensitive_on_the_file_name():
    got = labels(export(EXT_TREE, exts={"jpg"}))

    assert "photo.JPG" in got and "sub/pic.jpg" in got
    assert "song.mp3" not in got and "readme.md" not in got
    assert ".gitignore" not in got and "x.tar.gz" not in got


def test_extensionless_files_always_pass_the_extension_filter():
    got = labels(export(EXT_TREE, exts={"jpg"}))

    assert "notes" in got
    assert "archive." in got


def test_empty_extension_set_keeps_only_extensionless_files_and_all_folders():
    got = labels(export(EXT_TREE, exts=set()))

    assert got == ["drive/", "notes", "archive.", "sub/"]


def test_extension_filter_never_hides_folders():
    got = labels(export(EXT_TREE, exts={"zzz"}))

    assert "sub/" in got


def test_extension_filter_and_selection_both_apply():
    chosen = all_files(EXT_TREE) - {path_of("photo.JPG")}
    got = labels(export(EXT_TREE, files=chosen, exts={"jpg"}))

    assert "photo.JPG" not in got
    assert "sub/pic.jpg" in got


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


# ── Markdown ─────────────────────────────────────────────────────

def test_markdown_golden_output():
    out = render(exporter.write_md, GOLDEN_ITEMS, folder_notes=GOLDEN_NOTES)

    assert out == "\n".join([
        "# MY USB (E:) — file list",
        "",
        "**Date:** 2024-03-05 12:00  ",
        "**Path:** `E:\\`  ",
        "**Files:** 2 · **Total:** 2.0 KB",
        "",
        "---",
        "",
        "",
        "## drive",
        "",
        f"    - z.txt · 10 B · {DATE}",
        "",
        "### a (holiday pics)",
        "",
        f"        - one.txt · 2.0 KB · {DATE}",
        "        - **deep/ *(contents omitted)***",
    ])


def test_markdown_title_without_a_volume_label():
    out = render(exporter.write_md, [], {**META, "volume_label": ""})

    assert out.startswith("# E: — file list")


def test_markdown_deeper_folder_with_a_note_is_a_bullet():
    items = [row(0, "folder", "drive", "", 0), row(2, "folder", "b", "a/b", 0)]
    out = render(exporter.write_md, items, folder_notes={path_of("a/b"): "n"})

    assert out.endswith("\n        - **b/** (n)")


def test_markdown_omits_size_and_date_when_asked_or_empty():
    items = [
        row(0, "folder", "drive", "", 0),
        row(1, "file", "full.txt", "full.txt", 10),
        row(1, "file", "empty.txt", "empty.txt", 0),
        row(1, "file", "undated.txt", "undated.txt", 10, mtime=0),
    ]
    out = render(exporter.write_md, items)

    assert f"    - full.txt · 10 B · {DATE}" in out
    assert f"    - empty.txt · {DATE}" in out
    assert "    - undated.txt · 10 B" in out and "undated.txt · 10 B ·" not in out

    bare = render(exporter.write_md, items, include_size=False, include_date=False)
    assert "    - full.txt" in bare
    assert " B" not in bare.split("---")[1]
    assert DATE not in bare


def test_markdown_writes_names_verbatim():
    items = [row(0, "folder", "drive", "", 0), row(1, "file", "*star* #hash `tick`.txt", "x", 1)]

    assert "    - *star* #hash `tick`.txt" in render(exporter.write_md, items)


# ── TXT ──────────────────────────────────────────────────────────

def test_txt_golden_output():
    out = render(exporter.write_txt, GOLDEN_ITEMS, folder_notes=GOLDEN_NOTES)

    assert out == "\n".join([
        "=" * 60,
        "  MY USB (E:) — FILE LIST",
        "  2024-03-05 12:00  |  E:\\",
        "  2 files  |  2.0 KB",
        "=" * 60,
        "",
        "",
        "[drive/]",
        f"    z.txt  {'10 B':<10}  {DATE}",
        "",
        "  [a/]",
        "    > holiday pics",
        f"      one.txt  {'2.0 KB':<10}  {DATE}",
        "",
        "    [deep/  [name only]]",
    ])


def test_txt_title_without_a_volume_label():
    out = render(exporter.write_txt, [], {**META, "volume_label": ""})

    assert out.splitlines()[1] == "  E: — FILE LIST"


def test_txt_omits_size_and_date_when_asked():
    out = render(exporter.write_txt, GOLDEN_ITEMS, include_size=False, include_date=False)

    assert "z.txt" in out
    assert "10 B" not in out and DATE not in out


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
    assert page.texts("disk-date") == ["scanned <s>t"]
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
    assert page.texts("disk-date") == ["scanned 2024-03-05 12:00"]
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


def test_root_folder_is_not_rendered_and_folders_start_collapsed():
    tree = make_tree("a/", "a/x.bin", "b/", "b/y.bin")
    html, page = html_of(export(tree))

    assert page.texts("fname") == ["a/", "b/"]
    assert page.count("details") == 2
    assert not any("open" in a for t, a in page.tags if t == "details")
    assert "drive" not in page.texts("fname")


def test_folder_meta_shows_size_and_recursive_file_count():
    tree = make_tree("a/", "a/x.bin", "a/b/", "a/b/y.bin", "a/b/z.bin", "empty/")
    html, _page = html_of(export(tree))

    assert '<span class="fmeta">30 B · <b>3 files</b></span>' in html
    assert '<span class="fmeta">20 B · <b>2 files</b></span>' in html
    assert '<span class="fmeta"></span>' in html


def test_folder_meta_without_sizes():
    tree = make_tree("a/", "a/x.bin", "a/y.bin")
    html, _page = html_of(export(tree), include_size=False)

    assert '<span class="fmeta"><b>2 files</b></span>' in html


def test_name_only_folder_has_no_contents_and_is_marked():
    tree = make_tree("z.txt", "a/", "a/x.bin", "a/y.bin")
    items = export(tree, {path_of("a"): "name"})
    html, page = html_of(items, {**META, "name_only_count": 1})

    assert page.count("details") == 0
    assert page.texts("fname-muted") == ["a/"]
    assert page.texts("fmeta") == ["name only · 20 B"]
    assert page.texts("fn") == ["z.txt"]
    assert page.balanced


def test_file_columns_respect_the_toggles_and_empty_values():
    tree = make_tree("a.txt")
    html, _page = html_of(export(tree))
    assert f'<span class="fsz">10 B</span><span class="fdt">{DATE}</span>' in html

    html, _page = html_of(export(tree), include_size=False, include_date=False)
    assert '<span class="fsz"></span><span class="fdt"></span>' in html

    empty = [row(0, "folder", "drive", "", 0), row(1, "file", "e.txt", "e.txt", 0, mtime=0)]
    html, _page = html_of(empty)
    assert '<span class="fsz"></span><span class="fdt"></span>' in html


def test_folder_note_is_rendered_as_icon_plus_text():
    tree = make_tree("a/", "a/x.bin")
    html, page = html_of(export(tree), folder_notes={path_of("a"): "holiday pics"})

    assert page.texts("fnote-text") == ["holiday pics"]
    assert page.attr("fnote-inline", "title") == ["holiday pics"]
    assert page.count("svg") == 1


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


@pytest.mark.parametrize("fmt", ["MD", "TXT"])
def test_text_writers_keep_unicode_and_punctuation_names(fmt):
    names = ["naïve ☃ 日本語.txt", "a & b.txt", "it's #1 [x] {y}.txt", "say \"hi\".txt"]
    items = [row(0, "folder", "drive", "", 0)] + [row(1, "file", n, f"f{i}", 1) for i, n in enumerate(names)]
    out = render(exporter.WRITERS[fmt], items)

    assert all(name in out for name in names)


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

    md = render(exporter.write_md, items, folder_notes=notes)
    txt = render(exporter.write_txt, items, folder_notes=notes)
    data = json.loads(render(exporter.write_json, items, folder_notes=notes))
    _html, page = html_of(items, folder_notes=notes)

    for text in (md, txt):
        assert "a.jpg" in text and "b.zip" in text and "x.txt" not in text and "y.txt" not in text
    assert [f["name"] for folder in data["folders"] for f in folder["files"]] == ["top.txt", "a.jpg", "b.zip"]
    assert sorted(page.texts("fn")) == ["a.jpg", "b.zip", "top.txt"]
    assert page.texts("fnote-text") == ["keep me"]
    assert page.balanced
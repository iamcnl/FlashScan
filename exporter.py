"""
exporter.py — export format writers

No UI dependencies. iter_export() selects what goes into the export; each
write_* function streams those items into an open text file and reports
progress, so memory and UI responsiveness do not depend on the file count.

Shares design tokens with the GUI via export_templates/export.css.
"""

from __future__ import annotations

import html as _html
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────

_KB = 1_024
_MB = 1_048_576          # 1_024 ** 2
_GB = 1_073_741_824      # 1_024 ** 3

def fmt_size(b: int) -> str:
    if b < _KB: return f"{b} B"
    if b < _MB: return f"{b/_KB:.1f} KB"
    if b < _GB: return f"{b/_MB:.1f} MB"
    return f"{b/_GB:.2f} GB"


DEFAULT_DATE_PATTERN = "%d. %m. %Y"
_DATE_PATTERN = re.compile(r"(?:%[dmY]|[^%\x00-\x1f]){3,32}")


def normalize_date_pattern(pattern) -> str:
    """Returns pattern if it is a plain day/month/year layout, else the default."""
    if (isinstance(pattern, str) and _DATE_PATTERN.fullmatch(pattern)
            and all(pattern.count(d) == 1 for d in ("%d", "%m", "%Y"))):
        return pattern
    return DEFAULT_DATE_PATTERN


def _moment(ts: float) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(ts)
    except (ValueError, OverflowError, OSError):
        # Windows refuses dates before 1970, but a zero FILETIME (year 1601) is common; others are garbage
        try:
            return datetime(1970, 1, 1) + timedelta(seconds=ts)
        except (ValueError, OverflowError):
            return None


def fmt_date(ts: float, pattern: str = DEFAULT_DATE_PATTERN) -> str:
    moment = _moment(ts)
    return moment.strftime(pattern) if moment else ""


def fmt_iso(ts: float) -> str:
    moment = _moment(ts)
    if moment is None:
        return ""
    try:
        moment = moment.astimezone()
    except (ValueError, OverflowError, OSError):
        pass
    return moment.isoformat(timespec="seconds")


def _noun(n: int, word: str) -> str:
    return word if n == 1 else word + "s"


def _esc(s: str) -> str:
    """Escapes HTML special characters for safe insertion into attributes and content."""
    return _html.escape(str(s), quote=True)


_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>#|~&])")
_MD_LEADING_MARKER = re.compile(r"^(?:([-+])|(\d+)([.)]))")
_LINE_BREAKS = re.compile(r"\s*[\r\n]+\s*")


def _md_esc(s: str) -> str:
    """Escapes Markdown syntax so text renders literally; line breaks become spaces."""
    text = _MD_SPECIAL.sub(r"\\\1", _LINE_BREAKS.sub(" ", str(s)))
    return _MD_LEADING_MARKER.sub(
        lambda m: "\\" + m.group(1) if m.group(1) else m.group(2) + "\\" + m.group(3), text
    )


def _md_code(s: str) -> str:
    """Wraps text in a code span whose fence is longer than any backtick run inside it."""
    text = _LINE_BREAKS.sub(" ", str(s))
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


# ── Export iterator ───────────────────────────────────────────────

PROGRESS_EVERY = 1000


def _folder_totals(items: list) -> tuple[dict[str, int], dict[str, int]]:
    """File counts and byte totals per folder path, counting only the exported files."""
    counts: dict[str, int] = {}
    sizes: dict[str, int] = {}
    stack: list[tuple[int, str]] = []
    for lvl, typ, _, fpath, fsize, *_ in items:
        while stack and stack[-1][0] >= lvl:
            stack.pop()
        if typ == "folder":
            counts[fpath] = 0
            sizes[fpath] = 0
            stack.append((lvl, fpath))
        else:
            for _, fp in stack:
                counts[fp] += 1
                sizes[fp] += fsize
    return counts, sizes


def _folder_members(items: list) -> tuple[dict[str, str | None], dict[str, list[int]]]:
    """Each folder's parent path and the indexes of the files directly inside it, found by tree level."""
    parents: dict[str, str | None] = {}
    members: dict[str, list[int]] = {}
    stack: list[tuple[int, str]] = []
    for i, (lvl, typ, _, fpath, *_) in enumerate(items):
        while stack and stack[-1][0] >= lvl:
            stack.pop()
        if typ == "folder":
            parents[fpath] = stack[-1][1] if stack else None
            members[fpath] = []
            stack.append((lvl, fpath))
        elif stack:
            members[stack[-1][1]].append(i)
    return parents, members


def _scope_text(scope: dict) -> str:
    hidden, system = scope.get("include_hidden"), scope.get("include_system")
    if hidden == system:
        visibility = f"hidden and system items {'included' if hidden else 'excluded'}"
    else:
        visibility = (
            f"hidden items {'included' if hidden else 'excluded'}, "
            f"system items {'included' if system else 'excluded'}"
        )
    parts = ([f"depth {scope['depth']}"] if scope.get("depth") else []) + [visibility]
    counts = [
        (scope.get("excluded_folders", 0), "folder", "excluded"),
        (scope.get("names_only_folders", 0), "folder", "names only"),
        (scope.get("deselected_files", 0), "file", "deselected"),
        (len(scope.get("excluded_extensions", ())), "extension", "excluded"),
        (scope.get("unreadable", 0), "item", "unreadable"),
        (scope.get("beyond_depth", 0), "folder", "beyond the depth limit"),
        (scope.get("links_skipped", 0), "link", "skipped"),
    ]
    parts += [f"{n} {_noun(n, noun)} {what}" for n, noun, what in counts if n]
    return " · ".join(parts)


class _Lines:
    """Streams lines joined by "\n" with no trailing newline, like "\n".join(lines)."""

    def __init__(self, out):
        self._out = out
        self._first = True

    def add(self, line: str) -> None:
        self._out.write(line if self._first else "\n" + line)
        self._first = False


def iter_export(tree: list, folder_states: dict, selected_files: set,
                 hidden_exts: set | None = None):
    """
    Walks tree and yields only items that should appear in the export.
    Respects folder_states, selected_files and hidden_exts (extensions unticked in the
    sidebar; any other extension, listed there or not, and files without one, stay in).

    tree is the scanner's flat DFS list: a folder is followed by its contents,
    one level deeper. A skip or name folder hides everything below it, found
    through lvl rather than path strings, so drive roots like "E:\\" need no
    special case. State.exportStats in ui/js/state.js applies the same rule;
    tests/selection_cases.json keeps the two in step.

    Yields: (lvl, type, name, path, size, mtime, folder_state)
    """
    hides: dict[int, bool] = {}   # hides[lvl]: the latest folder at that level, or an ancestor, hides its contents
    for item in tree:
        lvl, typ, name, fpath, size, mtime = (
            item["lvl"], item["type"], item["name"],
            item["path"], item["size"], item["mtime"],
        )
        hidden = hides.get(lvl - 1, False)

        if typ == "folder":
            state = folder_states.get(fpath, "full")
            hides[lvl] = hidden or state in ("skip", "name")
            if state == "skip" or hidden:
                continue
            yield (lvl, typ, name, fpath, size, mtime, state)

        elif typ == "file":
            if hidden or fpath not in selected_files:
                continue
            if hidden_exts and "." in name and name.rsplit(".", 1)[-1].lower() in hidden_exts:
                continue
            yield (lvl, typ, name, fpath, size, mtime, "full")


# ── Markdown ──────────────────────────────────────────────────────

def _folder_info(state: str, files: int, shown_bytes: int, include_size: bool) -> str:
    if state == "name":
        parts = ["names only"]
    else:
        parts = [f"{files} {_noun(files, 'file')}"] if files else ["empty"]
    if include_size and shown_bytes:
        parts.append(fmt_size(shown_bytes))
    return " · ".join(parts)


def _md_header(meta) -> list[str]:
    label = meta.get('volume_label', '')
    title = _md_esc(f"{label} ({meta['disk_name']})" if label else meta['disk_name'])
    files_n, folders_n = meta['file_count'], meta['folder_count']
    contents = [f"{files_n} {_noun(files_n, 'file')}", f"{folders_n} {_noun(folders_n, 'folder')}", meta['total_size']]
    if meta.get('name_only_count'):
        contents.append(f"{meta['name_only_count']} names only")
    lines = [
        f"# {title} — file list",
        "",
        f"- **Exported:** {meta['timestamp']}",
        f"- **Path:** {_md_code(meta['path'])}",
        f"- **Contents:** {' · '.join(contents)}",
    ]
    if meta.get("scope"):
        lines.append(f"- **Scope:** {_scope_text(meta['scope'])}")
    return lines + ["", "---"]


def _md_file_parts(name: str, size: int, mtime: int, include_size: bool, include_date: bool, date_pattern: str) -> list[str]:
    parts = [name]
    if include_size:
        parts.append(fmt_size(size))
    date = fmt_date(mtime, date_pattern) if (include_date and mtime) else ""
    if date:
        parts.append(date)
    return parts


def write_md_list(out, items: list, meta, *, include_size=True, include_date=True,
                  date_pattern=DEFAULT_DATE_PATTERN, folder_notes=None, progress=None) -> None:
    folder_notes = folder_notes or {}
    folder_files, folder_bytes = _folder_totals(items)
    emit = _Lines(out).add
    blank_pending = False

    def put(line: str) -> None:
        nonlocal blank_pending
        if blank_pending:
            emit("")
            blank_pending = False
        emit(line)

    def blank() -> None:
        nonlocal blank_pending
        blank_pending = True

    for line in _md_header(meta):
        emit(line)
    blank()

    for n, (lvl, typ, name, fpath, size, mtime, state) in enumerate(items, 1):
        name = _md_esc(name)
        if typ == "folder":
            if lvl > 0:
                note = _md_esc(folder_notes.get(fpath, ""))
                shown_bytes = size if state == "name" else folder_bytes.get(fpath, 0)
                info = _folder_info(state, folder_files.get(fpath, 0), shown_bytes, include_size)
                if lvl == 1:
                    blank()
                    put(f"## {name}")
                    blank()
                    if note:
                        put(f"> {note}")
                        blank()
                    put(f"*{info}*")
                    blank()
                else:
                    tail = f" — *{note}*" if note else ""
                    put(f"{'    ' * (lvl - 2)}- **{name}/** · {info}{tail}")
        else:
            parts = _md_file_parts(name, size, mtime, include_size, include_date, date_pattern)
            put(f"{'    ' * max(lvl - 2, 0)}- {' · '.join(parts)}")
        if progress and n % PROGRESS_EVERY == 0:
            progress(n)
    out.write("\n")
    if progress:
        progress(len(items))


def _md_table_head(include_size: bool, include_date: bool) -> list[str]:
    head, rule = ["Name"], ["---"]
    if include_size:
        head.append("Size")
        rule.append("--:")
    if include_date:
        head.append("Modified")
        rule.append("---")
    return ["| " + " | ".join(head) + " |", "|" + "|".join(rule) + "|"]


def write_md_toggles(out, items: list, meta, *, include_size=True, include_date=True,
                     date_pattern=DEFAULT_DATE_PATTERN, folder_notes=None, progress=None) -> None:
    folder_notes = folder_notes or {}
    folder_files, folder_bytes = _folder_totals(items)
    table_head = _md_table_head(include_size, include_date)
    emit = _Lines(out).add
    blank_pending = False
    in_table = False
    open_levels: list[int] = []

    def put(line: str) -> None:
        nonlocal blank_pending
        if blank_pending:
            emit("")
            blank_pending = False
        emit(line)

    def blank() -> None:
        nonlocal blank_pending
        blank_pending = True

    def close_toggles(from_level: int) -> None:
        nonlocal in_table
        in_table = False
        while open_levels and open_levels[-1] >= from_level:
            open_levels.pop()
            blank()
            put("</details>")
            blank()

    for line in _md_header(meta):
        emit(line)
    blank()

    for n, (lvl, typ, name, fpath, size, mtime, state) in enumerate(items, 1):
        if typ == "folder":
            if lvl > 0:
                close_toggles(lvl)
                note = _md_esc(folder_notes.get(fpath, ""))
                shown_bytes = size if state == "name" else folder_bytes.get(fpath, 0)
                info = _folder_info(state, folder_files.get(fpath, 0), shown_bytes, include_size)
                has_children = n < len(items) and items[n][0] > lvl
                if state == "name" or not has_children:
                    tail = f" — *{note}*" if note else ""
                    blank()
                    put(f"**{_md_esc(name)}/** · {info}{tail}")
                    blank()
                else:
                    blank()
                    put("<details open>" if lvl == 1 else "<details>")
                    put(f"<summary><b>{_esc(name)}/</b> · {info}</summary>")
                    blank()
                    if note:
                        put(f"> {note}")
                        blank()
                    open_levels.append(lvl)
        else:
            if open_levels and open_levels[-1] >= lvl:
                close_toggles(lvl)
            if not in_table:
                blank()
                for line in table_head:
                    put(line)
                in_table = True
            cells = [_md_esc(name)]
            if include_size:
                cells.append(fmt_size(size))
            if include_date:
                cells.append(fmt_date(mtime, date_pattern) if mtime else "")
            put("| " + " | ".join(cells) + " |")
        if progress and n % PROGRESS_EVERY == 0:
            progress(n)
    close_toggles(0)
    out.write("\n")
    if progress:
        progress(len(items))


def write_md(out, items: list, meta, *, md_toggles=True, **options) -> None:
    writer = write_md_toggles if md_toggles else write_md_list
    writer(out, items, meta, **options)


# ── TXT ──────────────────────────────────────────────────────────

_TXT_NAME_COLUMN_MAX = 56


def _one_line(text: str) -> str:
    return _LINE_BREAKS.sub(" ", str(text))


def write_txt(out, items: list, meta, *, include_size=True, include_date=True,
              date_pattern=DEFAULT_DATE_PATTERN, folder_notes=None, progress=None) -> None:
    folder_notes = folder_notes or {}
    folder_files, folder_bytes = _folder_totals(items)
    file_rows = [(lvl, _one_line(name), fmt_size(size)) for lvl, typ, name, _, size, *_ in items if typ == "file"]
    size_width = max((len(size) for _, _, size in file_rows), default=0)
    name_width = min(
        max((2 * (lvl - 1) + len(name) for lvl, name, _ in file_rows), default=0), _TXT_NAME_COLUMN_MAX
    )
    label = meta.get('volume_label', '')
    title = f"{label} ({meta['disk_name']})" if label else meta['disk_name']
    emit = _Lines(out).add
    blank_pending = False
    last_folder_lvl: int | None = None

    def put(line: str) -> None:
        nonlocal blank_pending
        if blank_pending:
            emit("")
            blank_pending = False
        emit(line)

    files_n, folders_n = meta['file_count'], meta['folder_count']
    contents = [f"{files_n} {_noun(files_n, 'file')}", f"{folders_n} {_noun(folders_n, 'folder')}", meta['total_size']]
    if meta.get('name_only_count'):
        contents.append(f"{meta['name_only_count']} names only")
    bar = "=" * 60
    header = [
        bar,
        f"  {title} — file list",
        f"  Exported {meta['timestamp']}  |  {meta['path']}",
        f"  {'  |  '.join(contents)}",
    ]
    if meta.get("scope"):
        header.append(f"  Scope: {_scope_text(meta['scope'])}")
    for line in header + [bar]:
        emit(line)
    blank_pending = True

    for n, (lvl, typ, name, fpath, size, mtime, state) in enumerate(items, 1):
        name = _one_line(name)
        indent = "  " * max(lvl - 1, 0)
        if typ == "folder":
            if lvl > 0:
                shown_bytes = size if state == "name" else folder_bytes.get(fpath, 0)
                info = _folder_info(state, folder_files.get(fpath, 0), shown_bytes, include_size)
                if last_folder_lvl is None or lvl <= last_folder_lvl:
                    blank_pending = True
                put(f"{indent}[{name}/]  {info}")
                note = _one_line(folder_notes.get(fpath, ""))
                if note:
                    put(f"{indent}  > {note}")
                last_folder_lvl = lvl
        else:
            cells = []
            if include_size:
                cells.append(fmt_size(size).rjust(size_width))
            date = fmt_date(mtime, date_pattern) if (include_date and mtime) else ""
            if date:
                cells.append(date)
            line = f"{indent}{name}"
            if cells:
                line = f"{line:<{name_width}}  {'  '.join(cells)}"
            put(line)
            last_folder_lvl = None
        if progress and n % PROGRESS_EVERY == 0:
            progress(n)
    out.write("\n")
    if progress:
        progress(len(items))


# ── JSON ─────────────────────────────────────────────────────────

def _json_meta(meta: dict, items: list) -> dict:
    out = {"format_version": 1, "generated_by": meta.get("generated_by", "flashscan")}
    for key in ("app_version", "exported_at"):
        if key in meta:
            out[key] = meta[key]
    out.update(
        disk_name=meta["disk_name"],
        volume_label=meta.get("volume_label", ""),
        path=meta["path"],
        file_count=meta["file_count"],
        folder_count=meta["folder_count"],
        total_size_bytes=sum(item[4] for item in items if item[1] == "file"),
    )
    if "scope" in meta:
        out["scope"] = meta["scope"]
    return out


def write_json(out, items: list, meta, *, include_size=True, include_date=True,
               date_pattern=DEFAULT_DATE_PATTERN, folder_notes=None, progress=None) -> None:
    """Streams the same text as json.dumps({"meta": ..., "folders": [...]}, indent=2) plus a final newline."""
    folder_notes = folder_notes or {}
    folder_files, folder_bytes = _folder_totals(items)
    parents, members = _folder_members(items)
    wrote_folder = False

    def write_folder(entry: dict) -> None:
        nonlocal wrote_folder
        text = json.dumps(entry, ensure_ascii=False, indent=2).replace("\n", "\n    ")
        out.write(("," if wrote_folder else "") + "\n    " + text)
        wrote_folder = True

    meta_text = json.dumps(_json_meta(meta, items), ensure_ascii=False, indent=2).replace("\n", "\n  ")
    out.write('{\n  "meta": ' + meta_text + ',\n  "folders": [')

    done = 0

    def tick() -> None:
        nonlocal done
        done += 1
        if progress and done % PROGRESS_EVERY == 0:
            progress(done)

    for lvl, typ, name, fpath, size, mtime, state in items:
        if typ != "folder":
            continue
        tick()
        names_only = state == "name"
        entry: dict = {
            "name":   name,
            "path":   fpath,
            "parent": parents[fpath],
            "level":  lvl,
            "mode":   "names_only" if names_only else "full",
        }
        if include_size:
            entry["size_bytes"] = size if names_only else folder_bytes.get(fpath, 0)
        if not names_only:
            entry["file_count"] = folder_files.get(fpath, 0)
        if include_date and (modified := fmt_iso(mtime)):
            entry["modified"] = modified
        note = folder_notes.get(fpath, "")
        if note:
            entry["note"] = note
        files = []
        for index in members[fpath]:
            _, _, file_name, file_path, file_size, file_mtime, _ = items[index]
            file_entry: dict = {"name": file_name, "path": file_path}
            if include_size:
                file_entry["size_bytes"] = file_size
            if include_date and (file_modified := fmt_iso(file_mtime)):
                file_entry["modified"] = file_modified
            files.append(file_entry)
            tick()
        entry["files"] = files
        write_folder(entry)

    out.write("\n  ]\n}\n" if wrote_folder else "]\n}\n")
    if progress:
        progress(len(items))


# ── Extension → visual category mapping ───────────────────────────

_EXT_CATEGORIES: dict[str, tuple[str, str]] = {}

def _build_ext_map() -> None:
    groups = [
        ("Images",       "#85b7eb", ['jpg','jpeg','png','gif','bmp','webp','tiff','tif','svg','ico','heic','heif','raw','cr2','nef','arw','dng','psd','ai','eps','avif','jxl']),
        ("Video",        "#AFA9EC", ['mp4','mkv','avi','mov','wmv','flv','webm','m4v','mpg','mpeg','3gp','ts','mts','m2ts','vob','ogv','divx','rmvb','asf','f4v']),
        ("Audio",        "#f09595", ['mp3','wav','flac','aac','ogg','m4a','wma','opus','aiff','ape','mid','midi','amr','ac3','dts','ra','mka','tta','wv']),
        ("Documents",    "#97c459", ['pdf','doc','docx','odt','rtf','txt','md','tex','pages','wpd','wps','epub','mobi','azw','azw3','djvu','xps','oxps','fb2',
                                   'xls','xlsx','ods','csv','tsv','numbers','xlsm','xlsb','xltx','xltm',
                                   'ppt','pptx','odp','key','pps','ppsx','pptm']),
        ("Archives",     "#EF9F27", ['zip','rar','7z','tar','gz','bz2','xz','iso','dmg','pkg','deb','rpm','cab','lzh','lz4','zst','br','tgz','tbz2']),
        ("Code & Data",  "#5DCAA5", ['py','js','ts','jsx','tsx','html','htm','css','scss','sass','php','java','c','cpp','h','cs','go','rs','rb','swift','kt','dart','lua','r','sh','bat','ps1','sql','xml','json','yaml','yml','toml','ini','cfg','conf','env',
                                   'db','sqlite','sqlite3','mdb','accdb','dbf','frm','ibd','mdf','ldf','bak',
                                   'parquet','hdf5','h5','mat','npy','npz','pkl','feather','arrow','nc','fits','zarr',
                                   'ttf','otf','woff','woff2','eot','fon']),
        ("Other",        "#c8c5bc", []),
    ]
    for label, color, exts in groups:
        for e in exts:
            _EXT_CATEGORIES[e] = (label, color)
    _EXT_CATEGORIES["__fallback__"] = ("Other", "#c8c5bc")

_build_ext_map()


def _ext_category(ext: str) -> tuple[str, str]:
    return _EXT_CATEGORIES.get(ext.lower(), _EXT_CATEGORIES["__fallback__"])


# ── Note icon SVG (same chat bubble as tree view) ─────────────────

_NOTE_ICON_SVG = (
    '<svg class="fnote-icon" width="11" height="11" viewBox="0 0 24 24" '
    'fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'
    '</svg>'
)


# ── HTML ─────────────────────────────────────────────────────────

def write_html(out, items: list, meta, *, include_size=True, include_date=True,
               date_pattern=DEFAULT_DATE_PATTERN, folder_notes=None, progress=None) -> None:
    folder_notes = folder_notes or {}
    css_tokens = _load_export_css()
    emit = _Lines(out).add

    used_cats: dict[str, str] = {}  # label -> color, preserves insertion order

    def dot(ext: str) -> str:
        label, color = _ext_category(ext)
        used_cats[label] = color
        return f'<span class="dot" style="background:{color}"></span>'

    def render_tree(items: list) -> None:
        open_levels: list[int] = []

        folder_file_counts, folder_bytes = _folder_totals(items)

        # Reorder: within each folder's children, folders before files
        def reorder(items: list) -> list:
            if not items:
                return []
            runs = []
            i = 0
            while i < len(items):
                item = items[i]
                item_lvl = item[0]
                i += 1
                children = []
                while i < len(items) and items[i][0] > item_lvl:
                    children.append(items[i])
                    i += 1
                runs.append((item, reorder(children)))

            folder_runs = [(it, ch) for it, ch in runs if it[1] == "folder"]
            file_runs   = [(it, ch) for it, ch in runs if it[1] == "file"]

            result = []
            for it, ch in folder_runs:
                result.append(it)
                result.extend(ch)
            for it, ch in file_runs:
                result.append(it)
                result.extend(ch)
            return result

        items = reorder(items)

        def close_until(target_lvl: int) -> None:
            while open_levels and open_levels[-1] >= target_lvl:
                emit('</div>')
                emit('</details>')
                open_levels.pop()

        i = 0
        while i < len(items):
            if progress and i and i % PROGRESS_EVERY == 0:
                progress(i)
            lvl, typ, name, fpath, size, mtime, state = items[i]

            if typ == "folder":
                if lvl == 0:
                    i += 1
                    continue
                close_until(lvl)
                is_name_only = state == "name"
                shown_bytes = size if is_name_only else folder_bytes.get(fpath, 0)
                sz_html = _esc(fmt_size(shown_bytes)) if (include_size and shown_bytes) else ""
                fc = folder_file_counts.get(fpath, 0)
                if is_name_only:
                    count_html = "names only"
                else:
                    count_html = f"<b>{fc} {_noun(fc, 'file')}</b>" if fc else "empty"
                ename = _esc(name)
                note = folder_notes.get(fpath, "")
                note_html = (
                    f'<span class="fnote-inline" title="{_esc(note)}">'
                    f'{_NOTE_ICON_SVG}'
                    f'<span class="fnote-text">{_esc(note)}</span>'
                    f'</span>'
                ) if note else ""
                size_slot = f'<span class="fsz">{sz_html}</span>' if include_size else ""
                date_slot = '<span class="fdt"></span>' if include_date else ""
                fmeta = (
                    f'<span class="fmeta">{note_html}'
                    f'<span class="fcnt">{count_html}</span>'
                    f'{size_slot}{date_slot}'
                    f'</span>'
                )
                if is_name_only:
                    emit(
                        f'<div class="folder">'
                        f'<div class="fh fh-nameonly">'
                        f'<span class="farr"></span>'
                        f'<span class="fname fname-muted" title="{ename}/">{ename}/</span>'
                        f'{fmeta}'
                        f'</div>'
                        f'</div>'
                    )
                else:
                    open_attr = " open" if lvl == 1 else ""
                    emit(
                        f'<details class="folder"{open_attr}>'
                        f'<summary class="fh">'
                        f'<span class="farr"></span>'
                        f'<span class="fname" title="{ename}/">{ename}/</span>'
                        f'{fmeta}'
                        f'</summary>'
                        f'<div class="fc">'
                    )
                    open_levels.append(lvl)

            elif typ == "file":
                close_until(lvl)
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                sz_str = fmt_size(size) if include_size else ""
                dt_str = _esc(fmt_date(mtime, date_pattern)) if (include_date and mtime) else ""
                ename = _esc(name)
                root_cls = " fi-root" if not open_levels else ""
                size_slot = f'<span class="fsz">{sz_str}</span>' if include_size else ""
                date_slot = f'<span class="fdt">{dt_str}</span>' if include_date else ""
                emit(
                    f'<div class="fi{root_cls}">'
                    f'{dot(ext)}'
                    f'<span class="fn" title="{ename}">{ename}</span>'
                    f'{size_slot}{date_slot}'
                    f'</div>'
                )
            i += 1

        close_until(-1)

    name_only = meta.get("name_only_count", 0)
    name_only_stat = (
        f'<span class="meta-sep">·</span><span class="meta-stat"><span class="meta-n">{name_only}</span> names only</span>'
        if name_only else ""
    )

    label = meta.get('volume_label', '')
    display_name = f"{label}" if label else meta['disk_name']
    display_sub  = meta['disk_name'] if label else ""

    e_display_name = _esc(display_name)
    e_display_sub  = _esc(display_sub)
    e_path         = _esc(meta['path'])
    e_timestamp    = _esc(meta['timestamp'])
    e_total_size   = _esc(meta['total_size'])
    scope_html     = (
        f'\n      <div class="disk-date">{_esc(_scope_text(meta["scope"]))}</div>' if meta.get("scope") else ""
    )
    files_word     = _noun(meta['file_count'], 'file')
    folders_word   = _noun(meta['folder_count'], 'folder')

    out.write(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="generator" content="flashscan">
<title>{e_display_name or _esc(meta['disk_name'])} — {meta['file_count']} {files_word}</title>
<script>{_THEME_JS}</script>
<style>
{css_tokens}
{_EXPORT_CSS}
</style>
</head>
<body>
<div class="page">

  <div class="hdr">
    <div class="hdr-l">
      <div class="disk-name">{e_display_name}</div>
      <div class="disk-path">{e_path}{f' — {e_display_sub}' if display_sub else ''}</div>
      <div class="disk-date">exported {e_timestamp}</div>{scope_html}
    </div>
    <div class="hdr-r">
      <div class="watermark">flashscan</div>
    </div>
  </div>

  <div class="meta-row">
    <span class="meta-stat"><span class="meta-n">{meta['file_count']}</span> {files_word}</span>
    <span class="meta-sep">·</span>
    <span class="meta-stat"><span class="meta-n">{e_total_size}</span></span>
    <span class="meta-sep">·</span>
    <span class="meta-stat"><span class="meta-n">{meta['folder_count']}</span> {folders_word}</span>
    {name_only_stat}
  </div>

  <div class="tree-toolbar">
    <button onclick="document.querySelectorAll('.tree details').forEach(d=>d.open=true)" class="tb-btn">expand all</button>
    <button onclick="document.querySelectorAll('.tree details').forEach(d=>d.open=false)" class="tb-btn">collapse all</button>
    <input id="filter" type="search" class="tb-search" placeholder="filter by name" aria-label="Filter by name">
    <span id="filter-status" class="tb-status" role="status"></span>
    <button id="btn-theme" class="tb-btn tb-btn-theme" onclick="toggleTheme()">\u263e dark</button>
  </div>

  <div class="tree">
""")

    render_tree(items)

    ORDER = ["Images", "Video", "Audio", "Documents", "Archives", "Code & Data", "Other"]
    legend_items = [
        f'<span class="leg-item"><span class="dot" style="background:{used_cats[k]}"></span>{k}</span>'
        for k in ORDER if k in used_cats
    ]
    legend_html = (
        f'<div class="legend">{"".join(legend_items)}</div>'
        if legend_items else ""
    )

    out.write(f"""
  </div>

  {legend_html}

  <div class="footer">
    <span>flashscan</span>
    <span>{meta['file_count']} {files_word} · {e_total_size} · exported {e_timestamp}</span>
  </div>

</div>
</body>
</html>""")
    if progress:
        progress(len(items))


WRITERS = {
    "MD":   write_md,
    "TXT":  write_txt,
    "JSON": write_json,
    "HTML": write_html,
}


def _load_export_css() -> str:
    """Loads tokens.css for inline embedding into the HTML export."""
    try:
        here = Path(__file__).parent
        return (here / "export_templates" / "export.css").read_text(encoding="utf-8")
    except Exception:
        log.warning("Export CSS could not be loaded; the HTML export will be unstyled", exc_info=True)
        return ""


_EXPORT_CSS = """
/* ── Export-specific tokens (light) ── */
:root {
  --ex-bg:       #fafaf8;
  --ex-hover:    #f0ede6;
  --ex-border:   #e4e1d9;
  --ex-border2:  #dddad2;
  --ex-text:     #1a1a18;
  --ex-text2:    #444;
  --ex-muted:    #5c5951;
  --ex-subtle:   #6a675d;
  --ex-faint:    #d8d5cc;
}
[data-theme="dark"] {
  --ex-bg:       #1c1c1c;
  --ex-hover:    #2a2a2a;
  --ex-border:   rgba(255,255,255,.07);
  --ex-border2:  rgba(255,255,255,.05);
  --ex-text:     #d0ccc4;
  --ex-text2:    #bdbdb5;
  --ex-muted:    #a8a8a1;
  --ex-subtle:   #96968f;
  --ex-faint:    rgba(255,255,255,.04);
}

* { box-sizing: border-box; margin: 0; padding: 0; }
[hidden] { display: none !important; }
body { font-family: system-ui, -apple-system, sans-serif; background: var(--ex-bg); color: var(--ex-text); font-size: 13px; transition: background .2s, color .2s; }
.page { max-width: 800px; margin: 0 auto; padding: 48px 28px 80px; }

/* ── Header ── */
.hdr { display: flex; justify-content: space-between; align-items: flex-start;
       padding-bottom: 18px; border-bottom: 1px solid var(--ex-border); margin-bottom: 20px; }
.hdr-l { display: flex; flex-direction: column; gap: 4px; }
.hdr-r { display: flex; flex-direction: column; align-items: flex-end; gap: 10px; }
.disk-name { font-size: 24px; font-weight: 700; letter-spacing: -.03em; color: var(--ex-text); }
.disk-path { font-size: 11.5px; color: var(--ex-muted); font-family: 'Courier New', monospace; margin-top: 1px; }
.disk-date { font-size: 11px; color: var(--ex-subtle); }
.watermark { font-size: 10px; color: var(--ex-subtle); letter-spacing: .06em; }

/* ── Meta row ── */
.meta-row { display: flex; align-items: baseline; gap: 6px; margin-bottom: 24px; flex-wrap: wrap; }
.meta-stat { font-size: 13px; color: var(--ex-muted); }
.meta-n { font-size: 15px; font-weight: 600; color: var(--ex-text2); letter-spacing: -.01em; }
.meta-sep { color: var(--ex-subtle); font-size: 12px; }

/* ── Toolbar ── */
.tree-toolbar { display: flex; gap: 14px; margin-bottom: 12px; }
.tb-btn { font-size: 11.5px; background: none; border: none; padding: 0;
          cursor: pointer; font-family: inherit; color: var(--ex-muted);
          text-decoration: underline; text-underline-offset: 2px;
          text-decoration-color: var(--ex-subtle); }
.tb-btn:hover { color: var(--ex-text2); text-decoration-color: var(--ex-muted); }
.tb-search { font: inherit; font-size: 11.5px; width: 170px; padding: 3px 8px;
             border: 1px solid var(--ex-border); border-radius: 4px;
             background: transparent; color: var(--ex-text); }
.tb-search::placeholder { color: var(--ex-muted); }
.tb-status { font-size: 11px; color: var(--ex-muted); }
.tb-btn-theme { margin-left: auto; text-decoration: none; font-size: 11px; color: var(--ex-muted); }
.tb-btn-theme:hover { color: var(--ex-text2); }

/* ── Tree ── */
.folder { margin-bottom: 1px; }
.fh { display: flex; align-items: baseline; padding: 5px 4px; gap: 6px;
      list-style: none; cursor: pointer; user-select: none; border-radius: 3px; }
.fh:hover { background: var(--ex-hover); }
.fh::-webkit-details-marker { display: none; }
.fh-nameonly { cursor: default; }
.fh-nameonly .fname { color: var(--ex-subtle); font-weight: 400; }
.fh-nameonly .fcnt { font-style: italic; }
.farr { font-size: 14px; color: var(--ex-subtle); flex-shrink: 0; width: 16px;
        display: inline-block; transition: transform .15s; }
.farr::before { content: '▸'; }
details[open] > .fh > .farr { transform: rotate(90deg); }
details:not([open]) > .fh > .farr { transform: rotate(0deg); }
.fname { font-size: 13.5px; font-weight: 600; color: var(--ex-text); flex: 1;
         min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fname-muted { color: var(--ex-subtle); font-weight: 400; }
.fmeta { display: flex; align-items: baseline; flex-shrink: 0; white-space: nowrap; }
.fcnt { font-size: 11px; color: var(--ex-subtle); min-width: 58px; text-align: right; }
.fc { margin-left: 10px; padding-left: 14px; border-left: 1px solid var(--ex-faint); }

/* Files */
.fi { display: flex; align-items: center; padding: 5px 4px; gap: 0; border-radius: 3px; }
.fi-root { padding-left: 22px; }
.fi:hover { background: var(--ex-hover); }
.dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; margin-right: 9px; opacity: .8; }
.fn { font-size: 12.5px; color: var(--ex-text2); font-family: 'Courier New', monospace;
      flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fsz { font-size: 11px; color: var(--ex-subtle); margin-left: 8px; flex-shrink: 0; white-space: nowrap; min-width: 60px; text-align: right; }
.fdt { font-size: 11px; color: var(--ex-muted); margin-left: 6px; flex-shrink: 0; white-space: nowrap; min-width: 68px; text-align: right; }

/* ── Folder note — icon always visible, text on hover ── */
.fnote-inline { display: inline-flex; align-items: center; gap: 3px; margin-right: 10px; color: var(--ex-text2); cursor: default; }
.fnote-icon { flex-shrink: 0; vertical-align: middle; opacity: .55; transition: opacity .15s; }
.fnote-inline:hover .fnote-icon { opacity: 1; }
.fnote-text { font-size: 11px; color: var(--ex-text2); max-width: 0; overflow: hidden;
              white-space: nowrap; opacity: 0; transition: max-width .2s ease, opacity .15s ease; }
.fnote-inline:hover .fnote-text { max-width: 300px; opacity: 1; }

/* ── Narrow screens: name on its own line, details underneath ── */
@media (max-width: 600px) {
  .page { padding: 20px 12px 48px; }
  .hdr { flex-direction: column; gap: 10px; }
  .hdr-r { align-items: flex-start; }
  .disk-name, .disk-path { overflow-wrap: anywhere; }
  .tree-toolbar { flex-wrap: wrap; align-items: center; gap: 4px 16px; }
  .tb-btn { white-space: nowrap; padding: 6px 0; }
  .tb-search { order: 3; flex: 1 1 100%; width: auto; padding: 8px 10px; font-size: 16px; }
  .tb-status { order: 4; }
  .fc { margin-left: 4px; padding-left: 8px; }
  .fh { flex-wrap: wrap; padding: 8px 4px; }
  .fname { flex: 1 1 calc(100% - 24px); white-space: normal; overflow-wrap: anywhere; }
  .fmeta { flex: 1 1 100%; flex-wrap: wrap; padding-left: 22px; white-space: normal; }
  .fcnt, .fsz, .fdt { min-width: 0; margin-left: 0; text-align: left; }
  .fcnt:empty, .fsz:empty, .fdt:empty { display: none; }
  .fcnt:not(:empty) + .fsz:not(:empty)::before { content: '·'; margin: 0 6px; }
  .fnote-inline { margin-right: 8px; }
  .fnote-text { max-width: none; opacity: 1; white-space: normal; }
  .fi { flex-wrap: wrap; align-items: flex-start; padding-top: 6px; padding-bottom: 6px; }
  .dot { margin-top: 6px; }
  .fn { flex: 1 1 calc(100% - 18px); white-space: normal; overflow-wrap: anywhere; }
  .fi .fsz, .fi .fdt { margin-left: 16px; }
  .fi .fsz:not(:empty) + .fdt { margin-left: 0; }
  .fi .fsz:not(:empty) + .fdt:not(:empty)::before { content: '·'; margin: 0 6px; }
}

/* ── Print ── */
@media print {
  .tree-toolbar { display: none; }
  .page { max-width: none; padding: 0; }
  .fh { break-inside: avoid; }
}

/* ── Legend ── */
.legend { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 22px;
          padding-top: 14px; border-top: 1px solid var(--ex-border); }
.leg-item { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--ex-muted); }

/* ── Footer ── */
.footer { margin-top: 28px; padding-top: 14px; border-top: 1px solid var(--ex-border);
          display: flex; justify-content: space-between; font-size: 10.5px;
          color: var(--ex-subtle); }
"""

_THEME_JS = """
(function () {
  var root = document.documentElement;
  var saved = null;
  try { saved = localStorage.getItem('flashscan-theme'); } catch (e) {}
  var prefersDark = !!window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches;
  if (saved ? saved === 'dark' : prefersDark) {
    root.dataset.theme = 'dark';
  }

  function syncThemeButton() {
    document.getElementById('btn-theme').textContent =
      root.dataset.theme === 'dark' ? '\u2600 light' : '\u263e dark';
  }

  window.toggleTheme = function () {
    var next = root.dataset.theme === 'dark' ? 'light' : 'dark';
    if (next === 'dark') root.dataset.theme = 'dark'; else delete root.dataset.theme;
    try { localStorage.setItem('flashscan-theme', next); } catch (e) {}
    syncThemeButton();
  };

  function nameOf(el) {
    return el.querySelector('.fn, .fname').textContent.toLowerCase();
  }

  var savedOpen = null;

  function restoreFolders() {
    if (!savedOpen) return;
    document.querySelectorAll('.tree details').forEach(function (d, i) { d.open = savedOpen[i]; });
    savedOpen = null;
  }

  function filterTree(query) {
    var tree = document.querySelector('.tree');
    var status = document.getElementById('filter-status');
    tree.querySelectorAll('[hidden]').forEach(function (el) { el.hidden = false; });
    if (!query) {
      restoreFolders();
      status.textContent = '';
      return;
    }
    if (!savedOpen) {
      savedOpen = Array.prototype.map.call(tree.querySelectorAll('details'), function (d) { return d.open; });
    }
    var matches = 0;
    tree.querySelectorAll('.fi, div.folder').forEach(function (el) {
      var hit = nameOf(el).indexOf(query) >= 0;
      el.hidden = !hit;
      if (hit) matches++;
    });
    var folders = tree.querySelectorAll('details');
    for (var i = folders.length - 1; i >= 0; i--) {
      var folder = folders[i];
      var selfMatch = nameOf(folder).indexOf(query) >= 0;
      if (selfMatch) matches++;
      if (folder.querySelector('.fi:not([hidden]), .folder:not([hidden])')) {
        folder.open = true;
      } else if (selfMatch) {
        folder.querySelectorAll('[hidden]').forEach(function (el) { el.hidden = false; });
        folder.open = false;
      } else {
        folder.hidden = true;
      }
    }
    status.textContent = matches ? matches + (matches === 1 ? ' match' : ' matches') : 'no matches';
  }

  document.addEventListener('DOMContentLoaded', function () {
    syncThemeButton();
    var box = document.getElementById('filter');
    function applyFilter() { filterTree(box.value.trim().toLowerCase()); }
    box.addEventListener('input', applyFilter);
    box.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && box.value) { box.value = ''; applyFilter(); }
    });
    window.addEventListener('beforeprint', function () {
      document.querySelectorAll('.tree details').forEach(function (d) { d.open = true; });
    });
  });
})();
"""
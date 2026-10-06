"""
exporter.py — export format builders

No UI dependencies. Each function takes the same arguments
and returns a string of file content.

Shares design tokens with the GUI via export_templates/export.css.
"""

from __future__ import annotations

import html as _html
import json
import os
from datetime import datetime
from pathlib import Path


# ── Helpers ──────────────────────────────────────────────────────

_KB = 1_024
_MB = 1_048_576          # 1_024 ** 2
_GB = 1_073_741_824      # 1_024 ** 3

def fmt_size(b: int) -> str:
    if b < _KB: return f"{b} B"
    if b < _MB: return f"{b/_KB:.1f} KB"
    if b < _GB: return f"{b/_MB:.1f} MB"
    return f"{b/_GB:.2f} GB"


def fmt_date(ts: float) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts).strftime("%d. %m. %Y")


def _esc(s: str) -> str:
    """Escapes HTML special characters for safe insertion into attributes and content."""
    return _html.escape(str(s), quote=True)


# ── Export iterator ───────────────────────────────────────────────

def iter_export(tree: list, folder_states: dict, selected_files: set,
                 active_exts: set | None = None):
    """
    Walks tree and yields only items that should appear in the export.
    Respects folder_states, selected_files and active_exts (extension filter).

    Yields: (lvl, type, name, path, size, mtime, folder_state)
    """
    SEP = os.sep

    skip_prefixes = []
    name_prefixes = []
    for fpath, state in folder_states.items():
        prefix = fpath + SEP
        if state == "skip":
            skip_prefixes.append(prefix)
        elif state == "name":
            name_prefixes.append(prefix)

    def ancestor_state(p: str) -> str | None:
        for sp in skip_prefixes:
            if p.startswith(sp):
                return "skip"
        for np in name_prefixes:
            if p.startswith(np):
                return "name"
        return None

    for item in tree:
        lvl, typ, name, fpath, size, mtime = (
            item["lvl"], item["type"], item["name"],
            item["path"], item["size"], item["mtime"],
        )
        state = folder_states.get(fpath, "full")

        if typ == "folder":
            if state == "skip":
                continue
            block = ancestor_state(fpath)
            if block in ("skip", "name"):
                continue
            yield (lvl, typ, name, fpath, size, mtime, state)

        elif typ == "file":
            if fpath not in selected_files:
                continue
            # Extension filter
            if active_exts is not None:
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext and ext not in active_exts:
                    continue
            block = ancestor_state(fpath)
            if block in ("skip", "name"):
                continue
            parent_state = folder_states.get(str(Path(fpath).parent), "full")
            if parent_state in ("skip", "name"):
                continue
            yield (lvl, typ, name, fpath, size, mtime, "full")


# ── Markdown ──────────────────────────────────────────────────────

def build_md(tree, folder_states, selected_files, meta, active_exts=None, *,
             include_size=True, include_date=True, folder_notes=None) -> str:
    folder_notes = folder_notes or {}
    label = meta.get('volume_label', '')
    title = f"{label} ({meta['disk_name']})" if label else meta['disk_name']
    lines = [
        f"# {title} — file list\n",
        f"**Date:** {meta['timestamp']}  ",
        f"**Path:** `{meta['path']}`  ",
        f"**Files:** {meta['file_count']} · **Total:** {meta['total_size']}\n",
        "---\n",
    ]
    for (lvl, typ, name, fpath, size, mtime, state) in iter_export(
            tree, folder_states, selected_files, active_exts):
        indent = "    " * lvl
        if typ == "folder":
            hdr    = "#" * min(lvl + 2, 6)
            suffix = " *(contents omitted)*" if state == "name" else ""
            note        = folder_notes.get(fpath, "")
            note_inline = f" ({note})" if note else ""
            if lvl <= 1:
                lines.append(f"\n{hdr} {name}{suffix}{note_inline}\n")
            else:
                lines.append(f"{indent}- **{name}/{suffix}**{note_inline}")
        else:
            sz = f" · {fmt_size(size)}" if (include_size and size) else ""
            dt = f" · {fmt_date(mtime)}" if (include_date and mtime) else ""
            lines.append(f"{indent}- {name}{sz}{dt}")
    return "\n".join(lines)


# ── TXT ──────────────────────────────────────────────────────────

def build_txt(tree, folder_states, selected_files, meta, active_exts=None, *,
              include_size=True, include_date=True, folder_notes=None) -> str:
    folder_notes = folder_notes or {}
    label = meta.get('volume_label', '')
    title = f"{label} ({meta['disk_name']})" if label else meta['disk_name']
    lines = [
        "=" * 60,
        f"  {title.upper()} — FILE LIST",
        f"  {meta['timestamp']}  |  {meta['path']}",
        f"  {meta['file_count']} files  |  {meta['total_size']}",
        "=" * 60 + "\n",
    ]
    for (lvl, typ, name, fpath, size, mtime, state) in iter_export(
            tree, folder_states, selected_files, active_exts):
        indent = "  " * lvl
        if typ == "folder":
            suffix = "  [name only]" if state == "name" else ""
            lines.append(f"\n{indent}[{name}/{suffix}]")
            note = folder_notes.get(fpath, "")
            if note:
                lines.append(f"{indent}  > {note}")
        else:
            sz = f"  {fmt_size(size):<10}" if (include_size and size) else ""
            dt = f"  {fmt_date(mtime)}" if (include_date and mtime) else ""
            lines.append(f"{indent}  {name}{sz}{dt}")
    return "\n".join(lines)


# ── JSON ─────────────────────────────────────────────────────────

def build_json(tree, folder_states, selected_files, meta, active_exts=None, *,
               include_size=True, include_date=True, folder_notes=None) -> str:
    folder_notes = folder_notes or {}
    folders: dict = {}
    current: str | None = None

    for (lvl, typ, name, fpath, size, mtime, state) in iter_export(
            tree, folder_states, selected_files, active_exts):
        if typ == "folder":
            current = fpath
            entry: dict = {
                "name":  name,
                "path":  fpath,
                "level": lvl,
                "mode":  state,
                "files": [],
            }
            note = folder_notes.get(fpath, "")
            if note:
                entry["note"] = note
            folders[fpath] = entry
        elif typ == "file" and current:
            entry: dict = {"name": name, "path": fpath}
            if include_size:
                entry["size"]     = size
                entry["size_fmt"] = fmt_size(size)
            if include_date:
                entry["date"] = fmt_date(mtime)
            folders[current]["files"].append(entry)

    return json.dumps(
        {"meta": meta, "folders": list(folders.values())},
        ensure_ascii=False,
        indent=2,
    )


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

def build_html(tree, folder_states, selected_files, meta, active_exts=None, *,
               include_size=True, include_date=True, folder_notes=None) -> str:
    folder_notes = folder_notes or {}
    css_tokens = _load_export_css()

    items = list(iter_export(tree, folder_states, selected_files, active_exts))

    used_cats: dict[str, str] = {}  # label -> color, preserves insertion order

    def dot(ext: str) -> str:
        label, color = _ext_category(ext)
        used_cats[label] = color
        return f'<span class="dot" style="background:{color}"></span>'

    def render_tree(items: list) -> str:
        parts: list[str] = []
        open_levels: list[int] = []

        # Pre-compute file counts for each folder (including subfolders)
        folder_file_counts: dict[str, int] = {}
        folder_stack: list[tuple[int, str]] = []
        for lvl, typ, name, fpath, size, mtime, state in items:
            if typ == "folder":
                folder_stack = [(l, p) for l, p in folder_stack if l < lvl]
                folder_file_counts[fpath] = 0
                folder_stack.append((lvl, fpath))
            elif typ == "file":
                for _, fp in folder_stack:
                    folder_file_counts[fp] = folder_file_counts.get(fp, 0) + 1

        # Reorder: within each folder's children, folders before files
        def reorder(items: list) -> list:
            if not items:
                return []
            base_lvl = items[0][0]
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
                parts.append('</div>')
                parts.append('</details>')
                open_levels.pop()

        i = 0
        while i < len(items):
            lvl, typ, name, fpath, size, mtime, state = items[i]

            if typ == "folder":
                if lvl == 0:
                    i += 1
                    continue
                close_until(lvl)
                sz_str = fmt_size(size) if (include_size and size) else ""
                fc = folder_file_counts.get(fpath, 0)
                fc_html = f"<b>{fc} files</b>" if fc else ""
                sz_html = _esc(sz_str) if sz_str else ""
                fmeta_parts = [p for p in [sz_html, fc_html] if p]
                fmeta_html = " · ".join(fmeta_parts)
                if state == "name":
                    ename = _esc(name)
                    parts.append(
                        f'<div class="folder">'
                        f'<div class="fh fh-nameonly">'
                        f'<span class="farr"></span>'
                        f'<span class="fname fname-muted" title="{ename}/">{ename}/</span>'
                        f'<span class="fmeta">name only{f" · {_esc(sz_str)}" if sz_str else ""}</span>'
                        f'</div>'
                        f'</div>'
                    )
                else:
                    open_attr = " open" if lvl == 0 else ""
                    ename = _esc(name)
                    note = folder_notes.get(fpath, "")
                    # Note icon comes first; text is hidden until hover
                    if note:
                        note_meta = (
                            f'<span class="fnote-inline" title="{_esc(note)}">'
                            f'{_NOTE_ICON_SVG}'
                            f'<span class="fnote-text">{_esc(note)}</span>'
                            f'</span>'
                        )
                        fmeta_with_note = f'{note_meta}{" · " + fmeta_html if fmeta_html else ""}'
                    else:
                        fmeta_with_note = fmeta_html
                    parts.append(
                        f'<details class="folder"{open_attr}>'
                        f'<summary class="fh">'
                        f'<span class="farr"></span>'
                        f'<span class="fname" title="{ename}/">{ename}/</span>'
                        f'<span class="fmeta">{fmeta_with_note}</span>'
                        f'</summary>'
                        f'<div class="fc">'
                    )
                    open_levels.append(lvl)

            elif typ == "file":
                close_until(lvl)
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                sz_str = fmt_size(size) if (include_size and size) else ""
                dt_str = _esc(fmt_date(mtime)) if (include_date and mtime) else ""
                ename = _esc(name)
                root_cls = " fi-root" if not open_levels else ""
                parts.append(
                    f'<div class="fi{root_cls}">'
                    f'{dot(ext)}'
                    f'<span class="fn" title="{ename}">{ename}</span>'
                    f'<span class="fsz">{sz_str}</span>'
                    f'<span class="fdt">{dt_str}</span>'
                    f'</div>'
                )
            i += 1

        close_until(-1)
        return "\n".join(parts)

    tree_html = render_tree(items)

    # Legend
    ORDER = ["Images", "Video", "Audio", "Documents", "Archives", "Code & Data", "Other"]
    legend_items = [
        f'<span class="leg-item"><span class="dot" style="background:{used_cats[k]}"></span>{k}</span>'
        for k in ORDER if k in used_cats
    ]
    legend_html = (
        f'<div class="legend">{"".join(legend_items)}</div>'
        if legend_items else ""
    )

    name_only = meta.get("name_only_count", 0)
    name_only_stat = (
        f'<span class="meta-sep">·</span><span class="meta-stat"><span class="meta-n">{name_only}</span> name only</span>'
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

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="generator" content="flashscan">
<title>{e_display_name or _esc(meta['disk_name'])} — {meta['file_count']} files</title>
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
      <div class="disk-date">scanned {e_timestamp}</div>
    </div>
    <div class="hdr-r">
      <div class="watermark">flashscan</div>
    </div>
  </div>

  <div class="meta-row">
    <span class="meta-stat"><span class="meta-n">{meta['file_count']}</span> files</span>
    <span class="meta-sep">·</span>
    <span class="meta-stat"><span class="meta-n">{e_total_size}</span></span>
    <span class="meta-sep">·</span>
    <span class="meta-stat"><span class="meta-n">{meta['folder_count']}</span> folders</span>
    {name_only_stat}
  </div>

  <div class="tree-toolbar">
    <button onclick="document.querySelectorAll('.tree details').forEach(d=>d.open=true)" class="tb-btn">expand all</button>
    <button onclick="document.querySelectorAll('.tree details').forEach(d=>d.open=false)" class="tb-btn">collapse all</button>
    <button id="btn-theme" class="tb-btn tb-btn-theme" onclick="toggleTheme()">\u263e dark</button>
  </div>

  <div class="tree">
{tree_html}
  </div>

  {legend_html}

  <div class="footer">
    <span>flashscan</span>
    <span>{meta['file_count']} files · {e_total_size} · scanned {e_timestamp}</span>
  </div>

</div>
<script>{_THEME_JS}</script>
</body>
</html>"""


def _load_export_css() -> str:
    """Loads tokens.css for inline embedding into the HTML export."""
    try:
        here = Path(__file__).parent
        return (here / "export_templates" / "export.css").read_text(encoding="utf-8")
    except Exception:
        return ""


_EXPORT_CSS = """
/* ── Export-specific tokens (light) ── */
:root {
  --ex-bg:       #fafaf8;
  --ex-hover:    #f0ede6;
  --ex-border:   #e4e1d9;
  --ex-border2:  #dddad2;
  --ex-text:     #1a1a18;
  --ex-text2:    #555;
  --ex-muted:    #999;
  --ex-subtle:   #c4c1b8;
  --ex-faint:    #d8d5cc;
}
[data-theme="dark"] {
  --ex-bg:       #1c1c1c;
  --ex-hover:    #2a2a2a;
  --ex-border:   rgba(255,255,255,.07);
  --ex-border2:  rgba(255,255,255,.05);
  --ex-text:     #d0ccc4;
  --ex-text2:    #a0a09a;
  --ex-muted:    #6a6a64;
  --ex-subtle:   #484844;
  --ex-faint:    rgba(255,255,255,.04);
}

* { box-sizing: border-box; margin: 0; padding: 0; }
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
.tb-btn-theme { text-decoration: none; font-size: 11px; color: var(--ex-subtle); }
.tb-btn-theme:hover { color: var(--ex-muted); }

/* ── Tree ── */
.folder { margin-bottom: 1px; }
.fh { display: flex; align-items: baseline; padding: 5px 4px; gap: 6px;
      list-style: none; cursor: pointer; user-select: none; border-radius: 3px; }
.fh:hover { background: var(--ex-hover); }
.fh::-webkit-details-marker { display: none; }
.fh-nameonly { cursor: default; }
.fh-nameonly .fname { color: var(--ex-subtle); font-weight: 400; }
.fh-nameonly .fmeta { font-style: italic; }
.farr { font-size: 14px; color: var(--ex-subtle); flex-shrink: 0; width: 16px;
        display: inline-block; transition: transform .15s; }
.farr::before { content: '▸'; }
details[open] > .fh > .farr { transform: rotate(90deg); }
details:not([open]) > .fh > .farr { transform: rotate(0deg); }
.fname { font-size: 13.5px; font-weight: 600; color: var(--ex-text); flex: 1;
         min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fname-muted { color: var(--ex-subtle); font-weight: 400; }
.fmeta { font-size: 11px; color: var(--ex-subtle); flex-shrink: 0; white-space: nowrap; min-width: 120px; text-align: right; }
.fc { margin-left: 10px; padding-left: 14px; border-left: 1px solid var(--ex-faint); }

/* Files */
.fi { display: flex; align-items: center; padding: 5px 4px; gap: 0; border-radius: 3px; }
.fi-root { padding-left: 22px; }
.fi:hover { background: var(--ex-hover); }
.dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; margin-right: 9px; opacity: .8; }
.fn { font-size: 12.5px; color: var(--ex-text2); font-family: 'Courier New', monospace;
      flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fsz { font-size: 11px; color: var(--ex-subtle); margin-left: 12px; flex-shrink: 0; white-space: nowrap; min-width: 72px; text-align: right; }
.fdt { font-size: 11px; color: var(--ex-muted); margin-left: 8px; flex-shrink: 0; white-space: nowrap; min-width: 80px; text-align: right; }

/* ── Folder note — icon always visible, text on hover ── */
.fnote-inline { display: inline-flex; align-items: center; gap: 3px; color: var(--ex-text2); cursor: default; }
.fnote-icon { flex-shrink: 0; vertical-align: middle; opacity: .55; transition: opacity .15s; }
.fnote-inline:hover .fnote-icon { opacity: 1; }
.fnote-text { font-size: 11px; color: var(--ex-text2); max-width: 0; overflow: hidden;
              white-space: nowrap; opacity: 0; transition: max-width .2s ease, opacity .15s ease; }
.fnote-inline:hover .fnote-text { max-width: 300px; opacity: 1; }

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
  function applyTheme(theme) {
    if (theme === 'dark') {
      document.documentElement.dataset.theme = 'dark';
      document.getElementById('btn-theme').textContent = '\u2600 light';
    } else {
      delete document.documentElement.dataset.theme;
      document.getElementById('btn-theme').textContent = '\u263e dark';
    }
    try { localStorage.setItem('flashscan-theme', theme); } catch(e) {}
  }
  function toggleTheme() {
    applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  }
  try {
    var saved = localStorage.getItem('flashscan-theme');
    if (saved) applyTheme(saved);
  } catch(e) {}
"""
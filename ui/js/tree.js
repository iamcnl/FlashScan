/**
 * tree.js — virtual scroll file tree
 */

const ROW_H    = 28;
const FOLDER_H = 32;
const OVERSCAN = 15;

const IC = {
  disk:    `<span class="ic-primary"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/></svg></span>`,
  folder:  `<span class="ic-primary"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></span>`,
  folderD: `<span class="ic-muted"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></span>`,
  file:    `<span class="ic-muted"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg></span>`,
  img:     `<span class="ic-muted"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg></span>`,
  video:   `<span class="ic-muted"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg></span>`,
  audio:   `<span class="ic-muted"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg></span>`,
  archive: `<span class="ic-muted"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg></span>`,
  check:   `<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
  ckG:     `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
  listI:   `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>`,
  cross:   `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
  partI:   `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/></svg>`,
};

const EXT_ICON = {
  jpg:'img',jpeg:'img',png:'img',gif:'img',webp:'img',bmp:'img',tiff:'img',tif:'img',
  heic:'img',heif:'img',svg:'img',avif:'img',raw:'img',cr2:'img',nef:'img',arw:'img',
  mp4:'video',mkv:'video',avi:'video',mov:'video',wmv:'video',flv:'video',webm:'video',m4v:'video',ts:'video',
  mp3:'audio',wav:'audio',flac:'audio',aac:'audio',ogg:'audio',m4a:'audio',wma:'audio',opus:'audio',aiff:'audio',
  zip:'archive',rar:'archive','7z':'archive',tar:'archive',gz:'archive',bz2:'archive',xz:'archive',iso:'archive',
};

const PILLS = [
  { state:'full',    cls:'pill-full',    icon: IC.ckG,   label:'all' },
  { state:'name',    cls:'pill-name',    icon: IC.listI, label:'name only' },
  { state:'skip',    cls:'pill-skip',    icon: IC.cross, label:'skip' },
  { state:'partial', cls:'pill-partial', icon: IC.partI, label:'partial' },
];

function fmtSize(b) {
  if (!b)             return '';
  if (b < 1024)       return `${b} B`;
  if (b < 1048576)    return `${(b/1024).toFixed(1)} KB`;
  if (b < 1073741824) return `${(b/1048576).toFixed(1)} MB`;
  return `${(b/1073741824).toFixed(2)} GB`;
}
function fmtDate(ts) {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleDateString('en-US',
    { day:'2-digit', month:'2-digit', year:'numeric' });
}
function fileIcon(name) {
  const dot = name.lastIndexOf('.');
  const ext  = dot >= 0 ? name.slice(dot + 1).toLowerCase() : '';
  return IC[EXT_ICON[ext] || 'file'];
}
function getExt(name) {
  const dot = name.lastIndexOf('.');
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : '';
}
function pillHtml(state) {
  const p = PILLS.find(x => x.state === state) || PILLS[0];
  return `<span class="pill ${p.cls}" data-pill>${p.icon}${p.label}</span>`;
}

/* ═══════════════════════════════════════════════════════════ */
const Tree = {
  _container: null,
  _inner:     null,
  _rowsEl:    null,
  _flatRows:  [],
  _offsets:   [],
  _totalH:    0,
  _dirty:     true,
  _collapsed: new Set(),
  _focusIdx:     -1,   // index of currently focused row (-1 = none)
  _lastClickIdx:    -1,   // index of last clicked row (for Shift+click range)
  _lastClickSelect: true, // whether that click selected (true) or deselected (false)

  init(containerEl) {
    this._container = containerEl;
    containerEl.style.position = 'relative';
    containerEl.style.overflow = 'auto';

    this._inner = document.createElement('div');
    this._inner.style.cssText = 'position:relative;width:100%;';
    containerEl.appendChild(this._inner);

    this._rowsEl = document.createElement('div');
    this._rowsEl.style.cssText = 'position:absolute;top:0;left:0;right:0;';
    this._inner.appendChild(this._rowsEl);

    containerEl.addEventListener('scroll',      () => this.render(), { passive: true });
    containerEl.addEventListener('click',       e => this._onClick(e));
    containerEl.addEventListener('contextmenu', e => this._onContextMenu(e));

    // Global menu close on click outside
    document.addEventListener('click',   () => ContextMenu.hide());
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') ContextMenu.hide();
      this._onKeyDown(e);
    });
  },

  invalidate() { this._dirty = true; },

  /* ── Rebuild ──────────────────────────────────────────── */
  _rebuild() {
    const { treeData, activeExts, searchQuery, sortCol, sortDir } = State;
    const q = searchQuery.trim().toLowerCase();


  // Step 1: matching sets
    let matchFiles   = null;
    let matchFolders = null;

    const advFilter = State.advFilter || null;

    if (q || activeExts || advFilter) {
      matchFiles   = new Set();
      matchFolders = new Set();

      // Pass 1: find folders whose name matches the query.
      for (const item of treeData) {
        if (q && item.type === 'folder' && item.name.toLowerCase().includes(q))
          matchFolders.add(item.path);
      }

      // Pass 2: walk treeData once with a lvl-based stack.
      const folderMatchStack = []; // { lvl, matched }

      for (const item of treeData) {
        while (folderMatchStack.length > 0 &&
               folderMatchStack[folderMatchStack.length - 1].lvl >= item.lvl) {
          folderMatchStack.pop();
        }

        if (item.type === 'folder') {
          const parentMatched = folderMatchStack.length > 0 &&
                                folderMatchStack[folderMatchStack.length - 1].matched;
          const selfMatched   = matchFolders.has(item.path);
          folderMatchStack.push({ lvl: item.lvl, matched: parentMatched || selfMatched });
        } else {
          const insideMatchedFolder = folderMatchStack.length > 0 &&
                                      folderMatchStack[folderMatchStack.length - 1].matched;
          if (insideMatchedFolder) {
            matchFiles.add(item.path);
          } else {
            if (activeExts) {
              const ext = getExt(item.name);
              if (ext && activeExts.has(ext) === false && Filters._extState.hasOwnProperty(ext)) continue;
            }
            if (q && !item.name.toLowerCase().includes(q)) continue;
            if (advFilter && !advFilter.matches(item)) continue;
            matchFiles.add(item.path);
          }
        }
      }

      // Walk up from every matched file to ensure all ancestor folders are visible.
      // Do NOT break early — always walk to root so deep paths aren't cut off.
      for (const fp of matchFiles) {
        let p = fp;
        for (let attempt = 0; attempt < 50; attempt++) {
          let sep = -1;
          for (let k = p.length - 1; k >= 0; k--) {
            if (p[k] === '/' || p[k] === '\\') { sep = k; break; }
          }
          if (sep < 0) break;
          let parent = p.slice(0, sep);
          if (parent.length === 2 && parent[1] === ':') parent += p[sep];
          if (!parent || parent === p) break;
          matchFolders.add(parent);
          p = parent;
        }
      }

    }

    // Step 2: sort
    const sortFn = sortCol ? (a, b) => {
      let va, vb;
      if (sortCol === 'size')      { va = a.size  || 0; vb = b.size  || 0; }
      else if (sortCol === 'date') { va = a.mtime || 0; vb = b.mtime || 0; }
      else { va = a.name.toLowerCase(); vb = b.name.toLowerCase(); }
      if (va < vb) return sortDir === 'asc' ? -1 : 1;
      if (va > vb) return sortDir === 'asc' ?  1 : -1;
      return 0;
    } : null;

    // Step 3: traversal
    // Key fix: folderStack tracks CURRENTLY OPEN folders.
    // File belongs to the nearest parent folder = last on stack
    // whose lvl < file.lvl.
    const rows = [];
    const folderStack = []; // [{ lvl, path, filesBuffer[] }]

    for (let i = 0; i < treeData.length; i++) {
      const item = treeData[i];
      const { lvl, type, path, name } = item;

      if (type === 'folder') {
        // Pop folders at same or higher level
        // (= end of their subtree)
        while (folderStack.length > 0 &&
               folderStack[folderStack.length - 1].lvl >= lvl) {
          const done = folderStack.pop();
          if (done.filesBuffer.length > 0) {
            if (sortFn && done.filesBuffer.length > 1)
              done.filesBuffer.sort(sortFn);
            for (const f of done.filesBuffer)
              rows.push({ type:'file', item:f, depth:f.lvl });
          }
        }

        // Search filter
        if (matchFolders !== null && !matchFolders.has(path)) {
          // Skip entire subtree
          const skipLvl = lvl;
          i++;
          while (i < treeData.length && treeData[i].lvl > skipLvl) i++;
          i--; // for loop will ++
          continue;
        }

        rows.push({ type:'folder', item, depth:lvl });

        if (!this._collapsed.has(path)) {
          folderStack.push({ lvl, path, filesBuffer:[] });
        } else {
          // Collapsed — skip contents
          const skipLvl = lvl;
          i++;
          while (i < treeData.length && treeData[i].lvl > skipLvl) i++;
          i--;
        }

      } else {
        // File — filter
        if (activeExts) {
          const ext = getExt(name);
          // If extension is known and not in activeExts → skip
          // Unknown extensions (ext not in any group) always pass
          if (ext && activeExts.has(ext) === false && Filters._extState.hasOwnProperty(ext)) continue;
        }
        if (matchFiles !== null && !matchFiles.has(path)) continue;

        // Find the correct parent folder on the stack
        // = last folder whose lvl < file.lvl
        let targetBuf = null;
        for (let s = folderStack.length - 1; s >= 0; s--) {
          if (folderStack[s].lvl < lvl) {
            targetBuf = folderStack[s].filesBuffer;
            break;
          }
        }

        if (targetBuf !== null) {
          targetBuf.push(item);
        } else {
          // Top-level file (no parent folder)
          rows.push({ type:'file', item, depth:lvl });
        }
      }
    }

    // Empty the rest of the stack
    while (folderStack.length > 0) {
      const done = folderStack.pop();
      if (done.filesBuffer.length > 0) {
        if (sortFn && done.filesBuffer.length > 1)
          done.filesBuffer.sort(sortFn);
        for (const f of done.filesBuffer)
          rows.push({ type:'file', item:f, depth:f.lvl });
      }
    }


    // Step 4: offsets
    const offsets = new Array(rows.length);
    let y = 0;
    for (let j = 0; j < rows.length; j++) {
      offsets[j] = y;
      y += rows[j].type === 'folder' ? FOLDER_H : ROW_H;
    }

    this._flatRows = rows;
    this._offsets  = offsets;
    this._totalH   = y;
    this._dirty    = false;
  },

  /* ── Render ────────────────────────────────────────────── */
  render() {
    if (this._dirty) this._rebuild();
    if (!this._inner) return;

    this._inner.style.height = this._totalH + 'px';

    if (this._flatRows.length === 0) {
      this._rowsEl.innerHTML =
        '<div style="padding:24px 16px;font-size:12px;color:#9a9d94;">No results</div>';
      this.updateStats();
      return;
    }

    const scrollTop    = this._container.scrollTop;
    const viewH        = this._container.clientHeight;
    const effectiveH   = viewH > 10 ? viewH : 600;
    const topY         = Math.max(0, scrollTop - OVERSCAN * ROW_H);
    const botY         = scrollTop + effectiveH + OVERSCAN * ROW_H;

    let startIdx = 0;
    while (startIdx < this._flatRows.length - 1 &&
           this._offsets[startIdx + 1] <= topY) startIdx++;
    let endIdx = startIdx;
    while (endIdx < this._flatRows.length - 1 &&
           this._offsets[endIdx + 1] < botY) endIdx++;

    const parts = [];
    for (let j = startIdx; j <= endIdx; j++) {
      const { type, item, depth } = this._flatRows[j];
      const top     = this._offsets[j];
      const h       = type === 'folder' ? FOLDER_H : ROW_H;
      const focused = j === this._focusIdx;
      parts.push(type === 'folder'
        ? this._rowFolder(item, depth, top, h, focused)
        : this._rowFile(item, depth, top, h, focused));
    }
    this._rowsEl.innerHTML = parts.join('');
    this.updateStats();
  },

  /* ── Row HTML ──────────────────────────────────────────── */
  _rowFolder(item, depth, top, h, focused) {
    const state     = State.folderStates[item.path] || 'full';
    const collapsed = this._collapsed.has(item.path);
    const indent    = 12 + depth * 16;
    const dimmed    = state === 'skip' ? ' row-dimmed' : '';
    const focusCls  = focused ? ' row-focused' : '';
    const icon      = depth === 0 ? IC.disk : (state === 'skip' ? IC.folderD : IC.folder);
    const nameCls   = state === 'skip' ? 'row-name folder muted' : 'row-name folder';
    const sz        = item.size ? fmtSize(item.size) : '';
    const dt        = item.mtime ? fmtDate(item.mtime) : '';

    const note        = State.folderNotes[item.path] || '';
    const escapedNote = note.replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const noteIcon    = note
      ? `<span class="note-btn note-active" data-note-btn="${item.path}" title="${escapedNote}">` +
        `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></span>`
      : `<span class="note-btn note-empty" data-note-btn="${item.path}" title="Add note">` +
        `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></span>`;

    return `<div class="row row-folder${dimmed}${focusCls}" data-path="${item.path}" data-type="folder"
      style="position:absolute;top:${top}px;height:${h}px;left:0;right:0;
             padding-left:${indent}px;box-sizing:border-box;
             display:flex;align-items:center;gap:4px;">
      <span class="row-arrow" data-arrow-toggle="${item.path}">${collapsed ? '▶' : '▼'}</span>
      ${icon}
      <span class="${nameCls}">${item.name}</span>
      <div class="row-state">${pillHtml(state)}${noteIcon}</div>
      <span class="row-size">${sz}</span>
      <span class="row-date">${dt}</span>
    </div>`;
  },

  _rowFile(item, depth, top, h, focused) {
    const checked  = State.selectedFiles.has(item.path);
    const indent   = 12 + depth * 16;
    const sz       = fmtSize(item.size);
    const dt       = fmtDate(item.mtime);
    const cbCls    = checked ? 'fcb on' : 'fcb off';
    const nameCls  = checked ? 'row-name' : 'row-name muted strike';
    const opacity  = checked ? '' : 'opacity:.5;';
    const statePill = checked ? '' : '<span class="row-excluded-x">✕</span>';
    const focusCls = focused ? ' row-focused' : '';

    const rowCls = checked ? `row${focusCls}` : `row row-excluded${focusCls}`;
    return `<div class="${rowCls}" data-path="${item.path}" data-type="file"
      style="position:absolute;top:${top}px;height:${h}px;left:0;right:0;
             padding-left:${indent}px;${opacity}box-sizing:border-box;
             display:flex;align-items:center;gap:4px;">
      <div class="${cbCls}" data-cb-toggle="${item.path}">${checked ? IC.check : ''}</div>
      ${fileIcon(item.name)}
      <span class="${nameCls}">${item.name}</span>
      <div class="row-state">${statePill}</div>
      <span class="row-size">${sz}</span>
      <span class="row-date">${dt}</span>
    </div>`;
  },

  /* ── Click ─────────────────────────────────────────────── */
  _onClick(e) {
    // Pill click — cycle folder state (full/name/skip)
    const pillEl = e.target.closest('[data-pill]');
    if (pillEl) {
      const row = pillEl.closest('[data-type="folder"]');
      if (row) this._cycleFolderState(row.dataset.path);
      return;
    }

    // Note button click — open inline note editor
    const noteBtn = e.target.closest('[data-note-btn]');
    if (noteBtn) {
      e.stopPropagation();
      this._openNoteEditor(noteBtn.dataset.noteBtn, noteBtn);
      return;
    }

    // Folder row click — toggle collapse, update focus
    const folderRow = e.target.closest('[data-type="folder"]');
    if (folderRow) {
      const idx = this._flatRows.findIndex(r => r.item.path === folderRow.dataset.path);
      this._focusIdx     = idx;
      this._lastClickIdx = idx;
      this._toggleCollapse(folderRow.dataset.path);
      return;
    }

    // File row click — toggle selection, Shift+click = range select
    const fileRow = e.target.closest('[data-type="file"]');
    if (fileRow) {
      const idx = this._flatRows.findIndex(r => r.item.path === fileRow.dataset.path);
      if (e.shiftKey && this._lastClickIdx >= 0 && idx >= 0) {
        this._rangeSelect(this._lastClickIdx, idx);
      } else {
        this._focusIdx        = idx;
        this._lastClickIdx    = idx;
        // Record whether this click is selecting or deselecting (for range select direction)
        this._lastClickSelect = !State.selectedFiles.has(fileRow.dataset.path);
        this._toggleFile(fileRow.dataset.path, fileRow);
      }
    }
  },

  /* ── Note editor ───────────────────────────────────────── */
  _openNoteEditor(path, anchorEl) {
    // Remove any existing editor
    document.getElementById('note-editor-overlay')?.remove();

    const current = State.folderNotes[path] || '';
    const rect    = anchorEl.getBoundingClientRect();

    const wrap = document.createElement('div');
    wrap.id = 'note-editor-overlay';
    wrap.innerHTML =
      `<input id="note-input" type="text" maxlength="300"
              placeholder="Add note"
              value="${current.replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}">` +
      `<button class="note-editor-btn note-editor-save" id="note-save">Save</button>` +
      `<button class="note-editor-btn note-editor-clear" id="note-clear">Clear</button>`;

    // Position below the anchor; flip up if too close to bottom
    const spaceBelow = window.innerHeight - rect.bottom;
    const editorH = 44;
    const top = spaceBelow > editorH + 8
      ? rect.bottom + 4
      : rect.top - editorH - 4;

    wrap.style.cssText =
      `position:fixed;top:${top}px;left:${Math.max(0, rect.right - 360)}px;` +
      `z-index:9999;display:flex;align-items:center;gap:6px;` +
      `background:var(--card);border:1.5px solid var(--border2);` +
      `border-radius:var(--r-sm);padding:6px 8px;` +
      `box-shadow:0 4px 20px rgba(0,0,0,.18);`;

    document.body.appendChild(wrap);

    const inp = document.getElementById('note-input');
    inp.focus();
    inp.select();

    const commit = (val) => {
      if (val.trim()) State.folderNotes[path] = val.trim();
      else            delete State.folderNotes[path];
      wrap.remove();
      this.invalidate();
      this.render();
    };

    inp.addEventListener('keydown', ev => {
      if (ev.key === 'Enter')  { ev.preventDefault(); commit(inp.value); }
      if (ev.key === 'Escape') { wrap.remove(); }
    });
    document.getElementById('note-save').addEventListener('click',  () => commit(inp.value));
    document.getElementById('note-clear').addEventListener('click', () => commit(''));

    // Close on click outside, deferred so this click doesn't immediately close it
    setTimeout(() => {
      const handler = (ev) => {
        if (!wrap.contains(ev.target)) {
          wrap.remove();
          document.removeEventListener('click', handler);
        }
      };
      document.addEventListener('click', handler);
    }, 0);
  },

  /* ── Range select (Shift+click) ────────────────────────── */
  // Selects (or deselects) all files between from and to index.
  // State shared with the last clicked file.
  _rangeSelect(from, to) {
    const [a, b] = from <= to ? [from, to] : [to, from];
    // Use the direction recorded at the time of the anchor click, not the current state
    const select = this._lastClickSelect;
    for (let i = a; i <= b; i++) {
      const row = this._flatRows[i];
      if (!row || row.type !== 'file') continue;
      if (select) State.selectedFiles.add(row.item.path);
      else        State.selectedFiles.delete(row.item.path);
      // Recompute parent folder state
      const parent = this._parentFolderPath(row.item.path);
      if (parent) this._recomputeFolderState(parent);
    }
    this._focusIdx = to;
    State._markDirty();
    this.invalidate();
    this.render();
  },

  /* ── Keyboard shortcuts ────────────────────────────────── */
  _onKeyDown(e) {
    // Ignore if focus is in an input / textarea
    const tag = document.activeElement?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

    const ctrl = e.ctrlKey || e.metaKey;

    // Ctrl+A — select all
    if (ctrl && e.key === 'a') {
      e.preventDefault();
      this.selectAll();
      return;
    }

    // Ctrl+D — deselect all
    if (ctrl && e.key === 'd') {
      e.preventDefault();
      this.deselectAll();
      return;
    }

    // Ctrl+E — expand all
    if (ctrl && e.key === 'e') {
      e.preventDefault();
      this.expandAll();
      return;
    }

    // Ctrl+W — collapse all
    if (ctrl && e.key === 'w') {
      e.preventDefault();
      this.collapseAll();
      return;
    }

    // Arrows and Space/Enter — only work if focus exists or tree has rows
    const rows = this._flatRows;
    if (rows.length === 0) return;

    // ↑ / ↓ — move focus
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault();
      const dir  = e.key === 'ArrowUp' ? -1 : 1;
      const next = Math.max(0, Math.min(rows.length - 1,
        this._focusIdx < 0 ? (dir > 0 ? 0 : rows.length - 1)
                           : this._focusIdx + dir));
      this._focusIdx = next;
      this._scrollToIdx(next);
      this.invalidate();
      this.render();
      return;
    }

    // ← / → — collapse/expand folder (or navigate to parent)
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      if (this._focusIdx < 0) return;
      const row = rows[this._focusIdx];
      if (!row) return;
      if (row.type === 'folder') {
        const path = row.item.path;
        if (e.key === 'ArrowRight') {
          // Expand
          if (this._collapsed.has(path)) {
            this._collapsed.delete(path);
            this.invalidate();
            this.render();
          }
        } else {
          // Collapse
          if (!this._collapsed.has(path) && row.item.lvl > 0) {
            this._collapsed.add(path);
            this.invalidate();
            this.render();
          } else {
            // Navigate to parent folder
            const parentPath = this._parentFolderPath(path);
            if (parentPath) {
              const parentIdx = rows.findIndex(r => r.item.path === parentPath);
              if (parentIdx >= 0) {
                this._focusIdx = parentIdx;
                this._scrollToIdx(parentIdx);
                this.invalidate();
                this.render();
              }
            }
          }
        }
      }
      return;
    }

    // Space — toggle focused file selection / folder state
    if (e.key === ' ') {
      e.preventDefault();
      if (this._focusIdx < 0) return;
      const row = rows[this._focusIdx];
      if (!row) return;
      if (row.type === 'file') {
        this._lastClickIdx    = this._focusIdx;
        this._lastClickSelect = !State.selectedFiles.has(row.item.path);
        this._toggleFile(row.item.path, null);
      } else if (row.type === 'folder') {
        this._cycleFolderState(row.item.path);
      }
      return;
    }

    // Enter — toggle folder collapse / toggle file selection
    if (e.key === 'Enter') {
      e.preventDefault();
      if (this._focusIdx < 0) return;
      const row = rows[this._focusIdx];
      if (!row) return;
      if (row.type === 'folder') {
        this._toggleCollapse(row.item.path);
      } else if (row.type === 'file') {
        this._lastClickIdx    = this._focusIdx;
        this._lastClickSelect = !State.selectedFiles.has(row.item.path);
        this._toggleFile(row.item.path, null);
      }
      return;
    }
  },

  // Scrolls container so the row at the given index is visible
  _scrollToIdx(idx) {
    if (!this._container || idx < 0 || idx >= this._offsets.length) return;
    const top    = this._offsets[idx];
    const h      = this._flatRows[idx]?.type === 'folder' ? FOLDER_H : ROW_H;
    const bot    = top + h;
    const sTop   = this._container.scrollTop;
    const sBot   = sTop + this._container.clientHeight;
    if (top < sTop)       this._container.scrollTop = top - 4;
    else if (bot > sBot)  this._container.scrollTop = bot - this._container.clientHeight + 4;
  },

  /* ── Context menu ──────────────────────────────────────── */
  _onContextMenu(e) {
    const row = e.target.closest('[data-type]');
    if (!row) return;
    e.preventDefault();
    const path = row.dataset.path;
    const type = row.dataset.type;
    const item = State.treeData.find(i => i.path === path);
    if (!item) return;
    ContextMenu.show(e.clientX, e.clientY, path, type, item, this);
  },

  /* ── Folder actions ────────────────────────────────────── */
  _toggleCollapse(path) {
    if (this._collapsed.has(path)) this._collapsed.delete(path);
    else this._collapsed.add(path);
    this.invalidate(); this.render();
  },

  _cycleFolderState(path) {
    const states = ['full','name','skip'];
    const cur    = State.folderStates[path] || 'full';
    // partial is not in cycle — clicking from partial jumps to skip
    const next   = cur === 'partial'
      ? 'skip'
      : states[(states.indexOf(cur) + 1) % 3];
    State.folderStates[path] = next;
    this._syncFilesForFolder(path, next);
    // Propagate change upward
    const parent = this._parentFolderPath(path);
    if (parent) this._recomputeFolderState(parent);
    State._markDirty();
    this.invalidate();
    this.render();
  },

  /* ── File actions ──────────────────────────────────────── */
  _toggleFile(path, rowEl) {
    const was = State.selectedFiles.has(path);
    const parentPath = this._parentFolderPath(path);
    const curFolderState = parentPath ? (State.folderStates[parentPath] || 'full') : null;

    if (was) State.selectedFiles.delete(path);
    else     State.selectedFiles.add(path);

    // Recompute parent folder state
    if (parentPath) {
      if (!was && curFolderState === 'skip') {
        // folder was skip, adding file → partial
        State.folderStates[parentPath] = 'partial';
      } else {
        this._recomputeFolderState(parentPath);
      }
    }

    State._markDirty();
    if (rowEl) {
      const cb     = rowEl.querySelector('[data-cb-toggle]');
      const nameEl = rowEl.querySelector('.row-name');
      if (cb)     { cb.className = was ? 'fcb off' : 'fcb on'; cb.innerHTML = was ? '' : IC.check; }
      if (nameEl)   nameEl.className = was ? 'row-name muted strike' : 'row-name';
      const stateEl = rowEl.querySelector('.row-state');
      if (stateEl)  stateEl.innerHTML = was ? '<span class="row-excluded-x">✕</span>' : '';
      const isFocused = rowEl.classList.contains('row-focused');
      rowEl.className = (was ? 'row row-excluded' : 'row') + (isFocused ? ' row-focused' : '');
      rowEl.style.opacity = was ? '.5' : '';
    }
    // Redraw due to parent folder pill change
    this.invalidate();
    this.render();
  },

  /* ── File sync on folder state change ──────────────────── */
  _isDescendant(filePath, folderPath) {
    const sep = filePath.includes('/') ? '/' : '\\';
    return filePath.startsWith(folderPath + sep) || filePath === folderPath;
  },

  // Returns the direct parent folder (path → path or null).
  _parentFolderPath(filePath) {
    const sep = filePath.includes('/') ? '/' : '\\';
    const idx = filePath.lastIndexOf(sep);
    if (idx <= 0) return null;
    const parentPath = filePath.slice(0, idx);
    return State.treeData.find(i => i.type === 'folder' && i.path === parentPath)
      ? parentPath : null;
  },

  // Syncs files and subfolders when folder state changes (downward).
  // full  → all files + subfolders to full
  // otherwise → deselect files, subfolders to same state
  _syncFilesForFolder(folderPath, folderState) {
    for (const itm of State.treeData) {
      if (!this._isDescendant(itm.path, folderPath)) continue;
      if (itm.type === 'file') {
        if (folderState === 'full') State.selectedFiles.add(itm.path);
        else State.selectedFiles.delete(itm.path);
      } else if (itm.type === 'folder' && itm.path !== folderPath) {
        State.folderStates[itm.path] = folderState;
      }
    }
  },

  // Recomputes folder state bottom-up based on direct children states.
  // Direct children = direct subfolders + direct files.
  // Called recursively up to the root.
  _recomputeFolderState(folderPath) {
    const sep = folderPath.includes('/') ? '/' : '\\';

    // Direct subfolders (one level down, not deeper)
    const directFolders = State.treeData.filter(i => {
      if (i.type !== 'folder' || i.path === folderPath) return false;
      if (!this._isDescendant(i.path, folderPath)) return false;
      // direct: remainder of path after folderPath contains no sep
      const rel = i.path.slice(folderPath.length + 1);
      return !rel.includes(sep);
    });

    // Direct files
    const directFiles = State.treeData.filter(i => {
      if (i.type !== 'file') return false;
      if (!this._isDescendant(i.path, folderPath)) return false;
      const rel = i.path.slice(folderPath.length + 1);
      return !rel.includes(sep);
    });

    const folderStates = directFolders.map(i => State.folderStates[i.path] || 'full');
    const fileStates   = directFiles.map(i => State.selectedFiles.has(i.path) ? 'full' : 'none');
    const allStates    = [...folderStates, ...fileStates];

    let newState;
    if (allStates.length === 0) {
      newState = State.folderStates[folderPath] || 'full'; // folder with no contents — don't change
    } else if (allStates.every(s => s === 'full')) {
      newState = 'full';
    } else if (allStates.every(s => s === 'skip')) {
      newState = 'skip';
    } else if (allStates.every(s => s === 'name' || s === 'none')) {
      newState = 'name';
    } else {
      newState = 'partial';
    }

    State.folderStates[folderPath] = newState;

    // Propagate upward
    const parent = this._parentFolderPath(folderPath);
    if (parent) this._recomputeFolderState(parent);
  },

  /* ── Bulk actions ──────────────────────────────────────── */
  selectAll() {
    State.treeData.forEach(i => { if (i.type==='file') State.selectedFiles.add(i.path); });
    // Reset folders from 'name'/'skip' state back to 'full',
    // otherwise exportStats() still excludes files from these folders
    Object.keys(State.folderStates).forEach(p => {
      if (State.folderStates[p] !== 'full') State.folderStates[p] = 'full';
    });
    State._markDirty(); this.invalidate(); this.render();
  },
  deselectAll() {
    State.selectedFiles.clear();
    State.treeData.forEach(i => { if (i.type === 'folder') State.folderStates[i.path] = 'skip'; });
    State._markDirty(); this.invalidate(); this.render();
  },
  setAllFoldersNameOnly() {
    State.selectedFiles.clear();
    State.treeData.forEach(i => { if (i.type === 'folder') State.folderStates[i.path] = 'name'; });
    State._markDirty(); this.invalidate(); this.render();
  },
  collapseAll() {
    State.treeData.forEach(i => { if (i.type==='folder' && i.lvl > 0) this._collapsed.add(i.path); });
    this.invalidate(); this.render();
  },
  expandAll() {
    this._collapsed.clear();
    this.invalidate(); this.render();
  },

  /* ── Statistics ────────────────────────────────────────── */
  updateStats() {
    const { nameOnly } = State.exportStats();

    // If extension filter is active, count only matching files
    const activeExts = State.activeExts; // null = all, Set = allowed extensions
    const matchesExt = (item) => {
      if (!activeExts) return true;
      const dot = item.name.lastIndexOf('.');
      const ext = dot >= 0 ? item.name.slice(dot + 1).toLowerCase() : '';
      return activeExts.has(ext);
    };

    const allFiles = State.treeData.filter(i => i.type === 'file');
    const filteredFiles = allFiles.filter(matchesExt);

    // Export stats — only from visible (filtered) files
    let count = 0;
    let size  = 0;
    for (const item of filteredFiles) {
      if (!State.selectedFiles.has(item.path)) continue;
      count++;
      size += item.size || 0;
    }

    const total   = allFiles.length;
    const visible = this._flatRows.filter(r => r.type === 'file').length;
    const pct     = total > 0 ? Math.round((count / total) * 100) : 0;
    const $       = id => document.getElementById(id);
    if ($('stat-files'))    $('stat-files').textContent    = `${count} files`;
    if ($('stat-size'))     $('stat-size').textContent     = fmtSize(size) || '0 B';
    if ($('stat-progress')) $('stat-progress').style.width = `${pct}%`;
    if ($('stat-pct'))      $('stat-pct').textContent      = `${pct} %`;
    if ($('search-count'))  $('search-count').textContent  =
      State.searchQuery ? `${visible}` : `${total}`;
    const nameEl  = $('stat-name-only');
    const nameSep = $('stat-name-sep');
    if (nameEl && nameSep) {
      if (nameOnly > 0) {
        nameEl.textContent = `${nameOnly} folders name only`;
        nameEl.style.display = nameSep.style.display = '';
      } else {
        nameEl.style.display = nameSep.style.display = 'none';
      }
    }
  },

  updateSortHeadings() {
    const labels = { name:'name', size:'size', date:'date modified' };
    ['name','size','date'].forEach(col => {
      const el = document.getElementById(`th-${col}`);
      if (!el) return;
      el.textContent = labels[col] + (col === State.sortCol
        ? (State.sortDir === 'asc' ? ' ↑' : ' ↓') : '');
      el.classList.toggle('sorted', col === State.sortCol);
    });
  },
};
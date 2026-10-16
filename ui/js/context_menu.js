/**
 * context_menu.js — right-click context menu for tree rows
 *
 * Section 1: Open, Show in Explorer, Copy Path, Copy Name, Properties
 * Section 2: Select all in folder, Set folder state
 */

const ContextMenu = (() => {
  let _el       = null;   // menu DOM element
  let _curPath  = null;
  let _curItem  = null;   // { name, path, size, mtime, ... }
  let _curTree  = null;   // reference to the Tree object

  /* ── Icons ─────────────────────────────────────────────────── */
  const ICONS = {
    open:      `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>`,
    explorer:  `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>`,
    copyPath:  `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`,
    copyName:  `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><line x1="17" y1="10" x2="3" y2="10"/><line x1="21" y1="6" x2="3" y2="6"/><line x1="21" y1="14" x2="3" y2="14"/><line x1="17" y1="18" x2="3" y2="18"/></svg>`,
    props:     `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
    selAll:    `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
    deselAll:  `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
    stateFull: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><polyline points="9 11 12 14 22 4"/></svg>`,
    stateName: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>`,
    stateSkip: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>`,
    check:     `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
  };

  /* ── DOM initialization ──────────────────────────────────── */
  function _ensureEl() {
    if (_el) return;
    _el = document.createElement('div');
    _el.className = 'ctx-menu';
    _el.setAttribute('role', 'menu');
    document.body.appendChild(_el);
  }

  /* ── Render menu ─────────────────────────────────────────── */
  function show(x, y, path, type, itemData, treeRef) {
    _ensureEl();
    _curPath = path;
    _curItem = itemData;
    _curTree = treeRef;

    const isFolder   = type === 'folder';
    const curState   = isFolder ? (State.folderStates[path] || 'full') : null;

    /* ---- Build HTML ----------------------------------------- */
    let html = `<div class="ctx-header">${_escHtml(_truncate(itemData.name, 28))}</div>`;

    /* Section 1 */
    html += `<div class="ctx-section">`;
    html += _row('open',      ICONS.open,     isFolder ? 'Open folder' : 'Open file');
    html += _row('explorer',  ICONS.explorer,  'Show in Explorer');
    html += `<div class="ctx-divider-inner"></div>`;
    html += _row('copy-path', ICONS.copyPath,  'Copy path');
    html += _row('copy-name', ICONS.copyName,  'Copy name');
    html += `<div class="ctx-divider-inner"></div>`;
    html += _row('props',     ICONS.props,     'Properties');
    html += `</div>`;

    /* Section 2 — folders only */
    if (isFolder) {
      html += `<div class="ctx-divider"></div>`;
      html += `<div class="ctx-section">`;
      html += _row('sel-all',    ICONS.selAll,    'Select all in folder');
      html += _row('desel-all',  ICONS.deselAll,  'Deselect all in folder');
      html += `<div class="ctx-divider-inner"></div>`;
      html += _rowCheck('state-full', ICONS.stateFull, 'Full (contents & names)', curState === 'full');
      html += _rowCheck('state-name', ICONS.stateName, 'Folder name only',        curState === 'name');
      html += _rowCheck('state-skip', ICONS.stateSkip, 'Skip folder',             curState === 'skip');
      html += `</div>`;
    }

    _el.innerHTML = html;
    _el.onclick = _handleClick;

    /* ---- Positioning ---------------------------------------- */
    _el.style.visibility = 'hidden';
    _el.style.display    = 'block';
    const mw = _el.offsetWidth;
    const mh = _el.offsetHeight;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    _el.style.left       = Math.min(x, vw - mw - 8) + 'px';
    _el.style.top        = Math.min(y, vh - mh - 8) + 'px';
    _el.style.visibility = '';
  }

  function hide() {
    if (_el) _el.style.display = 'none';
  }

  /* ── HTML helpers ────────────────────────────────────────── */
  function _row(action, icon, label) {
    return `<button class="ctx-item" data-action="${action}" role="menuitem">
      <span class="ctx-icon">${icon}</span>
      <span class="ctx-label">${label}</span>
    </button>`;
  }

  function _rowCheck(action, icon, label, checked) {
    return `<button class="ctx-item ctx-item-check" data-action="${action}" role="menuitem">
      <span class="ctx-icon">${icon}</span>
      <span class="ctx-label">${label}</span>
      ${checked ? `<span class="ctx-checkmark">${ICONS.check}</span>` : ''}
    </button>`;
  }

  function _escHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function _truncate(s, max) {
    return s.length > max ? s.slice(0, max - 1) + '…' : s;
  }

  /* ── Click handler ───────────────────────────────────────── */
  function _handleClick(e) {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    e.stopPropagation();
    const action = btn.dataset.action;
    hide();
    _dispatch(action);
  }

  function _dispatch(action) {
    const api = window.pywebview?.api;

    switch (action) {
      case 'open':
        api ? api.open_path(_curPath) : console.log('[ctx] open_path:', _curPath);
        break;

      case 'explorer':
        api ? api.reveal_in_explorer(_curPath) : console.log('[ctx] reveal_in_explorer:', _curPath);
        break;

      case 'copy-path':
        _copyText(_curPath);
        break;

      case 'copy-name':
        _copyText(_curItem.name);
        break;

      case 'props':
        if (api) {
          api.open_properties(_curPath).then(r => {
            if (!r) return;
            if (r.error) { _toast('Error: ' + r.error); return; }
            if (r.meta)  { _showMetaToast(r); }   // Linux fallback
          });
        } else {
          _showMetaToast(_curItem);
        }
        break;

      case 'sel-all':
        _selectFolder(_curPath, true);
        break;

      case 'desel-all':
        _selectFolder(_curPath, false);
        break;

      case 'state-full':
        _setFolderState(_curPath, 'full');
        break;

      case 'state-name':
        _setFolderState(_curPath, 'name');
        break;

      case 'state-skip':
        _setFolderState(_curPath, 'skip');
        break;
    }
  }

  /* ── Actions ─────────────────────────────────────────────── */
  function _copyText(text) {
    navigator.clipboard.writeText(text)
      .then(() => _toast('Copied to clipboard'))
      .catch(() => {
        const ta = Object.assign(document.createElement('textarea'), {
          value: text, style: 'position:fixed;opacity:0'
        });
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
        _toast('Copied to clipboard');
      });
  }

  function _selectFolder(folderPath, select) {
    for (const itm of State.treeData) {
      if (itm.type !== 'file') continue;
      if (!_isDescendant(itm.path, folderPath)) continue;
      select ? State.selectedFiles.add(itm.path) : State.selectedFiles.delete(itm.path);
    }
    // Sync folder state: select all → full, deselect all → name
    State.folderStates[folderPath] = select ? 'full' : 'name';
    State._markDirty();
    if (_curTree) { _curTree.invalidate(); _curTree.render(); }
  }

  function _isDescendant(filePath, folderPath) {
    const sep  = filePath.includes('/') ? '/' : '\\';
    return filePath.startsWith(folderPath + sep) || filePath === folderPath;
  }

  function _setFolderState(folderPath, state) {
    State.folderStates[folderPath] = state;
    if (_curTree) {
      _curTree._syncFilesForFolder(folderPath, state);
      // Propagate change upward
      const parent = _curTree._parentFolderPath(folderPath);
      if (parent) _curTree._recomputeFolderState(parent);
    }
    State._markDirty();
    if (_curTree) { _curTree.invalidate(); _curTree.render(); }
  }

  function _showMetaToast(itm) {
    const size = itm.size != null
      ? (itm.size < 1048576
          ? (itm.size / 1024).toFixed(1) + ' KB'
          : (itm.size / 1048576).toFixed(2) + ' MB')
      : '—';
    const date = itm.mtime
      ? new Date(itm.mtime * 1000).toLocaleDateString('en-US')
      : '—';
    _toast(`${itm.name}  •  ${size}  •  ${date}`);
  }

  /* ── Toast ───────────────────────────────────────────────── */
  function _toast(msg) {
    let t = document.getElementById('ctx-toast');
    if (!t) {
      t = document.createElement('div');
      t.id = 'ctx-toast';
      t.className = 'ctx-toast';
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.classList.add('visible');
    clearTimeout(t._tid);
    t._tid = setTimeout(() => t.classList.remove('visible'), 1800);
  }

  return { show, hide };
})();
/**
 * app.js — main orchestrator
 *
 * Responsible for:
 *  - initialising all modules
 *  - navigating between steps
 *  - connecting UI actions to the Python API
 *  - receiving scan data
 */

/* ── Checkmark icon for completed step ── */
const CHECK_SVG = `<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;

/* ── Navigation ── */
const Nav = {
  _current: 0,
  _maxReached: 0,

  go(n) {
    if (n > this._maxReached && n !== 0) return;  // cannot skip forward

    this._current = n;
    if (n > this._maxReached) this._maxReached = n;

    // Screens
    document.querySelectorAll('.screen').forEach((el, i) => {
      el.classList.toggle('active', i === n);
    });

    // Steps
    document.querySelectorAll('.step').forEach((el, i) => {
      el.classList.remove('active', 'done', 'clickable');
      if (i === n) {
        el.classList.add('active');
      } else if (i < n || i <= this._maxReached) {
        el.classList.add('done');
        if (i <= this._maxReached && i !== n) el.classList.add('clickable');
      }
      // Step number: done → checkmark, otherwise number
      const snum = el.querySelector('.snum');
      if (snum) {
        if (i < n) snum.innerHTML = CHECK_SVG;
        else       snum.textContent = i + 1;
      }
    });

    // Side effects on transition
    if (n === 2) { Export.updateSummary(); Export.renderNameChips(); }
  },

  unlock(n) {
    if (n > this._maxReached) this._maxReached = n;
  },

  reset() {
    this._maxReached = 0;
    const el = document.getElementById('export-result');
    if (el) el.style.display = 'none';
    this.go(0);
  },
};

/* ── Checkbox helper ── */
function initCheckbox(id, stateKey, onChange) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.toggle('on', !!State.settings[stateKey]);
  const toggle = () => {
    const val = !el.classList.contains('on');
    el.classList.toggle('on', val);
    State.settings[stateKey] = val;
    window.pywebview?.api?.save_settings({ [stateKey]: val });
    if (onChange) onChange(val);
  };
  const label = el.closest('label');
  if (label) {
    // Listen only on the label; stop propagation so the click doesn't
    // also reach the cb div and fire a second toggle.
    label.addEventListener('click', (e) => {
      e.stopPropagation();
      toggle();
    });
  } else {
    el.addEventListener('click', toggle);
  }
}

function setCheckbox(id, on) {
  document.getElementById(id)?.classList.toggle('on', !!on);
}

/* ── Format cell ── */
function initFmtGrid() {
  document.querySelectorAll('.fmt-cell').forEach(cell => {
    cell.addEventListener('click', () => {
      cell.classList.toggle('selected');
      const dot = cell.querySelector('.fmt-dot');
      if (dot) dot.classList.toggle('on', cell.classList.contains('selected'));
      Export.updateSummary();
      Export.renderNameChips();
      const fmts = [...document.querySelectorAll('.fmt-cell.selected')].map(c => c.dataset.fmt).filter(Boolean);
      window.pywebview?.api?.save_settings({ lastFormats: fmts });
    });
  });
}

/* ── Sort headers ── */
function initSortHeaders() {
  ['name', 'size', 'date'].forEach(col => {
    document.getElementById(`th-${col}`)?.addEventListener('click', () => {
      if (State.sortCol === col) {
        State.sortDir = State.sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        State.sortCol = col;
        State.sortDir = 'asc';
      }
      State.settings.sortCol = State.sortCol;
      State.settings.sortDir = State.sortDir;
      window.pywebview?.api?.save_settings({ sortCol: State.sortCol, sortDir: State.sortDir });
      Tree.updateSortHeadings();
      Tree.invalidate();
      Tree.render();
    });
  });
}


/* ── Keyboard shortcuts ── */
function initKeyboard() {
  document.addEventListener('keydown', e => {
    // Ctrl/Cmd+F → focus search
    if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
      e.preventDefault();
      document.getElementById('search-input')?.focus();
    }
    // Escape → clear search
    if (e.key === 'Escape') {
      const el = document.getElementById('search-input');
      if (el && el.value) {
        el.value = '';
        State.searchQuery = '';
        Tree.invalidate();
        Tree.render();
        Tree.updateStats();
      }
    }
  });
}

/* ── Main init ── */
window.addEventListener('DOMContentLoaded', async () => {

  // Initialize modules
  // Wait for pywebview API (may initialise after DOMContentLoaded)
  await new Promise(resolve => {
    if (window.pywebview?.api) return resolve();
    window.addEventListener('pywebviewready', resolve, { once: true });
    setTimeout(resolve, 2000); // fallback
  });

  Tree.init(document.getElementById('tree'));
  await Filters.init();
  AdvFilter.init();
  Export.init();

  // Navigation — steps are clickable
  document.querySelectorAll('.step[data-step]').forEach(el => {
    el.addEventListener('click', () => {
      const n = parseInt(el.dataset.step);
      Nav.go(n);
    });
  });

  // Navigation buttons
  document.getElementById('btn-back-0')?.addEventListener('click', () => Nav.go(0));
  document.getElementById('btn-next-2')?.addEventListener('click', () => Nav.go(2));
  document.getElementById('btn-back-1')?.addEventListener('click', () => Nav.go(1));

  // Tree — bulk actions
  document.getElementById('btn-select-all')?.addEventListener('click',  () => Tree.selectAll());
  document.getElementById('btn-deselect-all')?.addEventListener('click',() => Tree.deselectAll());
  document.getElementById('btn-name-only')?.addEventListener('click',   () => Tree.setAllFoldersNameOnly());
  document.getElementById('btn-collapse')?.addEventListener('click',    () => Tree.collapseAll());
  document.getElementById('btn-expand')?.addEventListener('click',      () => Tree.expandAll());

  // Scanning
  document.getElementById('btn-browse')?.addEventListener('click', async () => {
    try {
      const path = await window.pywebview.api.browse_directory();
      if (path) document.getElementById('path-input').value = path;
    } catch (e) { console.error(e); }
  });

  document.getElementById('btn-scan')?.addEventListener('click', () => startScan());
  document.getElementById('path-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') startScan();
  });

  // Scan checkboxes
  initCheckbox('cb-hidden', 'inclHidden');
  initCheckbox('cb-system', 'inclSystem');
  document.getElementById('depth-input')?.addEventListener('change', e => {
    const depth = parseInt(e.target.value, 10);
    if (depth >= 1 && depth <= 50) window.pywebview?.api?.save_settings({ lastDepth: depth });
  });

  // Format grid
  initFmtGrid();

  // Sort headers
  initSortHeaders();

  // Keyboard shortcuts
  initKeyboard();

  // Load settings from Python
  try {
    const settings = await window.pywebview.api.get_settings();
    if (settings) {
      State.settings = { ...State.settings, ...settings };
      Theme.set(settings.theme === 'dark' ? 'dark' : 'light');
      setCheckbox('cb-hidden', settings.inclHidden);
      setCheckbox('cb-system', settings.inclSystem);
      Export.applyOptions(settings);
      if (settings.lastDepth) document.getElementById('depth-input').value = settings.lastDepth;
      if (settings.lastPath)   document.getElementById('path-input').value  = settings.lastPath;
      if (settings.lastOutput) document.getElementById('out-input').value   = settings.lastOutput;
      if (settings.lastFormats) {
        document.querySelectorAll('.fmt-cell').forEach(cell => {
          const selected = (settings.lastFormats || []).includes(cell.dataset.fmt);
          cell.classList.toggle('selected', selected);
          const dot = cell.querySelector('.fmt-dot');
          if (dot) dot.classList.toggle('on', selected);
        });
        Export.renderNameChips();
      }
    }
  } catch (e) {
    // Fallback for dev mode without pywebview
    console.warn('pywebview API unavailable, dev mode');
    _devMode();
  }

  Nav.go(0);

  try { await window.pywebview?.api?.ui_ready(); } catch (e) {}
});

/* ── Inline error message (replacement for alert()) ── */
function showScanError(msgs) {
  document.getElementById('scan-path-error')?.remove();
  const list = Array.isArray(msgs) ? msgs : [msgs];
  const err = document.createElement('p');
  err.id = 'scan-path-error';
  err.className = 'scan-error-msg';
  err.innerHTML = list.map((m, i) => (i === 0 ? '<b>Error:</b> ' : '<span style="display:inline-block;width:3em"></span>') + m).join('<br>');
  const footer = document.querySelector('.scan-footer');
  footer?.insertAdjacentElement('beforebegin', err);
}

/* ── Abort progress state on error ── */
function abortScan(msg) {
  const wrap = document.getElementById('scan-progress-wrap');
  const bar  = document.getElementById('scan-progress-bar');
  const btn  = document.getElementById('btn-scan');
  if (bar)  bar.classList.remove('animated');
  if (wrap) wrap.style.display = 'none';
  if (btn)  btn.disabled = false;
  showScanError(msg);
}

/* ── Scanning ── */
function startScan() {
  const path  = document.getElementById('path-input')?.value?.trim();
  const depthRaw = document.getElementById('depth-input')?.value?.trim();
  const depth = parseInt(depthRaw);

  const errs = [];
  if (!path) errs.push('Enter a path.');
  if (!depthRaw || isNaN(depth) || depth < 1 || depth > 50) errs.push('Depth must be a number between 1 and 50.');
  if (errs.length) { showScanError(errs); return; }

  document.getElementById('scan-path-error')?.remove();

  const inclHidden = document.getElementById('cb-hidden')?.classList.contains('on') || false;
  const inclSystem = document.getElementById('cb-system')?.classList.contains('on') || false;

  // Show progress
  const wrap = document.getElementById('scan-progress-wrap');
  const bar  = document.getElementById('scan-progress-bar');
  const txt  = document.getElementById('scan-status-text');
  if (wrap) wrap.style.display = 'flex';
  if (bar)  bar.classList.add('animated');
  if (txt)  txt.textContent = 'Scanning…';

  const btn = document.getElementById('btn-scan');
  if (btn) btn.disabled = true;

  // Call Python — scan runs in a thread, result comes back via onScanDone() from evaluate_js
  window.pywebview.api.scan({
    path, depth, incl_hidden: inclHidden, incl_system: inclSystem
  }).then(result => {
    if (result.errors) {
      abortScan(result.errors);
      return;
    }
    if (result.error) {
      abortScan(result.error);
      return;
    }
    // result.async === true → result will arrive via evaluate_js('onScanDone(...)')
  }).catch(e => {
    abortScan(e?.message ?? String(e));
  });
}

/** Called from Python periodically during scanning */
function onScanProgress(count) {
  const txt = document.getElementById('scan-status-text');
  if (txt) txt.textContent = `Found ${count} files…`;
}

/** Called after scanning completes */
async function onScanDone(result) {
  const { tree, file_count, folder_count, skipped, volume_label } = result;

  Persist.begin();
  State.reset(tree);
  State.volumeLabel = volume_label || '';
  await Filters.init();
  AdvFilter.init();

  Tree._focusIdx     = -1;
  Tree._lastClickIdx = -1;
  State.treeData.forEach(i => { if (i.type === 'folder' && i.lvl > 0) Tree._collapsed.add(i.path); });
  await Persist.restore(result);
  Tree.invalidate();
  Tree.render();
  Tree.updateSortHeadings();

  const txt = document.getElementById('scan-status-text');
  const bar  = document.getElementById('scan-progress-bar');
  const btn  = document.getElementById('btn-scan');
  if (txt) txt.textContent = `Done — ${file_count} files, ${folder_count} folders${skipped ? `, ${skipped} skipped` : ''}.`;
  if (bar) bar.classList.remove('animated');
  if (btn) btn.disabled = false;

  // Show disk name
  const labelEl = document.getElementById('disk-volume-label');
  const labelText = document.getElementById('disk-volume-label-text');
  if (labelEl && labelText) {
    labelText.textContent = volume_label || '';
    labelEl.style.display = volume_label ? '' : 'none';
  }

  Nav.unlock(1);
  Nav.unlock(2);
  Nav.go(1);

  // Save settings
  try {
    window.pywebview.api.save_settings({
      lastPath:   document.getElementById('path-input')?.value || '',
      lastDepth:  result.depth,
      inclHidden: document.getElementById('cb-hidden')?.classList.contains('on'),
      inclSystem: document.getElementById('cb-system')?.classList.contains('on'),
    });
  } catch (e) {}
}

/* ── Dev mode (without pywebview) ── */
function _devMode() {
  // Fake data for browser development
  const fakeSep = '/';
  const base = '/';
  const fake = [
    { lvl:0, type:'folder', name:'SANDISK_32GB',  path:base,                       size:0,    mtime:0 },
    { lvl:1, type:'folder', name:'Photos 2024',   path:base+'/Photos 2024',         size:0,    mtime:0 },
    { lvl:2, type:'file',   name:'DSC_0042.jpg',  path:base+'/Photos 2024/DSC_0042.jpg', size:4404019, mtime:1723420800 },
    { lvl:2, type:'file',   name:'DSC_0043.jpg',  path:base+'/Photos 2024/DSC_0043.jpg', size:3984588, mtime:1723420900 },
    { lvl:2, type:'file',   name:'.DS_Store',     path:base+'/Photos 2024/.DS_Store',    size:6148,    mtime:1704067200 },
    { lvl:1, type:'folder', name:'System',        path:base+'/System',               size:0,    mtime:0 },
    { lvl:1, type:'folder', name:'Documents',     path:base+'/Documents',            size:0,    mtime:0 },
    { lvl:2, type:'file',   name:'presentation.pptx',path:base+'/Documents/presentation.pptx',size:14784921,mtime:1730592000},
    { lvl:2, type:'file',   name:'budget.xlsx',   path:base+'/Documents/budget.xlsx',size:911360,mtime:1736899200},
    { lvl:1, type:'folder', name:'Backup',        path:base+'/Backup',               size:0,    mtime:0 },
    { lvl:2, type:'file',   name:'backup_2024-12-31.zip',path:base+'/Backup/backup_2024-12-31.zip',size:2254857830,mtime:1735603200},
    { lvl:2, type:'file',   name:'readme.txt',    path:base+'/Backup/readme.txt',     size:1024, mtime:1735603200},
  ];

  State.reset(fake);
  State.folderStates[base+'/System']    = 'skip';
  State.folderStates[base+'/Documents'] = 'name';

  document.getElementById('path-input').value  = '';
  document.getElementById('out-input').value   = '';

  Tree.invalidate();
  Tree.render();
  Tree.updateSortHeadings();
  Nav.unlock(2);
  Nav.go(1);
}

/* ── Dark mode toggle ── */
const Theme = {
  init() {
    // Theme may already have been applied by the inline script in <head> — just sync the icons.
    const isDark = document.documentElement.dataset.theme === 'dark';
    document.getElementById('icon-sun').style.display  = isDark ? 'none' : '';
    document.getElementById('icon-moon').style.display = isDark ? '' : 'none';

    document.getElementById('btn-theme-toggle')
      .addEventListener('click', () => this.toggle());
  },

  toggle() {
    const isDark = document.documentElement.dataset.theme === 'dark';
    this.set(isDark ? 'light' : 'dark', true);
  },

  set(theme, persist = false) {
    if (theme === 'dark') {
      document.documentElement.dataset.theme = 'dark';
      document.getElementById('icon-sun').style.display = 'none';
      document.getElementById('icon-moon').style.display = '';
    } else {
      delete document.documentElement.dataset.theme;
      document.getElementById('icon-sun').style.display = '';
      document.getElementById('icon-moon').style.display = 'none';
    }
    try { localStorage.setItem('flashscan-theme', theme); } catch (e) {}
    if (persist) {
      State.settings.theme = theme;
      window.pywebview?.api?.save_settings({ theme });
    }
  }
};

Theme.init();
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
const LOCKED_STEP_HINT = 'Scan a folder first';
const HELD_STEP_HINT   = 'Export in progress';

const STEP_FOCUS_TARGETS = ['path-input', 'tree', 'export-heading'];

function announce(message) {
  const el = document.getElementById('tree-live');
  if (!el) return;
  el.textContent = '';
  setTimeout(() => { el.textContent = message; }, 50);
}

const Nav = {
  _current: 0,
  _maxReached: 0,
  _held: false,

  go(n) {
    if (this._held && n !== this._current) return;  // an export is running
    if (n > this._maxReached && n !== 0) return;  // cannot skip forward

    const changed = n !== this._current;
    this._current = n;
    if (n > this._maxReached) this._maxReached = n;

    // Screens
    document.querySelectorAll('.screen').forEach((el, i) => {
      el.classList.toggle('active', i === n);
    });

    this._renderSteps();

    // Side effects on transition
    if (n === 2) { Export.updateSummary(); Export.renderNameChips(); }

    if (changed) document.getElementById(STEP_FOCUS_TARGETS[n])?.focus();
  },

  unlock(n) {
    if (n > this._maxReached) {
      this._maxReached = n;
      this._renderSteps();
    }
  },

  hold(held) {
    this._held = held;
    this._renderSteps();
  },

  _renderSteps() {
    const n = this._current;
    document.querySelectorAll('.step').forEach((el, i) => {
      const held = this._held && i !== n;
      el.classList.remove('active', 'done', 'clickable');
      if (i === n) {
        el.classList.add('active');
      } else if (i < n || i <= this._maxReached) {
        el.classList.add('done');
        if (i <= this._maxReached && !held) el.classList.add('clickable');
      }

      if (held || i > this._maxReached) {
        el.setAttribute('aria-disabled', 'true');
        el.title = held ? HELD_STEP_HINT : LOCKED_STEP_HINT;
      } else {
        el.removeAttribute('aria-disabled');
        el.removeAttribute('title');
      }
      if (i === n) el.setAttribute('aria-current', 'step');
      else         el.removeAttribute('aria-current');

      // Step number: done → checkmark, otherwise number
      const snum = el.querySelector('.snum');
      if (snum) {
        if (i < n) snum.innerHTML = CHECK_SVG;
        else       snum.textContent = i + 1;
      }
    });
  },

  reset() {
    this._maxReached = 0;
    const el = document.getElementById('export-result');
    if (el) el.style.display = 'none';
    const page = document.querySelector('.export-page');
    if (page) page.scrollTop = 0;
    this.go(0);
  },
};

/* ── Checkbox helper ── */
function initCheckbox(id, stateKey, onChange) {
  const el = document.getElementById(id);
  if (!el) return;
  el.checked = !!State.settings[stateKey];
  el.addEventListener('change', () => {
    State.settings[stateKey] = el.checked;
    window.pywebview?.api?.save_settings({ [stateKey]: el.checked });
    if (onChange) onChange(el.checked);
  });
}

function setCheckbox(id, on) {
  const el = document.getElementById(id);
  if (el) el.checked = !!on;
}

/* ── Step indicator ── */
function initSteps() {
  document.querySelectorAll('.step[data-step]').forEach(el => {
    const open = () => Nav.go(parseInt(el.dataset.step));
    el.addEventListener('click', open);
    el.addEventListener('keydown', e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      open();
    });
  });
}

/* ── Format cell ── */
function syncFmtCell(cell) {
  const on = !!cell.querySelector('.fmt-input')?.checked;
  cell.classList.toggle('selected', on);
  cell.querySelector('.fmt-dot')?.classList.toggle('on', on);
}

function applyFormats(formats) {
  document.querySelectorAll('.fmt-cell').forEach(cell => {
    const input = cell.querySelector('.fmt-input');
    if (input) input.checked = formats.includes(cell.dataset.fmt);
    syncFmtCell(cell);
  });
  Export.syncMdOption();
}

function initFmtGrid() {
  document.querySelectorAll('.fmt-cell').forEach(cell => {
    syncFmtCell(cell);
    cell.querySelector('.fmt-input')?.addEventListener('change', () => {
      syncFmtCell(cell);
      Export.syncMdOption();
      Export.updateSummary();
      Export.renderNameChips();
      window.pywebview?.api?.save_settings({ lastFormats: Export._selectedFormats() });
    });
  });
}

/* ── Modal helpers ── */
function modalEl(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/* ── Confirm dialog ── */
const ConfirmDialog = {
  _open: false,

  show({ title, intro = '', items = [], note = '', confirmLabel = 'OK', cancelLabel = 'Cancel' }) {
    if (this._open) return Promise.resolve(false);
    this._open = true;

    const backdrop = modalEl('div', 'modal-backdrop');
    const dialog   = modalEl('div', 'modal');
    dialog.setAttribute('role', 'alertdialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-labelledby', 'modal-title');
    dialog.setAttribute('aria-describedby', 'modal-desc');

    const heading = modalEl('h2', 'modal-title', title);
    heading.id = 'modal-title';
    const desc = modalEl('p', 'modal-text', intro);
    desc.id = 'modal-desc';
    const list = modalEl('ul', 'modal-list');
    items.forEach(text => list.append(modalEl('li', '', text)));
    const noteEl = modalEl('p', 'modal-note', note);

    const cancel  = modalEl('button', 'btn btn-secondary', cancelLabel);
    const confirm = modalEl('button', 'btn btn-danger', confirmLabel);
    cancel.type = confirm.type = 'button';
    const actions = modalEl('div', 'modal-actions');
    actions.append(cancel, confirm);

    dialog.append(heading, desc, list, noteEl, actions);
    backdrop.append(dialog);

    const previousFocus = document.activeElement;
    document.body.append(backdrop);
    cancel.focus();

    return new Promise(resolve => {
      const close = result => {
        window.removeEventListener('keydown', onKey, true);
        backdrop.remove();
        this._open = false;
        previousFocus?.focus?.();
        resolve(result);
      };
      // Capture phase on window: the tree's shortcuts (Space, Ctrl+A, ...) must not fire behind the dialog.
      const onKey = e => {
        e.stopPropagation();
        if (e.key === 'Escape') {
          e.preventDefault();
          close(false);
        } else if (e.key === 'Tab') {
          e.preventDefault();
          (document.activeElement === cancel ? confirm : cancel).focus();
        }
      };
      window.addEventListener('keydown', onKey, true);
      cancel.addEventListener('click', () => close(false));
      confirm.addEventListener('click', () => close(true));
      backdrop.addEventListener('mousedown', e => { if (e.target === backdrop) close(false); });
    });
  },
};

/* ── Settings and About dialogs ── */
function modalDialog(title, id) {
  const dialog = modalEl('div', 'modal');
  dialog.setAttribute('role', 'dialog');
  dialog.setAttribute('aria-modal', 'true');
  dialog.setAttribute('aria-labelledby', id);
  const heading = modalEl('h2', 'modal-title', title);
  heading.id = id;
  dialog.append(heading);
  return dialog;
}

function showModal(dialog, initialFocus, onClosed, onKeydown) {
  const backdrop = modalEl('div', 'modal-backdrop');
  backdrop.append(dialog);
  const previousFocus = document.activeElement;
  document.body.append(backdrop);
  initialFocus.focus();

  const finish = () => {
    window.removeEventListener('keydown', onKey, true);
    backdrop.remove();
    onClosed();
    previousFocus?.focus?.();
  };
  // Capture phase on window: the tree's shortcuts must not fire behind the dialog.
  const onKey = e => {
    e.stopPropagation();
    onKeydown?.(e);
    if (e.key === 'Escape') {
      e.preventDefault();
      finish();
    } else if (e.key === 'Tab') {
      e.preventDefault();
      const items = [...dialog.querySelectorAll('select, button, input, [tabindex="0"]')]
        .filter(el => !el.closest('[hidden]') && !el.disabled && el.tabIndex >= 0);
      const at    = Math.max(items.indexOf(document.activeElement), 0);
      items[(at + (e.shiftKey ? -1 : 1) + items.length) % items.length].focus();
    }
  };
  window.addEventListener('keydown', onKey, true);
  backdrop.addEventListener('mousedown', e => { if (e.target === backdrop) finish(); });
  return finish;
}

const SettingsDialog = {
  _open: false,

  open() {
    if (this._open || ConfirmDialog._open) return;
    this._open = true;

    const theme    = this._field('settings-theme', 'Theme', Theme.OPTIONS, Theme.mode);
    const list     = this._field('settings-date-format', 'Date format', DateFmt.OPTIONS, DateFmt.mode);
    const exported = this._field(
      'settings-export-date-format', 'Exports', DateFmt.OPTIONS,
      DateFmt.exportMode === 'same' ? DateFmt.mode : DateFmt.exportMode,
    );

    const linked = modalEl('input', 'cb-input sr-only');
    linked.type    = 'checkbox';
    linked.id      = 'settings-date-linked';
    linked.checked = DateFmt.exportMode === 'same';
    const box = modalEl('span', 'cb');
    box.setAttribute('aria-hidden', 'true');
    const linkedRow = modalEl('label', 'cb-row modal-check');
    linkedRow.append(linked, box, modalEl('span', '', 'Use for file list and exports'));

    const preview = modalEl('p', 'modal-text');
    const refresh = () => {
      list.label.textContent = linked.checked ? 'Date format' : 'File list';
      exported.field.hidden  = linked.checked;
      const now   = new Date();
      const shown = linked.checked
        ? `Example: ${DateFmt.formatDate(now)}.`
        : `File list: ${DateFmt.formatDate(now)}. Exports: ${DateFmt.formatDate(now, DateFmt.exportPattern())}.`;
      preview.textContent = `${shown} JSON exports always use ISO 8601.`;
    };
    refresh();

    const saveExportMode = () => {
      State.settings.exportDateFormat = DateFmt.exportMode;
      window.pywebview?.api?.save_settings({ exportDateFormat: DateFmt.exportMode });
      refresh();
    };

    const general = this._panel('settings-panel-general', 'settings-tab-general');
    general.append(theme.field, list.field, linkedRow, exported.field, preview);

    const driveCount = modalEl('span', 'count', '');
    const drives     = this._drivesPanel(n => { driveCount.textContent = n ? ` ${n}` : ''; });

    const tabGeneral = this._tab('settings-tab-general', 'General', general);
    const tabDrives  = this._tab('settings-tab-drives', 'Drive memory', drives);
    tabDrives.append(driveCount);
    const tabs   = [tabGeneral, tabDrives];
    const panels = [general, drives];
    const select = index => tabs.forEach((tab, i) => {
      tab.setAttribute('aria-selected', String(i === index));
      tab.tabIndex = i === index ? 0 : -1;
      panels[i].hidden = i !== index;
    });
    select(0);
    tabs.forEach((tab, i) => tab.addEventListener('click', () => select(i)));

    const tabList = modalEl('div', 'modal-tabs');
    tabList.setAttribute('role', 'tablist');
    tabList.append(...tabs);

    const dialog = modalDialog('Settings', 'settings-title');
    const close  = modalEl('button', 'modal-close', '\u00D7');
    close.type = 'button';
    close.setAttribute('aria-label', 'Close');
    const head = modalEl('div', 'modal-head');
    head.append(dialog.querySelector('.modal-title'), close);
    dialog.append(head, tabList, general, drives);

    const onKeydown = e => {
      const at = tabs.indexOf(document.activeElement);
      if (at < 0 || (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight')) return;
      e.preventDefault();
      const next = (at + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      select(next);
      tabs[next].focus();
    };
    const finish = showModal(dialog, theme.select, () => { this._open = false; }, onKeydown);

    close.addEventListener('click', finish);
    theme.select.addEventListener('change', () => Theme.set(theme.select.value, true));
    list.select.addEventListener('change', () => {
      DateFmt.setMode(list.select.value);
      State.settings.dateFormat = DateFmt.mode;
      window.pywebview?.api?.save_settings({ dateFormat: DateFmt.mode });
      refresh();
      AdvFilter.refreshDateFormat();
      if (State.treeData?.length) Tree.render();
    });
    linked.addEventListener('change', () => {
      if (!linked.checked) exported.select.value = list.select.value;
      DateFmt.setExportMode(linked.checked ? 'same' : exported.select.value);
      saveExportMode();
    });
    exported.select.addEventListener('change', () => {
      DateFmt.setExportMode(exported.select.value);
      saveExportMode();
    });
  },

  _field(id, text, options, value) {
    const select = modalEl('select', 'adv-select');
    select.id = id;
    options.forEach(({ value: optionValue, label }) => {
      const option = modalEl('option', '', label);
      option.value = optionValue;
      select.append(option);
    });
    select.value = value;
    const label = modalEl('label', '', text);
    label.htmlFor = id;
    const field = modalEl('div', 'modal-field');
    field.append(label, select);
    return { select, label, field };
  },

  _panel(id, tabId) {
    const panel = modalEl('div', 'modal-panel');
    panel.id = id;
    panel.setAttribute('role', 'tabpanel');
    panel.setAttribute('aria-labelledby', tabId);
    return panel;
  },

  _tab(id, text, panel) {
    const tab = modalEl('button', 'modal-tab', text);
    tab.type = 'button';
    tab.id = id;
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-controls', panel.id);
    return tab;
  },

  _drivesPanel(onCount) {
    const panel = this._panel('settings-panel-drives', 'settings-tab-drives');
    const intro = modalEl('p', 'modal-text', 'Notes, folder states and selections saved for each drive.');
    const list  = modalEl('ul', 'drive-list');
    list.tabIndex = 0;
    list.setAttribute('aria-label', 'Remembered drives');
    const empty = modalEl('p', 'modal-text', 'No drives remembered yet.');
    const forgetAll = modalEl('button', 'btn btn-secondary', 'Forget all\u2026');
    forgetAll.type = 'button';
    const actions = modalEl('div', 'modal-actions');
    actions.append(forgetAll);
    panel.append(intro, list, empty, actions);

    const show = items => {
      list.replaceChildren(...items.map(item => this._driveRow(item, forget)));
      list.hidden    = !items.length;
      empty.hidden   = !!items.length;
      actions.hidden = !items.length;
      onCount(items.length);
    };
    const load = async () => {
      let items = [];
      try {
        const result = await window.pywebview?.api?.get_profiles?.();
        if (Array.isArray(result)) items = result;
      } catch (e) {}
      show(items);
    };

    const forget = async item => {
      const name = this._driveName(item);
      const isOpen = Persist.active && Persist.volumeId === item.volumeId;
      const confirmed = await ConfirmDialog.show({
        title: `Forget ${name}?`,
        intro: 'Its saved notes, folder states and selections will be deleted.',
        note: isOpen ? 'This is the drive you scanned now, so it is reset as well.' : '',
        confirmLabel: 'Forget',
      });
      if (!confirmed) return;
      try { await window.pywebview?.api?.delete_profile?.(item.volumeId); } catch (e) { console.error(e); }
      this._resetOpenDrive(item.volumeId);
      await load();
    };

    forgetAll.addEventListener('click', async () => {
      const count = list.children.length;
      const confirmed = await ConfirmDialog.show({
        title: 'Forget all drives?',
        intro: `The saved notes, folder states and selections for ${count === 1 ? 'this drive' : `all ${count} drives`} will be deleted.`,
        note: Persist.active
          ? 'The drive you scanned now is reset as well. Your settings are not affected.'
          : 'Your settings are not affected.',
        confirmLabel: 'Forget all',
      });
      if (!confirmed) return;
      try { await window.pywebview?.api?.clear_profiles?.(); } catch (e) { console.error(e); }
      this._resetOpenDrive(null);
      await load();
    });

    panel.hidden = true;
    load();
    return panel;
  },

  // Otherwise the open drive's state would be written back on the next change.
  _resetOpenDrive(volumeId) {
    if (!Persist.active || (volumeId && Persist.volumeId !== volumeId)) return;
    Persist.reset();
    ProfileNote.hide();
    Tree.invalidate();
    Tree.render();
  },

  _driveRow(item, onForget) {
    const name = this._driveName(item);
    const text = modalEl('div', 'drive-text');
    text.append(modalEl('span', 'drive-name', name), modalEl('span', 'drive-meta', this._driveMeta(item)));
    const button = modalEl('button', 'drive-forget');
    button.type = 'button';
    button.dataset.tip = 'Forget this drive';
    button.setAttribute('aria-label', `Forget ${name}`);
    button.append(binIcon());
    button.addEventListener('click', () => onForget(item));
    const row = modalEl('li', 'drive-item');
    row.append(text, button);
    return row;
  },

  _driveName({ label, volumeId }) {
    if (label) return label;
    return volumeId.startsWith('serial:') ? `Unnamed drive (ID ${volumeId.slice(7)})` : volumeId;
  },

  _driveMeta(item, now = Date.now()) {
    const part = (n, one, many) => (n ? `${n} ${n === 1 ? one : many}` : '');
    return [
      part(item.notes, 'note', 'notes'),
      part(item.folders, 'folder state', 'folder states'),
      part(item.excluded, 'excluded file', 'excluded files'),
      `scanned ${this._ago(item.used, now)}`,
    ].filter(Boolean).join(' \u00B7 ');
  },

  _ago(seconds, now) {
    const days = Math.floor((now / 1000 - seconds) / 86400);
    if (days < 1) return 'today';
    if (days === 1) return 'yesterday';
    if (days < 14) return `${days} days ago`;
    if (days < 60) return `${Math.floor(days / 7)} weeks ago`;
    return `${Math.floor(days / 30)} months ago`;
  },
};

function svgNode(tag, attrs) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  Object.entries(attrs).forEach(([name, value]) => node.setAttribute(name, value));
  return node;
}

function binIcon() {
  const svg = svgNode('svg', {
    width: 15, height: 15, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
    'stroke-width': 1.75, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true',
  });
  svg.append(
    svgNode('polyline', { points: '3 6 5 6 21 6' }),
    svgNode('path', { d: 'M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6' }),
    svgNode('path', { d: 'M10 11v6M14 11v6' }),
    svgNode('path', { d: 'M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2' }),
  );
  return svg;
}

function appIcon() {
  const make = svgNode;
  const svg = make('svg', { viewBox: '0 0 256 256', 'aria-hidden': 'true' });
  svg.append(
    make('rect', { width: 256, height: 256, rx: 58, fill: '#2d3b2e' }),
    make('path', {
      d: 'M58 92a14 14 0 0 1 14-14h24a12 12 0 0 1 9 4l11 12h76a14 14 0 0 1 14 14v75a14 14 0 0 1-14 14H72a14 14 0 0 1-14-14z',
      fill: 'none', stroke: '#f0ede6', 'stroke-width': 10, 'stroke-linejoin': 'round',
    }),
    make('path', { d: 'M35 147h186', stroke: '#8fb897', 'stroke-width': 9, 'stroke-linecap': 'round' }),
  );
  return svg;
}

const AboutDialog = {
  _open: false,
  LINKS: [['issues', 'Report an issue'], ['license', 'MIT licence']],

  open() {
    if (this._open || ConfirmDialog._open) return;
    this._open = true;

    const dialog  = modalDialog('FlashScan', 'about-title');
    const icon    = modalEl('span', 'about-icon');
    icon.append(appIcon());
    const version = modalEl('p', 'modal-text');
    version.hidden = true;
    const title = modalEl('div');
    title.append(dialog.firstChild, version);
    const head = modalEl('div', 'about-head');
    head.append(icon, title);

    const note  = modalEl('p', 'modal-text', 'Works offline and sends nothing anywhere.');
    const links = modalEl('div', 'modal-links');
    this.LINKS.forEach(([key, text]) => {
      const button = modalEl('button', 'link-btn', text);
      button.type = 'button';
      button.dataset.link = key;
      links.append(button);
    });

    const close   = modalEl('button', 'btn btn-secondary', 'Close');
    close.type = 'button';
    const actions = modalEl('div', 'modal-actions');
    actions.append(close);

    dialog.append(head, note, links, actions);
    window.pywebview?.api?.get_about?.()
      ?.then(info => {
        if (!info?.version) return;
        version.textContent = `Version ${info.version}`;
        version.hidden = false;
      })
      .catch(() => {});

    const finish = showModal(dialog, close, () => { this._open = false; });
    close.addEventListener('click', finish);
  },
};

document.getElementById('btn-open-settings')?.addEventListener('click', () => SettingsDialog.open());
document.getElementById('btn-about')?.addEventListener('click', () => AboutDialog.open());

/* ── Drive profile note (status bar) ── */
/* ── Scan issues banner: unreadable entries, links and the depth limit ── */
const ScanIssues = {
  KIND_LABEL: {
    folder: 'folder not scanned', file: 'file skipped', date: 'date unknown',
    'link-folder': 'folder link not followed', 'link-file': 'file link not followed',
  },

  init() {
    document.getElementById('scan-issues-toggle')?.addEventListener('click', () => this._toggle());
    document.getElementById('scan-issues-close')?.addEventListener('click', () => {
      this.hide();
      Tree.render();
    });
  },

  show(result) {
    const unreadable = result.unreadable ?? [];
    const links      = (result.links ?? []).map(link => ({
      kind:   `link-${link.kind}`,
      path:   link.path,
      reason: link.target ? `\u2192 ${link.target}` : '',
    }));
    const items     = [...unreadable, ...links];
    const count     = result.unreadable_count ?? 0;
    const linkCount = result.links_skipped ?? 0;
    const tooDeep   = result.beyond_depth ?? 0;
    if (!count && !linkCount && !tooDeep) { this.hide(); return; }

    const parts = [];
    if (count) {
      parts.push(`${count} ${count === 1 ? 'item' : 'items'} couldn\u2019t be read`);
    }
    if (linkCount) {
      parts.push(`${linkCount} ${linkCount === 1 ? 'link' : 'links'} not followed`);
    }
    if (tooDeep) {
      parts.push(`${tooDeep} ${tooDeep === 1 ? 'folder' : 'folders'} below the depth limit (${result.depth}) `
        + `${tooDeep === 1 ? 'wasn\u2019t' : 'weren\u2019t'} scanned`);
    }
    document.getElementById('scan-issues-text').textContent = parts.join(' \u00B7 ');

    const list = document.getElementById('scan-issues-list');
    list.replaceChildren(...items.map(item => this._row(item)));
    const unlisted = (count - unreadable.length) + (linkCount - links.length);
    if (unlisted > 0) {
      const more = document.createElement('li');
      more.textContent = `\u2026 and ${unlisted} more`;
      list.append(more);
    }
    list.style.display = 'none';

    const toggle = document.getElementById('scan-issues-toggle');
    toggle.style.display = items.length ? '' : 'none';
    toggle.textContent = 'show details';
    toggle.setAttribute('aria-expanded', 'false');
    document.getElementById('scan-issues').style.display = '';
  },

  hide() {
    const box = document.getElementById('scan-issues');
    if (box) box.style.display = 'none';
  },

  _row(item) {
    const li     = document.createElement('li');
    const kind   = document.createElement('span');
    const path   = document.createElement('span');
    const reason = document.createElement('span');
    kind.className   = 'scan-issues-kind';
    path.className   = 'scan-issues-path';
    reason.className = 'scan-issues-reason';
    kind.textContent   = this.KIND_LABEL[item.kind] ?? item.kind;
    path.textContent   = item.path;
    path.title         = item.path;
    reason.textContent = item.reason;
    li.append(kind, path, reason);
    return li;
  },

  _toggle() {
    const list   = document.getElementById('scan-issues-list');
    const toggle = document.getElementById('scan-issues-toggle');
    const open   = list.style.display === 'none';
    list.style.display = open ? '' : 'none';
    toggle.textContent = open ? 'hide details' : 'show details';
    toggle.setAttribute('aria-expanded', String(open));
    Tree.render();
  },
};

const ProfileNote = {
  UNDO_MS: 10000,

  _mode:     null,
  _snapshot: null,
  _timer:    null,

  init() {
    document.getElementById('profile-note-action')?.addEventListener('click', () => {
      if (this._mode === 'reset') this.undo();
      else this.reset();
    });
    document.getElementById('btn-reset-profile')?.addEventListener('click', () => this.reset());

    // The room left for the note changes with the window and with every stats update.
    const bar = document.querySelector('.statusbar');
    if (bar && typeof ResizeObserver !== 'undefined') {
      const observer = new ResizeObserver(() => this._fit());
      [bar, bar.querySelector('.spacer'), document.getElementById('profile-note-text')]
        .forEach(el => el && observer.observe(el));
    }
  },

  afterScan(summary) {
    this.hide();
    const btn = document.getElementById('btn-reset-profile');
    if (btn) btn.disabled = !Persist.active;
    if (summary) {
      const title = `restored from last session: ${this._describe(summary)}`;
      this._show('restored', 'restored from last session', 'reset\u2026', 0, title);
    }
  },

  async reset() {
    const info = Persist.summary();
    if (!info) return;
    if (!info.notes && !info.folders && !info.files && !info.expanded && !info.unseen) {
      this._show('info', 'nothing saved yet', '', 4000, 'nothing saved for this drive yet');
      return;
    }
    if (!(await ConfirmDialog.show(this._resetPrompt(info)))) return;

    const snapshot = Persist.reset();
    if (!snapshot) return;
    this._refreshTree();
    this._show('reset', 'saved state reset', 'undo', this.UNDO_MS, 'saved state reset for this drive');
    this._snapshot = snapshot;
  },

  undo() {
    const summary = Persist.undo(this._snapshot);
    this._refreshTree();
    const hasState = summary && (summary.notes || summary.folders || summary.files);
    if (hasState) {
      const title = `saved state restored: ${this._describe(summary)}`;
      this._show('restored', 'saved state restored', 'reset\u2026', 0, title);
    }
    else this.hide();
  },

  hide() {
    clearTimeout(this._timer);
    this._mode = null;
    this._snapshot = null;
    const note = document.getElementById('profile-note');
    if (note) note.style.display = 'none';
  },

  _refreshTree() {
    Tree.invalidate();
    Tree.render();
  },

  _show(mode, text, action, autoHideMs = 0, tooltip = text) {
    clearTimeout(this._timer);
    this._mode = mode;
    const note = document.getElementById('profile-note');
    document.getElementById('profile-note-text').textContent = text;
    document.getElementById('profile-note-action').textContent = action;
    note.title = tooltip;
    note.style.display = 'flex';
    this._fit();
    if (note.classList.contains('is-clipped')) this._toastInstead(mode, tooltip, autoHideMs);
    if (autoHideMs) this._timer = setTimeout(() => this.hide(), autoHideMs);
  },

  _toastInstead(mode, message, autoHideMs) {
    const undo = mode === 'reset' ? { label: 'undo', run: () => this._mode === 'reset' && this.undo() } : null;
    ContextMenu.toast(message, autoHideMs || 4000, undo);
  },

  // Never show a clipped sliver: if the text does not fit in full, hide the whole note.
  _fit() {
    if (!this._mode) return;
    const note  = document.getElementById('profile-note');
    const label = document.getElementById('profile-note-text');
    note.classList.remove('is-clipped');
    if (label.scrollWidth > label.clientWidth + 1) note.classList.add('is-clipped');
  },

  _count(n, one, many) {
    return `${n.toLocaleString()} ${n === 1 ? one : many}`;
  },

  _describe({ notes, folders, files }) {
    return [
      notes   && this._count(notes,   'note',          'notes'),
      folders && this._count(folders, 'folder set',    'folders set'),
      files   && this._count(files,   'file excluded', 'files excluded'),
    ].filter(Boolean).join(' · ');
  },

  _resetPrompt(info) {
    const c = this._count.bind(this);
    return {
      title: 'Reset saved state for this drive?',
      intro: `This clears what FlashScan remembers about ${info.label ? `\u201C${info.label}\u201D` : 'this drive'}:`,
      items: [
        info.notes    && c(info.notes,    'folder note',                                'folder notes'),
        info.folders  && c(info.folders,  'folder set to names only or excluded',       'folders set to names only or excluded'),
        info.files    && c(info.files,    'excluded file',                              'excluded files'),
        info.expanded && c(info.expanded, 'expanded folder',                            'expanded folders'),
        info.unseen   && c(info.unseen,   'saved entry for folders outside this scan',  'saved entries for folders outside this scan'),
      ].filter(Boolean),
      note: 'All files will be selected for export again.\nNothing on the drive, in your exports, or in your settings is changed.\nYou can undo for 10 seconds.',
      confirmLabel: 'Reset',
    };
  },
};

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

/* ── Initial focus ──
   The native webview focuses the first tabbable element when the window is shown,
   which highlights the theme toggle. Ignore focus until the user actually interacts. */
(function suppressInitialFocus() {
  const onFocusIn = e => {
    if (!e.target.closest('.modal')) e.target.blur();
  };
  const stop = () => {
    document.removeEventListener('focusin', onFocusIn, true);
    ['keydown', 'mousedown', 'touchstart'].forEach(t => window.removeEventListener(t, stop, true));
  };
  document.addEventListener('focusin', onFocusIn, true);
  ['keydown', 'mousedown', 'touchstart'].forEach(t => window.addEventListener(t, stop, true));
})();

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
  ProfileNote.init();
  ScanIssues.init();

  initSteps();

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
      if (path) {
        document.getElementById('path-input').value = path;
        clearScanError();
      }
    } catch (e) { console.error(e); }
  });

  document.getElementById('btn-scan')?.addEventListener('click', () => startScan());
  document.getElementById('btn-cancel-scan')?.addEventListener('click', () => cancelScan());
  document.getElementById('path-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') startScan();
  });
  SCAN_FIELDS.forEach(id => document.getElementById(id)?.addEventListener('input', clearScanError));
  document.getElementById('out-input')?.addEventListener('input', () => Export.setOutputInvalid(false));

  // Scan checkboxes
  initCheckbox('cb-hidden', 'inclHidden');
  initCheckbox('cb-system', 'inclSystem');
  document.getElementById('depth-input')?.addEventListener('change', e => {
    const depth = parseDepth(e.target.value);
    if (depth !== null) window.pywebview?.api?.save_settings({ lastDepth: depth });
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
      Theme.set(settings.theme);
      DateFmt.setMode(settings.dateFormat);
      DateFmt.setExportMode(settings.exportDateFormat);
      setCheckbox('cb-hidden', settings.inclHidden);
      setCheckbox('cb-system', settings.inclSystem);
      Export.applyOptions(settings);
      if (settings.lastDepth) document.getElementById('depth-input').value = settings.lastDepth;
      if (settings.lastPath)   document.getElementById('path-input').value  = settings.lastPath;
      if (settings.lastOutput) document.getElementById('out-input').value   = settings.lastOutput;
      if (settings.lastFormats) {
        applyFormats(settings.lastFormats);
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
const SCAN_FIELDS = ['path-input', 'depth-input'];

function fieldOf(msg) {
  return /depth/i.test(msg) ? 'depth-input' : 'path-input';
}

function clearScanError() {
  document.getElementById('scan-path-error')?.replaceChildren();
  SCAN_FIELDS.forEach(id => {
    const el = document.getElementById(id);
    el?.removeAttribute('aria-invalid');
    el?.removeAttribute('aria-describedby');
  });
}

function showScanError(msgs, fields = []) {
  clearScanError();
  const err = document.getElementById('scan-path-error');
  if (!err) return;
  const list = Array.isArray(msgs) ? msgs : [msgs];
  list.forEach((m, i) => {
    if (i > 0) err.append(document.createElement('br'));
    if (i === 0) {
      const label = document.createElement('b');
      label.textContent = 'Error:';
      err.append(label, ' ');
    } else {
      const pad = document.createElement('span');
      pad.style.cssText = 'display:inline-block;width:3em';
      err.append(pad);
    }
    err.append(String(m));
  });
  const invalid = SCAN_FIELDS.filter(id => fields.includes(id));
  invalid.forEach(id => {
    const el = document.getElementById(id);
    el?.setAttribute('aria-invalid', 'true');
    el?.setAttribute('aria-describedby', 'scan-path-error');
  });
  document.getElementById(invalid[0])?.focus();
}

/* ── Scan run state ── */
const Scan = { running: false, cancelling: false };

function setScanBusy(busy) {
  Scan.running = busy;
  if (!busy) Scan.cancelling = false;
  const scanBtn   = document.getElementById('btn-scan');
  const cancelBtn = document.getElementById('btn-cancel-scan');
  if (scanBtn) scanBtn.disabled = busy;
  if (cancelBtn) {
    cancelBtn.disabled = false;
    cancelBtn.style.display = busy ? '' : 'none';
  }
}

/* ── Abort progress state on error ── */
function abortScan(msg, fields) {
  const wrap = document.getElementById('scan-progress-wrap');
  const bar  = document.getElementById('scan-progress-bar');
  if (bar)  bar.classList.remove('animated');
  if (wrap) wrap.style.display = 'none';
  setScanBusy(false);
  showScanError(msg, fields);
}

/* ── Scanning ── */
function parseDepth(raw) {
  const text = String(raw ?? '').trim();
  const depth = /^[0-9]{1,3}$/.test(text) ? Number(text) : NaN;
  return depth >= 1 && depth <= 50 ? depth : null;
}

function startScan() {
  if (Scan.running) return;

  const pathField = document.getElementById('path-input');
  const path  = cleanPath(pathField?.value);
  if (pathField) pathField.value = path;
  const depth = parseDepth(document.getElementById('depth-input')?.value);

  const errs = [];
  const fields = [];
  if (!path) { errs.push('Enter a path.'); fields.push('path-input'); }
  if (depth === null) {
    errs.push('Depth must be a whole number between 1 and 50.');
    fields.push('depth-input');
  }
  if (errs.length) { showScanError(errs, fields); return; }

  clearScanError();

  const inclHidden = document.getElementById('cb-hidden')?.checked || false;
  const inclSystem = document.getElementById('cb-system')?.checked || false;

  // Show progress
  const wrap = document.getElementById('scan-progress-wrap');
  const bar  = document.getElementById('scan-progress-bar');
  const txt  = document.getElementById('scan-status-text');
  if (wrap) wrap.style.display = 'flex';
  if (bar)  bar.classList.add('animated');
  if (txt)  txt.textContent = 'Scanning…';

  setScanBusy(true);

  // Call Python — scan runs in a thread, result comes back via onScanDone() from evaluate_js
  window.pywebview.api.scan({
    path, depth, incl_hidden: inclHidden, incl_system: inclSystem
  }).then(result => {
    if (result.errors) {
      abortScan(result.errors, result.errors.map(fieldOf));
      return;
    }
    if (result.error) {
      abortScan(result.error, ['path-input']);
      return;
    }
    // result.busy: a scan is already running, the UI keeps showing it
    // result.async === true → result will arrive via evaluate_js('onScanDone(...)')
    // Cancel clicked before the scan was registered in Python
    if (result.async && Scan.cancelling) window.pywebview.api.cancel_scan();
  }).catch(e => {
    console.error(e);
    abortScan(UNEXPECTED_ERROR);
  });
}

function cancelScan() {
  if (!Scan.running || Scan.cancelling) return;
  Scan.cancelling = true;
  const cancelBtn = document.getElementById('btn-cancel-scan');
  const txt = document.getElementById('scan-status-text');
  if (cancelBtn) cancelBtn.disabled = true;
  if (txt) txt.textContent = 'Cancelling…';
  window.pywebview.api.cancel_scan().catch(e => console.error(e));
}

/** Called from Python periodically during scanning */
function onScanProgress(count) {
  if (Scan.cancelling) return;
  const txt = document.getElementById('scan-status-text');
  if (txt) txt.textContent = `Found ${count} files…`;
}

/** Called from Python after cancel_scan() stopped the scan */
function onScanCancelled() {
  const txt = document.getElementById('scan-status-text');
  const bar = document.getElementById('scan-progress-bar');
  if (txt) txt.textContent = 'Scan cancelled.';
  if (bar) bar.classList.remove('animated');
  setScanBusy(false);
}

/** Called after scanning completes */
async function onScanDone(result) {
  try {
    if (result.error) {
      abortScan(result.error);
      return;
    }
    await applyScanResult(result);
  } finally {
    setScanBusy(false);
  }
}

async function applyScanResult(result) {
  const { tree, file_count, folder_count, skipped, unreadable_count, links_skipped, volume_label } = result;

  Persist.begin();
  State.reset(tree);
  State.scanId = result.scan_id ?? null;
  State.volumeLabel = volume_label || '';
  await Filters.init();
  AdvFilter.init();

  Tree._focusIdx     = -1;
  Tree._lastClickIdx = -1;
  State.treeData.forEach(i => { if (i.type === 'folder' && i.lvl > 0) Tree._collapsed.add(i.path); });
  const restored = await Persist.restore(result);
  ScanIssues.show(result);
  Tree.invalidate();
  Tree.render();
  Tree.updateSortHeadings();
  ProfileNote.afterScan(restored);

  const txt = document.getElementById('scan-status-text');
  const bar  = document.getElementById('scan-progress-bar');
  const summary = `Done — ${file_count} files, ${folder_count} folders`
    + `${skipped ? `, ${skipped} skipped` : ''}${unreadable_count ? `, ${unreadable_count} unreadable` : ''}`
    + `${links_skipped ? `, ${links_skipped} ${links_skipped === 1 ? 'link' : 'links'} not followed` : ''}.`;
  if (txt) txt.textContent = summary;
  if (bar) bar.classList.remove('animated');

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
  announce(summary);

  // Save settings
  try {
    window.pywebview.api.save_settings({
      lastPath:   document.getElementById('path-input')?.value || '',
      lastDepth:  result.depth,
      inclHidden: document.getElementById('cb-hidden')?.checked,
      inclSystem: document.getElementById('cb-system')?.checked,
    });
  } catch (e) {}
}

/* ── Dev mode (without pywebview) ── */
function _devMode() {
  // Fake data for browser development
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

/* ── Theme ── */
const Theme = {
  OPTIONS: [
    { value: 'light',  label: 'Light' },
    { value: 'dark',   label: 'Dark' },
    { value: 'system', label: 'System default' },
  ],
  mode: 'light',

  init() {
    let stored;
    try { stored = localStorage.getItem('flashscan-theme'); } catch (e) {}
    this.mode = this.normalize(stored);
    this.apply();

    document.getElementById('btn-theme-toggle')
      .addEventListener('click', () => this.toggle());
    window.matchMedia?.('(prefers-color-scheme: dark)')
      .addEventListener?.('change', () => this._onSystemChange());
  },

  normalize(mode) {
    return this.OPTIONS.some(o => o.value === mode) ? mode : 'light';
  },

  systemIsDark() {
    return !!window.matchMedia?.('(prefers-color-scheme: dark)').matches;
  },

  isDark() {
    return this.mode === 'dark' || (this.mode === 'system' && this.systemIsDark());
  },

  apply() {
    const dark = this.isDark();
    if (dark) document.documentElement.dataset.theme = 'dark';
    else      delete document.documentElement.dataset.theme;
    document.getElementById('icon-sun').style.display  = dark ? 'none' : '';
    document.getElementById('icon-moon').style.display = dark ? '' : 'none';
  },

  toggle() {
    this.set(this.isDark() ? 'light' : 'dark', true);
  },

  set(mode, persist = false) {
    this.mode = this.normalize(mode);
    this.apply();
    try { localStorage.setItem('flashscan-theme', this.mode); } catch (e) {}
    if (persist) {
      State.settings.theme = this.mode;
      window.pywebview?.api?.save_settings({ theme: this.mode });
    }
  },

  _onSystemChange() {
    if (this.mode === 'system') this.apply();
  },
};

Theme.init();

function toastOpenFailure(what, outcome) {
  const message = outcome?.error ? `Could not open ${what}. ${outcome.error}` : UNEXPECTED_ERROR;
  console.error(message);
  ContextMenu.toast(message, 6000);
}

document.addEventListener('click', async e => {
  const link = e.target.closest?.('[data-link]');
  if (!link) return;
  e.preventDefault();
  try {
    const r = await window.pywebview?.api?.open_external(link.dataset.link);
    if (!r || r.error) toastOpenFailure('the link', r);
  } catch (err) {
    console.error(err);
    toastOpenFailure('the link');
  }
});

document.getElementById('btn-open-log')?.addEventListener('click', async () => {
  try {
    const r = await window.pywebview?.api?.open_log_folder();
    if (!r || r.error) toastOpenFailure('the log folder', r);
  } catch (e) {
    console.error(e);
    toastOpenFailure('the log folder');
  }
});
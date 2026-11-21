/**
 * export.js — communication with the Python backend for export
 *
 * Calls window.pywebview.api.export() with the selection only (the tree lives in Python).
 * The files are written in a Python thread: onExportProgress() fills the progress bar and
 * onExportDone() shows the result. Also updates the summary box on the export screen.
 */

const STEM_MAX = 150;
const STEM_INVALID = /[\\/:*?"<>|\u0000-\u001f]/g;
const STEM_SPACES = /[ \u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/g;
const STEM_EDGES = /^[ .]+|[ .]+$/g;
const STEM_DEVICE = /^(?:con|prn|aux|nul|(?:com|lpt)[1-9\u00b9\u00b2\u00b3])$/i;

const Export = {
  // stem overrides keyed by format: { MD: "my_report", HTML: "report" }
  _nameOverrides: {},

  _optionKeys: {
    'chk-include-size': 'exportIncludeSize',
    'chk-include-date': 'exportIncludeDate',
    'chk-md-toggles':   'exportMdToggles',
  },

  init() {
    document.getElementById('btn-export')?.addEventListener('click', () => this.doExport());
    document.getElementById('btn-browse-out')?.addEventListener('click', () => this.browseOutput());

    // Advanced options toggle
    const toggle = document.getElementById('adv-export-toggle');
    const body   = document.getElementById('adv-export-body');
    if (toggle && body) {
      toggle.addEventListener('click', () => {
        const open = toggle.getAttribute('aria-expanded') === 'true';
        toggle.setAttribute('aria-expanded', String(!open));
        body.style.display = open ? 'none' : 'flex';
      });
    }

    Object.entries(this._optionKeys).forEach(([id, key]) => {
      document.getElementById(id)?.addEventListener('change', e => {
        window.pywebview?.api?.save_settings({ [key]: e.target.checked });
      });
    });
  },

  applyOptions(settings) {
    Object.entries(this._optionKeys).forEach(([id, key]) => {
      const el = document.getElementById(id);
      if (el) el.checked = settings[key] !== false;
    });
  },

  _defaultStem(fmt) {
    const now      = new Date();
    const pad      = n => String(n).padStart(2, '0');
    const ts       = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    return this._sanitizeStem(`${ts}_${this._diskName()}_LIST`);
  },

  // Must stay identical to _safe_stem in api.py (tests/stem_cases.json checks both)
  _sanitizeStem(raw) {
    let text = String(raw ?? '').replace(STEM_INVALID, '').replace(STEM_SPACES, ' ').replace(STEM_EDGES, '');
    if (STEM_DEVICE.test(text.split('.')[0].replace(/ +$/, ''))) text = '_' + text;
    return Array.from(text).slice(0, STEM_MAX).join('').replace(STEM_EDGES, '');
  },

  _diskName() {
    if (State.volumeLabel) return State.volumeLabel;
    const path  = document.getElementById('path-input')?.value || '';
    const parts = path.replace(/\\/g, '/').split('/').filter(Boolean);
    return parts[parts.length - 1] || 'DISK';
  },

  _selectedFormats() {
    return [...document.querySelectorAll('.fmt-cell')]
      .filter(el => el.querySelector('.fmt-input')?.checked)
      .map(el => el.dataset.fmt)
      .filter(Boolean);
  },

  syncMdOption() {
    const row = document.getElementById('adv-md-toggles');
    if (row) row.hidden = !this._selectedFormats().includes('MD');
  },

  _advOptions() {
    return {
      include_size: document.getElementById('chk-include-size')?.checked !== false,
      include_date: document.getElementById('chk-include-date')?.checked !== false,
      md_toggles:   document.getElementById('chk-md-toggles')?.checked !== false,
    };
  },

  /** Returns { MD: "my_stem", HTML: "other_stem", … } for selected formats. */
  _customNames() {
    const names = {};
    this._selectedFormats().forEach(fmt => {
      const stem  = this._nameOverrides[fmt];
      const clean = stem ? this._sanitizeStem(stem) : '';
      names[fmt]  = clean || this._defaultStem(fmt);
    });
    return names;
  },

  // ── Summary box ────────────────────────────────────────────────

  /** Updates the summary box when switching to screen 2 */
  updateSummary() {
    const { count, size, nameOnly, empty } = State.exportStats();
    const fmts = this._selectedFormats();

    const parts = [`<strong>${count} files</strong>`];
    if (size)     parts.push(fmtSize(size));
    if (nameOnly) parts.push(namesOnlyLabel(nameOnly));
    if (empty)    parts.push('<span class="export-warn">⚠ nothing selected to export</span>');
    if (fmts.length) parts.push(`format: <strong>${escapeHtml(fmts.join(', '))}</strong>`);
    else             parts.push('<span class="export-warn">⚠ no format selected</span>');

    const extMap = { MD: 'md', HTML: 'html', JSON: 'json', TXT: 'txt' };

    const fnamesHtml = fmts.length
      ? '<span class="summary-fnames">' + fmts.map(fmt => {
          const stem  = escapeHtml(this._nameOverrides[fmt] || this._defaultStem(fmt));
          const ext   = escapeHtml(extMap[fmt] || fmt.toLowerCase());
          const eFmt  = escapeHtml(fmt);
          return `<span class="summary-fname-row" data-fmt="${eFmt}">` +
            `<span class="summary-fname-text">` +
              `<span class="summary-fname-pencil"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></span>` +
              `<span class="summary-fname-name">${stem}<span class="summary-fname-ext">.${ext}</span></span>` +
            `</span>` +
            `<span class="summary-fname-edit" style="display:none;">` +
              `<input class="summary-fname-input" value="${stem}" maxlength="${STEM_MAX}" spellcheck="false" data-fmt="${eFmt}" data-ext="${ext}">` +
              `<span class="summary-fname-ext-static">.${ext}</span>` +
            `</span>` +
          `</span>`;
        }).join('') + '</span>'
      : '—';

    const el = document.getElementById('export-summary');
    if (!el) return;

    el.innerHTML = parts.join(' · ')
      + `<br><span class="summary-output-label">output:</span><br>${fnamesHtml}`;

    // Wire up inline editing on each filename row
    el.querySelectorAll('.summary-fname-row').forEach(row => {
      const fmt      = row.dataset.fmt;
      const textEl   = row.querySelector('.summary-fname-text');
      const editEl   = row.querySelector('.summary-fname-edit');
      const input    = row.querySelector('.summary-fname-input');
      const ext      = input?.dataset.ext || '';

      const enterEdit = () => {
        textEl.style.display = 'none';
        editEl.style.display = 'inline-flex';
        input.style.width = Math.max(input.value.length, 4) + 'ch';
        input.focus();
        input.select();
      };

      const commitEdit = () => {
        const clean = this._sanitizeStem(input.value) || this._defaultStem(fmt);
        input.value = clean;
        input.style.width = Math.max(clean.length, 4) + 'ch';
        this._nameOverrides[fmt] = clean;
        // Update the text label without re-rendering the whole summary
        textEl.innerHTML = `<span class="summary-fname-pencil"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></span><span class="summary-fname-name">${escapeHtml(clean)}<span class="summary-fname-ext">.${escapeHtml(ext)}</span></span>`;
        editEl.style.display = 'none';
        textEl.style.display = '';
      };

      textEl.addEventListener('click', enterEdit);
      input.addEventListener('input', () => {
        input.style.width = Math.max(input.value.length, 4) + 'ch';
      });
      input.addEventListener('blur', commitEdit);
      input.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
        if (e.key === 'Escape') {
          input.value = this._nameOverrides[fmt] || this._defaultStem(fmt);
          input.blur();
        }
      });
    });
  },

  // ── Stub kept for callers in app.js ───────────────────────────
  renderNameChips() {},

  // ── Browse / Export ───────────────────────────────────────────

  async browseOutput() {
    try {
      const dir = await window.pywebview.api.browse_directory();
      if (dir) {
        const el = document.getElementById('out-input');
        if (el) el.value = dir;
        this.setOutputInvalid(false);
        window.pywebview?.api?.save_settings({ lastOutput: dir });
      }
    } catch (e) {
      console.error('browseOutput error', e);
    }
  },

  _running: false,

  async doExport() {
    if (this._running) return;

    const fmts   = this._selectedFormats();
    const outField = document.getElementById('out-input');
    const outDir = cleanPath(outField?.value);
    if (outField) outField.value = outDir;
    this.setOutputInvalid(false);

    if (!fmts.length) {
      this._showResult('Select at least one format.', 'error');
      return;
    }
    if (State.exportStats().empty) {
      this._showResult('Nothing selected to export.', 'error');
      return;
    }
    if (!outDir) {
      this._showResult('Enter an output folder.', 'error');
      this.setOutputInvalid(true);
      return;
    }

    this._setRunning(true);
    try {
      const adv = this._advOptions();
      const result = await window.pywebview.api.export({
        scan_id:      State.scanId,
        formats:      fmts,
        output_dir:   outDir,
        selection:    State.selectionDelta(),
        include_size: adv.include_size,
        include_date: adv.include_date,
        md_toggles:   adv.md_toggles,
        date_pattern: DateFmt.exportPattern(),
        custom_names: this._customNames(),
      });

      if (result.async) return;  // progress and result arrive via onExportProgress / onExportDone

      this._setRunning(false);
      if (result.busy) this._showResult('An export is already running.', 'error');
      else             this._showResult('Error: ' + (result.error || 'unknown error'), 'error');
      if (result.field === 'output_dir') this.setOutputInvalid(true);
    } catch (e) {
      this._setRunning(false);
      console.error(e);
      this._showResult(UNEXPECTED_ERROR, 'error');
    }
  },

  setOutputInvalid(invalid) {
    const el = document.getElementById('out-input');
    if (!el) return;
    if (invalid) {
      el.setAttribute('aria-invalid', 'true');
      el.setAttribute('aria-describedby', 'export-result');
      el.focus({ preventScroll: true });
    } else {
      el.removeAttribute('aria-invalid');
      el.removeAttribute('aria-describedby');
    }
  },

  _setRunning(running) {
    this._running = running;
    Nav.hold(running);
    const back = document.getElementById('btn-back-1');
    if (back) back.disabled = running;
    const btn  = document.getElementById('btn-export');
    const wrap = document.getElementById('export-progress-wrap');
    const bar  = document.getElementById('export-progress-bar');
    const txt  = document.getElementById('export-status-text');
    if (running) {
      if (btn)  { btn.disabled = true; btn.textContent = 'Exporting…'; }
      if (wrap) { wrap.style.display = 'flex'; this._reveal(wrap); }
      if (bar)  { bar.style.width = ''; bar.classList.add('animated'); }
      if (txt)  txt.textContent = 'Preparing…';
      const exportResult = document.getElementById('export-result');
      if (exportResult) exportResult.style.display = 'none';
    } else {
      if (btn)  { btn.disabled = false; btn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> export'; }
      if (bar)  bar.classList.remove('animated');
      if (wrap) wrap.style.display = 'none';
    }
  },

  /** Called from Python while the files are being written */
  onProgress(done, total, fmt) {
    if (!this._running) return;
    const bar = document.getElementById('export-progress-bar');
    const txt = document.getElementById('export-status-text');
    const pct = total ? Math.min(100, Math.round(done / total * 100)) : 100;
    if (bar) { bar.classList.remove('animated'); bar.style.width = `${pct}%`; }
    if (txt) txt.textContent = `Writing ${fmt}… ${pct} %`;
  },

  /** Called from Python when all formats are written (or the export failed) */
  onDone(result) {
    this._setRunning(false);
    if (result.success) {
      this._showResultFiles(result.saved || [], result.errors || []);
    } else {
      const detail = result.error || (result.errors || []).join('; ') || 'unknown error';
      this._showResult('Error: ' + detail, 'error');
    }
  },

  async _fileAction(method, path, phrase) {
    let outcome;
    try { outcome = await window.pywebview?.api?.[method]?.(path); }
    catch (e) { outcome = { error: String(e) }; }
    const name = path.replace(/.*[/\\]/, '');
    this._fileNote(outcome?.error ? `Could not ${phrase.replace('{name}', name)}. ${outcome.error}` : '');
  },

  _fileNote(text) {
    const el = document.getElementById('export-result');
    let note = el?.querySelector('.export-file-note');
    if (!text) {
      note?.remove();
      return;
    }
    if (!note) {
      note = document.createElement('div');
      note.className = 'export-errors export-file-note';
      note.setAttribute('role', 'alert');
      const newScan = el.querySelector('.export-new-scan-row');
      if (newScan) newScan.before(note);
      else el.append(note);
    }
    note.textContent = text;
  },

  _reveal(el) {
    el.scrollIntoView?.({ block: 'nearest' });
  },

  _showResult(msg, type) {
    const el = document.getElementById('export-result');
    if (!el) return;
    el.style.display = '';
    el.className     = `export-result ${type}`;
    el.textContent   = msg;
    this._reveal(el);
  },

  _showResultFiles(saved, errors) {
    const el = document.getElementById('export-result');
    if (!el) return;
    el.style.display = '';
    el.className     = 'export-result success';

    const errHtml = errors.length
      ? `<span class="export-errors">${errors.map(escapeHtml).join('<br>')}</span>`
      : '';

    el.innerHTML = `<span class="export-saved-label">Saved:</span>${
      saved.map((p, i) => {
        const name  = escapeHtml(p.replace(/.*[/\\]/, ''));
        const ePath = escapeHtml(p);
        return `<span class="export-file-row">
          <a class="export-file-link" data-path="${ePath}" data-idx="${i}" title="Open file">${name}</a>
          <span class="export-file-actions">
            <a class="export-file-open" data-path="${ePath}" data-idx="${i}" title="Open file"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg></a>
            <a class="export-file-reveal" data-path="${ePath}" data-idx="${i}" title="Show in Explorer"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></a>
          </span>
        </span>`;
      }).join('')
    }${errHtml}<div class="export-new-scan-row"><button class="btn btn-secondary" id="btn-new-scan">← new scan</button></div>`;

    el.querySelectorAll('.export-file-link, .export-file-open').forEach(a => {
      a.addEventListener('click', () => this._fileAction('open_path', a.dataset.path, 'open {name}'));
    });
    el.querySelectorAll('.export-file-reveal').forEach(a => {
      a.addEventListener('click', () => this._fileAction('reveal_in_explorer', a.dataset.path, 'show {name} in its folder'));
    });

    document.getElementById('btn-new-scan')?.addEventListener('click', () => Nav.reset());
    this._reveal(el);
  },
};

function onExportProgress(done, total, fmt) { Export.onProgress(done, total, fmt); }
function onExportDone(result) { Export.onDone(result); }

/** fmtSize available globally (defined in tree.js, loaded earlier) */
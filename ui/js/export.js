/**
 * export.js — communication with the Python backend for export
 *
 * Calls window.pywebview.api.export() and displays the result.
 * Also updates the summary box on the export screen.
 */

const Export = {
  // stem overrides keyed by format: { MD: "my_report", HTML: "report" }
  _nameOverrides: {},

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

    // Custom checkbox toggles
    ['chk-include-size', 'chk-include-date'].forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener('click', () => {
        const checked = el.dataset.checked !== 'false';
        el.dataset.checked = String(!checked);
        el.querySelector('.cb').classList.toggle('on', !checked);
      });
    });
  },

  _defaultStem(fmt) {
    const ts       = new Date().toISOString().slice(0, 10);
    const diskName = this._diskName();
    return `${ts}_${diskName}_LIST`  },

  _sanitizeStem(raw) {
    return raw.replace(/[\/\\:*?"<>|]/g, '').replace(/\s+/g, ' ').trim();
  },

  _diskName() {
    if (State.volumeLabel) return State.volumeLabel;
    const path  = document.getElementById('path-input')?.value || '';
    const parts = path.replace(/\\/g, '/').split('/').filter(Boolean);
    return parts[parts.length - 1] || 'DISK';
  },

  _selectedFormats() {
    return [...document.querySelectorAll('.fmt-cell.selected')]
      .map(el => el.dataset.fmt)
      .filter(Boolean);
  },

  _advOptions() {
    return {
      include_size: document.getElementById('chk-include-size')?.dataset.checked !== 'false',
      include_date: document.getElementById('chk-include-date')?.dataset.checked !== 'false',
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
    const { count, size, nameOnly } = State.exportStats();
    const fmts = this._selectedFormats();

    let parts = [`<strong>${count} files</strong>`];
    if (size)     parts.push(fmtSize(size));
    if (nameOnly) parts.push(`${nameOnly} folders name only`);
    if (fmts.length) parts.push(`format: <strong>${fmts.join(', ')}</strong>`);
    else             parts.push('<span class="export-warn">⚠ no format selected</span>');

    const extMap = { MD: 'md', HTML: 'html', JSON: 'json', TXT: 'txt' };

    const fnamesHtml = fmts.length
      ? '<span class="summary-fnames">' + fmts.map(fmt => {
          const stem = this._nameOverrides[fmt] || this._defaultStem(fmt);
          const ext  = extMap[fmt] || fmt.toLowerCase();
          return `<span class="summary-fname-row" data-fmt="${fmt}">` +
            `<span class="summary-fname-text">` +
              `<span class="summary-fname-pencil"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></span>` +
              `<span class="summary-fname-name">${stem}<span class="summary-fname-ext">.${ext}</span></span>` +
            `</span>` +
            `<span class="summary-fname-edit" style="display:none;">` +
              `<input class="summary-fname-input" value="${stem}" spellcheck="false" data-fmt="${fmt}" data-ext="${ext}">` +
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
        textEl.innerHTML = `<span class="summary-fname-pencil"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></span><span class="summary-fname-name">${clean}<span class="summary-fname-ext">.${ext}</span></span>`;
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
        window.pywebview?.api?.save_settings({ lastOutput: dir });
      }
    } catch (e) {
      console.error('browseOutput error', e);
    }
  },

  async doExport() {
    const fmts   = this._selectedFormats();
    const outDir = document.getElementById('out-input')?.value?.trim();

    if (!fmts.length) {
      this._showResult('Select at least one format.', 'error');
      return;
    }
    if (!outDir) {
      this._showResult('Enter an output folder.', 'error');
      document.getElementById('out-input')?.focus();
      return;
    }

    const btn  = document.getElementById('btn-export');
    const wrap = document.getElementById('export-progress-wrap');
    const bar  = document.getElementById('export-progress-bar');
    const txt  = document.getElementById('export-status-text');
    try {
      if (btn)  { btn.disabled = true; btn.textContent = 'Exporting…'; }
      if (wrap) wrap.style.display = 'flex';
      if (bar)  bar.classList.add('animated');
      if (txt)  txt.textContent = 'Exporting…';
      const exportResult = document.getElementById('export-result');
      if (exportResult) exportResult.style.display = 'none';

      const adv = this._advOptions();
      const payload = {
        formats:        fmts,
        output_dir:     outDir,
        path:           document.getElementById('path-input')?.value?.trim() || '',
        volume_label:   State.volumeLabel || '',
        tree:           State.treeData,
        folder_states:  State.folderStates,
        selected_files: [...State.selectedFiles],
        active_exts:    State.activeExts ? [...State.activeExts] : null,
        include_size:   adv.include_size,
        include_date:   adv.include_date,
        custom_names:   this._customNames(),
      };

      const result = await window.pywebview.api.export(payload);

      if (result.success) {
        this._showResultFiles(result.saved || [], result.errors || []);
      } else {
        this._showResult('Error: ' + (result.error || 'unknown error'), 'error');
      }
    } catch (e) {
      this._showResult('Export error: ' + e.message, 'error');
    } finally {
      if (btn)  { btn.disabled = false; btn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> export'; }
      if (bar)  bar.classList.remove('animated');
      if (wrap) wrap.style.display = 'none';
    }
  },

  _showResult(msg, type) {
    const el = document.getElementById('export-result');
    if (!el) return;
    el.style.display = '';
    el.className     = `export-result ${type}`;
    el.textContent   = msg;
  },

  _showResultFiles(saved, errors) {
    const el = document.getElementById('export-result');
    if (!el) return;
    el.style.display = '';
    el.className     = 'export-result success';

    const errHtml = errors.length
      ? `<span class="export-errors">${errors.join('<br>')}</span>`
      : '';

    el.innerHTML = `<span class="export-saved-label">Saved:</span>${
      saved.map((p, i) => {
        const name = p.replace(/.*[\/\\]/, '');
        return `<span class="export-file-row">
          <a class="export-file-link" data-path="${p}" data-idx="${i}" title="Open file">${name}</a>
          <span class="export-file-actions">
            <a class="export-file-open" data-path="${p}" data-idx="${i}" title="Open file"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg></a>
            <a class="export-file-reveal" data-path="${p}" data-idx="${i}" title="Show in Finder / Explorer"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></a>
          </span>
        </span>`;
      }).join('')
    }${errHtml}<div class="export-new-scan-row"><button class="btn btn-secondary" id="btn-new-scan">← new scan</button></div>`;

    el.querySelectorAll('.export-file-link, .export-file-open').forEach(a => {
      a.addEventListener('click', () => window.pywebview.api.open_path(a.dataset.path));
    });
    el.querySelectorAll('.export-file-reveal').forEach(a => {
      a.addEventListener('click', () => window.pywebview.api.reveal_in_explorer(a.dataset.path));
    });

    document.getElementById('btn-new-scan')?.addEventListener('click', () => Nav.reset());
  },
};

/** fmtSize available globally (defined in tree.js, loaded earlier) */
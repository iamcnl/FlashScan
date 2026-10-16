/**
 * filters.js — extensions and search
 */

const ALL_EXTENSIONS = {
  'Images':     ['jpg','jpeg','png','gif','bmp','webp','tiff','tif','svg','ico','heic','heif','raw','cr2','nef','arw','dng','psd','ai','eps','avif','jxl'],
  'Video':       ['mp4','mkv','avi','mov','wmv','flv','webm','m4v','mpg','mpeg','3gp','ts','mts','m2ts','vob','ogv','divx','rmvb','asf','f4v'],
  'Audio':       ['mp3','wav','flac','aac','ogg','m4a','wma','opus','aiff','ape','mid','midi','amr','ac3','dts','ra','mka','tta','wv'],
  'Documents':   ['pdf','doc','docx','odt','rtf','txt','md','tex','pages','wpd','wps','epub','mobi','azw','azw3','djvu','xps','oxps','fb2'],
  'Spreadsheets':     ['xls','xlsx','ods','csv','tsv','numbers','xlsm','xlsb','xltx','xltm'],
  'Presentation':  ['ppt','pptx','odp','key','pps','ppsx','pptm'],
  'Archives':     ['zip','rar','7z','tar','gz','bz2','xz','iso','dmg','pkg','deb','rpm','cab','lzh','lz4','zst','br','tgz','tbz2'],
  'Code':         ['py','js','ts','jsx','tsx','html','htm','css','scss','sass','php','java','c','cpp','h','cs','go','rs','rb','swift','kt','dart','lua','r','sh','bat','ps1','sql','xml','json','yaml','yml','toml','ini','cfg','conf','env'],
  'Databases':    ['db','sqlite','sqlite3','mdb','accdb','dbf','frm','ibd','mdf','ldf','bak'],
  'Fonts':       ['ttf','otf','woff','woff2','eot','fon'],
  'Executables': ['exe','msi','app','apk','ipa','dll','so','dylib','sys','inf','com','vbs','scr'],
  '3D / CAD':    ['obj','fbx','stl','blend','3ds','dae','gltf','glb','ply','step','iges','dwg','dxf','skp'],
  'Data':        ['parquet','hdf5','h5','mat','npy','npz','pkl','feather','arrow','nc','fits','zarr'],
  'Other':     ['log','bak','tmp','swp','lock','pid','dat','bin','hex','img','vmdk','vhd','vhdx','ova','ovf'],
};

const CUSTOM_GROUP = 'Custom';

const Filters = {
  _extState:    {},
  _customExts:  [],   // custom extensions added by user
  _searchTimer: null,
  _filterTimer: null,

  async init() {
    for (const exts of Object.values(ALL_EXTENSIONS))
      exts.forEach(e => { this._extState[e] = true; });
    // Load saved custom extensions from Python
    try {
      const saved = await window.pywebview.api.get_custom_exts();
      if (Array.isArray(saved)) saved.forEach(ext => this._registerCustomExt(ext));
    } catch (_) {}
    State.activeExts = null;
    this._renderGroups();
    this._bindSearch();
    this._bindButtons();
    this._bindCustomExt();
  },

  _bindSearch() {
    const el = document.getElementById('search-input');
    if (!el) return;
    if (this._searchAbort) this._searchAbort.abort();
    this._searchAbort = new AbortController();
    el.addEventListener('input', () => {
      clearTimeout(this._searchTimer);
      this._searchTimer = setTimeout(() => {
        State.searchQuery = el.value.trim();
        Tree.invalidate();
        Tree.render();
      }, 200);
    }, { signal: this._searchAbort.signal });
  },

  _bindButtons() {
    const allBtn  = document.getElementById('btn-ext-all');
    const noneBtn = document.getElementById('btn-ext-none');
    if (allBtn) {
      const a = allBtn.cloneNode(true);
      allBtn.replaceWith(a);
      a.addEventListener('click', () => this.selectAll());
    }
    if (noneBtn) {
      const n = noneBtn.cloneNode(true);
      noneBtn.replaceWith(n);
      n.addEventListener('click', () => this.deselectNone());
    }
  },

  // ── Groups ──────────────────────────────────────────────────────

  _renderGroups() {
    const container = document.getElementById('ext-groups');
    if (!container) return;

    let html = '';
    for (const [groupName, exts] of Object.entries(ALL_EXTENSIONS)) {
      html += this._groupHTML(groupName, exts);
    }
    // Custom group (may be empty)
    html += this._customGroupHTML();
    container.innerHTML = html;

    container.onclick = e => this._onClick(e);
  },

  _groupHTML(groupName, exts) {
    return `
      <div class="grp">
        <div class="grp-header" data-group="${groupName}">
          <span class="grp-arrow">▶</span>
          <div class="gcb on" data-gcb="${groupName}"></div>
          <span class="grp-name">${groupName}</span>
          <span class="grp-count">${exts.length}</span>
        </div>
        <div class="grp-body" data-grp-body="${groupName}">
          ${exts.map(ext => this._extItemHTML(ext)).join('')}
        </div>
      </div>`;
  },

  _extItemHTML(ext, removable = false) {
    const rm = removable
      ? `<span class="ext-rm" data-rm="${ext}" title="Remove">×</span>`
      : '';
    return `
      <div class="ext-item" data-ext="${ext}">
        <div class="ecb on" data-ecb="${ext}"></div>
        <span class="ext-name">.${ext}</span>
        ${rm}
      </div>`;
  },

  _customGroupHTML() {
    const exts = this._customExts;
    const gcbClass = exts.length === 0 || exts.every(e => this._extState[e])
      ? 'gcb on' : exts.every(e => !this._extState[e]) ? 'gcb' : 'gcb half';
    return `
      <div class="grp" id="grp-custom">
        <div class="grp-header" data-group="${CUSTOM_GROUP}">
          <span class="grp-arrow">▶</span>
          <div class="${gcbClass}" data-gcb="${CUSTOM_GROUP}"></div>
          <span class="grp-name">${CUSTOM_GROUP}</span>
          <span class="grp-count" id="custom-grp-count">${exts.length}</span>
        </div>
        <div class="grp-body" data-grp-body="${CUSTOM_GROUP}">
          ${exts.map(ext => this._extItemHTML(ext, true)).join('')}
          ${this._customInputHTML()}
        </div>
      </div>`;
  },

  _customInputHTML() {
    return `
      <div id="custom-ext-form" style="display:flex;flex-direction:column;gap:2px;padding:4px 6px 2px;">
        <div style="display:flex;gap:4px;">
          <input id="custom-ext-input" type="text" placeholder=".xyz or xyz"
            style="flex:1;min-width:0;padding:2px 6px;font-size:11px;border-radius:6px;
                   border:1px solid var(--border);background:var(--card2);color:var(--text);outline:none;" />
          <button id="btn-custom-ext-add" title="Add extension"
            style="padding:2px 8px;font-size:13px;border-radius:6px;border:1px solid var(--border);
                   background:var(--accent);color:#fff;cursor:pointer;line-height:1;">+</button>
        </div>
        <div id="custom-ext-error" style="display:none;font-size:10px;color:var(--danger,#c0392b);padding:0 2px;"></div>
      </div>`;
  },

  _onClick(e) {
    // 0. × button to remove custom extension
    const rmEl = e.target.closest('[data-rm]');
    if (rmEl) {
      this._removeCustomExt(rmEl.dataset.rm);
      return;
    }

    // 1. Checkbox groups
    const gcbEl = e.target.closest('[data-gcb]');
    if (gcbEl) {
      this._toggleGroup(gcbEl.dataset.gcb);
      return;
    }

    // 2. Header → collapse/expand
    const hdrEl = e.target.closest('[data-group]');
    if (hdrEl) {
      // Open Custom group on first click (so input is visible)
      const body  = hdrEl.nextElementSibling;
      const arrow = hdrEl.querySelector('.grp-arrow');
      if (body) {
        const open = body.classList.toggle('open');
        if (arrow) arrow.textContent = open ? '▼' : '▶';
        // After opening, wire up input (DOM just created)
        if (open && hdrEl.dataset.group === CUSTOM_GROUP) {
          this._bindCustomExt();
        }
      }
      return;
    }

    // 3. Extension
    const extEl = e.target.closest('[data-ext]');
    if (extEl && !e.target.closest('[data-rm]')) {
      this._toggleExt(extEl.dataset.ext);
    }
  },

  _toggleGroup(groupName) {
    const exts = groupName === CUSTOM_GROUP
      ? this._customExts
      : (ALL_EXTENSIONS[groupName] || []);
    const allOn  = exts.length > 0 && exts.every(e => this._extState[e]);
    const newVal = !allOn;
    exts.forEach(ext => {
      this._extState[ext] = newVal;
      const ecb = document.querySelector(`[data-ecb="${ext}"]`);
      if (ecb) ecb.classList.toggle('on', newVal);
    });
    const gcb = document.querySelector(`[data-gcb="${groupName}"]`);
    if (gcb) gcb.className = newVal ? 'gcb on' : 'gcb';
    this._scheduleRender();
  },

  _toggleExt(ext) {
    this._extState[ext] = !this._extState[ext];
    const ecb = document.querySelector(`[data-ecb="${ext}"]`);
    if (ecb) ecb.classList.toggle('on', this._extState[ext]);
    // Update group state
    const groupName = this._customExts.includes(ext)
      ? CUSTOM_GROUP
      : Object.entries(ALL_EXTENSIONS).find(([, v]) => v.includes(ext))?.[0];
    if (groupName) this._updateGroupCheckbox(groupName);
    this._scheduleRender();
  },

  _updateGroupCheckbox(groupName) {
    const exts = groupName === CUSTOM_GROUP
      ? this._customExts
      : (ALL_EXTENSIONS[groupName] || []);
    const gcb  = document.querySelector(`[data-gcb="${groupName}"]`);
    if (!gcb || exts.length === 0) return;
    const vals = exts.map(e => this._extState[e]);
    const all  = vals.every(Boolean);
    const none = vals.every(v => !v);
    gcb.className = all ? 'gcb on' : (none ? 'gcb' : 'gcb half');
  },

  _scheduleRender() {
    clearTimeout(this._filterTimer);
    this._filterTimer = setTimeout(() => {
      this._applyExtFilter();
      Tree.invalidate();
      Tree.render();
    }, 30);
  },

  _applyExtFilter() {
    const allOn = Object.values(this._extState).every(Boolean);
    State.activeExts = allOn ? null : new Set(
      Object.entries(this._extState).filter(([, v]) => v).map(([k]) => k)
    );
  },

  // ── Custom extensions ─────────────────────────────────────────────

  _bindCustomExt() {
    const input  = document.getElementById('custom-ext-input');
    const addBtn = document.getElementById('btn-custom-ext-add');
    if (!input || !addBtn) return;
    // Prevent double binding
    if (input._bound) return;
    input._bound = true;

    const doAdd = () => {
      const raw = input.value.trim();
      if (!raw) return;
      const ext = raw.replace(/^\.+/, '').toLowerCase();
      if (!ext) return;
      if (this._addCustomExt(ext)) {
        input.value = '';
      }
    };
    addBtn.addEventListener('click', doAdd);
    input.addEventListener('input', () => this._clearExtError());
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); doAdd(); }
    });
  },

  _registerCustomExt(ext) {
    // Register state only, no DOM (called before renderGroups)
    if (!ext || this._extState.hasOwnProperty(ext) || this._customExts.includes(ext)) return false;
    this._customExts.push(ext);
    this._extState[ext] = true;
    return true;
  },

  _showExtError(msg) {
    const el = document.getElementById('custom-ext-error');
    if (!el) return;
    el.textContent = msg;
    el.style.display = 'block';
    clearTimeout(this._extErrorTimer);
    this._extErrorTimer = setTimeout(() => { el.style.display = 'none'; el.textContent = ''; }, 3000);
  },

  _clearExtError() {
    const el = document.getElementById('custom-ext-error');
    if (el) { el.style.display = 'none'; el.textContent = ''; }
    clearTimeout(this._extErrorTimer);
  },

  _addCustomExt(ext) {
    if (!ext) return false;
    if (this._extState.hasOwnProperty(ext) || this._customExts.includes(ext)) {
      this._showExtError(`.${ext} is already in the list`);
      return false;
    }
    this._clearExtError();

    this._customExts.push(ext);
    this._extState[ext] = true;
    this._saveCustomExts();

    // Add item to Custom group DOM
    const body = document.querySelector(`[data-grp-body="${CUSTOM_GROUP}"]`);
    if (body) {
      const form = document.getElementById('custom-ext-form');
      const item = document.createElement('div');
      item.innerHTML = this._extItemHTML(ext, true);
      body.insertBefore(item.firstElementChild, form);
    }

    // Update counter
    const counter = document.getElementById('custom-grp-count');
    if (counter) counter.textContent = this._customExts.length;

    this._updateGroupCheckbox(CUSTOM_GROUP);
    this._scheduleRender();
    return true;
  },

  _removeCustomExt(ext) {
    this._customExts = this._customExts.filter(e => e !== ext);
    delete this._extState[ext];
    const item = document.querySelector(`[data-ext="${ext}"]`);
    if (item) item.remove();
    const counter = document.getElementById('custom-grp-count');
    if (counter) counter.textContent = this._customExts.length;
    this._updateGroupCheckbox(CUSTOM_GROUP);
    this._saveCustomExts();
    this._scheduleRender();
  },

  _saveCustomExts() {
    try {
      window.pywebview.api.save_custom_exts(this._customExts);
    } catch (_) {}
  },

  selectAll() {
    for (const ext of Object.keys(this._extState)) this._extState[ext] = true;
    document.querySelectorAll('[data-ecb]').forEach(el => el.classList.add('on'));
    document.querySelectorAll('[data-gcb]').forEach(el => { el.className = 'gcb on'; });
    State.activeExts = null;
    Tree.invalidate(); Tree.render();
  },

  deselectNone() {
    for (const ext of Object.keys(this._extState)) this._extState[ext] = false;
    document.querySelectorAll('[data-ecb]').forEach(el => el.classList.remove('on'));
    document.querySelectorAll('[data-gcb]').forEach(el => { el.className = 'gcb'; });
    State.activeExts = new Set();
    Tree.invalidate(); Tree.render();
  },
};


/**
 * AdvFilter — advanced filter (category, size, date)
 */
const AdvFilter = {
  _open: false,
  _category: '',       // '' = all
  _sizeMin: null,      // bytes or null
  _sizeMax: null,
  _datePreset: '',     // '', 'today', 'yesterday', '7d', '30d', '90d', 'custom'
  _dateFrom: null,     // Date or null (only for custom range)
  _dateTo: null,

  init() {
    this._bindToggle();
    this._bindCategory();
    this._bindSizeDate();
    this._bindReset();
    this._bindSearchClear();
    this._calInit();
  },

  _bindToggle() {
    const btn = document.getElementById('btn-adv-filter');
    const panel = document.getElementById('adv-filter');
    if (!btn || !panel || btn._advBound) return;
    btn._advBound = true;
    btn.addEventListener('click', () => {
      this._open = !this._open;
      panel.classList.toggle('open', this._open);
      btn.classList.toggle('active', this._open);
      btn.setAttribute('aria-expanded', this._open);
    });
  },

  _bindCategory() {
    const container = document.getElementById('adv-category');
    if (!container || container._advBound) return;
    container._advBound = true;
    container.addEventListener('click', e => {
      const pill = e.target.closest('.apill');
      if (!pill) return;
      container.querySelectorAll('.apill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      this._category = pill.dataset.cat;
      this._apply();
    });
  },

  _bindSizeDate() {
    const unit = document.getElementById('adv-size-unit');
    if (unit?._advBound) return;
    if (unit) unit._advBound = true;

    // Size
    const onSizeChange = () => {
      const unit = parseInt(document.getElementById('adv-size-unit')?.value || '1048576', 10);
      const minVal = document.getElementById('adv-size-min')?.value;
      const maxVal = document.getElementById('adv-size-max')?.value;
      this._sizeMin = minVal !== '' && minVal !== null ? parseFloat(minVal) * unit : null;
      this._sizeMax = maxVal !== '' && maxVal !== null ? parseFloat(maxVal) * unit : null;
      this._apply();
    };
    ['adv-size-min','adv-size-max','adv-size-unit'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.addEventListener('input', onSizeChange);
    });

    // Date — preset dropdown
    const preset = document.getElementById('adv-date-preset');
    const customWrap = document.getElementById('adv-date-custom');
    if (preset) {
      preset.addEventListener('change', () => {
        this._datePreset = preset.value;
        const isCustom = preset.value === 'custom';
        if (customWrap) customWrap.style.display = isCustom ? 'flex' : 'none';
        if (isCustom) {
          this._calFrom = null;
          this._calTo   = null;
          this._calStep = 0; // 0 = waiting for first click
          this._calRenderMonth(this._calYear, this._calMonth);
          this._calUpdateHint();
        } else {
          this._dateFrom = null;
          this._dateTo   = null;
        }
        this._apply();
      });
    }
  },

  // ── Inline calendar ─────────────────────────────────────────────

  _calYear:  new Date().getFullYear(),
  _calMonth: new Date().getMonth(),
  _calFrom:  null,   // Date (selected start) or null
  _calTo:    null,   // Date (selected end) or null
  _calStep:  0,      // 0 = waiting for start, 1 = waiting for end
  _calView:  'days', // 'days' | 'months' | 'years'

  _calInit() {
    const prev = document.getElementById('adv-cal-prev');
    const next = document.getElementById('adv-cal-next');
    const grid = document.getElementById('adv-cal-grid');
    if (!grid || grid._calBound) return;
    grid._calBound = true;

    const title = document.getElementById('adv-cal-title');
    title?.addEventListener('click', () => {
      if (this._calView === 'days')   { this._calView = 'months'; this._calRenderMonths(); }
      else if (this._calView === 'months') { this._calView = 'years';  this._calRenderYears(); }
      // 'years' has no further drill-up
    });

    prev?.addEventListener('click', () => {
      if (this._calView === 'days') {
        this._calMonth--;
        if (this._calMonth < 0) { this._calMonth = 11; this._calYear--; }
        this._calRenderMonth(this._calYear, this._calMonth);
      } else if (this._calView === 'months') {
        this._calYear--;
        this._calRenderMonths();
      } else {
        this._calYear -= 12;
        this._calRenderYears();
      }
    });
    next?.addEventListener('click', () => {
      if (this._calView === 'days') {
        this._calMonth++;
        if (this._calMonth > 11) { this._calMonth = 0; this._calYear++; }
        this._calRenderMonth(this._calYear, this._calMonth);
      } else if (this._calView === 'months') {
        this._calYear++;
        this._calRenderMonths();
      } else {
        this._calYear += 12;
        this._calRenderYears();
      }
    });
    grid.addEventListener('click', e => {
      const cell = e.target.closest('.adv-cal-day:not(.empty)');
      if (!cell) return;
      const d = new Date(parseInt(cell.dataset.ts));
      this._calPickDay(d);
    });
    grid.addEventListener('click', e => {
      const mCell = e.target.closest('.adv-cal-month');
      if (!mCell) return;
      this._calMonth = parseInt(mCell.dataset.month);
      this._calView = 'days';
      this._calRenderMonth(this._calYear, this._calMonth);
    });
    grid.addEventListener('click', e => {
      const yCell = e.target.closest('.adv-cal-year-cell');
      if (!yCell) return;
      this._calYear = parseInt(yCell.dataset.year);
      this._calView = 'months';
      this._calRenderMonths();
    });

    this._calView = 'days';
    this._calRenderMonth(this._calYear, this._calMonth);
    this._calUpdateHint();
  },

  _calPickDay(d) {
    if (this._calStep === 0) {
      // First click — start
      this._calFrom = d;
      this._calTo   = null;
      this._calStep = 1;
      this._dateFrom = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 0, 0, 0);
      this._dateTo   = null;
    } else {
      // Second click — end (swap if before start)
      if (d < this._calFrom) {
        this._calTo   = this._calFrom;
        this._calFrom = d;
      } else {
        this._calTo = d;
      }
      this._calStep = 0;
      this._dateFrom = new Date(this._calFrom.getFullYear(), this._calFrom.getMonth(), this._calFrom.getDate(), 0, 0, 0);
      this._dateTo   = new Date(this._calTo.getFullYear(),   this._calTo.getMonth(),   this._calTo.getDate(),   23, 59, 59);
    }
    this._calRenderMonth(this._calYear, this._calMonth);
    this._calUpdateHint();
    this._apply();
  },

  _calRenderMonth(year, month) {
    const grid  = document.getElementById('adv-cal-grid');
    const title = document.getElementById('adv-cal-title');
    if (!grid || !title) return;

    const MONTHS = ['January','February','March','April','May','June',
                    'July','August','September','October','November','December'];
    const DAYS   = ['Mo','Tu','We','Th','Fr','Sa','Su'];

    title.textContent = `${MONTHS[month]} ${year}`;
    title.style.cursor = 'pointer';
    title.title = 'Click to pick month';

    const today    = new Date();
    const todayStr = `${today.getFullYear()}-${today.getMonth()}-${today.getDate()}`;

    const firstDay = new Date(year, month, 1);
    // Monday as first day of week (0=Sun → 6, 1=Mon → 0, ...)
    const startOffset = (firstDay.getDay() + 6) % 7;
    const daysInMonth = new Date(year, month + 1, 0).getDate();

    let html = DAYS.map(d => `<div class="adv-cal-dow">${d}</div>`).join('');

    // Empty cells before first day
    for (let i = 0; i < startOffset; i++) html += `<div class="adv-cal-day empty"></div>`;

    for (let day = 1; day <= daysInMonth; day++) {
      const d   = new Date(year, month, day);
      const ts  = d.getTime();
      const key = `${year}-${month}-${day}`;

      let cls = 'adv-cal-day';
      if (key === todayStr) cls += ' today';

      if (this._calFrom && this._calTo) {
        const from = new Date(this._calFrom.getFullYear(), this._calFrom.getMonth(), this._calFrom.getDate());
        const to   = new Date(this._calTo.getFullYear(),   this._calTo.getMonth(),   this._calTo.getDate());
        if (d.getTime() === from.getTime()) cls += ' range-start';
        if (d.getTime() === to.getTime())   cls += ' range-end';
        if (d > from && d < to)             cls += ' in-range';
      } else if (this._calFrom) {
        const from = new Date(this._calFrom.getFullYear(), this._calFrom.getMonth(), this._calFrom.getDate());
        if (d.getTime() === from.getTime()) cls += ' range-start range-end';
      }

      html += `<div class="${cls}" data-ts="${ts}">${day}</div>`;
    }

    grid.innerHTML = html;
  },

  _calRenderMonths() {
    const grid  = document.getElementById('adv-cal-grid');
    const title = document.getElementById('adv-cal-title');
    if (!grid || !title) return;
    const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun',
                    'Jul','Aug','Sep','Oct','Nov','Dec'];
    title.textContent = `${this._calYear}`;
    title.style.cursor = 'pointer';
    title.title = 'Click to pick year';
    grid.innerHTML = MONTHS.map((m, i) => {
      const active = i === this._calMonth ? ' cal-grid-active' : '';
      return `<div class="adv-cal-month${active}" data-month="${i}">${m}</div>`;
    }).join('');
  },

  _calRenderYears() {
    const grid  = document.getElementById('adv-cal-grid');
    const title = document.getElementById('adv-cal-title');
    if (!grid || !title) return;
    // Show a 12-year range centred around current _calYear
    const start = this._calYear - (this._calYear % 12);
    title.textContent = `${start} – ${start + 11}`;
    title.style.cursor = 'default';
    title.title = '';
    grid.innerHTML = Array.from({ length: 12 }, (_, i) => {
      const y = start + i;
      const active = y === this._calYear ? ' cal-grid-active' : '';
      return `<div class="adv-cal-year-cell${active}" data-year="${y}">${y}</div>`;
    }).join('');
  },

  _calUpdateHint() {
    const hint = document.getElementById('adv-cal-hint');
    if (!hint) return;
    if (this._calStep === 0 && this._calFrom && this._calTo) {
      const fmt = d => d.toLocaleDateString('en-US', { day:'numeric', month:'numeric', year:'numeric' });
      hint.textContent = `${fmt(this._calFrom)} – ${fmt(this._calTo)}`;
    } else if (this._calStep === 1) {
      hint.textContent = 'Select end date';
    } else {
      hint.textContent = 'Select start date';
    }
  },

  // Converts preset to { from, to } Date objects
  _resolveDateRange() {
    if (!this._datePreset) return { from: null, to: null };
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const endOfToday = new Date(today.getTime() + 86400000 - 1);
    switch (this._datePreset) {
      case 'today':
        return { from: today, to: endOfToday };
      case 'yesterday': {
        const yest = new Date(today.getTime() - 86400000);
        return { from: yest, to: new Date(today.getTime() - 1) };
      }
      case '7d':
        return { from: new Date(today.getTime() - 6 * 86400000), to: endOfToday };
      case '30d':
        return { from: new Date(today.getTime() - 29 * 86400000), to: endOfToday };
      case '90d':
        return { from: new Date(today.getTime() - 89 * 86400000), to: endOfToday };
      case 'custom':
        return { from: this._dateFrom, to: this._dateTo };
      default:
        return { from: null, to: null };
    }
  },

  _bindReset() {
    const btn = document.getElementById('btn-adv-reset');
    if (!btn || btn._advBound) return;
    btn._advBound = true;
    btn.addEventListener('click', () => this.reset());
  },

  _bindSearchClear() {
    const btn   = document.getElementById('btn-search-clear');
    const input = document.getElementById('search-input');
    if (!btn || !input || btn._advBound) return;
    btn._advBound = true;
    input.addEventListener('input', () => {
      btn.style.display = input.value ? 'flex' : 'none';
    });
    btn.addEventListener('click', () => {
      input.value = '';
      btn.style.display = 'none';
      State.searchQuery = '';
      Tree.invalidate();
      Tree.render();
    });
  },

  reset() {
    this._category = '';
    this._sizeMin = null;
    this._sizeMax = null;
    this._datePreset = '';
    this._dateFrom = null;
    this._dateTo = null;

    // Reset UI
    document.querySelectorAll('#adv-category .apill').forEach(p => p.classList.remove('active'));
    const allPill = document.querySelector('#adv-category .apill[data-cat=""]');
    if (allPill) allPill.classList.add('active');

    ['adv-size-min','adv-size-max','adv-date-from','adv-date-to'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    const unitSel = document.getElementById('adv-size-unit');
    if (unitSel) unitSel.value = '1048576';
    const presetSel = document.getElementById('adv-date-preset');
    if (presetSel) presetSel.value = '';
    const customRow = document.getElementById('adv-date-custom');
    if (customRow) customRow.style.display = 'none';
    this._calFrom = null;
    this._calTo   = null;
    this._calStep = 0;
    this._calYear  = new Date().getFullYear();
    this._calMonth = new Date().getMonth();
    this._calRenderMonth(this._calYear, this._calMonth);
    this._calUpdateHint();

    this._apply();
  },

  // Returns true if any advanced filters are active
  isActive() {
    return !!(this._category || this._sizeMin !== null || this._sizeMax !== null ||
              this._datePreset);
  },

  // Returns true if file passes the filter
  matches(item) {
    if (item.type !== 'file') return true; // folders always pass

    // Category
    if (this._category) {
      const ext = item.name.split('.').pop()?.toLowerCase() || '';
      const catExts = ALL_EXTENSIONS[this._category] || [];
      if (!catExts.includes(ext)) return false;
    }

    // Size
    const size = item.size || 0;
    if (this._sizeMin !== null && size < this._sizeMin) return false;
    if (this._sizeMax !== null && size > this._sizeMax) return false;

    // Date
    if (this._datePreset) {
      const { from, to } = this._resolveDateRange();
      const mtime = item.mtime ? new Date(item.mtime * 1000) : null;
      if (!mtime) return false;
      if (from && mtime < from) return false;
      if (to   && mtime > to)   return false;
    }

    return true;
  },

  _apply() {
    State.advFilter = this.isActive() ? this : null;

    // Update badge
    const badge = document.getElementById('adv-active-badge');
    const btn   = document.getElementById('btn-adv-filter');
    if (badge) badge.style.display = this.isActive() ? 'flex' : 'none';
    if (btn)   btn.classList.toggle('has-filter', this.isActive());

    Tree.invalidate();
    Tree.render();
  },
};
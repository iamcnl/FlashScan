/**
 * state.js — central application store
 *
 * All shared data lives here. Other modules read from this object.
 *
 * treeData structure: array of objects
 *   { lvl, type, name, path, size, mtime }
 */

const _HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => _HTML_ESCAPES[ch]);
}

function cssEscape(value) {
  return CSS.escape(String(value));
}

const State = {
  treeData:      [],
  selectedFiles: new Set(),
  folderStates:  {},
  folderNotes:   {},   // { path: "note text" } — secondary locations (YouTube, Drive, etc.)

  activeExts:  null,   // null = all; Set<string> = extension filter
  searchQuery: '',
  advFilter:   null,   // null = inactive; AdvFilter object = active
  sortCol: 'name',
  sortDir: 'asc',

  settings: {
    lastPath:    '',
    lastOutput:  '',
    lastFormats: ['MD'],
    inclHidden:  false,
    inclSystem:  false,
    sortCol:     'name',
    sortDir:     'asc',
  },

  // ── Export cache ──────────────────────────────────────────────
  // Recomputed only when selectedFiles or folderStates change
  _exportCacheDirty: true,
  _exportCache: null,   // { count, size, nameOnly, files[] }

  _markDirty() {
    this._exportCacheDirty = true;
    Persist.schedule();
  },

  exportStats() {
    if (!this._exportCacheDirty && this._exportCache) return this._exportCache;

    let count    = 0;
    let size     = 0;
    let nameOnly = 0;

    const sepRe  = /[\\/]/;

    // Pre-compute skip/name prefixes once
    const skipPfx = [];
    const namePfx = [];
    for (const [fp, st] of Object.entries(this.folderStates)) {
      const p = fp + (fp.slice(-1).match(sepRe) ? '' : '/');
      if (st === 'skip') skipPfx.push(p);
      else if (st === 'name') namePfx.push(p);
      if (st === 'name') nameOnly++;
    }

    const blocked = (p) => {
      for (const s of skipPfx) if (p.startsWith(s)) return true;
      for (const n of namePfx) if (p.startsWith(n)) return true;
      return false;
    };

    for (const item of this.treeData) {
      if (item.type !== 'file') continue;
      if (!this.selectedFiles.has(item.path)) continue;
      if (blocked(item.path)) continue;
      const parentState = this.folderStates[item.path.replace(/[\\/][^\\/]+$/, '')];
      if (parentState === 'skip' || parentState === 'name') continue;
      count++;
      size += item.size || 0;
    }

    this._exportCache      = { count, size, nameOnly };
    this._exportCacheDirty = false;
    return this._exportCache;
  },

  reset(treeData) {
    this.treeData = treeData;
    this.resetProfileState();
    this.searchQuery = '';
    this.sortCol     = ['name', 'size', 'date'].includes(this.settings.sortCol) ? this.settings.sortCol : 'name';
    this.sortDir     = this.settings.sortDir === 'desc' ? 'desc' : 'asc';
    this.activeExts  = null;
    this.advFilter   = null;
    this._markDirty();
  },

  resetProfileState() {
    this.selectedFiles = new Set(this.treeData.filter(i => i.type === 'file').map(i => i.path));
    this.folderStates  = {};
    this.treeData.filter(i => i.type === 'folder').forEach(i => {
      this.folderStates[i.path] = 'full';
    });
    this.folderNotes = {};
  },
};
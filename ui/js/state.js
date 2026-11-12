/**
 * state.js — central application store
 *
 * All shared data lives here. Other modules read from this object.
 *
 * treeData structure: array of objects
 *   { lvl, type, name, path, size, mtime }
 */

const UNEXPECTED_ERROR = 'Something went wrong. Details are in the log.';

const _HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => _HTML_ESCAPES[ch]);
}

function cssEscape(value) {
  return CSS.escape(String(value));
}

const State = {
  treeData:      [],
  scanId:        null,   // identifies the tree Python keeps; sent back with every export
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
  _exportCache: null,   // { count, size, nameOnly, empty }
  _exportCacheExts: null,   // activeExts the cache was computed for (filters.js always assigns a new value)

  _markDirty() {
    this._exportCacheDirty = true;
    Persist.schedule();
  },

  exportStats() {
    if (!this._exportCacheDirty && this._exportCache && this._exportCacheExts === this.activeExts) {
      return this._exportCache;
    }

    let count    = 0;
    let size     = 0;
    let nameOnly = 0;

    // Same rule as exporter.iter_export: a skip/name folder hides everything below it.
    const hides = [];   // hides[lvl]: the latest folder at that level, or an ancestor, hides its contents
    for (const item of this.treeData) {
      const hidden = item.lvl > 0 && hides[item.lvl - 1] === true;
      if (item.type === 'folder') {
        const state = this.folderStates[item.path] || 'full';
        hides[item.lvl] = hidden || state === 'skip' || state === 'name';
        if (!hidden && state === 'name') nameOnly++;
      } else if (!hidden && this.selectedFiles.has(item.path) && this.matchesExt(item.name)) {
        count++;
        size += item.size || 0;
      }
    }

    this._exportCache      = { count, size, nameOnly, empty: count === 0 && nameOnly === 0 };
    this._exportCacheExts  = this.activeExts;
    this._exportCacheDirty = false;
    return this._exportCache;
  },

  // Files without an extension always pass, as in the exporter.
  matchesExt(name) {
    if (!this.activeExts) return true;
    const dot = name.lastIndexOf('.');
    const ext = dot >= 0 ? name.slice(dot + 1).toLowerCase() : '';
    return !ext || this.activeExts.has(ext);
  },

  // ── Tree structure ────────────────────────────────────────────
  // treeData is a flat DFS list: a folder is followed by its contents, one level deeper.
  // Parents and subtrees come from lvl, never from path strings, so roots like "E:\" need no special case.
  _structure: null,

  structure() {
    const tree = this.treeData;
    if (this._structure?.tree === tree && this._structure.size === tree.length) return this._structure;
    const parent = new Int32Array(tree.length).fill(-1);
    const index  = new Map();
    const lastAt = [];
    tree.forEach((item, i) => {
      index.set(item.path, i);
      if (item.lvl > 0) parent[i] = lastAt[item.lvl - 1] ?? -1;
      if (item.type === 'folder') lastAt[item.lvl] = i;
    });
    this._structure = { tree, size: tree.length, parent, index };
    return this._structure;
  },

  parentPath(path) {
    const { parent, index } = this.structure();
    const i = index.get(path);
    return i === undefined || parent[i] < 0 ? null : this.treeData[parent[i]].path;
  },

  _subtreeEnd(i) {
    const tree = this.treeData;
    let j = i + 1;
    while (j < tree.length && tree[j].lvl > tree[i].lvl) j++;
    return j;
  },

  // ── Selection changes ─────────────────────────────────────────
  // Every change to files or folders goes through these two, so a folder's state always
  // follows from its contents and from the folders above it.
  setFolderState(path, state) {
    const i = this.structure().index.get(path);
    if (i === undefined) return;
    this.folderStates[path] = state;
    for (let j = i + 1, end = this._subtreeEnd(i); j < end; j++) {
      const item = this.treeData[j];
      if (item.type === 'folder') this.folderStates[item.path] = state;
      else if (state === 'full')  this.selectedFiles.add(item.path);
      else                        this.selectedFiles.delete(item.path);
    }
    this._recomputeAbove(i);
    this._markDirty();
  },

  setFilesSelected(paths, selected) {
    const { parent, index } = this.structure();
    const parents = new Set();
    for (const path of paths) {
      const i = index.get(path);
      if (i === undefined) continue;
      if (selected) this.selectedFiles.add(path);
      else          this.selectedFiles.delete(path);
      if (parent[i] >= 0) parents.add(parent[i]);
    }
    for (const folder of parents) this._recomputeUp(folder);
    this._markDirty();
  },

  _recomputeAbove(i) {
    const parent = this.structure().parent[i];
    if (parent >= 0) this._recomputeUp(parent);
  },

  _recomputeUp(folder) {
    const { parent } = this.structure();
    for (let f = folder; f >= 0; f = parent[f]) {
      this.folderStates[this.treeData[f].path] = this._derivedState(f);
    }
  },

  // A folder's state from its direct children. A deselected file fits both "excluded" and
  // "names only", so it takes the side of the subfolders: excluded folder + unticked file stays excluded.
  _derivedState(f) {
    const tree = this.treeData;
    const lvl  = tree[f].lvl + 1;
    let any = false, full = true, skipLike = true, nameLike = true, hasSkip = false;
    for (let j = f + 1, end = this._subtreeEnd(f); j < end; j++) {
      const item = tree[j];
      if (item.lvl !== lvl) continue;
      const s = item.type === 'file'
        ? (this.selectedFiles.has(item.path) ? 'full' : 'none')
        : (this.folderStates[item.path] || 'full');
      any = true;
      if (s !== 'full') full = false;
      if (s !== 'skip' && s !== 'none') skipLike = false;
      if (s !== 'name' && s !== 'none') nameLike = false;
      if (s === 'skip') hasSkip = true;
    }
    if (!any) return this.folderStates[tree[f].path] || 'full';
    return full ? 'full' : (skipLike && hasSkip) ? 'skip' : nameLike ? 'name' : 'partial';
  },

  selectionDelta() {
    const selected = [];
    const deselected = [];
    for (const item of this.treeData) {
      if (item.type !== 'file') continue;
      (this.selectedFiles.has(item.path) ? selected : deselected).push(item.path);
    }
    const folderStates = {};
    for (const [path, state] of Object.entries(this.folderStates)) {
      if (state !== 'full') folderStates[path] = state;
    }
    return {
      ...(deselected.length <= selected.length ? { all_except: deselected } : { only: selected }),
      folder_states: folderStates,
      folder_notes:  this.folderNotes,
      active_exts:   this.activeExts ? [...this.activeExts] : null,
    };
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
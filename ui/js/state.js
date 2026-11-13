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

  hiddenExts:  null,   // null = nothing hidden; Set<string> = extensions unticked in the sidebar
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
  _exportCacheExts: null,   // hiddenExts the cache was computed for (filters.js always assigns a new value)

  _markDirty() {
    this._exportCacheDirty = true;
    Persist.schedule();
  },

  exportStats() {
    if (!this._exportCacheDirty && this._exportCache && this._exportCacheExts === this.hiddenExts) {
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
    this._exportCacheExts  = this.hiddenExts;
    this._exportCacheDirty = false;
    return this._exportCache;
  },

  // Only extensions unticked in the sidebar are hidden; unlisted ones and files without one always pass,
  // as in the tree and the exporter.
  matchesExt(name) {
    if (!this.hiddenExts) return true;
    const dot = name.lastIndexOf('.');
    return dot < 0 || !this.hiddenExts.has(name.slice(dot + 1).toLowerCase());
  },

  // ── Tree structure ────────────────────────────────────────────
  // treeData is a flat DFS list: a folder is followed by its contents, one level deeper.
  // Parents and subtrees come from lvl, never from path strings, so roots like "E:\" need no special case.
  _structure: null,

  structure() {
    const tree = this.treeData;
    if (this._structure?.tree === tree && this._structure.size === tree.length) return this._structure;
    const parent = new Int32Array(tree.length).fill(-1);
    const end    = new Int32Array(tree.length);   // end[i]: first index after item i's subtree
    const index  = new Map();
    const lastAt = [];
    const open   = [];
    let files = 0;
    tree.forEach((item, i) => {
      index.set(item.path, i);
      while (open.length && tree[open[open.length - 1]].lvl >= item.lvl) end[open.pop()] = i;
      if (item.lvl > 0) parent[i] = lastAt[item.lvl - 1] ?? -1;
      if (item.type === 'folder') { lastAt[item.lvl] = i; open.push(i); }
      else { end[i] = i + 1; files++; }
    });
    for (const i of open) end[i] = tree.length;
    this._structure = { tree, size: tree.length, parent, end, index, files };
    return this._structure;
  },

  parentPath(path) {
    const { parent, index } = this.structure();
    const i = index.get(path);
    return i === undefined || parent[i] < 0 ? null : this.treeData[parent[i]].path;
  },

  // ── Selection changes ─────────────────────────────────────────
  // Every change to files or folders goes through these two, so a folder's state always
  // follows from its contents and from the folders above it.
  setFolderState(path, state) {
    const i = this.structure().index.get(path);
    if (i === undefined) return;
    this.folderStates[path] = state;
    for (let j = i + 1, end = this.structure().end[i]; j < end; j++) {
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
    const touched = new Set();
    for (const path of paths) {
      const i = index.get(path);
      if (i === undefined) continue;
      if (selected) this.selectedFiles.add(path);
      else          this.selectedFiles.delete(path);
      for (let f = parent[i]; f >= 0 && !touched.has(f); f = parent[f]) touched.add(f);
    }
    // A parent always precedes its children in the list, so going backwards derives each folder once, after its contents.
    for (const f of [...touched].sort((x, y) => y - x)) {
      this.folderStates[this.treeData[f].path] = this._derivedState(f);
    }
    this._markDirty();
  },

  _recomputeAbove(i) {
    const { parent } = this.structure();
    for (let f = parent[i]; f >= 0; f = parent[f]) {
      this.folderStates[this.treeData[f].path] = this._derivedState(f);
    }
  },

  // A folder's state from its direct children. A deselected file fits both "excluded" and
  // "names only", so it takes the side of the subfolders: excluded folder + unticked file stays excluded.
  _derivedState(f) {
    const tree = this.treeData;
    let any = false, full = true, skipLike = true, nameLike = true, hasSkip = false;
    const { end: ends } = this.structure();
    for (let j = f + 1, end = ends[f]; j < end; j = ends[j]) {
      const item = tree[j];
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
      hidden_exts:   this.hiddenExts ? [...this.hiddenExts] : null,
    };
  },

  reset(treeData) {
    this.treeData = treeData;
    this.resetProfileState();
    this.searchQuery = '';
    this.sortCol     = ['name', 'size', 'date'].includes(this.settings.sortCol) ? this.settings.sortCol : 'name';
    this.sortDir     = this.settings.sortDir === 'desc' ? 'desc' : 'asc';
    this.hiddenExts  = null;
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
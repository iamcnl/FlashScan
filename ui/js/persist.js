/**
 * persist.js — per-drive profile (notes, folder states, exclusions, expanded folders)
 *
 * Profile keys are paths relative to the drive root, '/'-separated, so they survive
 * drive-letter changes and scans of different sub-roots on the same drive.
 *
 * Stored sparsely:
 *   notes       { key: text }
 *   folders     { key: 'name' | 'skip' }  only where the parent's state differs
 *   deselected  [key]                      files outside name/skip folders
 *   expanded    [key]
 * 'full' and 'partial' folder states are derived on restore.
 */

const Persist = {
  DEBOUNCE_MS: 1000,

  _volume:  null,   // { id, root, label }
  _orphans: null,   // stored entries the current scan did not cover
  _ready:   false,  // false while a scan is being loaded, so reset() cannot overwrite the profile
  _timer:   null,

  relKey(path) {
    const root = this._volume?.root || '';
    const rel  = path.startsWith(root) ? path.slice(root.length) : path;
    return rel.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
  },

  begin() {
    if (this._timer) this.flush();
    this._ready = false;
  },

  async restore(scanResult) {
    const { volume_id, volume_root, volume_label, depth } = scanResult;
    this._volume  = volume_id
      ? { id: volume_id, root: volume_root || '', label: volume_label || '' }
      : null;
    this._orphans = { notes: {}, folders: {}, deselected: [], expanded: [] };

    if (this._volume) {
      const profile = await this._fetch(volume_id);
      if (profile) this._apply(profile, depth);
    }
    State._markDirty();
    this._ready = !!this._volume;
  },

  schedule() {
    if (!this._ready) return;
    clearTimeout(this._timer);
    this._timer = setTimeout(() => this.flush(), this.DEBOUNCE_MS);
  },

  flush() {
    clearTimeout(this._timer);
    this._timer = null;
    const api = window.pywebview?.api;
    if (!this._ready || !api?.save_profile) return;
    api.save_profile(this._volume.id, this._capture()).catch(() => {});
  },

  async _fetch(volumeId) {
    try {
      return (await window.pywebview?.api?.get_profile(volumeId)) || null;
    } catch (e) {
      return null;
    }
  },

  _capture() {
    const { treeData, folderStates, selectedFiles, folderNotes } = State;
    const notes      = { ...this._orphans.notes };
    const folders    = { ...this._orphans.folders };
    const deselected = [...this._orphans.deselected];
    const expanded   = [...this._orphans.expanded];
    const stateAt    = [];

    for (const item of treeData) {
      const key = this.relKey(item.path);
      if (item.type === 'folder') {
        const state       = folderStates[item.path] || 'full';
        const parentState = item.lvl > 0 ? stateAt[item.lvl - 1] : null;
        stateAt[item.lvl] = state;
        if ((state === 'name' || state === 'skip') && state !== parentState) folders[key] = state;
        if (folderNotes[item.path]) notes[key] = folderNotes[item.path];
        if (item.lvl > 0 && !Tree._collapsed.has(item.path)) expanded.push(key);
      } else if (!selectedFiles.has(item.path)) {
        const parentState = stateAt[item.lvl - 1];
        if (parentState !== 'name' && parentState !== 'skip') deselected.push(key);
      }
    }

    return { volume: { label: this._volume.label }, notes, folders, deselected, expanded };
  },

  _apply(profile, depth) {
    const notes      = profile.notes   || {};
    const folders    = profile.folders || {};
    const deselected = new Set(profile.deselected || []);
    const expanded   = new Set(profile.expanded   || []);

    const unmatched = {
      notes:      new Set(Object.keys(notes)),
      folders:    new Set(Object.keys(folders)),
      deselected: new Set(deselected),
      expanded:   new Set(expanded),
    };

    const tree      = State.treeData;
    const fixed     = new Array(tree.length).fill(null);
    const parentIdx = new Int32Array(tree.length).fill(-1);
    const lastAt    = [];

    for (let i = 0; i < tree.length; i++) {
      const item   = tree[i];
      const key    = this.relKey(item.path);
      const parent = item.lvl > 0 ? (lastAt[item.lvl - 1] ?? -1) : -1;
      parentIdx[i] = parent;

      if (item.type === 'folder') {
        const own = folders[key];
        if (own === 'name' || own === 'skip') unmatched.folders.delete(key);
        fixed[i]  = (own === 'name' || own === 'skip') ? own : (parent >= 0 ? fixed[parent] : null);
        lastAt[item.lvl] = i;
        State.folderStates[item.path] = fixed[i] || 'full';

        if (key in notes) {
          State.folderNotes[item.path] = notes[key];
          unmatched.notes.delete(key);
        }
        if (item.lvl > 0 && expanded.has(key)) {
          Tree._collapsed.delete(item.path);
          unmatched.expanded.delete(key);
        }
      } else if (parent >= 0 && fixed[parent]) {
        State.selectedFiles.delete(item.path);
      } else if (deselected.has(key)) {
        State.selectedFiles.delete(item.path);
        unmatched.deselected.delete(key);
      }
    }

    const allFull = new Uint8Array(tree.length).fill(1);
    for (let i = tree.length - 1; i >= 0; i--) {
      const item = tree[i];
      let full;
      if (item.type === 'folder') {
        if (!fixed[i]) State.folderStates[item.path] = allFull[i] ? 'full' : 'partial';
        full = State.folderStates[item.path] === 'full';
      } else {
        full = State.selectedFiles.has(item.path);
      }
      if (!full && parentIdx[i] >= 0) allFull[parentIdx[i]] = 0;
    }

    this._keepOrphans(notes, folders, unmatched, tree[0] ? this.relKey(tree[0].path) : '', depth);
  },

  // Notes are always kept. Everything else is kept only if this scan could not have seen it;
  // an in-scope entry that is missing from the tree refers to a deleted path.
  _keepOrphans(notes, folders, unmatched, rootKey, depth) {
    const outside = (key, isFile) => !this._inScope(key, rootKey, depth, isFile);

    for (const key of unmatched.notes) {
      this._orphans.notes[key] = notes[key];
    }
    for (const key of unmatched.folders) {
      if (outside(key, false)) this._orphans.folders[key] = folders[key];
    }
    this._orphans.deselected = [...unmatched.deselected].filter(k => outside(k, true));
    this._orphans.expanded   = [...unmatched.expanded].filter(k => outside(k, false));
  },

  _inScope(key, rootKey, depth, isFile) {
    if (!Number.isFinite(depth)) return false;
    if (rootKey && key !== rootKey && !key.startsWith(rootKey + '/')) return false;
    const levels = k => (k ? k.split('/').length : 0);
    return levels(key) - levels(rootKey) <= depth + (isFile ? 1 : 0);
  },
};

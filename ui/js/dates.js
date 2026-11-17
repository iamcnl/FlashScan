/**
 * dates.js — the date formats of the file list and of the exports
 *
 * A format is a strftime layout of %d %m %Y. The UI renders the file list here and
 * export() sends the export layout to Python. The export format follows the file
 * list unless it is set on its own.
 */

const DateFmt = {
  OPTIONS: [
    { value: 'system', label: 'System default' },
    { value: 'dmy',    label: 'dd. mm. yyyy' },
    { value: 'mdy',    label: 'mm/dd/yyyy' },
    { value: 'iso',    label: 'yyyy-mm-dd' },
  ],
  FIXED: { dmy: '%d. %m. %Y', mdy: '%m/%d/%Y', iso: '%Y-%m-%d' },

  mode: 'system',
  exportMode: 'same',
  _systemPattern: null,

  exportOptions() {
    return [{ value: 'same', label: 'Same as file list' }, ...this.OPTIONS];
  },

  setMode(mode) {
    this.mode = this.OPTIONS.some(o => o.value === mode) ? mode : 'system';
  },

  setExportMode(mode) {
    this.exportMode = mode === 'same' || this.OPTIONS.some(o => o.value === mode) ? mode : 'same';
  },

  patternFor(mode) {
    return this.FIXED[mode] ?? this.systemPattern();
  },

  pattern() {
    return this.patternFor(this.mode);
  },

  exportPattern() {
    return this.patternFor(this.exportMode === 'same' ? this.mode : this.exportMode);
  },

  systemPattern() {
    this._systemPattern ??= this.patternForLocale(navigator.language);
    return this._systemPattern;
  },

  // Gregorian calendar and Latin digits are forced so Python's strftime can reproduce the result.
  patternForLocale(locale) {
    try {
      const tag = new Intl.Locale(locale, { calendar: 'gregory', numberingSystem: 'latn' });
      const parts = new Intl.DateTimeFormat(tag, { day: '2-digit', month: '2-digit', year: 'numeric' })
        .formatToParts(new Date(2024, 10, 22));
      const directive = { day: '%d', month: '%m', year: '%Y' };
      let pattern = '';
      for (const { type, value } of parts) {
        if (type === 'literal' && !value.includes('%')) pattern += value;
        else if (directive[type]) pattern += directive[type];
        else return this.FIXED.iso;
      }
      return pattern;
    } catch (e) {
      return this.FIXED.iso;
    }
  },

  formatDate(date, pattern = this.pattern()) {
    const pad = n => String(n).padStart(2, '0');
    return pattern.replace(/%([dmY])/g, (_, d) =>
      d === 'd' ? pad(date.getDate())
      : d === 'm' ? pad(date.getMonth() + 1)
      : String(date.getFullYear()));
  },

  // Dates the exporter cannot write (outside years 1-9999) are blank here as well.
  format(ts) {
    if (!ts) return '';
    const date = new Date(ts * 1000);
    const year = date.getFullYear();
    return year >= 1 && year <= 9999 ? this.formatDate(date) : '';
  },
};
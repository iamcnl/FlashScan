/**
 * dates.js — the date format shared by the file list and the exports
 *
 * A format is a strftime layout of %d %m %Y. The UI renders it here and export()
 * sends the same layout to Python, so both always show the same dates.
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
  _systemPattern: null,

  setMode(mode) {
    this.mode = this.OPTIONS.some(o => o.value === mode) ? mode : 'system';
  },

  pattern() {
    return this.FIXED[this.mode] ?? this.systemPattern();
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

  formatDate(date) {
    const pad = n => String(n).padStart(2, '0');
    return this.pattern().replace(/%([dmY])/g, (_, d) =>
      d === 'd' ? pad(date.getDate())
      : d === 'm' ? pad(date.getMonth() + 1)
      : String(date.getFullYear()));
  },

  format(ts) {
    return ts ? this.formatDate(new Date(ts * 1000)) : '';
  },
};
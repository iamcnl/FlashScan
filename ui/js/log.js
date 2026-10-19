/**
 * log.js — forwards JS errors to the Python log file (flashscan.log).
 * Loaded first, so errors during startup are queued until the bridge is ready.
 */
const Log = (() => {
  const MAX_QUEUED = 50;
  const queue = [];

  function _send(level, message, source) {
    const api = window.pywebview?.api;
    if (!api?.log_js) {
      if (queue.length < MAX_QUEUED) queue.push([level, message, source]);
      return;
    }
    api.log_js(level, message, source).catch(() => {});
  }

  function _flush() {
    while (queue.length && window.pywebview?.api?.log_js) _send(...queue.shift());
  }

  function _text(value) {
    if (value instanceof Error) return value.stack || `${value.name}: ${value.message}`;
    if (typeof value === 'string') return value;
    try { return JSON.stringify(value); } catch (_) { return String(value); }
  }

  window.addEventListener('pywebviewready', _flush);

  window.addEventListener('error', e => {
    const where = e.filename ? ` (${e.filename}:${e.lineno}:${e.colno})` : '';
    _send('error', `${e.message}${where}${e.error?.stack ? '\n' + e.error.stack : ''}`, 'window.onerror');
  });

  window.addEventListener('unhandledrejection', e => {
    _send('error', _text(e.reason), 'unhandledrejection');
  });

  const nativeError = console.error;
  console.error = (...args) => {
    nativeError.apply(console, args);
    _send('error', args.map(_text).join(' '), 'console.error');
  };

  return {
    error: (msg, source = '') => _send('error', _text(msg), source),
    warn:  (msg, source = '') => _send('warn',  _text(msg), source),
    info:  (msg, source = '') => _send('info',  _text(msg), source),
  };
})();
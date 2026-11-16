/* The page's action trail for the debug log (contracts/diag.md, "ui.*" events). Loaded by the dashboard; same-origin
   add-on frames are watched through it (DiagTrail.watchFrame). It records WHAT happened, never content: window
   errors, unhandled rejections, console.error (the kind, not the text), fetch route + status + duration (no
   bodies, no headers), the id of a clicked [data-action] button, route changes, client vs server revision with the
   age of the state cache, and once per load the viewport, zoom, browser and asset version. Events go in batches
   to POST /api/diag, which writes them through orch's own log (same hider and budgets) and says when the log is off. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) {
    root.DiagTrail = api;
    if (typeof root.ORCH_SNAPSHOT === 'undefined') api.install(root);
  }
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';
  const TICKET = /^#ticket\/(t_[a-z0-9]{6,16})/;
  const QUIET = /^\/api\/(state|term|update-status|chat\/)/; // polls: logged only when slow or failing
  const SKIP = /^\/api\/(diag|events)/; // our own batches and the live stream
  const SLOW_MS = 800, BATCH = 60, QUEUE_MAX = 200, EVERY_MS = 2000;
  const path = url => {
    try { return new URL(String(url && url.url ? url.url : url), 'http://x').pathname; } catch (_) { return ''; }
  };
  const fold = text => String(text || '').split('?')[0].replace(/\b(?:ws|t|q|m|ph|wh|b|f|r|j|c)_[A-Za-z0-9]{4,}\b|\b\d{3,}\b/g, ':id').slice(0, 80);
  const browser = ua => {
    const m = /(Edg|Firefox|Chrome|Version)\/(\d+)/.exec(ua || '');
    return m ? ({Edg: 'Edge', Version: 'Safari'}[m[1]] || m[1]) + ' ' + m[2] : 'unknown';
  };

  // One tracker per top window: it owns the queue and the timer; frames push into it.
  function install(win, options) {
    if (win.__orchDiagTrail) return win.__orchDiagTrail;
    const opts = options || {};
    const rawFetch = win.fetch ? win.fetch.bind(win) : null;
    const queue = [];
    let enabled = true, timer = null, lastHash = win.location ? win.location.hash : '';
    const tracker = {
      get enabled() { return enabled; },
      queue,
      push(ev, kv, ticket) {
        if (!enabled) return;
        const t = ticket !== undefined ? ticket : (TICKET.exec(win.location ? win.location.hash : '') || [])[1];
        if (queue.length >= QUEUE_MAX) queue.shift();
        queue.push({ev, kv: kv || {}, at: Date.now(), ticket: t || null});
        if (!timer) { timer = setTimeout(() => { timer = null; tracker.flush(); }, EVERY_MS); if (timer.unref) timer.unref(); }
      },
      async flush() {
        if (!enabled || !queue.length || !rawFetch) return;
        const now = Date.now(), batch = queue.splice(0, BATCH);
        const events = batch.map(e => Object.assign({ev: e.ev, kv: e.kv, ago: Math.min(600000, Math.max(0, now - e.at))}, e.ticket ? {ticket: e.ticket} : {}));
        try {
          const res = await rawFetch('/api/diag', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({events}), keepalive: true});
          const answer = res.ok ? await res.json() : null;
          if (answer && answer.enabled === false) { enabled = false; queue.length = 0; } // the log is off: stop sending
        } catch (_) { /* a failed batch is dropped; the trail never disturbs the page */ }
        if (queue.length && enabled && !timer) timer = setTimeout(() => { timer = null; tracker.flush(); }, EVERY_MS);
      },
      state(clientRev, serverRev, ageMs) {
        tracker.push('ui.state', {client_rev: String(clientRev || '').slice(0, 12), server_rev: String(serverRev || '').slice(0, 12), cache_age_ms: Math.max(-1, Math.round(Number(ageMs) || 0))});
      },
      watch(target) { watchWindow(tracker, target, opts); },
      frames: new Set(),
    };
    win.__orchDiagTrail = tracker;
    watchWindow(tracker, win, opts);
    if (win.addEventListener) {
      win.addEventListener('hashchange', () => {
        tracker.push('ui.route', {from: fold(lastHash), to: fold(win.location.hash)});
        lastHash = win.location.hash;
      });
      win.addEventListener('pagehide', () => { tracker.flush(); });
    }
    const nav = win.navigator || {};
    tracker.push('ui.env', {
      w: Math.round(win.innerWidth || 0), h: Math.round(win.innerHeight || 0),
      zoom: Math.round((win.devicePixelRatio || 1) * 100), browser: browser(nav.userAgent),
      assets: String((win.document && win.document.querySelector && (win.document.querySelector('meta[name="orch-assets"]') || {}).content) || '').slice(0, 40),
      touch: !!(nav.maxTouchPoints > 0),
    });
    return tracker;
  }

  // Errors, rejections, console.error, fetch and [data-action] clicks of one window (the top window or a frame).
  function watchWindow(tracker, w, opts) {
    if (!w || w.__orchDiagWatched) return;
    w.__orchDiagWatched = true;
    w.addEventListener('error', e => {
      if (e.target && e.target !== w) return; // a missing picture or script file is not a script error
      const err = e.error;
      tracker.push('ui.error', {kind: 'error', what: String((err && err.name) || 'Error').slice(0, 60), file: String(e.filename || '').split('?')[0].split('/').pop(), line: e.lineno | 0, col: e.colno | 0});
    });
    w.addEventListener('unhandledrejection', e => {
      const r = e.reason;
      tracker.push('ui.error', {kind: 'rejection', what: String((r && r.name) || typeof r).slice(0, 60)});
    });
    const c = w.console;
    if (c && typeof c.error === 'function') {
      const orig = c.error.bind(c);
      c.error = (...args) => {
        const a = args[0];
        tracker.push('ui.console_error', {what: String((a && a.name) || typeof a).slice(0, 60), n: args.length});
        return orig(...args);
      };
    }
    if (w.fetch && !(opts && opts.noFetch)) {
      const orig = w.fetch.bind(w);
      w.fetch = (input, init) => {
        const route = path(input);
        if (SKIP.test(route)) return orig(input, init);
        const t0 = Date.now(), method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
        const log = (status, outcome) => {
          const ms = Date.now() - t0;
          if (QUIET.test(route) && outcome === 'ok' && ms < SLOW_MS) return;
          tracker.push('ui.fetch', {route: fold(route), method, status, ms, outcome});
        };
        return orig(input, init).then(res => { log(res.status, res.ok ? 'ok' : 'error'); return res; }, err => {
          log(0, err && err.name === 'AbortError' ? 'cancelled' : 'failed');
          throw err;
        });
      };
    }
    w.document.addEventListener('click', e => {
      const b = e.target && e.target.closest ? e.target.closest('[data-action]') : null;
      if (b) tracker.push('ui.action', {id: String(b.dataset.action).slice(0, 60), route: fold(w.top && w.top.location ? w.top.location.hash : '')});
    }, true);
  }

  // A same-origin add-on frame: watched again after each load. A sandboxed one (opaque origin) cannot be reached: skipped.
  function watchFrame(win, frame) {
    const t = install(win);
    const attach = () => {
      try {
        const cw = frame.contentWindow;
        if (cw && cw.document) t.watch(cw);
      } catch (_) { /* cross-origin or sandboxed frame: nothing to watch */ }
    };
    frame.addEventListener('load', attach);
    attach();
  }

  return {install, watchFrame, fold, browser};
}
);

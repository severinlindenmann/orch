'use strict';
// Live sessions (ORCH-359): the one list of sessions the new Focus reads (the bar, the panes, later the wall), from
// GET /api/sessions (sessions.py: built from the state the page already polls, plus one read of the live screens).
// Polled every few seconds while the Preview switch is on and the page is shown; nothing else asks for it.
// window.LiveSessions: list (in the API's order), get(id or key), ready (true after the first answer), refresh().
// Every answer fires 'orch:live-sessions' on window; the bar and the layer repaint on it.
//
// The words below are shared by every place that shows a session, so the wall says it the same way (draft D).
const LIVE_SESSIONS_EVERY = 3000;  // ms between two reads (the state poll's pace)
const LIVE_SESSIONS_LINES = 8;
const LIVE_STATUS_BAR = {'needs-you':'wait', working:'run', 'in-line':'queue', idle:'idle'};  // the bar's codes; closed is not in the bar

// "25 min", "1 h 5 min", "2 h"
function liveDur(seconds) {
  const m = Math.max(0, Math.floor((Number(seconds) || 0) / 60));
  if (m < 60) return m + ' min';
  return Math.floor(m / 60) + ' h' + (m % 60 ? ' ' + (m % 60) + ' min' : '');
}
// What the session does now, in one plain sentence: the open question, else the core's detail, else what it waits on.
function liveNow(s) {
  if (!s) return '';
  if (s.status === 'needs-you') return s.question || s.detail || 'Waits for you.';
  if (s.status === 'in-line') return 'Waits in line for a free helper place.';
  if (s.status === 'closed') return 'No session right now.';
  const w = Array.isArray(s.waiting_on) ? s.waiting_on.filter(x => x && x.what && x.kind !== 'person') : [];
  if (s.detail) return s.detail;
  if (w.length) return 'Waiting for ' + w.map(x => x.what).join(', ');
  return s.word || '';
}
// "Tool · Model", or one of them, or ''
function liveTool(s) {
  return [s?.tool, s?.model].filter(x => typeof x === 'string' && x).join(' · ');
}
// How long it stays: draft D's words
function liveWarm(s) {
  if (!s) return '';
  if (s.status === 'idle') return Number.isFinite(s.closes_in_seconds) ? 'closes in ' + liveDur(s.closes_in_seconds) + ' if left idle' : 'idle';
  if (s.status === 'closed') return 'closed, the conversation is kept';
  if (s.status === 'in-line') return 'starts when a place is free';
  return s.status === 'needs-you' ? 'stays warm while it waits for you' : 'stays warm while it works';
}
// The meta line of a pane or tile: tool and model, open time, how long it stays
function liveMeta(s) {
  return [liveTool(s), Number.isFinite(s?.open_seconds) ? 'open ' + liveDur(s.open_seconds) : '', liveWarm(s)].filter(Boolean);
}
// The bar's rows from the sessions: {id, key, title, s: wait|run|queue|idle, word, pin}; closed sessions are left out.
function liveBarRows(sessions, pins) {
  const pinned = new Set(Array.isArray(pins) ? pins.map(String) : []), out = [];
  for (const x of Array.isArray(sessions) ? sessions : []) {
    const s = x && LIVE_STATUS_BAR[x.status];
    if (!s || !x.id) continue;
    out.push({id:String(x.id), key:typeof x.key === 'string' ? x.key : '', title:String(x.title || ''), s,
      word:s === 'wait' ? 'Needs you' : s === 'queue' ? 'In line' : String(x.word || ''), pin:pinned.has(String(x.id))});
  }
  const rank = {wait:0, run:1, queue:2, idle:3};
  out.sort((a, b) => rank[a.s] - rank[b.s] || (b.pin ? 1 : 0) - (a.pin ? 1 : 0));
  return out;
}

if (typeof module === 'object' && module.exports) {
  module.exports = {liveDur, liveNow, liveTool, liveWarm, liveMeta, liveBarRows, LIVE_STATUS_BAR};
} else {
  (() => {
    const store = {list:[], ready:false, sig:'', timer:0, busy:false};
    const on = () => typeof livePreviewOn === 'function' && livePreviewOn();
    async function read() {
      if (store.busy || !on() || document.visibilityState === 'hidden') return;
      store.busy = true;
      try {
        const r = await fetch('api/sessions?lines=' + LIVE_SESSIONS_LINES, {cache:'no-store', credentials:'same-origin'});
        const body = r.ok ? await r.json() : null;
        const list = Array.isArray(body?.sessions) ? body.sessions.filter(x => x && typeof x.id === 'string') : null;
        if (list) {
          const sig = JSON.stringify(list), first = !store.ready;
          store.list = list; store.ready = true;
          if (sig !== store.sig || first) { store.sig = sig; window.dispatchEvent(new CustomEvent('orch:live-sessions', {detail:{sessions:list}})); }
        }
      } catch { /* offline or the server restarts: the next read tries again */ }
      finally { store.busy = false; }
    }
    function tick() {
      clearTimeout(store.timer);
      store.timer = setTimeout(tick, LIVE_SESSIONS_EVERY);
      read();
    }
    document.addEventListener('visibilitychange', () => { if (document.visibilityState !== 'hidden') read(); });
    window.LiveSessions = {
      get list() { return store.list; },
      get ready() { return store.ready; },
      get(ref) { return store.list.find(x => x.id === ref || (x.key && String(x.key).toLowerCase() === String(ref || '').toLowerCase())) || null; },
      refresh: read,
      // app.js calls it after every render: starts the poll the first time the Preview switch is seen on
      sync() { if (on() && !store.timer) tick(); },
    };
  })();
}

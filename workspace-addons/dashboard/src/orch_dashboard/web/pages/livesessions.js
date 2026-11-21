'use strict';
// Live sessions (ORCH-359): the one list of sessions the live page reads (the bar, the panes, later the wall), from
// GET /api/sessions (sessions.py: built from the state the page already polls, plus one read of the live screens).
// Polled every few seconds while the page is shown; nothing else asks for it.
// window.LiveSessions: list (in the API's order), get(id or key), ready (true after the first answer), refresh(),
// pins, name(id), pin(id, on), rename(id, name): pins and own names kept by orch for the workspace (ORCH-361).
// Every answer fires 'orch:live-sessions' on window; the bar and the layer repaint on it.
//
// The words below are shared by every place that shows a session, so the wall says it the same way (draft D).
const LIVE_SESSIONS_EVERY = 3000;  // ms between two reads (the state poll's pace)
const LIVE_SESSIONS_LINES = 8;
const LIVE_STATUS_BAR = {'needs-you':'wait', working:'run', 'in-line':'queue', idle:'idle'};  // the bar's codes; closed is in the bar only when it asks (`needs`, liveBarRows)

// "25 min", "1 h 5 min", "2 h"
function liveDur(seconds) {
  const m = Math.max(0, Math.floor((Number(seconds) || 0) / 60));
  if (m < 60) return m + ' min';
  return Math.floor(m / 60) + ' h' + (m % 60 ? ' ' + (m % 60) + ' min' : '');
}
// What the session does now, in one plain sentence: the open question, else the core's detail, else what it waits on,
// else the step it works on (ORCH-463: a helper that said nothing showed only 'Working').
function liveNow(s) {
  if (!s) return '';
  if (s.status === 'needs-you') return s.question || s.detail || 'Needs you.';
  if (s.status === 'in-line') return 'Waits in line for a free helper place.';
  if (s.status === 'closed') return 'No session right now.';
  const w = Array.isArray(s.waiting_on) ? s.waiting_on.filter(x => x && x.what && x.kind !== 'person') : [];
  if (s.detail) return s.detail;
  if (w.length) return 'Waiting for ' + w.map(x => x.what).join(', ');
  if (typeof s.step === 'string' && s.step) return 'Working on: ' + s.step;
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
// The name a session shows (tile, pane, chip, list): the person's own name, else its title (ORCH-361).
function liveName(s) {
  const own = typeof s?.name === 'string' ? s.name.trim() : '';
  return own || String(s?.title || '');
}
// The pinned session ids: what orch keeps for the workspace ("pinned" of the API; a session without a ticket is
// pinned until it is unpinned), with a click that is still being saved on top.
function livePinIds(sessions, pending) {
  const wait = pending && typeof pending === 'object' ? pending : {};
  return (Array.isArray(sessions) ? sessions : []).filter(x => x && x.id && (typeof wait[x.id]?.pinned === 'boolean' ? wait[x.id].pinned : x.pinned === true)).map(x => String(x.id));
}
// The bar's rows from the sessions: {id, key, title, name, s: wait|run|queue|idle, word, pin, kind}; closed sessions
// are left out. title is the name shown (own name, else the title); name is the own name or ''. kind is '' for a
// ticket's session, else empty | chat | terminal | manager (a session without a ticket, ORCH-364).
// With groups (ORCH-345) an epic or a run order is ONE row: id = the session a click opens, n = its helpers (the
// same count as its wall tile), members = every session of it (a chip is current when one of them is open).
function liveBarRows(sessions, pins, groups) {
  const pinned = new Set(Array.isArray(pins) ? pins.map(String) : livePinIds(sessions)), out = [];
  let list = Array.isArray(sessions) ? sessions : [];
  if (Array.isArray(groups) && groups.length) {
    const fold = typeof liveGroupFold === 'function' ? liveGroupFold : require('./livegroups.js').liveGroupFold;
    list = fold(list, groups);
  }
  for (const x of list) {
    // ORCH-1358: an idle or closed session whose ticket waits for the person (`needs`) is a Needs you chip, as on the wall
    const s = x && (x.needs === true && (x.status === 'idle' || x.status === 'closed') ? 'wait' : LIVE_STATUS_BAR[x.status]);
    if (!s || !x.id) continue;
    const row = {id:String(x.opens || x.id), key:typeof x.key === 'string' ? x.key : '', title:liveName(x), name:typeof x.name === 'string' ? x.name.trim() : '', s,
      word:s === 'wait' ? 'Needs you' : s === 'queue' ? 'In line' : String(x.word || ''), pin:pinned.has(String(x.id)) || (!!x.opens && pinned.has(String(x.opens))),
      kind:typeof x.kind === 'string' ? x.kind : ''};
    if (x.group) {
      row.group = x.id;
      row.members = x.group.members.map(m => m.id);
      row.n = x.group.members.filter(m => ['needs-you', 'working', 'idle'].includes(m.status)).length;
      row.line = x.detail || '';
    }
    out.push(row);
  }
  const rank = {wait:0, run:1, queue:2, idle:3};
  out.sort((a, b) => rank[a.s] - rank[b.s] || (b.pin ? 1 : 0) - (a.pin ? 1 : 0));
  return out;
}

if (typeof module === 'object' && module.exports) {
  module.exports = {liveDur, liveNow, liveTool, liveWarm, liveMeta, liveBarRows, liveName, livePinIds, LIVE_STATUS_BAR};
} else {
  (() => {
    const store = {list:[], groups:[], ready:false, sig:'', timer:0, busy:false, pending:{}, moved:false};
    // A pin or a name the person just chose shows at once; a read that comes back before orch kept it keeps the choice.
    const mark = list => list.map(x => store.pending[x.id] ? {...x, ...store.pending[x.id]} : x);
    const told = (key, extra) => {
      store.list = mark(store.list);
      store.sig = JSON.stringify(store.list);
      window.dispatchEvent(new CustomEvent('orch:live-sessions', {detail:{sessions:store.list}}));
      if (extra) window.dispatchEvent(new CustomEvent('orch:live-pins', {detail:{key, ...extra}}));
    };
    // Pins and names are kept by orch for the workspace (POST /api/act session.pin / session.name, sessionprefs.py),
    // so every browser and every reload shows them (issue 1351). A refused or failed save goes back and says why.
    async function save(op, id, change, quiet = false) {
      const was = store.list.find(x => x.id === id);
      if (!was || typeof window.orchAct !== 'function') return false;
      const before = {pinned:was.pinned, name:was.name ?? null};
      store.pending[id] = {...store.pending[id], ...change};
      told(id, 'pinned' in change ? {pinned:change.pinned} : null);
      const r = await window.orchAct(op, {session:id, ...change});
      const rest = {...store.pending[id]};
      for (const k of Object.keys(change)) if (rest[k] === change[k]) delete rest[k];
      if (Object.keys(rest).length) store.pending[id] = rest; else delete store.pending[id];
      if (!r?.ok) {
        store.list = store.list.map(x => x.id === id ? {...x, ...Object.fromEntries(Object.keys(change).map(k => [k, before[k]]))} : x);
        told(id, 'pinned' in change ? {pinned:before.pinned} : null);
        if (!quiet) window.orch?.toast?.(r?.text || 'That did not work.', 'error');
        return false;
      }
      read();
      return true;
    }
    // Pins kept in this browser before orch kept them (the bar's old key): moved into orch once, then forgotten.
    function moveOldPins() {
      if (store.moved) return;
      store.moved = true;
      let old = [];
      try { old = JSON.parse(localStorage.getItem('orch.live.pins') || '[]'); } catch { return; }
      if (!Array.isArray(old) || !old.length || typeof window.orchAct !== 'function') return;
      const here = old.filter(id => store.list.some(x => x.id === id && !x.pinned));
      Promise.all(here.map(id => save('session.pin', id, {pinned:true}, true))).then(done => {
        if (done.every(Boolean)) try { localStorage.removeItem('orch.live.pins'); } catch { /* private window */ }
      });
    }
    const on = () => typeof liveFocusOn === 'function' && liveFocusOn();
    async function read() {
      if (store.busy || !on() || document.visibilityState === 'hidden') return;
      if (window.orchQuiet?.()) return;  // an add-on change restarts the server: the next tick asks it (ORCH-1034)
      store.busy = true;
      try {
        const r = await fetch('api/sessions?lines=' + LIVE_SESSIONS_LINES, {cache:'no-cache', credentials:'same-origin'});
        const body = r.ok ? await r.json() : null;
        const list = Array.isArray(body?.sessions) ? body.sessions.filter(x => x && typeof x.id === 'string') : null;
        if (list) {
          const groups = Array.isArray(body.groups) ? body.groups.filter(g => g && typeof g.id === 'string' && Array.isArray(g.members)) : [];
          const marked = mark(list), sig = JSON.stringify([marked, groups]), first = !store.ready;
          store.list = marked; store.groups = groups; store.ready = true;
          if (first) setTimeout(moveOldPins, 0);
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
      get groups() { return store.groups; },  // epics and run orders with sessions (ORCH-345, pages/livegroups.js)
      get ready() { return store.ready; },
      get(ref) { return store.list.find(x => x.id === ref || (x.key && String(x.key).toLowerCase() === String(ref || '').toLowerCase())) || null; },
      refresh: read,
      // the pinned session ids and the name a session shows (pin and rename, ORCH-361)
      get pins() { return livePinIds(store.list, store.pending); },
      name(ref) { const x = this.get(ref); return x ? liveName(x) : ''; },
      pin(id, on) { const x = this.get(id); return x ? save('session.pin', x.id, {pinned:typeof on === 'boolean' ? on : !livePinIds([x], store.pending).length}) : Promise.resolve(false); },
      rename(id, name) { const x = this.get(id); return x ? save('session.name', x.id, {name:String(name || '').trim() || null}) : Promise.resolve(false); },
      // app.js calls it after every render: starts the poll the first time the live page is on
      sync() { if (on() && !store.timer) tick(); },
    };
  })();
}

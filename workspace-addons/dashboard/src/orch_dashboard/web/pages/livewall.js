'use strict';
// The wall of the live page (draft D, ORCH-360; pages/live.js). Every session of the
// workspace in bands: Pinned, Needs you and working (orange needs-you tiles first), In line, Idle and no session. A
// working tile shows what its helper does in one sentence and a peek of its last lines, kept current by the live
// sessions API (pages/livesessions.js, ORCH-359). A filter keeps the matching tiles; a band folds away and stays
// folded (per workspace, in this browser). Clicking a tile zooms into it: it opens in the layer (pages/live-layer.js);
// full screen and Esc are the layer's. Pins and own names are kept by orch for the workspace (window.LiveSessions, ORCH-361).
// Look: the kit's .wall-* rules (widgets.css).
const LIVE_WALL_KEY = 'orch.live.wall';
const LIVE_WALL_MANY = 12;  // from this many sessions the long bands scroll inside themselves (draft D, 24 and more)
const LIVE_WALL_PEEK = 3;  // last lines in a tile's peek
const LIVE_WALL_SYM = {'needs-you':'◆', working:'●', 'in-line':'◷', idle:'◐', closed:'○'};
const LIVE_WALL_WORD = {'needs-you':'Needs you', working:'Working', 'in-line':'In line', idle:'Idle', closed:'No session'};

// --- the model: plain data, no page (tested in tests/live_wall.test.js) ---
// Groups (ORCH-345, pages/livegroups.js): an epic or a run order is ONE entry, found by any of its helpers.
const liveWallGroups = typeof liveGroupFold === 'function' ? {fold:liveGroupFold, match:liveGroupMatch}
  : (() => { try { const g = require('./livegroups.js'); return {fold:g.liveGroupFold, match:g.liveGroupMatch}; } catch { return null; } })();
// The bands of the wall from the sessions (the API's order), the pinned ids, the filter text and the groups.
// Pinned sessions sit in their own band; a pinned one that needs you is still orange there.
function liveWallBands(sessions, pins, filter, groups) {
  const pinned = new Set(Array.isArray(pins) ? pins.map(String) : []);
  const f = String(filter || '').trim().toLowerCase();
  const folded = Array.isArray(groups) && groups.length && liveWallGroups ? liveWallGroups.fold(sessions, groups) : sessions;
  const all = (Array.isArray(folded) ? folded : []).filter(s => s && typeof s.id === 'string' && LIVE_WALL_WORD[s.status]);
  const shown = f ? all.filter(s => s.group ? liveWallGroups.match(s.group, f)
    : [s.key, s.name, s.title, s.word, LIVE_WALL_WORD[s.status]].filter(x => typeof x === 'string' && x).join(' ').toLowerCase().includes(f)) : all;
  const rank = {'needs-you':0, working:1, idle:2, 'in-line':3, closed:4};
  // ORCH-790: an idle or closed session whose ticket waits for the person (`needs`) sorts and lands with needs you
  const asks = s => s.status === 'needs-you' || ((s.status === 'idle' || s.status === 'closed') && s.needs === true);
  const sorted = shown.map((s, i) => [s, i]).sort((a, b) => (asks(a[0]) ? 0 : rank[a[0].status]) - (asks(b[0]) ? 0 : rank[b[0].status]) || a[1] - b[1]).map(x => x[0]);
  const pin = sorted.filter(s => pinned.has(s.id)), rest = sorted.filter(s => !pinned.has(s.id));
  return {
    pin, need:rest.filter(s => asks(s) || s.status === 'working'),
    queue:rest.filter(s => s.status === 'in-line'), idle:rest.filter(s => !asks(s) && (s.status === 'idle' || s.status === 'closed')),
    total:all.length, shown:shown.length,
  };
}
// The summary line: counts of every session, whatever the filter says.
function liveWallCounts(sessions) {
  const c = {'needs-you':0, working:0, 'in-line':0, idle:0, closed:0, total:0};
  // ORCH-1358: one that asks (`needs`, ORCH-790) counts as needs you, as its tile sits in that band and the bar shows it
  for (const s of Array.isArray(sessions) ? sessions : []) if (s && typeof s.id === 'string' && LIVE_WALL_WORD[s.status]) {
    c[(s.status === 'idle' || s.status === 'closed') && s.needs === true ? 'needs-you' : s.status]++; c.total++;
  }
  return c;
}
// The parts of the summary line, in draft D's words: "3 need you", "1 needs you", "4 working", "9 in line", "8 idle".
// `total` is the one number of things waiting on the person (the Review badge, as the live bar reads it, ORCH-464);
// the wall never says less than it or than the sessions that ask (ORCH-674).
function liveWallSummary(sessions, total) {
  const c = liveWallCounts(sessions), out = [];
  c['needs-you'] = Math.max(Number(total) || 0, c['needs-you']);
  out.push(c['needs-you'] ? {s:'needs-you', text:c['needs-you'] + (c['needs-you'] === 1 ? ' needs you' : ' need you')} : {s:'', text:'Nobody needs you'});
  if (c.working) out.push({s:'working', text:c.working + ' working'});
  if (c['in-line']) out.push({s:'in-line', text:c['in-line'] + ' in line'});
  if (c.idle) out.push({s:'idle', text:c.idle + ' idle'});
  return out;
}
// "1 session", "2 sessions"
function liveWallSessions(n) { return n + (n === 1 ? ' session' : ' sessions'); }
// The line under the summary (draft D): "24 sessions · 8 of 8 helper places in use"; without a limit (Settings > Helper >
// Helpers at once) "· 3 helper places in use". p: {used, max} as the Start choice reads it (pages/live-start.js).
function liveWallTotal(n, p) {
  if (!p || typeof p !== 'object') return liveWallSessions(n);
  const max = Number.isInteger(p.max) && p.max > 0 ? p.max : null, used = Number.isInteger(p.used) ? Math.max(0, p.used) : 0;
  const places = max === null ? used + (used === 1 ? ' helper place' : ' helper places') : used + ' of ' + max + (max === 1 ? ' helper place' : ' helper places');
  return liveWallSessions(n) + ' · ' + places + ' in use';
}
// The peek: the last few lines that say something; none while a question waits (the tile shows the question).
function liveWallPeek(s, n = LIVE_WALL_PEEK) {
  if (!s || s.status === 'needs-you' || !Array.isArray(s.lines)) return '';
  return s.lines.map(x => String(x == null ? '' : x).replace(/\s+$/, '')).filter(x => x.trim()).slice(-n).join('\n');
}
// What is kept per workspace in this browser: the folded bands. The filter is not kept (a fresh visit shows all).
function liveWallRead(store, ws) {
  try {
    const all = JSON.parse(store?.getItem(LIVE_WALL_KEY) || 'null');
    const mine = all && typeof all === 'object' ? all[String(ws || '')] : null;
    const col = mine && typeof mine.col === 'object' ? mine.col : {};
    return {col:Object.fromEntries(['pin', 'need', 'queue', 'idle'].filter(k => col[k] === true).map(k => [k, true]))};
  } catch { return {col:{}}; }
}
function liveWallWrite(store, ws, ui) {
  try {
    let all = JSON.parse(store?.getItem(LIVE_WALL_KEY) || 'null');
    if (!all || typeof all !== 'object' || Array.isArray(all)) all = {};
    all[String(ws || '')] = {col:ui.col};
    store?.setItem(LIVE_WALL_KEY, JSON.stringify(all));
  } catch { /* private window: nothing kept */ }
}

if (typeof module === 'object' && module.exports) {
  module.exports = {liveWallBands, liveWallCounts, liveWallSummary, liveWallSessions, liveWallTotal, liveWallPeek, liveWallRead, liveWallWrite, LIVE_WALL_MANY};
}

// --- the page ---
let liveWallUi = null;
let liveWallWs = null;
function liveWallStore() { try { return window.localStorage; } catch { return null; } }
function liveWallState() {
  const ws = typeof state === 'object' && state ? String(state.workspace || state.settings?.ws_name || '') : '';
  if (!liveWallUi || liveWallWs !== ws) { liveWallUi = {...liveWallRead(liveWallStore(), ws), f:liveWallUi?.f || ''}; liveWallWs = ws; }
  return liveWallUi;
}
function liveWallPins() {
  return Array.isArray(window.LiveSessions?.pins) ? window.LiveSessions.pins : [];
}
function liveWallStat(s) {
  return h('span', {className:'wall-st', 'data-s':s.status},
    h('span', {className:'wall-sym', 'aria-hidden':'true'}, LIVE_WALL_SYM[s.status]), s.status === 'needs-you' ? 'Needs you' : s.word || LIVE_WALL_WORD[s.status]);
}
function liveWallLabel(s) { return s.key || liveName(s) || 'this session'; }
function liveWallOpen(s, cls, ...children) {
  return h('button', {type:'button', className:cls, 'data-wall-open':s.opens || s.id, 'data-key':'wall-open-' + s.id,
    'aria-label':'Open ' + liveWallLabel(s) + ', ' + liveName(s) + ', ' + (s.status === 'needs-you' ? 'Needs you' : s.word || LIVE_WALL_WORD[s.status])}, ...children);
}
function liveWallTicketLink(s) {
  const t = typeof ticketOf === 'function' ? ticketOf(s.id) : null;
  return t ? h('a', {className:'wall-tk', href:'#ticket/' + encodeURIComponent(t.id), 'data-key':'wall-ticket-' + s.id, 'aria-label':'Open ticket ' + liveWallLabel(s)}, 'Open ticket') : null;
}
function liveWallSteps(s) {
  const t = typeof ticketOf === 'function' ? ticketOf(s.id) : null, tasks = Array.isArray(t?.checklist) ? t.checklist : [];
  if (!tasks.length || !window.DashHelpers) return null;
  const done = tasks.filter(window.DashHelpers.resolved).length, bar = h('span', {});
  bar.style.width = Math.round(done / tasks.length * 100) + '%';
  return h('span', {className:'wall-steps'},
    h('span', {className:'progress', role:'progressbar', 'aria-label':'Tasks done', 'aria-valuemin':0, 'aria-valuemax':tasks.length, 'aria-valuenow':done}, bar),
    h('span', {className:'meta'}, window.DashHelpers.stepsText(done, tasks.length)));
}
function liveWallBeside(s) {
  return h('button', {type:'button', className:'btn icon sm ghost wall-beside', 'data-wall-beside':s.opens || s.id, 'data-key':'wall-beside-' + s.id,
    'aria-label':'Open ' + liveWallLabel(s) + ' beside what is open', title:'Open beside'}, iconEl('plus'));
}
// Pin or unpin from the wall (draft D: on every tile and line); kept by orch for the workspace (ORCH-361).
function liveWallPin(s, pinned) {
  return h('button', {type:'button', className:'btn icon sm ghost', 'data-wall-pin':s.id, 'data-key':'wall-pin-' + s.id,
    'aria-pressed':String(pinned), 'aria-label':(pinned ? 'Unpin ' : 'Pin ') + liveWallLabel(s), title:pinned ? 'Unpin' : 'Pin'}, iconEl('pinned'));
}
// Stop and End session from the wall (ORCH-817, pages/live-end.js): a More button with its menu on tiles and lines.
function liveWallEnd(s) {
  if (typeof window.liveEndMore !== 'function' || s.group) return [];
  return [window.liveEndMore(s.id, 'tile', liveWallLabel(s)), window.liveEndOpenAt('tile') === s.id ? window.liveEndMenu(s.id, 'tile:' + s.id) : null];
}
// A group's tile (ORCH-345): the group's title, its helper counts, the small tree; orange when one helper needs you.
function liveWallGroupTile(s, pinned) {
  const g = s.group;
  return h('article', {className:'wall-tile', 'data-s':s.status, 'data-group':'', 'data-key':'wall-tile-' + s.id, 'data-tile':s.id, 'data-pinned':pinned ? '1' : null},
    liveWallOpen(s, 'wall-open',
      h('span', {className:'wall-th'}, liveWallStat(s), h('span', {className:'wall-key'}, s.key || '')),
      h('span', {className:'wall-tt'}, s.title || ''),
      h('span', {className:'wall-now', 'data-wall-now':s.id}, liveGroupLine(g)),
      liveGroupPreview(g)),
    h('span', {className:'wall-foot'}, liveWallSteps(s), h('span', {className:'grow'}), liveWallTicketLink(s), liveWallPin(s, pinned), liveWallBeside(s)));
}
function liveWallTile(s, pinned) {
  if (s.group && typeof liveGroupPreview === 'function') return liveWallGroupTile(s, pinned);
  const peek = liveWallPeek(s), meta = liveMeta(s);
  return h('article', {className:'wall-tile', 'data-s':s.status, 'data-key':'wall-tile-' + s.id, 'data-tile':s.id, 'data-pinned':pinned ? '1' : null},
    liveWallOpen(s, 'wall-open',
      h('span', {className:'wall-th'}, liveWallStat(s), h('span', {className:'wall-key'}, s.key || '')),
      h('span', {className:'wall-tt'}, liveName(s)),
      h('span', {className:'wall-now', 'data-wall-now':s.id}, liveNow(s)),
      peek ? h('span', {className:'wall-peek', 'data-wall-peek':s.id, 'aria-hidden':'true'}, peek) : null),
    meta.length ? h('span', {className:'wall-meta meta'}, meta.map(x => h('span', {}, x))) : null,
    liveWallResults(s),
    // the buttons stay together: a tile with a task bar never leaves ⋯ alone on a row of its own (ORCH-1663)
    h('span', {className:'wall-foot'}, liveWallSteps(s), h('span', {className:'grow'}), h('span', {className:'wall-acts'}, liveWallTicketLink(s), liveWallPin(s, pinned), liveWallBeside(s), ...liveWallEnd(s))));
}
// The ticket's newest result, small, and "+N more" (ORCH-697); a click opens it big. None without a ticket.
function liveWallResults(s) {
  const t = typeof ticketOf === 'function' ? ticketOf(s.id) : null;
  return t && typeof resultsHost === 'function' ? resultsHost(t.id, {key:'wall-results-' + s.id, max:typeof RESULTS_TILE === 'number' ? RESULTS_TILE : 1, cls:'wall-results', label:'Results of ' + liveWallLabel(s)}) : null;
}
function liveWallLine(s, pinned) {
  const meta = [liveTool(s), liveWarm(s)].filter(Boolean), now = liveNow(s);
  const said = now && ![s.word, LIVE_WALL_WORD[s.status]].includes(now) ? now : '';  // "Idle" once, not twice
  return h('div', {className:'wall-line', 'data-s':s.status, 'data-key':'wall-tile-' + s.id, 'data-tile':s.id},
    liveWallOpen(s, 'wall-lopen', liveWallStat(s), h('span', {className:'wall-key'}, s.key || ''), h('span', {className:'wall-tt'}, liveName(s)),
      h('span', {className:'wall-lnow', 'data-wall-now':s.id, 'aria-hidden':said ? null : 'true'}, said || '\u00a0')),
    meta.length ? h('span', {className:'wall-lmeta meta'}, meta.map(x => h('span', {}, x))) : null,
    liveWallTicketLink(s), liveWallPin(s, pinned), ...liveWallEnd(s));
}
const LIVE_WALL_BANDS = [
  ['pin', 'Pinned', 'Nothing is pinned. Pin a session to keep it here.'],
  ['need', 'Needs you and working', 'No helper is working right now.'],
  ['queue', 'In line', ''],
  ['idle', 'Idle and no session', 'Every ticket has a working helper.'],
];
function liveWallBand(id, title, empty, list, ui, many) {
  const col = !!ui.col[id], tiles = id === 'pin' || id === 'need';
  return h('section', {className:'wall-band', 'data-band':id, 'data-key':'wall-band-' + id, 'aria-label':title},
    h('h2', {className:'wall-bh'}, h('button', {type:'button', className:'wall-bt', 'data-wall-fold':id, 'data-key':'wall-fold-' + id, 'aria-expanded':String(!col)},
      h('span', {className:'wall-chev', 'aria-hidden':'true'}, col ? '▸' : '▾'), title + ' (' + list.length + ')')),
    col ? null : list.length
      ? h('div', {className:tiles ? 'wall-tiles' : 'wall-lines', 'data-key':'wall-list-' + id, 'data-many':many && list.length > 4 ? '1' : null},
        list.map(s => tiles ? liveWallTile(s, id === 'pin') : liveWallLine(s, false)))
      : h('p', {className:'meta wall-none'}, empty));
}
// The bands and the summary (repainted in place on every answer of the sessions API).
function liveWallBody() {
  const ui = liveWallState(), list = window.LiveSessions?.list || [], ready = !!window.LiveSessions?.ready;
  const b = liveWallBands(list, liveWallPins(), ui.f, window.LiveSessions?.groups), many = b.total >= LIVE_WALL_MANY;
  const summary = h('div', {className:'wall-sum', 'data-key':'wall-sum'},
    h('p', {className:'wall-hero', 'data-key':'wall-hero', role:'status'}, liveWallSummary(list, typeof needsYouTotal === 'function' ? needsYouTotal() : 0).map(p => h('span', {className:'wall-st', 'data-s':p.s || null},
      p.s ? h('span', {className:'wall-sym', 'aria-hidden':'true'}, LIVE_WALL_SYM[p.s]) : null, p.text))),
    h('p', {className:'meta', 'data-key':'wall-total'}, liveWallTotal(liveWallCounts(list).total,
      typeof liveStartPlaces === 'function' ? liveStartPlaces(state?.runs, state?.settings, state?.start_line) : null)),
    // the four start buttons sit right of the counts, as in draft D (ORCH-1568; pages/live.js)
    typeof liveNewButtons === 'function' ? liveNewButtons() : null);
  let bands;
  if (!ready) bands = h('p', {className:'meta wall-none', 'data-key':'wall-wait'}, 'Reading the sessions…');
  else if (!b.total) bands = h('p', {className:'meta wall-none', 'data-key':'wall-empty'}, 'No sessions yet. A ticket’s session shows here when a helper works on it.');
  else if (!b.shown) bands = h('p', {className:'meta wall-none', 'data-key':'wall-nomatch'}, 'No session matches “' + ui.f.trim() + '”.');
  else bands = h('div', {className:'wall-bands', 'data-key':'wall-bands', 'data-many':many ? '1' : null},
    LIVE_WALL_BANDS.filter(([id]) => id !== 'queue' || b.queue.length).filter(([id]) => id !== 'pin' || b.pin.length || !ui.f.trim())
      .map(([id, title, empty]) => liveWallBand(id, title, empty, b[id], ui, many)));
  return [summary, bands];
}
function liveWall() {
  const ui = liveWallState();
  return h('div', {className:'wall', 'data-key':'live-wall'},
    h('div', {className:'wall-body', 'data-key':'wall-body'}, ...liveWallBody()),
    h('div', {className:'wall-tools', 'data-key':'wall-tools'},
      h('label', {className:'sr-only', for:'wall-filter'}, 'Filter sessions'),
      h('input', {className:'input', id:'wall-filter', type:'search', placeholder:'Filter by name, ticket or status', autocomplete:'off', value:ui.f, 'data-wall-filter':'1'})));
}
// Motion (draft D, ORCH-1329): a pin or unpin (on the wall or in a pane) notes where every tile is; the next repaint
// slides the tiles from there to their new band (kit/motion.js orch.flip; still with reduced motion). A routine data
// refresh moves nothing.
let liveWallMoving = null;
function liveWallBeforePin() {
  const host = document.querySelector('main [data-key="wall-body"]');
  liveWallMoving = host && window.orch?.flip ? {rects:window.orch.rects(host, '[data-tile]', 'data-tile'), at:Date.now()} : null;
}
function liveWallRepaint() {
  const host = document.querySelector('main [data-key="wall-body"]');
  if (!host || typeof reconcile !== 'function') return;
  const moving = liveWallMoving && Date.now() - liveWallMoving.at < 1000 ? liveWallMoving.rects : null;
  liveWallMoving = null;
  const next = h('div', {}, ...liveWallBody());
  reconcile(host, next);
  if (typeof resultsFillAll === 'function') resultsFillAll(host);
  if (moving) for (const el of host.querySelectorAll('[data-tile]')) { const r = moving.get(el.dataset.tile); if (r) window.orch.flip(el, r, {scale:false}); }
}
if (typeof window === 'object' && typeof document === 'object' && !(typeof module === 'object' && module.exports)) {
  window.addEventListener('orch:live-sessions', liveWallRepaint);
  window.addEventListener('orch:live-pins', liveWallRepaint);
  document.addEventListener('input', e => {
    if (!e.target.matches?.('[data-wall-filter]')) return;
    liveWallState().f = e.target.value;
    liveWallRepaint();
  });
  document.addEventListener('click', e => {
    const fold = e.target.closest?.('[data-wall-fold]');
    if (fold) {
      const ui = liveWallState(), id = fold.dataset.wallFold;
      if (ui.col[id]) delete ui.col[id]; else ui.col[id] = true;
      liveWallWrite(liveWallStore(), liveWallWs, ui);
      liveWallRepaint();
      document.querySelector('main [data-wall-fold="' + id + '"]')?.focus({preventScroll:true});
      return;
    }
    const pin = e.target.closest?.('[data-wall-pin]');
    if (pin && window.LiveSessions) {
      const id = pin.dataset.wallPin;
      // the tile moves band, and the page is drawn again when orch answers: keep the keyboard on its pin button
      const keep = () => {
        const a = document.activeElement;
        if (!a || a === document.body || !a.isConnected || a.dataset?.wallPin === id) document.querySelector('main [data-wall-pin="' + id + '"]')?.focus({preventScroll:true});
      };
      liveWallBeforePin();
      const saved = window.LiveSessions.pin(id, pin.getAttribute('aria-pressed') !== 'true');
      keep();
      Promise.resolve(saved).then(() => requestAnimationFrame(keep));
      return;
    }
    const beside = e.target.closest?.('[data-wall-beside]');
    if (beside && window.LiveLayer) { window.LiveLayer.beside(beside.dataset.wallBeside); return; }
    const open = e.target.closest?.('[data-wall-open]');
    if (open && window.LiveLayer) window.LiveLayer.open(open.dataset.wallOpen, true);  // zoom: the session in the layer, the keyboard in its pane
  });
}

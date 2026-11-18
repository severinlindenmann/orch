'use strict';
// The layer of the new live page (draft D, ORCH-338), behind the Preview switch (pages/live.js). One dock under every
// page, outside main, so it stays open while the page changes: a panel at the bottom, on the right or full screen,
// above a bar; minimised it is only the bar, closed to the side it is a slim edge tab. Place and size are kept per
// browser. Esc goes one step back: an open menu, then full screen, then the panel to the bar. The split (ORCH-339):
// 1, 2 or 3 sessions side by side (stacked on the right), one of them selected; each pane has pin, add beside, place,
// full screen, minimise and close (pin and place fold into More when the pane is narrow). On a phone
// only the selected session shows. A pane shows the session's live data (pages/livesessions.js, ORCH-359): what it
// does now, its last lines, tool and model, open time; the chat and terminal tasks fill it further.
// Look: the kit's .live-* rules (widgets.css). The bar's session chips go into [data-key="live-bar-sessions"].
const LIVE_LAYER_KEY = 'orch.live.layer';
const LIVE_PLACES = ['bottom', 'right'];
const LIVE_SIZE = {height:[200, 0.85], width:[320, 0.7]};  // smallest px, largest share of the window
const LIVE_MAX = 3;  // sessions side by side
const LIVE_NARROW = 480;  // a pane narrower than this folds pin and place into More (draft D)

// --- the model: plain data, no page (tested in tests/live_layer.test.js) ---
function liveLayerFresh() {
  return {mode:'bar', last:'bottom', back:'bottom', height:null, width:null, panes:[], cur:'', menu:''};
}
// Narrow panes: on a phone, on the right with more than one, or when a share of the room is under LIVE_NARROW.
function liveLayerNarrow(where, n, room, phone) {
  return !!phone || (n > 1 && (where === 'right' || room / n < LIVE_NARROW));
}
function liveLayerRead(store) {
  const s = liveLayerFresh();
  let saved = null;
  try { saved = JSON.parse(store?.getItem(LIVE_LAYER_KEY) || 'null'); } catch { saved = null; }
  if (!saved || typeof saved !== 'object') return s;
  if (['bar', 'side', 'bottom', 'right'].includes(saved.mode)) s.mode = saved.mode;  // full screen is never where a new page opens
  if (saved.mode === 'full' && LIVE_PLACES.includes(saved.back)) s.mode = saved.back;
  if (LIVE_PLACES.includes(saved.last)) s.last = saved.last;
  s.back = s.last;
  for (const k of ['height', 'width']) if (Number.isFinite(saved[k]) && saved[k] > 0) s[k] = Math.round(saved[k]);
  if (Array.isArray(saved.panes)) s.panes = saved.panes.filter((k, i, a) => typeof k === 'string' && /^[A-Za-z0-9_.-]{1,64}$/.test(k) && a.indexOf(k) === i).slice(0, LIVE_MAX);
  s.cur = s.panes.includes(saved.cur) ? saved.cur : s.panes[0] || '';
  if (!s.panes.length && s.mode !== 'bar' && s.mode !== 'side') s.mode = 'bar';
  return s;
}
function liveLayerWrite(store, s) {
  try { store?.setItem(LIVE_LAYER_KEY, JSON.stringify({mode:s.mode, last:s.last, back:s.back, height:s.height, width:s.width, panes:s.panes, cur:s.cur})); } catch { /* private window: nothing kept */ }
}
// Panes sit in the same order as the chips in the bar (draft D): order is the bar's list; a session not in it stays last.
function liveLayerSort(s, order) {
  const at = k => { const i = order.indexOf(k); return i < 0 ? order.length : i; };
  const panes = s.panes.map((k, i) => [k, i]).sort((a, b) => at(a[0]) - at(b[0]) || a[1] - b[1]).map(x => x[0]);
  return panes.every((k, i) => k === s.panes[i]) ? s : {...s, panes};
}
// Where the layer really is: on a phone the right edge falls back to the bottom.
function liveLayerWhere(s, phone) {
  return phone && s.mode === 'right' ? 'bottom' : s.mode;
}
function liveLayerOpenAt(s, phone) {
  return phone ? 'bottom' : s.last;
}
// One step of the layer: returns the next model, never changes the one it got.
function liveLayerStep(s, act, phone = false) {
  const n = {...s, panes:[...s.panes], menu:''};
  const opened = () => { if (n.mode === 'bar' || n.mode === 'side') n.mode = liveLayerOpenAt(n, phone); return n; };
  switch (act.type) {
    case 'open':  // a session from the bar, a tile or a ticket: shown already, it is selected; else it takes the selected pane
      if (act.key && !n.panes.includes(act.key)) {
        const at = n.panes.indexOf(n.cur);
        if (at < 0) n.panes = [act.key, ...n.panes].slice(0, LIVE_MAX); else n.panes[at] = act.key;
      }
      if (act.key) n.cur = act.key;
      if (!n.panes.length) return s;
      if (!n.panes.includes(n.cur)) n.cur = n.panes[0];
      return opened();
    case 'beside': {  // Add beside: one more pane next to the others (the third is the most: it then takes the last pane)
      if (!act.key) return s;
      if (!n.panes.includes(act.key)) {
        if (n.panes.length >= LIVE_MAX) n.panes[LIVE_MAX - 1] = act.key; else n.panes.push(act.key);
      }
      n.cur = act.key;
      return opened();
    }
    case 'select':
      if (!n.panes.includes(act.key) || n.cur === act.key) return s;
      n.cur = act.key;
      return n;
    case 'place':
      if (act.mode === 'bar' || act.mode === 'side') { if (n.mode === 'full') n.back = n.back || n.last; n.mode = act.mode; return n; }
      if (act.mode === 'full') { if (!n.panes.length) return s; if (n.mode !== 'full') n.back = LIVE_PLACES.includes(n.mode) ? n.mode : liveLayerOpenAt(n, phone); n.mode = 'full'; return n; }
      if (!LIVE_PLACES.includes(act.mode)) return s;
      if (!n.panes.length) return s;
      n.mode = phone ? 'bottom' : act.mode;
      if (!phone) n.last = act.mode;
      n.back = n.mode;
      return n;
    case 'reopen':  // Open in the bar, or the edge tab: where it was last
      if (!n.panes.length) return s;
      n.mode = liveLayerOpenAt(n, phone);
      return n;
    case 'leave-full':
      if (n.mode !== 'full') return s;
      n.mode = phone ? 'bottom' : (LIVE_PLACES.includes(n.back) ? n.back : n.last);
      return n;
    case 'min':
      if (n.mode === 'full') n.back = n.back || n.last;
      n.mode = 'bar';
      return n;
    case 'close': {  // the others take its room and the selection moves to its neighbour; the last pane closes: the bar stays
      const at = n.panes.indexOf(act.key);
      if (at < 0) return s;
      n.panes.splice(at, 1);
      if (!n.panes.includes(n.cur)) n.cur = n.panes[Math.min(at, n.panes.length - 1)] || '';
      if (!n.panes.length) n.mode = n.mode === 'side' ? 'side' : 'bar';
      return n;
    }
    case 'menu':
      n.menu = s.menu === act.menu ? '' : act.menu;
      return n;
    case 'size': {
      const k = act.dim === 'width' ? 'width' : 'height', [lo, share] = LIVE_SIZE[k], hi = Math.max(lo, Math.round((act.room || 0) * share));
      n[k] = Math.round(Math.min(hi, Math.max(lo, act.px)));
      n.menu = s.menu;
      return n;
    }
    case 'escape':  // one step back
      if (s.menu) return n;
      if (n.mode === 'full') return liveLayerStep(n, {type:'leave-full'}, phone);
      if ((n.mode === 'bottom' || n.mode === 'right') && act.inside) { n.mode = 'bar'; return n; }
      return s;
    default:
      return s;
  }
}

// --- the page ---
let liveLayer = null;
let liveLayerPainted = '';
let liveLayerWas = '';
let liveLayerWasPanes = [];  // the panes painted last: a new one slides in
function liveLayerStore() { try { return window.localStorage; } catch { return null; } }
function liveLayerPhone() { return !!window.matchMedia?.('(max-width: 720px)').matches; }
function liveLayerModel() {
  if (!liveLayer) liveLayer = liveLayerRead(liveLayerStore());
  return liveLayer;
}
function liveLayerPage() {
  return addons().find(a => a.page?.live_session === true) || null;
}
function liveLayerName() {
  return addonLabel(liveLayerPage());
}
// A session the layer can show: a ticket of this workspace, named by its key (ORCH-12), never its raw id (sessions without a ticket come with their own task).
function liveLayerSession(key) {
  const t = array(state?.tickets).find(x => x.id === key || x.key === key);
  if (!t) return null;
  const run = state.runs?.[t.id], helper = run?.running && window.DashHelpers?.helperState ? window.DashHelpers.helperState(run, t) : null;
  const pill = window.UI?.ticketState && window.UI?.ticketPill ? window.UI.ticketPill(window.UI.ticketState(t, helper)) : null;
  const live = window.LiveSessions?.get(t.id) || null;
  return {pill, key:window.DashHelpers?.ticketKey?.(t) || '', id:t.id, title:clean(t.title) || 'Untitled', live,
    running:live ? ['working', 'needs-you', 'idle'].includes(live.status) : !!state.runs?.[t.id]?.running};
}
// The live sessions in the bar's order (needs you, pinned, working, idle; pages/livebar.js), else the ticket order.
function liveLayerLive() {
  const list = array(window.LiveSessions?.list).filter(x => ['working', 'needs-you', 'idle'].includes(x.status));
  if (typeof liveBarModel !== 'function') return list.map(x => x.id);
  return liveBarModel(list, liveLayerPins()).map(o => o.id);
}
// What Open shows when nothing was open yet: the first working helper.
function liveLayerFirst() {
  return liveLayerLive()[0] || '';
}
// What Add beside opens: the first live session not shown yet.
function liveLayerNext(panes) {
  return liveLayerLive().find(k => !panes.includes(k)) || '';
}
// Pinned sessions: kept in this browser under the bar's key until orch stores them (the wall task); the bar reads them.
const LIVE_PINS_KEY = 'orch.live.pins';
function liveLayerPins() {
  try { const p = JSON.parse(liveLayerStore()?.getItem(LIVE_PINS_KEY) || '[]'); return Array.isArray(p) ? p.filter(k => typeof k === 'string') : []; } catch { return []; }
}
function liveLayerPin(key) {
  const pins = liveLayerPins(), on = !pins.includes(key);
  try { liveLayerStore()?.setItem(LIVE_PINS_KEY, JSON.stringify(on ? [...pins, key] : pins.filter(k => k !== key))); } catch { /* private window */ }
  window.paintLiveBar?.();
  liveLayer = liveLayerSort(liveLayerModel(), liveLayerLive());  // a pinned session moves first, in the bar and here
  liveLayerWrite(liveLayerStore(), liveLayer);
  liveLayerPaint();
  window.dispatchEvent(new CustomEvent('orch:live-pins', {detail:{key, pinned:on}}));
  return on;
}
function liveDockHost() {
  // Inside the mount that survives a page change (#keep of the soft page changes: render() never touches it and a
  // page change closes only dialogs outside it). Where that is missing, right after main, where #keep sits.
  let host = document.getElementById('live-dock');
  if (!host) {
    host = document.createElement('div');
    host.id = 'live-dock';
  }
  const keep = document.getElementById('keep');
  if (keep && host.parentNode !== keep) {
    if (typeof window.orchKeep?.mount === 'function') window.orchKeep.mount(host); else keep.append(host);
  } else if (!keep && !host.isConnected) document.getElementById('content')?.after(host);
  host.className = 'live-dock';
  return host;
}
function liveLayerDo(act, after) {
  const before = liveLayerModel(), stepped = liveLayerStep(before, act, liveLayerPhone());
  if (stepped === before) return;
  const next = liveLayerSort(stepped, liveLayerLive());
  liveLayer = next;
  liveLayerWrite(liveLayerStore(), next);
  liveLayerPaint();
  if (after) document.querySelector('#live-dock ' + after)?.focus({preventScroll:true});
  window.dispatchEvent(new CustomEvent('orch:live-layer', {detail:{mode:liveLayerWhere(next, liveLayerPhone()), panes:[...next.panes]}}));
}
const liveIc = name => { const s = h('span', {className:'ic-wrap', 'aria-hidden':'true'}); s.innerHTML = icon(name, 18); return s; };
function liveBtn(cls, act, label, glyph, extra = {}, word = '') {
  return h('button', {type:'button', className:cls, 'data-live':act, 'aria-label':word ? null : label, title:label, ...extra}, glyph ? liveIc(glyph) : null, word ? h('span', {className:'live-word'}, word) : null);
}
const liveOpt = (mode, glyph, words, on) => h('button', {type:'button', className:'live-opt', 'data-live':'place', 'data-mode':mode, 'aria-pressed':String(on)}, liveIc(glyph), h('span', {}, words));
function livePlaceMenu(where, inPane) {
  const phone = liveLayerPhone(), placeWords = 'Where ' + liveLayerName() + ' sits', opt = liveOpt;
  return h('div', {className:'live-pop', role:'group', 'aria-label':placeWords, 'data-key':'live-place-menu'},
    h('p', {className:'live-pop-h'}, placeWords),
    opt('bottom', 'dock-bottom', 'At the bottom', where === 'bottom'),
    phone ? null : opt('right', 'dock-right', 'On the right', where === 'right'),
    opt('full', 'full-screen', 'Full screen', where === 'full'),
    inPane ? null : opt('bar', 'chevron-down', 'Bar only', where === 'bar'),
    opt('side', 'dock-side', 'Closed to the side', where === 'side'));
}
// The More menu of a narrow pane: pin and the places.
function liveMoreMenu(key, label, where, pinned) {
  const sess = liveLayerSession(key), phone = liveLayerPhone(), item = (act, glyph, words, extra = {}) => h('button', {type:'button', className:'live-opt', 'data-live':act, 'data-session':key, ...extra}, liveIc(glyph), h('span', {}, words));
  return h('div', {className:'live-pop', role:'group', 'aria-label':'More for ' + label, 'data-key':'live-more-menu'},
    h('p', {className:'live-pop-h'}, 'More for ' + label),
    item('pin', 'pinned', pinned ? 'Unpin' : 'Pin', {'aria-pressed':String(pinned), 'data-key':'live-pin'}),
    typeof liveHistMenuItem === 'function' ? liveHistMenuItem(key) : null,
    h('p', {className:'live-pop-h'}, 'Where ' + liveLayerName() + ' sits'),
    liveOpt('bottom', 'dock-bottom', 'At the bottom', where === 'bottom'),
    phone ? null : liveOpt('right', 'dock-right', 'On the right', where === 'right'),
    sess ? h('a', {className:'live-opt', href:'#ticket/' + encodeURIComponent(sess.id), 'data-key':'live-more-ticket', 'data-live-ticket':''}, liveIc('ticket'), h('span', {}, 'Open ticket')) : null);
}
function livePane(key, where, s, o) {
  const sess = liveLayerSession(key), name = liveLayerName(), n = o.n;
  const title = sess ? sess.title : 'This session has ended', label = sess?.key || title, on = key === s.cur;
  const pinned = o.pins.includes(key), placeMenu = 'pane:' + key, moreMenu = 'more:' + key;
  const full = where === 'full'
    ? liveBtn('btn icon sm ghost', 'leave-full', 'Leave full screen', 'full-exit', {'data-key':'live-full'})
    : liveBtn('btn icon sm ghost', 'full', 'Full screen', 'full-screen', {'data-key':'live-full'});
  const besideWhy = o.total >= LIVE_MAX ? 'Three sessions is the most' : o.next ? 'Add a session beside this one' : 'No other session is live';
  return h('section', {className:'live-pane', 'data-key':'live-pane', 'data-session':key, 'data-on':on && n > 1 ? '' : null,
    'data-new':o.fresh ? '' : null, 'aria-label':(sess?.key ? sess.key + ', ' : '') + title},
    h('header', {className:'live-ph'},
      o.narrow ? null : sess?.pill || null,
      sess?.key ? h('span', {className:'key'}, sess.key) : null,
      n > 1 && !on
        ? h('button', {type:'button', className:'live-pt', 'data-live':'select', 'data-session':key, title, 'aria-label':'Select the pane of ' + label}, title)
        : h('span', {className:'live-pt', title}, title),
      h('span', {className:'live-ctl'},
        o.narrow || typeof liveHistButton !== 'function' ? null : liveHistButton(sess, label),
        o.narrow ? null : liveBtn('btn icon sm ghost', 'pin', (pinned ? 'Unpin ' : 'Pin ') + label, 'pinned', {'data-session':key, 'aria-pressed':String(pinned), 'data-key':'live-pin'}),
        o.phone ? null : liveBtn('btn icon sm ghost', 'beside', besideWhy, 'plus', {'data-key':'live-beside', disabled:o.total >= LIVE_MAX || !o.next}),
        o.narrow || where === 'full' ? null : liveBtn('btn icon sm ghost', 'menu', 'Where ' + name + ' sits', where === 'right' ? 'dock-right' : 'dock-bottom', {'data-menu':placeMenu, 'aria-expanded':String(s.menu === placeMenu), 'data-key':'live-pane-place'}),
        full,
        liveBtn('btn icon sm ghost', 'min', 'Minimise to the bar', 'chevron-down', {'data-key':'live-min'}),
        liveBtn('btn icon sm ghost', 'close', o.total > 1 ? 'Close this pane' : 'Close (the bar stays)', 'x', {'data-session':key, 'data-key':'live-close'}),
        o.narrow ? liveBtn('btn icon sm ghost', 'menu', 'More for ' + label, 'more', {'data-menu':moreMenu, 'aria-expanded':String(s.menu === moreMenu), 'data-key':'live-pane-more'}) : null,
        s.menu === placeMenu ? livePlaceMenu(where, true) : null,
        s.menu === moreMenu ? liveMoreMenu(key, label, where, pinned) : null)),
    sess?.running && typeof window.liveModelRow === 'function' ? window.liveModelRow(sess, s) : null,
    typeof liveHistShown === 'function' && liveHistShown(sess) ? h('div', {className:'live-pb live-pb-hist'}, liveHistBody(sess))
      : sess && !sess.running && typeof window.liveStartBody === 'function' ? h('div', {className:'live-pb live-pb-start'}, window.liveStartBody(sess))
      : sess ? h('div', {className:'live-pb', 'data-live-body':key},
      h('p', {className:'live-now', 'data-live-now':''}),
      h('pre', {className:'live-lines', 'data-live-lines':'', 'aria-label':'Last lines of ' + label, tabindex:'0', hidden:true}),
      h('p', {className:'meta live-meta', 'data-live-meta':''}),
      h('a', {className:'btn ghost sm', href:'#ticket/' + encodeURIComponent(sess.id), 'data-key':'live-open-ticket', 'data-live-ticket':'', 'aria-label':'Open ticket ' + label}, 'Open ticket'))
      : h('div', {className:'live-pb'}, h('p', {}, 'This session is no longer in the list.')));
}
// The live part of a pane, written in place on every answer of the sessions API: no repaint, so the keyboard place,
// an open menu and the scroll of the lines stay.
function liveLayerFill() {
  for (const body of document.querySelectorAll('#live-dock [data-live-body]')) {
    const live = window.LiveSessions?.get(body.dataset.liveBody) || null;
    const now = body.querySelector('[data-live-now]'), pre = body.querySelector('[data-live-lines]'), meta = body.querySelector('[data-live-meta]');
    const text = !window.LiveSessions?.ready ? 'Loading…' : live ? liveNow(live) : 'No helper is working on this ticket right now.';
    if (now.textContent !== text) now.textContent = text;
    const lines = live && Array.isArray(live.lines) ? live.lines.join('\n') : '';
    if (pre.textContent !== lines) {
      const end = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 8;  // following the end: keep following it
      pre.textContent = lines;
      if (end) pre.scrollTop = pre.scrollHeight;
    }
    pre.hidden = !lines;
    const m = live ? liveMeta(live).join(' · ') : '';
    if (meta.textContent !== m) meta.textContent = m;
    meta.hidden = !m;
  }
}
// The layer's part of the bar: Open (when only the bar shows), Place with its menu, and in full screen the way out.
function liveBarEnd(where, s) {
  const name = liveLayerName(), open = where === 'bottom' || where === 'right' || where === 'full';
  return h('span', {className:'live-end', 'data-key':'live-end'},
    where === 'full' ? h('span', {className:'meta live-word'}, 'Esc to leave') : null,
    open ? null : liveBtn('btn sm ghost', 'reopen', 'Open ' + name + ' where it was last', 'up', {'data-key':'live-open'}, 'Open'),
    where === 'full' ? liveBtn('btn icon sm ghost', 'leave-full', 'Leave full screen', 'full-exit', {'data-key':'live-bar-leave'})
      : liveBtn('btn sm ghost', 'menu', 'Where ' + name + ' sits', where === 'right' ? 'dock-right' : 'dock-bottom', {'data-menu':'bar', 'aria-expanded':String(s.menu === 'bar'), 'data-key':'live-place'}, open ? (where === 'right' ? 'Right' : 'Bottom') : ''),
    s.menu === 'bar' ? livePlaceMenu(where, false) : null);
}
// The bar of the bar task (pages/livebar.js, window.LiveBar) when it is there; else a minimal bar of the layer's own.
function liveBarShared() {
  return window.LiveBar && typeof window.LiveBar.mount === 'function' && typeof window.LiveBar.end === 'function' ? window.LiveBar : null;
}
function liveBar(where, s) {
  const name = liveLayerName();
  return h('div', {className:'live-bar', role:'group', 'aria-label':name + ' bar', 'data-key':'live-bar'},
    h('a', {className:'live-home', href:'#addon/' + encodeURIComponent(liveLayerPage()?.name || ''), title:name + ' start page'}, name),
    h('div', {className:'live-bar-sessions', 'data-key':'live-bar-sessions'}),
    liveBarEnd(where, s));
}
function liveLayerTree(s, where) {
  if (where === 'side') {
    const name = liveLayerName();
    return h('button', {type:'button', className:'live-edge', 'data-live':s.panes.length ? 'reopen' : 'place', 'data-mode':'bar', 'data-key':'live-edge', 'aria-label':'Open ' + name + ' again'}, liveIc('dock-side'), h('span', {}, name));
  }
  const bar = liveBarShared() ? null : liveBar(where, s);
  if (where === 'bar' || !s.panes.length) return bar;
  const dim = where === 'right' ? 'width' : 'height', px = s[dim], v = liveLayerView(s, where);
  const panel = h('div', {className:'live-panel', 'data-mode':where, 'data-n':String(v.shown.length), 'data-key':'live-panel'},
    where === 'full' ? null : h('div', {className:'live-grip', role:'separator', tabindex:'0', 'data-live-grip':dim,
      'aria-orientation':dim === 'width' ? 'vertical' : 'horizontal', 'aria-label':dim === 'width' ? 'Width of the panel' : 'Height of the panel',
      'aria-valuenow':px ? String(px) : null, title:'Drag or use the arrow keys to resize'}),
    v.shown.map(k => livePane(k, where, s, {...v, fresh:!!liveLayerWasPanes.length && !liveLayerWasPanes.includes(k)})));
  return fragment(panel, bar);
}
// What the panel shows: on a phone only the selected session; whether the panes are narrow; what Add beside opens.
function liveLayerView(s, where) {
  const phone = liveLayerPhone(), shown = phone ? [s.cur || s.panes[0]] : s.panes;
  const host = document.getElementById('live-dock');
  const room = where === 'right' ? (s.width || Math.min(window.innerWidth * 0.42, 760)) : (host?.offsetWidth || window.innerWidth);
  return {shown, n:shown.length, total:s.panes.length, phone, narrow:liveLayerNarrow(where, shown.length, room, phone), pins:liveLayerPins(), next:liveLayerNext(s.panes)};
}
// Paints the dock when something it shows changed; a state poll that changes nothing leaves it alone (no flicker, the
// keyboard place and any open menu stay).
function liveLayerPaint() {
  const host = liveDockHost(), s = liveLayerModel(), where = liveLayerWhere(s, liveLayerPhone());
  const shown = s.panes.map(liveLayerSession).map(x => x && [x.key, x.title, x.running, x.pill?.textContent || '']);
  const v = s.panes.length && where !== 'bar' && where !== 'side' ? liveLayerView(s, where) : null;
  const key = JSON.stringify([where, s.menu, s.panes, s.cur, shown, v && [v.narrow, v.pins.filter(k => s.panes.includes(k)), !!v.next], liveLayerName(), liveLayerPage()?.name, typeof liveHistKey === 'function' ? liveHistKey() : null, typeof window.liveStartKey === 'function' ? window.liveStartKey() : null, typeof window.liveModelKey === 'function' ? window.liveModelKey(s.panes) : null]);
  host.dataset.mode = where;
  host.style.setProperty('--live-h', s.height ? s.height + 'px' : '');
  host.style.setProperty('--live-w', s.width ? s.width + 'px' : '');
  if (!s.height) host.style.removeProperty('--live-h');
  if (!s.width) host.style.removeProperty('--live-w');
  if (key !== liveLayerPainted) {
    // the panel animates only when it appears or moves, not on every repaint
    if (where === liveLayerWas) host.dataset.still = ''; else delete host.dataset.still;
    const shared = liveBarShared(), keepBar = shared ? document.getElementById('live-bar') : null;
    host.replaceChildren(...[liveLayerTree(s, where)].filter(Boolean), ...(keepBar ? [keepBar] : []));
    if (shared) {
      // the shared bar goes after the panel in the dock (on top in full screen) and carries Open and Place at its end
      if (!keepBar || keepBar.parentNode !== host) shared.mount(host, {docked:true});
      shared.end(() => [liveBarEnd(liveLayerWhere(liveLayerModel(), liveLayerPhone()), liveLayerModel())]);
    }
    liveLayerPainted = key;
    liveLayerWas = where;
    liveLayerWasPanes = where === 'bar' || where === 'side' ? [] : [...s.panes];
  }
  liveLayerFill();
  document.body.dataset.liveLayer = where;
  liveLayerInert(where === 'full');
  liveLayerPad();
}
// Full screen covers the page: the page behind leaves the Tab order and the screen reader (inert), so the keyboard
// cannot wander into what is not shown (ORCH-340). Dialogs and live regions stay usable; only what this set is undone.
function liveLayerInert(on) {
  const dock = document.getElementById('live-dock');
  for (const el of document.querySelectorAll('body > *, .shell-body > *')) {
    if (on) {
      if (el.inert || (dock && el.contains(dock)) || el.matches('script, dialog, [aria-live], [role=status], [role=alert]')) continue;
      el.inert = true;
      el.dataset.liveInert = '';
    } else if (el.hasAttribute('data-live-inert')) {
      el.inert = false;
      delete el.dataset.liveInert;
    }
  }
}
// Keeps the page usable behind the layer: room at the bottom for the bar (and the bottom panel), at the right for the
// right panel; the phone's bottom tab bar stays visible under it.
function liveLayerPad() {
  const host = document.getElementById('live-dock');
  if (!host) return;
  const tabbar = document.getElementById('tabbar'), tb = tabbar && getComputedStyle(tabbar).display !== 'none' ? tabbar.offsetHeight : 0;
  host.style.setProperty('--live-bottom', tb + 'px');
  const where = host.dataset.mode, panel = host.querySelector('.live-panel');
  const pad = where === 'side' || where === 'full' ? 0 : host.offsetHeight;
  document.body.style.setProperty('--live-pad', pad + 'px');
  document.body.style.setProperty('--live-padr', where === 'right' && panel ? panel.offsetWidth + 'px' : '0px');
}
function liveLayerOff() {
  liveLayerInert(false);
  document.getElementById('live-dock')?.remove();
  delete document.body.dataset.liveLayer;
  document.body.style.removeProperty('--live-pad');
  document.body.style.removeProperty('--live-padr');
  liveLayerPainted = '';
  liveLayerWas = '';
  liveLayerWasPanes = [];
}
// Called after every page render (app.js): on with the Preview switch, gone without it.
function liveDockSync() {
  window.LiveSessions?.sync();
  if (!livePreviewOn() || !liveLayerPage()) { liveLayerOff(); return; }
  liveLayerPaint();
}
// A new answer of the sessions API: the panes' live part in place; the dock itself only when what it shows changed.
window.addEventListener('orch:live-sessions', () => { if (document.getElementById('live-dock')) liveLayerPaint(); });
// For the bar, the wall and the ticket page: open a session in the layer.
window.LiveLayer = {
  open(key, into = false) {  // the bar marks chips by ticket id; a ticket's session button moves the keyboard into the pane
    const id = liveLayerSession(key)?.id || key;
    liveLayerDo({type:'open', key:id}, into ? liveSel(id, 'live-open-ticket') : undefined);
  },
  place(mode) { liveLayerDo({type:'place', mode}); },
  beside(key) { liveLayerDo({type:liveLayerPhone() ? 'open' : 'beside', key:liveLayerSession(key)?.id || key}); },  // a wall tile's Add beside
  pin(key) { return liveLayerPin(liveLayerSession(key)?.id || key); },
  get mode() { return liveLayerWhere(liveLayerModel(), liveLayerPhone()); },
  get panes() { return [...liveLayerModel().panes]; },
  get pins() { return liveLayerPins(); },
};

// The session button of a ticket (draft D feature 3): on the ticket page (long: "Watch in" + the page's name) and on every ticket row.
// It opens the ticket's session in the layer; with no helper running the pane offers the Start choice (pages/live-start.js).
// Only with the Preview switch on; otherwise null and the page keeps what it had (Watch live, Answer).
function liveFocusButton(t, long = false) {
  if (!t?.id || snapshot || !livePreviewOn() || !liveLayerPage() || !window.DashHelpers?.helperState) return null;
  const verb = liveFocusVerb(t, state.runs?.[t.id], window.DashHelpers.helperState);
  if (!verb) return null;
  const name = liveLayerName(), key = window.DashHelpers.ticketKey?.(t) || clean(t.title) || 'this ticket';
  const b = h('button', {type:'button', className:'btn outline sm', 'data-key':'live-session-btn', 'data-ticket':t.id,
    'data-verb':verb, 'aria-label':verb + ' ' + key + ' in ' + name}, long ? verb + ' in ' + name : verb);
  b.addEventListener('click', e => { e.stopPropagation(); window.LiveLayer.open(t.id, true); });
  return b;
}
document.addEventListener('click', e => {
  // Open ticket from full screen: the ticket page would stay hidden behind it, so full screen steps back first
  if (e.target.closest?.('#live-dock [data-live-ticket]') && liveLayerModel().mode === 'full') liveLayerDo({type:'leave-full'});
  const b = e.target.closest?.('#live-dock [data-live]');
  if (!b) {
    if (liveLayer?.menu && !e.target.closest?.('#live-dock .live-pop')) liveLayerDo({type:'menu', menu:liveLayer.menu});
    return;
  }
  const act = b.dataset.live;
  if (act === 'menu') liveLayerDo({type:'menu', menu:b.dataset.menu}, `[data-menu="${b.dataset.menu}"]`);
  else if (act === 'place') liveLayerDo({type:'place', mode:b.dataset.mode}, b.dataset.mode === 'side' ? '[data-key="live-edge"]' : '[data-key="live-place"]');
  else if (act === 'reopen') {
    const s = liveLayerModel();
    if (s.panes.length) liveLayerDo({type:'reopen'}, '[data-key="live-pane-place"]');
    else { const first = liveLayerFirst(); if (first) liveLayerDo({type:'open', key:first}, '[data-key="live-pane-place"]'); else liveLayerDo({type:'place', mode:'bar'}, '[data-key="live-open"]'); }
  }
  else if (act === 'full') liveLayerDo({type:'place', mode:'full'}, '[data-key="live-full"]');
  else if (act === 'leave-full') liveLayerDo({type:'leave-full'}, '[data-key="live-full"]');
  else if (act === 'min') liveLayerDo({type:'min'}, '[data-key="live-open"]');
  else if (act === 'close') {
    const s = liveLayerModel(), at = s.panes.indexOf(b.dataset.session);
    liveLayerDo({type:'close', key:b.dataset.session}, s.panes.length > 1 ? liveSel(s.panes[at + 1] || s.panes[at - 1], 'live-close') : '[data-key="live-open"]');
  }
  else if (act === 'beside') {
    const next = liveLayerNext(liveLayerModel().panes);
    if (next) liveLayerDo({type:'beside', key:next}, liveSel(next, 'live-close'));
  }
  else if (act === 'select') liveLayerDo({type:'select', key:b.dataset.session}, liveSel(b.dataset.session, 'live-close'));
  else if (act === 'pin') {
    const key = b.dataset.session, menu = liveLayerModel().menu;
    liveLayerPin(key);
    if (menu) liveLayerDo({type:'menu', menu});  // the More menu closes after its choice
    document.querySelector('#live-dock ' + liveSel(key, 'live-pin') + ', #live-dock ' + liveSel(key, 'live-pane-more'))?.focus({preventScroll:true});
  }
});
// A control of one pane, for the keyboard place after a repaint.
function liveSel(key, what) {
  return `.live-pane[data-session="${String(key || '').replace(/["\\]/g, '')}"] [data-key="${what}"]`;
}
document.addEventListener('keydown', e => {
  if (!document.getElementById('live-dock')) return;
  const grip = e.target.closest?.('[data-live-grip]');
  if (grip && /^Arrow(Up|Down|Left|Right)$/.test(e.key)) {
    const dim = grip.dataset.liveGrip, panel = grip.closest('.live-panel'), now = dim === 'width' ? panel.offsetWidth : panel.offsetHeight;
    const grow = dim === 'width' ? e.key === 'ArrowLeft' : e.key === 'ArrowUp', shrink = dim === 'width' ? e.key === 'ArrowRight' : e.key === 'ArrowDown';
    if (!grow && !shrink) return;
    e.preventDefault();
    liveLayerDo({type:'size', dim, px:now + (grow ? 24 : -24), room:dim === 'width' ? window.innerWidth : window.innerHeight}, '[data-live-grip]');
    return;
  }
  if (e.key !== 'Escape' || e.defaultPrevented || document.querySelector('dialog[open]')) return;
  const inside = !!e.target.closest?.('#live-dock'), s = liveLayerModel();
  if (!inside && s.mode !== 'full' && !s.menu) return;
  const was = s.menu;
  liveLayerDo({type:'escape', inside}, was ? `[data-menu="${was}"]` : s.mode === 'full' ? '[data-key="live-full"]' : '[data-key="live-open"]');
});
// Drag to resize: the top edge of the bottom panel, the left edge of the right one. Kept when the drag ends.
document.addEventListener('pointerdown', e => {
  const grip = e.target.closest?.('#live-dock [data-live-grip]');
  if (!grip || e.button !== 0) return;
  e.preventDefault();
  const dim = grip.dataset.liveGrip, panel = grip.closest('.live-panel'), host = document.getElementById('live-dock');
  const start = dim === 'width' ? e.clientX : e.clientY, from = dim === 'width' ? panel.offsetWidth : panel.offsetHeight;
  const room = () => dim === 'width' ? window.innerWidth : window.innerHeight;
  let px = from;
  grip.dataset.drag = '';
  grip.setPointerCapture?.(e.pointerId);
  const move = ev => {
    const at = dim === 'width' ? ev.clientX : ev.clientY;
    px = liveLayerStep(liveLayerModel(), {type:'size', dim, px:from + (start - at), room:room()})[dim];
    host.style.setProperty(dim === 'width' ? '--live-w' : '--live-h', px + 'px');
    liveLayerPad();
  };
  let done = false;
  const up = () => {
    if (done) return;  // pointerup and lostpointercapture both come: keep the size once
    done = true;
    grip.removeEventListener('pointermove', move);
    delete grip.dataset.drag;
    liveLayerDo({type:'size', dim, px, room:room()}, '[data-live-grip]');
  };
  grip.addEventListener('pointermove', move);
  for (const end of ['pointerup', 'pointercancel', 'lostpointercapture']) grip.addEventListener(end, up, {once:true});
});
{
  let frame = 0, phone = null;
  window.addEventListener('resize', () => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      if (!document.getElementById('live-dock')) return;
      const now = liveLayerPhone();
      if (now !== phone) { phone = now; liveLayerPainted = ''; liveLayerPaint(); } else liveLayerPad();  // the keyboard place and the open menu stay
    });
  });
}

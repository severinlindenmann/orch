'use strict';
// The layer of the new live page (draft D, ORCH-338), behind the Preview switch (pages/live.js). One dock under every
// page, outside main, so it stays open while the page changes: a panel at the bottom, on the right or full screen,
// above a bar; minimised it is only the bar, closed to the side it is a slim edge tab. Place and size are kept per
// browser. Esc goes one step back: an open menu, then full screen, then the panel to the bar. One session for now;
// panes is a list so the split can add more. The pane is a placeholder until the chat and terminal tasks fill it.
// Look: the kit's .live-* rules (widgets.css). The bar's session chips go into [data-key="live-bar-sessions"].
const LIVE_LAYER_KEY = 'orch.live.layer';
const LIVE_PLACES = ['bottom', 'right'];
const LIVE_SIZE = {height:[200, 0.85], width:[320, 0.7]};  // smallest px, largest share of the window

// --- the model: plain data, no page (tested in tests/live_layer.test.js) ---
function liveLayerFresh() {
  return {mode:'bar', last:'bottom', back:'bottom', height:null, width:null, panes:[], menu:''};
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
  if (Array.isArray(saved.panes)) s.panes = saved.panes.filter(k => typeof k === 'string' && /^[A-Za-z0-9_.-]{1,64}$/.test(k)).slice(0, 1);
  if (!s.panes.length && s.mode !== 'bar' && s.mode !== 'side') s.mode = 'bar';
  return s;
}
function liveLayerWrite(store, s) {
  try { store?.setItem(LIVE_LAYER_KEY, JSON.stringify({mode:s.mode, last:s.last, back:s.back, height:s.height, width:s.width, panes:s.panes})); } catch { /* private window: nothing kept */ }
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
  switch (act.type) {
    case 'open':  // a session from the bar, a tile or a ticket; it replaces the one shown (split adds beside later)
      if (act.key) n.panes = [act.key];
      if (!n.panes.length) return s;
      if (n.mode === 'bar' || n.mode === 'side') n.mode = liveLayerOpenAt(n, phone);
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
    case 'close':  // the last pane closes: the bar stays
      n.panes = n.panes.filter(k => k !== act.key);
      if (!n.panes.length) n.mode = n.mode === 'side' ? 'side' : 'bar';
      return n;
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
  return {key:window.DashHelpers?.ticketKey?.(t) || '', id:t.id, title:clean(t.title) || 'Untitled', running:!!state.runs?.[t.id]?.running};
}
// What Open shows when nothing was open yet: the first working helper.
function liveLayerFirst() {
  const t = array(state?.tickets).find(x => state.runs?.[x.id]?.running);
  return t ? t.id : '';
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
  const before = liveLayerModel(), next = liveLayerStep(before, act, liveLayerPhone());
  if (next === before) return;
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
function livePlaceMenu(where, inPane) {
  const phone = liveLayerPhone(), placeWords = 'Where ' + liveLayerName() + ' sits', opt = (mode, glyph, words, on) => h('button', {type:'button', className:'live-opt', 'data-live':'place', 'data-mode':mode, 'aria-pressed':String(on)}, liveIc(glyph), h('span', {}, words));
  return h('div', {className:'live-pop', role:'group', 'aria-label':placeWords, 'data-key':'live-place-menu'},
    h('p', {className:'live-pop-h'}, placeWords),
    opt('bottom', 'dock-bottom', 'At the bottom', where === 'bottom'),
    phone ? null : opt('right', 'dock-right', 'On the right', where === 'right'),
    opt('full', 'full-screen', 'Full screen', where === 'full'),
    inPane ? null : opt('bar', 'chevron-down', 'Bar only', where === 'bar'),
    opt('side', 'dock-side', 'Closed to the side', where === 'side'));
}
function livePane(key, where, s) {
  const sess = liveLayerSession(key), name = liveLayerName();
  const title = sess ? sess.title : 'This session has ended';
  return h('section', {className:'live-pane', 'data-key':'live-pane', 'data-session':key, 'aria-label':(sess?.key ? sess.key + ', ' : '') + title},
    h('header', {className:'live-ph'},
      sess?.key ? h('span', {className:'key'}, sess.key) : null,
      h('span', {className:'live-pt', title}, title),
      h('span', {className:'live-ctl'},
        where === 'full' ? null : liveBtn('btn icon sm ghost', 'menu', 'Where ' + name + ' sits', where === 'right' ? 'dock-right' : 'dock-bottom', {'data-menu':'pane', 'aria-expanded':String(s.menu === 'pane'), 'data-key':'live-pane-place'}),
        liveBtn('btn icon sm ghost', where === 'full' ? 'leave-full' : 'full', where === 'full' ? 'Leave full screen' : 'Full screen', where === 'full' ? 'full-exit' : 'full-screen', {'data-key':'live-full'}),
        liveBtn('btn icon sm ghost', 'min', 'Minimise to the bar', 'chevron-down', {'data-key':'live-min'}),
        liveBtn('btn icon sm ghost', 'close', 'Close (the bar stays)', 'x', {'data-session':key, 'data-key':'live-close'}),
        s.menu === 'pane' ? livePlaceMenu(where, true) : null)),
    h('div', {className:'live-pb'},
      h('p', {}, sess ? (sess.running ? 'The helper’s session shows here.' : 'No helper is working on this ticket right now.') : 'This session is no longer in the list.'),
      sess ? h('a', {className:'btn ghost sm', href:'#ticket/' + encodeURIComponent(sess.id), 'data-key':'live-open-ticket'}, 'Open ticket') : null,
      h('p', {className:'meta'}, 'The chat and the terminal of ' + name + ' come here next.')));
}
function liveBar(where, s) {
  const name = liveLayerName(), open = where === 'bottom' || where === 'right' || where === 'full';
  return h('div', {className:'live-bar', role:'group', 'aria-label':name + ' bar', 'data-key':'live-bar'},
    h('a', {className:'live-home', href:'#addon/' + encodeURIComponent(liveLayerPage()?.name || ''), title:name + ' start page'}, name),
    h('div', {className:'live-bar-sessions', 'data-key':'live-bar-sessions'}),
    where === 'full' ? h('span', {className:'meta live-word'}, 'Esc to leave') : null,
    open ? null : liveBtn('btn sm ghost', 'reopen', 'Open ' + name + ' where it was last', 'up', {'data-key':'live-open'}, 'Open'),
    where === 'full' ? liveBtn('btn icon sm ghost', 'leave-full', 'Leave full screen', 'full-exit', {'data-key':'live-bar-leave'})
      : liveBtn('btn sm ghost', 'menu', 'Where ' + name + ' sits', where === 'right' ? 'dock-right' : 'dock-bottom', {'data-menu':'bar', 'aria-expanded':String(s.menu === 'bar'), 'data-key':'live-place'}, open ? (where === 'right' ? 'Right' : 'Bottom') : ''),
    s.menu === 'bar' ? livePlaceMenu(where, false) : null);
}
function liveLayerTree(s, where) {
  if (where === 'side') {
    const name = liveLayerName();
    return h('button', {type:'button', className:'live-edge', 'data-live':s.panes.length ? 'reopen' : 'place', 'data-mode':'bar', 'data-key':'live-edge', 'aria-label':'Open ' + name + ' again'}, liveIc('dock-side'), h('span', {}, name));
  }
  const bar = liveBar(where, s);
  if (where === 'bar' || !s.panes.length) return bar;
  const dim = where === 'right' ? 'width' : 'height', px = s[dim];
  const panel = h('div', {className:'live-panel', 'data-mode':where, 'data-n':String(s.panes.length), 'data-key':'live-panel'},
    where === 'full' ? null : h('div', {className:'live-grip', role:'separator', tabindex:'0', 'data-live-grip':dim,
      'aria-orientation':dim === 'width' ? 'vertical' : 'horizontal', 'aria-label':dim === 'width' ? 'Width of the panel' : 'Height of the panel',
      'aria-valuenow':px ? String(px) : null, title:'Drag or use the arrow keys to resize'}),
    s.panes.map(k => livePane(k, where, s)));
  return fragment(panel, bar);
}
// Paints the dock when something it shows changed; a state poll that changes nothing leaves it alone (no flicker, the
// keyboard place and any open menu stay).
function liveLayerPaint() {
  const host = liveDockHost(), s = liveLayerModel(), where = liveLayerWhere(s, liveLayerPhone());
  const shown = s.panes.map(liveLayerSession).map(x => x && [x.key, x.title, x.running]);
  const key = JSON.stringify([where, s.menu, s.panes, shown, liveLayerName(), liveLayerPage()?.name]);
  host.dataset.mode = where;
  host.style.setProperty('--live-h', s.height ? s.height + 'px' : '');
  host.style.setProperty('--live-w', s.width ? s.width + 'px' : '');
  if (!s.height) host.style.removeProperty('--live-h');
  if (!s.width) host.style.removeProperty('--live-w');
  if (key !== liveLayerPainted) {
    // the panel animates only when it appears or moves, not on every repaint
    if (where === liveLayerWas) host.dataset.still = ''; else delete host.dataset.still;
    host.replaceChildren(liveLayerTree(s, where));
    liveLayerPainted = key;
    liveLayerWas = where;
  }
  document.body.dataset.liveLayer = where;
  liveLayerPad();
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
  document.getElementById('live-dock')?.remove();
  delete document.body.dataset.liveLayer;
  document.body.style.removeProperty('--live-pad');
  document.body.style.removeProperty('--live-padr');
  liveLayerPainted = '';
  liveLayerWas = '';
}
// Called after every page render (app.js): on with the Preview switch, gone without it.
function liveDockSync() {
  if (!livePreviewOn() || !liveLayerPage()) { liveLayerOff(); return; }
  liveLayerPaint();
}
// For the bar, the wall and the ticket page: open a session in the layer.
window.LiveLayer = {
  open(key) { liveLayerDo({type:'open', key}); },
  place(mode) { liveLayerDo({type:'place', mode}); },
  get mode() { return liveLayerWhere(liveLayerModel(), liveLayerPhone()); },
  get panes() { return [...liveLayerModel().panes]; },
};

document.addEventListener('click', e => {
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
  else if (act === 'close') liveLayerDo({type:'close', key:b.dataset.session}, '[data-key="live-open"]');
});
document.addEventListener('keydown', e => {
  if (!document.getElementById('live-dock')) return;
  const grip = e.target.closest?.('[data-live-grip]');
  if (grip && /^Arrow(Up|Down|Left|Right)$/.test(e.key)) {
    e.preventDefault();
    const dim = grip.dataset.liveGrip, panel = grip.closest('.live-panel'), now = dim === 'width' ? panel.offsetWidth : panel.offsetHeight;
    const grow = dim === 'width' ? e.key === 'ArrowLeft' : e.key === 'ArrowUp', shrink = dim === 'width' ? e.key === 'ArrowRight' : e.key === 'ArrowDown';
    if (!grow && !shrink) return;
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
  const up = () => {
    grip.removeEventListener('pointermove', move);
    delete grip.dataset.drag;
    liveLayerDo({type:'size', dim, px, room:room()}, '[data-live-grip]');
  };
  grip.addEventListener('pointermove', move);
  grip.addEventListener('pointerup', up, {once:true});
  grip.addEventListener('pointercancel', up, {once:true});
});
window.addEventListener('resize', () => { if (document.getElementById('live-dock')) { liveLayerPainted = ''; liveLayerPaint(); } });

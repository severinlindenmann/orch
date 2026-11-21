'use strict';
// The layer of the live page (draft D, ORCH-338; pages/live.js). One dock under every
// page, outside main, so it stays open while the page changes: a panel at the bottom, on the right or full screen,
// above a bar; minimised it is only the bar, closed to the side it is a slim edge tab. Place and size are kept per
// browser. Esc goes one step back: an open menu, then full screen, then the panel to the bar. The split (ORCH-339):
// 1, 2 or 3 sessions side by side (stacked on the right), one of them selected; each pane has pin, add beside, place,
// full screen, minimise and close, each with its word (ORCH-463). A compact pane (split, narrow or short of room) puts
// its title on a row of its own and the buttons on a second row; pin, place and full screen fold into More there. Add
// beside asks which session to show (a menu of the live sessions not shown yet). On a phone
// only the selected session shows. A pane shows the session's live data (pages/livesessions.js, ORCH-359): what it
// does now, its last lines, tool and model, open time; the chat and terminal tasks fill it further.
// Look: the kit's .live-* rules (widgets.css). The bar's session chips go into [data-key="live-bar-sessions"].
const LIVE_LAYER_KEY = 'orch.live.layer';
const LIVE_PLACES = ['bottom', 'right'];
const LIVE_SIZE = {height:[200, 0.85], width:[320, 0.7]};  // smallest px, largest share of the window
const LIVE_MAX = 3;  // sessions side by side
const LIVE_NARROW = 600;  // a pane narrower than this folds pin, place and Chat | Terminal into More (draft D; the full header needs about 600 px)
const LIVE_ROOMY = 1200;  // a single pane narrower than this is compact too: its title gets a row of its own (ORCH-463)

// --- the model: plain data, no page (tested in tests/live_layer.test.js) ---
function liveLayerFresh() {
  return {mode:'bar', last:'bottom', back:'bottom', height:null, width:null, panes:[], cur:'', menu:''};
}
// Narrow panes: on a phone, on the right with more than one, or when a share of the room is under LIVE_NARROW
// (one pane on the right at 1280 wide too: its header would push Full screen out of sight).
function liveLayerNarrow(where, n, room, phone) {
  return !!phone || (n > 1 && where === 'right') || room / Math.max(n, 1) < LIVE_NARROW;
}
// Compact panes: the title on a row of its own, the buttons with their words on a second row (ORCH-463: in the split
// the titles were cut to 'Plan…' and the state to 'Wor…'). Every split is compact, and so is a narrow or small pane.
function liveLayerCompact(where, n, room, phone) {
  return liveLayerNarrow(where, n, room, phone) || n > 1 || room < LIVE_ROOMY;
}
// Kept per workspace (issue 1351: the dashboards of two workspaces can get the same port, so the same browser store).
function liveLayerKey(ws) { return ws ? LIVE_LAYER_KEY + '.' + ws : LIVE_LAYER_KEY; }
function liveLayerRead(store, ws = '') {
  const s = liveLayerFresh();
  let saved = null;
  try { saved = JSON.parse(store?.getItem(liveLayerKey(ws)) || 'null'); } catch { saved = null; }
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
function liveLayerWrite(store, s, ws = '') {
  try { store?.setItem(liveLayerKey(ws), JSON.stringify({mode:s.mode, last:s.last, back:s.back, height:s.height, width:s.width, panes:s.panes, cur:s.cur})); } catch { /* private window: nothing kept */ }
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
    case 'swap': {  // the group switcher of a pane (ORCH-345): that pane shows another session of its group
      if (!act.key || !n.panes.includes(act.from)) return s;
      if (act.key === act.from) { if (n.cur === act.key) return s; n.cur = act.key; return n; }
      if (n.panes.includes(act.key)) n.panes.splice(n.panes.indexOf(act.from), 1);  // shown already: the two become one
      else n.panes[n.panes.indexOf(act.from)] = act.key;
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
    case 'to-ticket':  // Open ticket: a layer over the page (bottom, full screen) steps down to the bar so the ticket page is usable; docked right sits beside it
      if (n.mode !== 'full' && n.mode !== 'bottom') return s;
      return liveLayerStep(n, {type:'min'}, phone);
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

// The question a ticket's helper waits on, as the pane shows it (ORCH-675): the first unanswered one, its options when
// it is a plain question (kind unset), else only a link to the ticket where its card (plan, draft, choice) lives.
function liveAskModel(t) {
  const q = Array.isArray(t?.questions) ? t.questions.find(x => x && x.answer == null) : null;
  if (!q) return null;
  const options = Array.isArray(q.options) ? q.options.filter(o => typeof o === 'string' && o.trim()).slice(0, 6) : [];
  return {id:q.id, digest:q.digest, text:String(q.text || ''), options, plain:q.kind == null};
}
// --- the page ---
let liveLayer = null;
let liveLayerPainted = '';
let liveLayerWas = '';
let liveLayerWasPanes = [];  // the panes painted last: a new one slides in
function liveLayerStore() { try { return window.localStorage; } catch { return null; } }
function liveLayerPhone() { return !!window.matchMedia?.('(max-width: 720px)').matches; }
let liveLayerWs = null;
function liveLayerModel() {
  const ws = typeof state === 'object' && state ? String(state.workspace || '') : '';
  if (!liveLayer || (ws && liveLayerWs !== ws)) { liveLayer = liveLayerRead(liveLayerStore(), ws); liveLayerWs = ws; }  // a state without its name (an answer in between) keeps the layer
  return liveLayer;
}
function liveLayerPage() {
  return addons().find(a => a.page?.live_session === true) || null;
}
function liveLayerName() {
  return addonLabel(liveLayerPage());
}
// A session the layer can show: a ticket of this workspace, named by its key (ORCH-12), never its raw id; or an open
// session without a ticket (state.sessions: empty helper, chat helper, plain terminal, Manager), named by its title.
function liveLayerSession(key) {
  const t = array(state?.tickets).find(x => x.id === key || x.key === key);
  if (!t) {
    const x = array(state?.sessions).find(o => o && o.id === key && o.open === true);
    if (!x) return null;
    const live = window.LiveSessions?.get(x.id) || null;
    return {pill:null, key:'', id:x.id, title:clean(x.title) || 'Session', live, kind:x.kind,
      running:live ? ['working', 'needs-you', 'idle'].includes(live.status) && x.kind !== 'terminal' : !!state.runs?.[x.id]?.running};
  }
  const run = state.runs?.[t.id], helper = run?.running && window.DashHelpers?.helperState ? window.DashHelpers.helperState(run, t) : null;
  const pill = window.UI?.ticketState && window.UI?.ticketPill ? window.UI.ticketPill(window.UI.ticketState(t, helper)) : null;
  const live = window.LiveSessions?.get(t.id) || null;
  return {pill, key:window.DashHelpers?.ticketKey?.(t) || '', id:t.id, title:clean(live ? liveName(live) : t.title) || 'Untitled', live,
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
// What Add beside offers: the live sessions not shown yet, in the bar's order; the person picks one (ORCH-463).
function liveLayerOthers(panes) {
  return liveLayerLive().filter(k => !panes.includes(k));
}
function liveLayerNext(panes) {
  return liveLayerOthers(panes)[0] || '';
}
// Pinned sessions: kept by orch for the workspace (window.LiveSessions.pins, ORCH-361); the bar and the wall read them.
function liveLayerPins() {
  return array(window.LiveSessions?.pins);
}
function liveLayerPin(key) {
  const on = !liveLayerPins().includes(key);
  window.LiveSessions?.pin(key, on);  // shows at once ('orch:live-pins'), saved in the workspace
  return on;
}
// A pin or unpin (here, on the wall, after a failed save): a pinned session moves first, in the bar and here.
window.addEventListener('orch:live-pins', () => {
  if (!document.getElementById('live-dock')) return;
  window.paintLiveBar?.();
  liveLayer = liveLayerSort(liveLayerModel(), liveLayerLive());
  liveLayerWrite(liveLayerStore(), liveLayer, liveLayerWs);
  liveLayerPaint();
});
// Renaming a session in its pane header (draft D: click the name, type, Enter): which session and what is typed so
// far, so a repaint while typing keeps the text.
let liveRen = '', liveRenText = '';
function liveRenForm(key, title) {
  const id = 'live-ren-' + String(key).replace(/[^a-z0-9_]/gi, '');
  return h('form', {className:'live-ren', 'data-live-ren':key, 'data-key':'live-ren'},
    h('label', {className:'sr-only', for:id}, 'Name of this session'),
    h('input', {className:'input', id, value:liveRenText || title, maxlength:'60', autocomplete:'off', 'data-key':'live-ren-input'}),
    h('button', {type:'submit', className:'btn outline sm', 'data-key':'live-ren-save'}, 'Save name'));
}
function liveRenStart(key) {
  liveRen = key; liveRenText = '';
  liveLayerPainted = '';
  liveLayerPaint();
  const input = document.querySelector('#live-dock [data-live-ren] input');
  input?.focus({preventScroll:true});
  input?.select();
}
function liveRenEnd(key, saved) {
  liveRen = ''; liveRenText = '';
  liveLayerPainted = '';
  liveLayerPaint();
  document.querySelector('#live-dock ' + liveSel(key, 'live-rename'))?.focus({preventScroll:true});
  if (saved) window.orch?.toast?.('Name saved.');
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
  liveLayerWrite(liveLayerStore(), next, liveLayerWs);
  liveLayerPaint();
  if (after) document.querySelector('#live-dock ' + after)?.focus({preventScroll:true});
  window.dispatchEvent(new CustomEvent('orch:live-layer', {detail:{mode:liveLayerWhere(next, liveLayerPhone()), panes:[...next.panes]}}));
}
const liveIc = name => { const s = h('span', {className:'ic-wrap', 'aria-hidden':'true'}); s.innerHTML = icon(name, 18); return s; };
function liveBtn(cls, act, label, glyph, extra = {}, word = '') {
  // a button with a word is named by it; the longer label stays the tooltip, and the name when it starts with the word
  const named = !word || label.startsWith(word);
  return h('button', {type:'button', className:cls, 'data-live':act, 'aria-label':named ? label : null, title:label, ...extra}, glyph ? liveIc(glyph) : null, word ? h('span', {className:'live-word'}, word) : null);
}
// A pane's button: the icon and its word (ORCH-463: the owner asked for words, not only icons)
const livePaneBtn = (act, label, glyph, word, extra = {}) => liveBtn('btn sm ghost live-pbtn', act, label, glyph, extra, word);
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
// Add beside's menu: which live session shows next to this one (ORCH-463: it used to take the first one unasked).
function liveBesideMenu(key, label, others) {
  const head = 'Show beside ' + label;
  return h('div', {className:'live-pop live-pop-scroll', role:'group', 'aria-label':head, 'data-key':'live-beside-menu'},
    h('p', {className:'live-pop-h'}, head),
    others.map(id => {
      const o = liveLayerSession(id), name = o ? (o.key ? o.key + ' ' : '') + o.title : id;
      const word = o?.live?.status === 'needs-you' ? 'Needs you' : clean(o?.live?.word || '');
      return h('button', {type:'button', className:'live-opt', 'data-live':'beside-pick', 'data-session':id, 'data-key':'live-beside-pick', 'aria-label':'Show ' + name + ' beside ' + label},
        h('span', {className:'live-opt-t'}, h('span', {}, o ? (o.key ? h('span', {className:'key'}, o.key + ' ') : null) : null, o ? o.title : id), word ? h('span', {className:'meta'}, word) : null));
    }));
}
// The More menu of a compact pane: pin, history, full screen (and minimise for a narrow split pane) and the places.
function liveMoreMenu(key, label, where, pinned, narrow, minHere) {
  const sess = liveLayerSession(key), phone = liveLayerPhone(), item = (act, glyph, words, extra = {}) => h('button', {type:'button', className:'live-opt', 'data-live':act, 'data-session':key, ...extra}, liveIc(glyph), h('span', {}, words));
  return h('div', {className:'live-pop', role:'group', 'aria-label':'More for ' + label, 'data-key':'live-more-menu'},
    h('p', {className:'live-pop-h'}, 'More for ' + label),
    item('pin', 'pinned', pinned ? 'Unpin' : 'Pin', {'aria-pressed':String(pinned), 'data-key':'live-pin'}),
    typeof liveHistMenuItem === 'function' ? liveHistMenuItem(key) : null,
    where === 'full' ? null : item('full', 'full-screen', 'Full screen', {'data-key':'live-more-full'}),
    minHere ? item('min', 'chevron-down', 'Minimise to the bar', {'data-key':'live-more-min'}) : null,
    narrow && sess && !sess.kind && typeof liveViewOf === 'function' ? (v => h('button', {type:'button', className:'live-opt', 'data-live':'view', 'data-live-view':v, 'data-session':key, 'data-key':'live-more-view'},
      liveIc(v === 'term' ? 'code' : 'comment'), h('span', {}, v === 'term' ? 'Show terminal' : 'Show chat')))(liveViewOf(key) === 'term' ? 'chat' : 'term') : null,
    h('p', {className:'live-pop-h'}, 'Where ' + liveLayerName() + ' sits'),
    liveOpt('bottom', 'dock-bottom', 'At the bottom', where === 'bottom'),
    phone ? null : liveOpt('right', 'dock-right', 'On the right', where === 'right'),
    sess && !sess.kind ? h('a', {className:'live-opt', href:'#ticket/' + encodeURIComponent(sess.id), 'data-key':'live-more-ticket', 'data-live-ticket':''}, liveIc('ticket'), h('span', {}, 'Open ticket')) : null);
}
// ORCH-679: Stop in the pane itself, the same run.stop the ticket page has; an idle or stuck helper says so.
function liveStopLabel(sess) {
  const t = (Array.isArray(state?.tickets) ? state.tickets : []).find(x => x.id === sess.id), h2 = t ? window.DashHelpers?.helperState?.(state?.runs?.[sess.id], t) : null;
  return h2 && ['idle', 'stuck'].includes(h2.state) ? 'Stop idle helper' : 'Stop';
}
document.addEventListener('click', async e => {
  const b = e.target.closest?.('#live-dock [data-live-stop]');
  if (!b || b.disabled) return;
  b.disabled = true;
  const r = await act('run.stop', {ticket:b.dataset.liveStop});
  b.disabled = false;
  window.orch?.toast?.(r.ok ? 'Helper stopped.' : r.text || 'Could not stop the helper.', r.ok ? 'ok' : 'error');
});
function livePane(key, where, s, o) {
  const sess = liveLayerSession(key), name = liveLayerName(), n = o.n, compact = o.compact;
  const title = sess ? sess.title : 'This session has ended', label = sess?.key || title, on = key === s.cur;
  const pinned = o.pins.includes(key), placeMenu = 'pane:' + key, moreMenu = 'more:' + key, besideMenu = 'beside:' + key;
  const leave = where === 'full' ? livePaneBtn('leave-full', 'Leave full screen', 'full-exit', 'Leave full screen', {'data-key':'live-full'}) : null;
  const besideWhy = o.total >= LIVE_MAX ? 'Three sessions is the most' : o.others.length ? 'Add beside: pick a session to show next to this one' : 'Add beside: no other session is live';
  const group = sess && !sess.kind && typeof liveGroupOf === 'function' ? liveGroupOf(liveGroups(), sess.id) : null;
  return h('section', {className:'live-pane', 'data-key':'live-pane', 'data-session':key, 'data-on':on && n > 1 ? '' : null,
    'data-new':o.fresh ? '' : null, 'data-group':group ? '' : null, 'data-narrow':o.narrow ? '' : null, tabindex:'-1', 'aria-label':(sess?.key ? sess.key + ', ' : '') + title},
    h('header', {className:'live-ph', 'data-compact':compact ? '' : null},
      o.narrow ? null : sess?.pill || null,
      sess?.key ? h('span', {className:'key'}, sess.key) : null,
      n > 1 && !on
        ? h('button', {type:'button', className:'live-pt', 'data-live':'select', 'data-session':key, title, 'aria-label':'Select the pane of ' + label}, title)
        : sess && liveRen === key ? liveRenForm(key, title)
        : sess?.live ? h('button', {type:'button', className:'live-pt', 'data-live':'rename', 'data-session':key, 'data-key':'live-rename', title:'Click to rename', 'aria-label':'Rename ' + title}, title)
        : h('span', {className:'live-pt', title}, title),
      o.narrow || typeof liveViewSwitch !== 'function' ? null : liveViewSwitch(sess),
      h('span', {className:'live-ctl'},
        compact || typeof liveHistButton !== 'function' ? null : liveHistButton(sess, label),
        compact ? null : livePaneBtn('pin', (pinned ? 'Unpin ' : 'Pin ') + label, 'pinned', pinned ? 'Unpin' : 'Pin', {'data-session':key, 'aria-pressed':String(pinned), 'data-key':'live-pin'}),
        o.phone ? null : livePaneBtn('menu', besideWhy, 'plus', 'Add beside', {'data-menu':besideMenu, 'aria-expanded':String(s.menu === besideMenu), 'aria-haspopup':'true', 'data-key':'live-beside', disabled:o.total >= LIVE_MAX || !o.others.length}),
        compact || where === 'full' ? null : livePaneBtn('menu', 'Place: where ' + name + ' sits', where === 'right' ? 'dock-right' : 'dock-bottom', 'Place', {'data-menu':placeMenu, 'aria-expanded':String(s.menu === placeMenu), 'data-key':'live-pane-place'}),
        leave || (compact ? null : livePaneBtn('full', 'Full screen', 'full-screen', 'Full screen', {'data-key':'live-full'})),
        o.narrow && n > 1 && !o.phone ? null : livePaneBtn('min', 'Minimise to the bar', 'chevron-down', 'Minimise', {'data-key':'live-min'}),
        livePaneBtn('close', o.total > 1 ? 'Close this pane' : 'Close (the bar stays)', 'x', 'Close', {'data-session':key, 'data-key':'live-close'}),
        compact ? livePaneBtn('menu', 'More for ' + label, 'more', 'More', {'data-menu':moreMenu, 'aria-expanded':String(s.menu === moreMenu), 'data-key':'live-pane-more'}) : null,
        s.menu === placeMenu ? livePlaceMenu(where, true) : null,
        s.menu === besideMenu && o.others.length ? liveBesideMenu(key, label, o.others) : null,
        s.menu === moreMenu ? liveMoreMenu(key, label, where, pinned, o.narrow, o.narrow && n > 1 && !o.phone) : null)),
    sess?.running && (!sess.kind || sess.kind === 'empty') && typeof window.liveModelRow === 'function' ? window.liveModelRow(sess, s) : null,
    group ? h('div', {className:'live-gwrap', 'data-key':'live-gwrap'}, liveGroupSwitcher(group, key, o.narrow), livePaneBody(key, sess, label))
      : livePaneBody(key, sess, label));
}
// The body of a pane: the History tab, the Start choice, or the session itself with its message box (ORCH-345).
function livePaneBody(key, sess, label) {
  return typeof liveHistShown === 'function' && liveHistShown(sess) ? h('div', {className:'live-pb live-pb-hist'}, liveHistBody(sess))
      : sess && !sess.kind && !sess.running && typeof window.liveStartBody === 'function' ? h('div', {className:'live-pb live-pb-start'}, window.liveStartBody(sess))
      : sess ? h('div', {className:'live-pb', 'data-live-body':key, 'data-live-kind':sess.kind || null},
      h('p', {className:'live-now', 'data-live-now':''}),
      sess.kind ? null : h('div', {className:'live-ask', 'data-live-ask':'', hidden:true}),
      typeof liveChatBox === 'function' ? liveChatBox(sess, label) : null,
      h('pre', {className:'live-lines', 'data-live-lines':'', 'aria-label':'Last lines of ' + label, tabindex:'0', hidden:true}),
      h('p', {className:'meta live-meta', 'data-live-meta':''}),
      sess.kind || !sess.running ? null : h('button', {type:'button', className:'btn outline sm', 'data-key':'live-stop', 'data-live-stop':sess.id}, liveStopLabel(sess)),
      sess.kind ? null : h('a', {className:'btn ghost sm', href:'#ticket/' + encodeURIComponent(sess.id), 'data-key':'live-open-ticket', 'data-live-ticket':'', 'aria-label':'Open ticket ' + label}, 'Open ticket'),
      typeof liveMsgBox === 'function' ? liveMsgBox(sess) : null)
      : h('div', {className:'live-pb'}, h('p', {}, 'This session is no longer in the list.'));
}
// The waiting question of a ticket's pane: its words, one button per option and a field for an own answer, so it is
// answered where it is shown (ORCH-675). Written only when the question changes, so a typed answer stays.
const liveAskDrafts = new Map();
function liveAskFill(box, id) {
  const q = snapshot ? null : liveAskModel(ticketOf(id)), sig = q ? [q.id, q.digest, q.text, q.options.join('|')].join('\u0001') : '';
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig; box.textContent = ''; box.hidden = !q;
  if (!q) return;
  const send = async answer => {
    const text = String(answer || '').trim(); if (!text || box.dataset.busy) return;
    // a disabled or removed button drops the keyboard to the page, where Esc no longer reaches the layer (ORCH-709):
    // it waits on the box and goes back into the pane when the answer is in
    const had = box.contains(document.activeElement);
    if (had) { box.tabIndex = -1; box.focus({preventScroll:true}); }
    box.dataset.busy = '1'; box.querySelectorAll('button,input').forEach(c => { c.disabled = true; });
    const r = await act('answer', {ticket:id, question:q.id, digest:q.digest, answer:text});
    delete box.dataset.busy;
    window.orch?.toast?.(r.ok ? 'Answered: ' + text : r.text || 'Could not send your answer.', r.ok ? 'ok' : 'error');
    if (r.ok) { liveAskDrafts.delete(id + '/' + q.id); box.dataset.sig = ''; liveAskFill(box, id); }
    else box.querySelectorAll('button,input').forEach(c => { c.disabled = false; });  // the typed words stay
    const now = document.activeElement;  // still waiting on the box (or dropped by a repaint): not moved by the person meanwhile
    if (had && (!now || now === document.body || now === box)) { liveLayerWant = {id, until:Date.now() + 5000, ask:true}; liveLayerTake(); requestAnimationFrame(liveLayerTake); }
  };
  box.append(h('p', {className:'live-ask-q'}, q.text));
  if (!q.plain) { box.append(h('a', {className:'btn primary sm', href:'#ticket/' + encodeURIComponent(id), 'data-key':'live-ask-open'}, 'Answer on the ticket')); return; }
  const row = h('div', {className:'live-ask-opts'});
  q.options.forEach((o, i) => { const b = h('button', {type:'button', className:'btn outline sm', 'data-key':'live-ask-option-' + i}, o); b.addEventListener('click', () => send(o)); row.append(b); });
  const input = h('input', {type:'text', className:'input', 'data-key':'live-ask-text', placeholder:q.options.length ? 'Or write an answer' : 'Write an answer', 'aria-label':'Your answer', value:liveAskDrafts.get(id + '/' + q.id) || ''});
  input.addEventListener('input', () => liveAskDrafts.set(id + '/' + q.id, input.value));  // a redraw of the pane keeps it
  const go = h('button', {type:'button', className:'btn primary sm', 'data-key':'live-ask-send'}, 'Send');
  go.addEventListener('click', () => send(input.value)); input.addEventListener('keydown', e => { if (e.key === 'Enter') send(input.value); });
  if (q.options.length) box.append(row);
  box.append(h('div', {className:'live-ask-line'}, input, go));
}
// The live part of a pane, written in place on every answer of the sessions API: no repaint, so the keyboard place,
// an open menu and the scroll of the lines stay.
function liveLayerFill() {
  for (const body of document.querySelectorAll('#live-dock [data-live-body]')) {
    const live = window.LiveSessions?.get(body.dataset.liveBody) || null;
    const now = body.querySelector('[data-live-now]'), pre = body.querySelector('[data-live-lines]'), meta = body.querySelector('[data-live-meta]');
    const kind = body.dataset.liveKind || '';  // a session without a ticket (ORCH-364)
    const text = kind === 'terminal' ? 'A plain terminal in this workspace, no helper. The terminal itself comes here next.'
      : !window.LiveSessions?.ready ? 'Loading…' : live ? liveNow(live) : kind ? 'This helper is not on right now.' : 'No helper is working on this ticket right now.';
    if (now.textContent !== text) now.textContent = text;
    const askBox = body.querySelector('[data-live-ask]');
    if (askBox) liveAskFill(askBox, body.dataset.liveBody);
    now.hidden = !!askBox && !askBox.hidden;  // the question card says it already (ORCH-687)
    const lines = live && Array.isArray(live.lines) ? live.lines.join('\n') : '';
    if (pre.textContent !== lines) {
      const end = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 8;  // following the end: keep following it
      pre.textContent = lines;
      if (end) pre.scrollTop = pre.scrollHeight;
    }
    pre.hidden = !lines;
    if (typeof liveViewApply === 'function') liveViewApply(body);
    const m = live && kind !== 'terminal' ? liveMeta(live).join(' · ') : '';
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
  const others = liveLayerOthers(s.panes);
  return {shown, n:shown.length, total:s.panes.length, phone, narrow:liveLayerNarrow(where, shown.length, room, phone),
    compact:liveLayerCompact(where, shown.length, room, phone), pins:liveLayerPins(), others, next:others[0] || ''};
}
// Paints the dock when something it shows changed; a state poll that changes nothing leaves it alone (no flicker, the
// keyboard place and any open menu stay).
function liveLayerPaint() {
  const host = liveDockHost(), s = liveLayerModel(), where = liveLayerWhere(s, liveLayerPhone());
  const shown = s.panes.map(liveLayerSession).map(x => x && [x.key, x.title, x.running, x.pill?.textContent || '', x.running && !x.kind ? liveStopLabel(x) : '']);
  const v = s.panes.length && where !== 'bar' && where !== 'side' ? liveLayerView(s, where) : null;
  const key = JSON.stringify([where, s.menu, s.panes, s.cur, shown, liveRen, v && [v.narrow, v.compact, v.pins.filter(k => s.panes.includes(k)), v.others], liveLayerName(), liveLayerPage()?.name, typeof liveHistKey === 'function' ? liveHistKey() : null, typeof window.liveStartKey === 'function' ? window.liveStartKey() : null, typeof window.liveModelKey === 'function' ? window.liveModelKey(s.panes) : null]);
  host.dataset.mode = where;
  host.style.setProperty('--live-h', s.height ? s.height + 'px' : '');
  host.style.setProperty('--live-w', s.width ? s.width + 'px' : '');
  if (!s.height) host.style.removeProperty('--live-h');
  if (!s.width) host.style.removeProperty('--live-w');
  if (key !== liveLayerPainted) {
    // the panel animates only when it appears or moves, not on every repaint
    if (where === liveLayerWas) host.dataset.still = ''; else delete host.dataset.still;
    const shared = liveBarShared(), keepBar = shared ? document.getElementById('live-bar') : null;
    const typing = document.activeElement?.closest?.('#live-dock [data-live-msg-text]')?.dataset.liveMsgText;  // the message box keeps the keyboard
    const renaming = !!document.activeElement?.closest?.('#live-dock [data-live-ren]');
    host.replaceChildren(...[liveLayerTree(s, where)].filter(Boolean), ...(keepBar ? [keepBar] : []));
    if (renaming) host.querySelector('[data-live-ren] input')?.focus({preventScroll:true});
    if (shared) {
      // the shared bar goes after the panel in the dock (on top in full screen) and carries Open and Place at its end
      if (!keepBar || keepBar.parentNode !== host) shared.mount(host, {docked:true});
      shared.end(() => [liveBarEnd(liveLayerWhere(liveLayerModel(), liveLayerPhone()), liveLayerModel())]);
    }
    if (typing) {
      const box = host.querySelector(`[data-live-msg-text="${typing.replace(/["\\]/g, '')}"]`);
      if (box) { box.focus({preventScroll:true}); box.setSelectionRange(box.value.length, box.value.length); }
    }
    liveLayerPainted = key;
    liveLayerWas = where;
    liveLayerWasPanes = where === 'bar' || where === 'side' ? [] : [...s.panes];
  }
  liveLayerFill();
  window.liveStartMount?.();  // the Start choice of a pane with no helper (pages/live-start.js)
  document.body.dataset.liveLayer = where;
  liveLayerInert(where === 'full');
  liveLayerPad();
  liveLayerTake();
}
// The keyboard goes into a pane a ticket's button or address opened (ORCH-677). The pane is drawn again when its live
// data or Start choice arrives and that drops the keyboard to the page, so every paint puts it back until the person
// presses a key or clicks somewhere (or 5 seconds pass). After an answer in the pane (`ask`) it goes to the next
// question's first choice when there is one, else to Open ticket (ORCH-709).
let liveLayerWant = null;
function liveLayerTake() {
  if (!liveLayerWant) return;
  if (Date.now() > liveLayerWant.until) { liveLayerWant = null; return; }
  const pane = document.querySelector('#live-dock .live-pane[data-session="' + String(liveLayerWant.id).replace(/["\\]/g, '') + '"]');
  if (!pane) return;
  const a = document.activeElement, ask = liveLayerWant.ask && pane.querySelector('[data-live-ask]:not([hidden]) :is(button, input):not(:disabled)');
  if (a && a !== document.body && pane.contains(a) && !(ask && a.matches('[data-live-ask]'))) return;
  (ask || pane.querySelector('[data-key="live-open-ticket"]') || pane).focus({preventScroll:true});
}
for (const type of ['keydown', 'pointerdown']) document.addEventListener(type, () => { liveLayerWant = null; }, true);
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
// Called after every page render (app.js): on wherever the live page runs, gone without it (a shared copy, no add-on).
function liveDockSync() {
  window.LiveSessions?.sync();
  if (!liveFocusOn() || !liveLayerPage()) { liveLayerOff(); return; }
  liveLayerPaint();
}
// A new answer of the sessions API: the panes' live part in place; the dock itself only when what it shows changed.
window.addEventListener('orch:live-sessions', () => { if (document.getElementById('live-dock')) liveLayerPaint(); });
// For the bar, the wall and the ticket page: open a session in the layer.
window.LiveLayer = {
  open(key, into = false) {  // the bar marks chips by ticket id; a ticket's session button moves the keyboard into the pane
    const id = liveLayerSession(key)?.id || key;
    liveLayerDo({type:'open', key:id});
    if (into) { liveLayerWant = {id, until:Date.now() + 5000}; liveLayerTake(); }
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
// Only where the live page runs; otherwise null and the page keeps what it had (Watch live, Answer).
function liveFocusButton(t, long = false) {
  if (!t?.id || snapshot || !liveFocusOn() || !liveLayerPage() || !window.DashHelpers?.helperState) return null;
  const verb = liveFocusVerb(t, state.runs?.[t.id], window.DashHelpers.helperState);
  if (!verb) return null;
  const name = liveLayerName(), key = window.DashHelpers.ticketKey?.(t) || clean(t.title) || 'this ticket';
  const b = h('button', {type:'button', className:'btn outline sm', 'data-key':'live-session-btn', 'data-ticket':t.id,
    'data-verb':verb, 'aria-label':verb + ' ' + key + ' in ' + name}, long ? verb + ' in ' + name : verb);
  b.addEventListener('click', e => { e.stopPropagation(); window.LiveLayer.open(t.id, true); });
  return b;
}
document.addEventListener('click', e => {
  // Open ticket: the layer would stay over the ticket page (full screen hides it, the bottom panel covers the answer buttons)
  if (e.target.closest?.('#live-dock [data-live-ticket]')) liveLayerDo({type:'to-ticket'});
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
    if (s.panes.length) liveLayerDo({type:'reopen'}, '.live-pane :is([data-key="live-min"], [data-key="live-pane-more"])');
    else { const first = liveLayerFirst(); if (first) liveLayerDo({type:'open', key:first}, '.live-pane :is([data-key="live-min"], [data-key="live-pane-more"])'); else liveLayerDo({type:'place', mode:'bar'}, '[data-key="live-open"]'); }
  }
  else if (act === 'full') liveLayerDo({type:'place', mode:'full'}, '[data-key="live-full"]');
  else if (act === 'leave-full') liveLayerDo({type:'leave-full'}, LIVE_BACK_FROM_FULL);
  else if (act === 'min') liveLayerDo({type:'min'}, '[data-key="live-open"]');
  else if (act === 'close') {
    const s = liveLayerModel(), at = s.panes.indexOf(b.dataset.session);
    liveLayerDo({type:'close', key:b.dataset.session}, s.panes.length > 1 ? liveSel(s.panes[at + 1] || s.panes[at - 1], 'live-close') : '[data-key="live-open"]');
  }
  else if (act === 'beside-pick') liveLayerDo({type:'beside', key:b.dataset.session}, liveSel(b.dataset.session, 'live-close'));
  else if (act === 'select') liveLayerDo({type:'select', key:b.dataset.session}, liveSel(b.dataset.session, 'live-close'));
  else if (act === 'swap') {  // a row of the group switcher: History closes, the keyboard stays on the row
    const to = b.dataset.to;
    if (typeof liveHistOpen === 'object') liveHistOpen.delete(b.dataset.session);
    liveLayerDo({type:'swap', from:b.dataset.session, key:to}, liveSel(to, 'live-group-' + to));
    if (b.dataset.session === to && typeof liveHistOpen === 'object') liveLayerPaint();
  }
  else if (act === 'view') {  // Show chat / Show terminal in the More menu: livechat.js switched it; the menu closes
    const menu = liveLayerModel().menu;
    if (menu) liveLayerDo({type:'menu', menu}, liveSel(b.dataset.session, 'live-pane-more'));
  }
  else if (act === 'rename') liveRenStart(b.dataset.session);
  else if (act === 'pin') {
    const key = b.dataset.session, menu = liveLayerModel().menu;
    liveLayerPin(key);
    if (menu) liveLayerDo({type:'menu', menu});  // the More menu closes after its choice
    document.querySelector('#live-dock ' + liveSel(key, 'live-pin') + ', #live-dock ' + liveSel(key, 'live-pane-more'))?.focus({preventScroll:true});
  }
});
// Where the keyboard lands after full screen: Full screen, or More where a compact pane keeps it (ORCH-463).
const LIVE_BACK_FROM_FULL = ':is([data-key="live-full"], [data-key="live-pane-more"])';
// A control of one pane, for the keyboard place after a repaint.
function liveSel(key, what) {
  return `.live-pane[data-session="${String(key || '').replace(/["\\]/g, '')}"] [data-key="${what}"]`;
}
document.addEventListener('input', e => {
  if (e.target.closest?.('#live-dock [data-live-ren]')) liveRenText = e.target.value;
});
document.addEventListener('submit', e => {
  const form = e.target.closest?.('#live-dock [data-live-ren]');
  if (!form) return;
  e.preventDefault();
  const key = form.dataset.liveRen, text = form.querySelector('input')?.value || '';
  const sess = liveLayerSession(key), own = text.trim() && text.trim() !== clean(sess?.live?.title || '') ? text.trim() : '';
  const saved = window.LiveSessions?.rename(key, own);  // an empty name, or the title itself, goes back to the title
  liveRenEnd(key, true);
  Promise.resolve(saved).then(() => requestAnimationFrame(() => {  // the page is drawn again when orch answers
    const a = document.activeElement;
    if (!a || a === document.body || !a.isConnected) document.querySelector('#live-dock ' + liveSel(key, 'live-rename'))?.focus({preventScroll:true});
  }));
});
document.addEventListener('keydown', e => {
  if (!document.getElementById('live-dock')) return;
  if (e.key === 'Escape' && liveRen && e.target.closest?.('#live-dock [data-live-ren]')) {  // Esc leaves the name as it was
    e.preventDefault();
    liveRenEnd(liveRen, false);
    return;
  }
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
  liveLayerDo({type:'escape', inside}, was ? `[data-menu="${was}"]` : s.mode === 'full' ? LIVE_BACK_FROM_FULL : '[data-key="live-open"]');
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

'use strict';
// The layer of the live page (draft D, ORCH-338; pages/live.js). One dock under every
// page, outside main, so it stays open while the page changes: a panel at the bottom, on the right or full screen,
// above a bar; minimised it is only the bar, closed to the side it is a slim edge tab. Place and size are kept per
// browser. Esc goes one step back: an open menu, then full screen, then the panel to the bar. The split (ORCH-339):
// 1, 2 or 3 sessions side by side (stacked on the right), one of them selected; each pane has pin, add beside, place,
// full screen, minimise and close, each with its word (ORCH-463). A compact pane (split, narrow or short of room) shows
// them as one row of icon buttons beside the title (draft D, ORCH-1328); full screen folds into More there, pin and
// place only in a tight pane (ORCH-1568). Add
// beside asks which session to show (a menu of the live sessions not shown yet). On a phone
// only the selected session shows. A pane shows the session's live data (pages/livesessions.js, ORCH-359): what it
// does now, its last lines, tool and model, open time; the chat and terminal tasks fill it further.
// Look: the kit's .live-* rules (widgets.css). The bar's session chips go into [data-key="live-bar-sessions"].
const LIVE_LAYER_KEY = 'orch.live.layer';
const LIVE_PLACES = ['bottom', 'right'];
const LIVE_SIZE = {height:[200, 0.85], width:[320, 0.7]};  // smallest px, largest share of the window
const LIVE_MAX = 3;  // sessions side by side
const LIVE_NARROW = 600;  // a pane narrower than this folds pin, place and Chat | Terminal into More (draft D; the full header needs about 600 px)
const LIVE_TIGHT = 400;  // a pane narrower than this folds pin and place into More too (draft D shows them down to about 430 px, ORCH-1568)
const LIVE_CROWDED = 1500;  // a single wide pane under this puts Pin, Add beside and Minimise in More, so its title shows whole (ORCH-1600)
const LIVE_ROOMY = 1200;
// ORCH-1616 (owner's look stop, split at 1280 cut every title): a pane in a split gets at least LIVE_PANE_MIN px, so 2
// panes show side by side at 1280 wide and 3 at 1920; the others stay open on the bar (its chip opens them here). On
// the right the panes stack: at most LIVE_RIGHT_MAX. The page beside the right panel keeps LIVE_PAGE_MIN px.
const LIVE_PANE_MIN = 480, LIVE_RIGHT_MAX = 2, LIVE_PAGE_MIN = 600;  // a single pane narrower than this is compact too: its title gets a row of its own (ORCH-463)

// --- the model: plain data, no page (tested in tests/live_layer.test.js) ---
// ORCH-1643 (bottom split at 1280 sliced the page behind it): a layer that was never placed opens on the right on a
// desktop window under LIVE_RIGHT_FIRST px wide, so the page keeps its full height beside it (the page beside keeps
// LIVE_PAGE_MIN px); at 1920 the bottom keeps room for three panes. A place the person picked is always kept.
const LIVE_RIGHT_FIRST = 1600;
function liveLayerFirstPlace(win, phone) {
  const w = Number(win) || 0;
  return !phone && w > 720 && w < LIVE_RIGHT_FIRST ? 'right' : 'bottom';
}
function liveLayerFresh(first = 'bottom') {
  const at = LIVE_PLACES.includes(first) ? first : 'bottom';
  return {mode:'bar', last:at, back:at, height:null, width:null, panes:[], cur:'', menu:''};
}
// Narrow panes: on a phone, on the right with more than one, or when a share of the room is under LIVE_NARROW
// (one pane on the right at 1280 wide too: its header would push Full screen out of sight).
function liveLayerNarrow(where, n, room, phone) {
  return !!phone || (n > 1 && where === 'right') || room / Math.max(n, 1) < LIVE_NARROW;
}
// Tight panes: pin and place fold into More (draft D, ORCH-1568): on a phone, stacked on the right, or under LIVE_TIGHT.
function liveLayerTight(where, n, room, phone) {
  return !!phone || (n > 1 && where === 'right') || room / Math.max(n, 1) < LIVE_TIGHT;
}
// Compact panes: icon buttons beside the title, the words as tooltips (draft D, ORCH-1328; ORCH-463 had the words on a
// second row, which cost the split a row). Every split is compact, and so is a narrow or small pane.
function liveLayerCompact(where, n, room, phone) {
  return liveLayerNarrow(where, n, room, phone) || n > 1 || room < LIVE_ROOMY;
}
// Crowded panes (ORCH-1600): a single pane with the full header but under LIVE_CROWDED (1280 wide) keeps its title whole:
// Pin, Add beside and Minimise go into More; Chat | Terminal, History, Stop, End session and the way out stay.
function liveLayerCrowded(where, n, room, phone) {
  return !liveLayerCompact(where, n, room, phone) && room < LIVE_CROWDED;
}
// The width of the dashboard's side menu (0 on a phone, where it is not beside the page).
function liveLayerSide() {
  const el = typeof document === 'object' ? document.querySelector('.shell > .sidebar') : null;
  return el && getComputedStyle(el).position !== 'fixed' ? el.offsetWidth : 0;
}
// How many of the open panes show at once in this room; the selected one (cur) is always among them.
// ORCH-261 ship stop (bottom split over Review): while the page behind has cards to answer, a pane with nothing in it
// yet (quiet: no message, no question) folds to its chip on the bar, so the split does not spend half its room on
// "No messages yet". The selected pane always shows, and a split of only quiet panes stays as it is.
function liveLayerFit(panes, cur, where, room, phone, quiet = []) {
  let list = Array.isArray(panes) ? panes : [];
  const hush = Array.isArray(quiet) ? quiet : [];
  if (hush.length && list.some(k => !hush.includes(k))) list = list.filter(k => k === cur || !hush.includes(k));
  if (phone) return list.length ? [list.includes(cur) ? cur : list[0]] : [];
  const most = where === 'right' ? LIVE_RIGHT_MAX : Math.max(1, Math.min(LIVE_MAX, Math.floor((Number(room) || 0) / LIVE_PANE_MIN)));
  if (list.length <= most) return list.slice();
  const out = list.slice(0, most);
  if (cur && list.includes(cur) && !out.includes(cur)) out[most - 1] = cur;
  return out;
}
// ORCH-261 ship stop: the bottom panel's height when the person never dragged it. While the page behind has cards to
// answer it keeps LIVE_ANSWER_ROOM px of the window above the bar and panel (top bar, page heading, one card and its
// answer buttons), never under LIVE_ANSWER_MIN (a pane header, a question card and the message box with two attached
// files stay whole in the panel); otherwise the style sheet's own height (null).
const LIVE_ANSWER_ROOM = 412, LIVE_BAR_H = 48, LIVE_ANSWER_MIN = 340;
function liveLayerBottomCap(winH, answering) {
  if (!answering) return null;
  const h = Number(winH) || 0;
  return Math.max(LIVE_ANSWER_MIN, Math.min(Math.round(h * 0.45), h - LIVE_ANSWER_ROOM - LIVE_BAR_H));
}
// The widest the right panel may be so the page beside it keeps LIVE_PAGE_MIN px (never under the smallest size).
function liveLayerRightMax(win, side) {
  return Math.max(LIVE_SIZE.width[0], (Number(win) || 0) - (Number(side) || 0) - LIVE_PAGE_MIN);
}
// Kept per workspace (issue 1351: the dashboards of two workspaces can get the same port, so the same browser store).
function liveLayerKey(ws) { return ws ? LIVE_LAYER_KEY + '.' + ws : LIVE_LAYER_KEY; }
function liveLayerRead(store, ws = '', first = 'bottom') {
  const s = liveLayerFresh(first);
  let saved = null;
  try { saved = JSON.parse(store?.getItem(liveLayerKey(ws)) || 'null'); } catch { saved = null; }
  if (!saved || typeof saved !== 'object') return s;
  // ORCH-1661: full screen is kept after a reload too, as every other place; Esc still goes back to where it was
  if (['bar', 'side', 'bottom', 'right', 'full'].includes(saved.mode)) s.mode = saved.mode;
  if (LIVE_PLACES.includes(saved.last)) s.last = saved.last;
  s.back = s.mode === 'full' && LIVE_PLACES.includes(saved.back) ? saved.back : s.last;
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
  // ORCH-1643 (draft D): a suggested answer is highlighted only with the helper's reason; without one, nothing is
  const because = typeof q.because === 'string' ? q.because.trim() : '';
  const suggest = because && options.includes(q.recommended) ? q.recommended : '';
  return {id:q.id, digest:q.digest, text:String(q.text || ''), options, plain:q.kind == null, suggest, because:suggest ? because : ''};
}
// The line under a question with a suggested answer: "The helper suggests “Keep the old name”: links keep working."
function liveAskWhy(q) {
  return q && q.suggest && q.because ? 'The helper suggests \u201c' + q.suggest + '\u201d: ' + q.because : '';
}
// ORCH-1358: the pane header follows the live sessions API, the list the bar and the wall read, so the three never
// disagree (the page's own state is polled at another time): a session that ended has no helper (never Working), one
// that needs you says Needs you. Without an answer of the API yet, the page's own helper state (`own`) stays.
const LIVE_LAYER_HELPER = {'needs-you':'you', working:'working', idle:'idle'};
const LIVE_LAYER_FINE = {Starting:'starting', 'On hold':'waiting', Stuck:'stuck', 'Stopped: usage limit':'limit'};
function liveLayerHelper(live, own) {
  if (!live || typeof live.status !== 'string') return own || null;
  const st = LIVE_LAYER_HELPER[live.status];
  if (!st) return null;  // in line or closed: no helper runs
  if (own && (own.state === st || (st === 'working' && ['working', 'starting', 'waiting', 'stuck', 'limit'].includes(own.state)))) return own;
  // a working session keeps the API's finer word (Starting, On hold, Stuck, Stopped: usage limit)
  const fine = st === 'working' ? LIVE_LAYER_FINE[live.word] : null;
  // ORCH-2201: a helper at its prompt reads "Quiet 2 d", the time it has been quiet, instead of Idle or Stuck
  const quiet = st === 'idle' || live.word === 'Stuck';
  return {state:fine || st, word:quiet && typeof liveQuietWord === 'function' ? liveQuietWord(live.idle_seconds) : fine ? live.word : {you:'Needs you', working:'Working', idle:'Idle'}[st], detail:typeof live.detail === 'string' ? live.detail : ''};
}
// ORCH-1362 (UX checklist D5): Add beside is never greyed. When nothing can go beside, its menu says why and what to
// do instead; '' when there are sessions to pick.
function liveBesideNote(total, others) {
  if (total >= LIVE_MAX) return 'Three sessions show at once, the most. Close one to show another here.';
  return others > 0 ? '' : 'No other session is live. Start one from the wall or New on the bar, then add it here.';
}
// ORCH-1659: a pane added beside that leaves another without room (two fit at 1280, three at 1920) says so once, with
// the names of the sessions that wait on the bar; '' when every pane shows.
function liveBesideHidden(shown, names) {
  const n = Number(shown) || 0, wait = (Array.isArray(names) ? names : []).filter(Boolean);
  if (!n || !wait.length) return '';
  const room = n === 1 ? 'Room for 1 session here' : 'Room for ' + n + ' sessions here';
  return room + ', so ' + wait.join(', ') + (wait.length === 1 ? ' waits' : ' wait') + ' on the bar. Open it there, or close a pane.';
}
// ORCH-1600: which sides of a pane are folded, as stored on this computer (anything unreadable: both open)
const LIVE_FOLD_KEY = 'orch.live.fold';
function liveFoldRead(store) {
  try { const v = JSON.parse(store?.getItem(LIVE_FOLD_KEY) || '{}'); return {left:v?.left === true, right:v?.right === true}; } catch { return {left:false, right:false}; }
}
// --- the page ---
let liveLayer = null;
let liveLayerPainted = '';
let liveLayerWas = '';
let liveLayerWasPanes = [];  // the panes painted last: a new one slides in
let liveLayerActed = 0;  // when a person last changed the layer: only then it moves, never on a live-data repaint
let liveLayerFrom = null;  // {id, rect}: the wall tile a session was opened from; its pane grows out of it (draft D zoom)
function liveLayerStore() { try { return window.localStorage; } catch { return null; } }
// ORCH-1600 (owner): the helper list on the left and the Results column on the right fold away for more room, and the
// choice is remembered on this computer. A folded side keeps a narrow strip with the button that opens it again.
let liveFoldNow = null;
function liveFold() { if (!liveFoldNow) liveFoldNow = liveFoldRead(liveLayerStore()); return liveFoldNow; }
function liveFoldSet(side, on) {
  liveFoldNow = {...liveFold(), [side]:!!on};
  try { liveLayerStore()?.setItem(LIVE_FOLD_KEY, JSON.stringify(liveFoldNow)); } catch { /* private window: it lasts this page */ }
}
const LIVE_FOLD_WORDS = {left:['Hide the helper list', 'Show the helper list'], right:['Hide results', 'Show results']};
function liveFoldBtn(side) {
  const folded = liveFold()[side], label = LIVE_FOLD_WORDS[side][folded ? 1 : 0];
  return h('button', {type:'button', className:'btn icon sm ghost live-fold', 'data-live':'fold', 'data-side':side, 'data-key':'live-fold-' + side,
    'aria-expanded':String(!folded), 'aria-label':label, title:label}, liveIc((side === 'left') === folded ? 'chevron-right' : 'chevron-left'));
}
// Folds or opens a side in every pane in place: no repaint, so the terminal and the keyboard stay where they are.
function liveFoldApply(host) {
  const f = liveFold();
  host?.querySelectorAll('.live-pane').forEach(p => { p.toggleAttribute('data-fold-left', f.left); p.toggleAttribute('data-fold-right', f.right); });
  // the buttons change in place: the one just clicked keeps the keyboard and shows no keyboard ring after a mouse click, so
  // both arrows always look the same
  host?.querySelectorAll('.live-fold').forEach(b => { const n = liveFoldBtn(b.dataset.side); for (const a of ['aria-expanded', 'aria-label', 'title']) b.setAttribute(a, n.getAttribute(a)); b.replaceChildren(...n.childNodes); });
}
function liveLayerPhone() { return !!window.matchMedia?.('(max-width: 720px)').matches; }
let liveLayerWs = null;
function liveLayerModel() {
  const ws = typeof state === 'object' && state ? String(state.workspace || '') : '';
  if (!liveLayer || (ws && liveLayerWs !== ws)) { liveLayer = liveLayerRead(liveLayerStore(), ws, liveLayerFirstPlace(window.innerWidth, window.matchMedia('(max-width: 720px)').matches)); liveLayerWs = ws; }  // a state without its name (an answer in between) keeps the layer
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
    const x = array(state?.sessions).find(o => o && o.id === key && (o.open === true || o.kind !== 'terminal'));
    if (!x) return null;
    const live = window.LiveSessions?.get(x.id) || null;
    const running = live ? ['working', 'needs-you', 'idle'].includes(live.status) && x.kind !== 'terminal' : !!state.runs?.[x.id]?.running;
    // ORCH-817: an ended helper without a ticket (Manager, empty or chat helper) keeps its pane: Start again and History
    const quiet = live?.status === 'idle' && x.kind !== 'terminal' && window.UI?.helperPill && typeof liveQuietWord === 'function' ? window.UI.helperPill('idle', liveQuietWord(live.idle_seconds)) : null;
    return {pill:quiet, key:'', id:x.id, title:clean(x.title) || 'Session', live, kind:x.kind, running, ended:!running && x.kind !== 'terminal' && (x.open !== true || (!!window.LiveSessions?.ready && !live))};
  }
  const run = state.runs?.[t.id], live = window.LiveSessions?.get(t.id) || null;
  const own = run?.running && window.DashHelpers?.helperState ? window.DashHelpers.helperState(run, t) : null;
  const helper = liveLayerHelper(live, own);
  const pill = window.UI?.ticketState && window.UI?.ticketPill ? window.UI.ticketPill(window.UI.ticketState(t, helper)) : null;
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
  if (typeof liveWallBeforePin === 'function') liveWallBeforePin();  // the wall's tile slides to its band (pages/livewall.js)
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
// `before`: the own name the session had (null = none); Undo on the toast puts it back (ORCH-1359).
function liveRenEnd(key, saved, before = null) {
  liveRen = ''; liveRenText = '';
  liveLayerPainted = '';
  liveLayerPaint();
  document.querySelector('#live-dock ' + liveSel(key, 'live-rename'))?.focus({preventScroll:true});
  if (saved) window.orch?.toast?.('Name saved.', 'ok', () => window.LiveSessions?.rename(key, before || ''));
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
  // The shared bar mounts after the paint and the panel changes height by itself (a drag, the phone sheet): the room
  // kept for the layer follows its real size, or the page's last links stay under the bar (ORCH-1360).
  if (typeof ResizeObserver === 'function' && !host.dataset.sized) { host.dataset.sized = '1'; new ResizeObserver(() => liveLayerPad()).observe(host); }
  return host;
}
function liveLayerDo(act, after) {
  const before = liveLayerModel(), stepped = liveLayerStep(before, act, liveLayerPhone());
  if (stepped === before) return;
  liveLayerActed = Date.now();
  const next = liveLayerSort(stepped, liveLayerLive());
  liveLayer = next;
  liveLayerWrite(liveLayerStore(), next, liveLayerWs);
  liveLayerPaint();
  if (after) document.querySelector('#live-dock ' + after)?.focus({preventScroll:true});
  if (act.type === 'beside') liveBesideSay(next);
  window.dispatchEvent(new CustomEvent('orch:live-layer', {detail:{mode:liveLayerWhere(next, liveLayerPhone()), panes:[...next.panes]}}));
}
// After Add beside: the panes that found no room are named (ORCH-1659: at 1280 the third quietly hid one).
function liveBesideSay(s) {
  const where = liveLayerWhere(s, liveLayerPhone());
  if (liveLayerPhone() || where === 'bar' || where === 'side' || !s.panes.length) return;
  const v = liveLayerView(s, where);
  // a quiet pane folded because the page behind has cards to answer (ORCH-261) did not lose its place for lack of room
  // (only when the fold happened: a split of only quiet panes folds nothing, liveLayerFit)
  const hush = liveLayerAnswering() ? liveLayerQuiet(s.panes) : [], quiet = s.panes.some(k => !hush.includes(k)) ? hush : [];
  const wait = s.panes.filter(k => !v.shown.includes(k) && !quiet.includes(k)).map(k => liveLayerSession(k)?.title || k);
  const text = liveBesideHidden(v.n, wait);
  if (text) window.orch?.toast?.(text, 'ok');
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
function liveBesideMenu(key, label, others, note) {
  const head = 'Show beside ' + label;
  return h('div', {className:'live-pop live-pop-scroll', role:'group', 'aria-label':head, 'data-key':'live-beside-menu'},
    h('p', {className:'live-pop-h'}, head),
    note ? h('p', {className:'meta', role:'status', 'data-key':'live-beside-none'}, note) : others.map(id => {
      const o = liveLayerSession(id), name = o ? (o.key ? o.key + ' ' : '') + o.title : id;
      const word = o?.live?.status === 'needs-you' ? 'Needs you' : clean(o?.live?.word || '');
      return h('button', {type:'button', className:'live-opt', 'data-live':'beside-pick', 'data-session':id, 'data-key':'live-beside-pick', 'aria-label':'Show ' + name + ' beside ' + label},
        h('span', {className:'live-opt-t'}, h('span', {}, o ? (o.key ? h('span', {className:'key'}, o.key + ' ') : null) : null, o ? o.title : id), word ? h('span', {className:'meta'}, word) : null));
    }));
}
// The More menu of every pane (ORCH-1616): history, full screen, minimise, the place, Open ticket, Stop and End
// session; pin and Add beside only for a pane too tight to keep them in its header.
function liveMoreMenu(key, label, where, pinned, narrow, minHere, tight = narrow, beside = '') {
  const sess = liveLayerSession(key), phone = liveLayerPhone(), item = (act, glyph, words, extra = {}) => h('button', {type:'button', className:'live-opt', 'data-live':act, 'data-session':key, ...extra}, liveIc(glyph), h('span', {}, words));
  return h('div', {className:'live-pop', role:'group', 'aria-label':'More for ' + label, 'data-key':'live-more-menu'},
    h('p', {className:'live-pop-h'}, 'More for ' + label),
    tight || beside ? item('pin', 'pinned', pinned ? 'Unpin' : 'Pin', {'aria-pressed':String(pinned), 'data-key':'live-pin'}) : null,
    beside ? h('button', {type:'button', className:'live-opt', 'data-live':'menu', 'data-menu':beside, 'data-key':'live-more-beside', 'aria-haspopup':'true'}, liveIc('plus'), h('span', {}, 'Add beside')) : null,
    typeof liveHistMenuItem === 'function' ? liveHistMenuItem(key) : null,
    where === 'full' ? null : item('full', 'full-screen', 'Full screen', {'data-key':'live-more-full'}),
    minHere ? item('min', 'chevron-down', 'Minimise to the bar', {'data-key':'live-more-min'}) : null,
    narrow && sess && !sess.kind && typeof liveViewOf === 'function' ? (v => h('button', {type:'button', className:'live-opt', 'data-live':'view', 'data-live-view':v, 'data-session':key, 'data-key':'live-more-view'},
      liveIc(v === 'term' ? 'code' : 'comment'), h('span', {}, v === 'term' ? 'Show terminal' : 'Show chat')))(liveViewOf(key) === 'term' ? 'chat' : 'term') : null,
    // ORCH-1663: Open ticket is one of this session's actions, not a place; Stop and End come before the places, so a
    // menu taller than the room never scrolls them out of sight
    sess && !sess.kind ? h('a', {className:'live-opt', href:'#ticket/' + encodeURIComponent(sess.id), 'data-key':'live-more-ticket', 'data-live-ticket':''}, liveIc('ticket'), h('span', {}, 'Open ticket')) : null,
    sess && typeof window.liveEndMenu === 'function' ? liveMoreEnd(key) : null,
    where === 'full' ? null : h('p', {className:'live-pop-h'}, 'Where ' + liveLayerName() + ' sits'),
    where === 'full' ? null : liveOpt('bottom', 'dock-bottom', 'At the bottom', where === 'bottom'),
    where === 'full' || phone ? null : liveOpt('right', 'dock-right', 'On the right', where === 'right'),
    where === 'full' ? null : liveOpt('side', 'dock-side', 'Closed to the side', where === 'side'));
}
// Stop and End session in More (ORCH-817): End closes More and opens the one question under the header.
function liveMoreEnd(key) {
  const m = typeof liveEndModel === 'function' ? liveEndModel(window.LiveSessions?.get(key) || null) : {on:false};
  if (!m.on) return null;
  return fragment(h('p', {className:'live-pop-h'}, 'This session'),
    m.stop ? h('button', {type:'button', className:'live-opt', 'data-live-end':'stop', 'data-id':key, 'data-key':'live-more-stop'}, liveIc('stop'),
      h('span', {className:'live-opt-t'}, h('span', {}, 'Stop'), h('span', {className:'meta'}, m.busy ? 'Ends the current step. The session stays.' : 'Nothing is running right now.'))) : null,
    h('button', {type:'button', className:'live-opt', 'data-live-end':'ask', 'data-where':'pane:' + key, 'data-id':key, 'data-key':'live-more-end'}, liveIc('power'), h('span', {}, 'End session')));
}
// ORCH-817: Stop (the current step) and End session (asks once) of every kind of session: pages/live-end.js. In a
// narrow pane (a phone) they sit in More; a compact one keeps them in its header; the End question then opens under the header.
const liveEndHere = (key, label, narrow) => typeof window.liveEndButtons !== 'function' ? []
  : narrow ? [window.liveEndOpenAt?.('pane') === key ? window.liveEndMenu(key, 'pane:' + key) : null] : window.liveEndButtons(key, label);
function livePane(key, where, s, o) {
  const sess = liveLayerSession(key), name = liveLayerName(), n = o.n, compact = o.compact;
  const title = sess ? sess.title : 'This session has ended', label = sess?.key || title, on = key === s.cur;
  const pinned = o.pins.includes(key), placeMenu = 'pane:' + key, moreMenu = 'more:' + key, besideMenu = 'beside:' + key;
  // a sign-in card's terminal full screen (on a phone, ORCH-865): the way back says where it goes, in words
  const signin = array(state?.sessions).some(o => o?.id === key && o.signin === true);
  const leave = where !== 'full' ? null : signin
    ? h('button', {type:'button', className:'btn sm outline', 'data-live':'leave-full', 'data-key':'live-full', title:'Leave full screen'}, 'Back to the ticket')
    : livePaneBtn('leave-full', 'Leave full screen', 'full-exit', 'Leave full screen', {'data-key':'live-full'});
  const besideNone = liveBesideNote(o.total, o.others.length), besideWhy = besideNone ? 'Add beside: ' + besideNone : 'Add beside: pick a session to show next to this one';
  const group = sess && !sess.kind && typeof liveGroupOf === 'function' ? liveGroupOf(liveGroups(), sess.id) : null;
  return h('section', {className:'live-pane', 'data-key':'live-pane', 'data-session':key, 'data-on':on && n > 1 ? '' : null,
    'data-new':o.fresh ? '' : null, 'data-group':group ? '' : null, 'data-narrow':o.narrow ? '' : null, 'data-tight':o.tight ? '' : null,
    'data-fold-left':liveFold().left ? '' : null, 'data-fold-right':liveFold().right ? '' : null, tabindex:'-1', 'aria-label':(sess?.key ? sess.key + ', ' : '') + title},
    liveIconRow(h('header', {className:'live-ph', 'data-compact':compact ? '' : null},
      o.narrow ? null : sess?.pill || null,
      sess?.key ? h('span', {className:'key'}, sess.key) : null,
      n > 1 && !on
        ? h('button', {type:'button', className:'live-pt', 'data-live':'select', 'data-session':key, title, 'aria-label':'Select the pane of ' + label}, title)
        : sess && liveRen === key ? liveRenForm(key, title)
        : sess?.live ? h('button', {type:'button', className:'live-pt', 'data-live':'rename', 'data-session':key, 'data-key':'live-rename', title:'Click to rename', 'aria-label':'Rename ' + title}, title)
        : h('span', {className:'live-pt', title}, title),
      o.narrow || typeof liveViewSwitch !== 'function' ? null : liveViewSwitch(sess),
      // ORCH-1616 (owner's look stop: about 8 icons were too many): as in draft D, three buttons (pin, add beside,
      // close) and More for the rest: history, full screen, minimise, the place, Stop and End session, Open ticket
      h('span', {className:'live-ctl'},
        // History stays a word beside Chat and Terminal in a wide pane, as in draft D
        compact || typeof liveHistButton !== 'function' ? null : liveHistButton(sess, label),
        ...(sess ? liveEndHere(key, label, true) : []),
        leave,
        o.tight || o.crowded ? null : livePaneBtn('pin', (pinned ? 'Unpin ' : 'Pin ') + label, 'pinned', pinned ? 'Unpin' : 'Pin', {'data-session':key, 'aria-pressed':String(pinned), 'data-key':'live-pin'}),
        o.phone || o.crowded ? null : livePaneBtn('menu', besideWhy, 'plus', 'Add beside', {'data-menu':besideMenu, 'aria-expanded':String(s.menu === besideMenu), 'aria-haspopup':'true', 'data-key':'live-beside'}),
        livePaneBtn('close', o.total > 1 ? 'Close this pane' : 'Close (the bar stays)', 'x', 'Close', {'data-session':key, 'data-key':'live-close'}),
        livePaneBtn('menu', 'More for ' + label, 'more', 'More', {'data-menu':moreMenu, 'aria-expanded':String(s.menu === moreMenu), 'data-key':'live-pane-more'}),
        s.menu === placeMenu ? livePlaceMenu(where, true) : null,
        s.menu === besideMenu ? liveBesideMenu(key, label, o.others, besideNone) : null,
        s.menu === moreMenu ? liveMoreMenu(key, label, where, pinned, o.narrow, true, o.tight || o.crowded, o.crowded ? besideMenu : '') : null)), compact),
    sess?.running && (!sess.kind || sess.kind === 'empty') && typeof window.liveModelRow === 'function' ? window.liveModelRow(sess, s) : null,
    sess?.running && sess.kind && typeof window.livePermPaneRow === 'function' ? window.livePermPaneRow(sess, s) : null,
    group ? h('div', {className:'live-gwrap', 'data-key':'live-gwrap'}, liveFoldable(liveGroupSwitcher(group, key, o.narrow), o.narrow), liveShelfWrap(livePaneBody(key, sess, label), sess, label, n))
      : liveShelfWrap(livePaneBody(key, sess, label), sess, label, n));
}
// The group switcher of a wide pane gets its fold button (ORCH-1600); a narrow pane shows it as a strip on top.
function liveFoldable(sw, narrow) { if (!narrow && sw) sw.prepend(liveFoldBtn('left')); return sw; }
// The Results shelf of a ticket's pane (draft D, ORCH-1356): the ticket's results as the style guide's widgets, so an
// earlier result does not scroll away with the chat. widgets.css places it: a column beside the chat in full screen and
// in the bottom layer from 900 px wide, a one-row strip above the chat on the right and at phone width. A split pane
// leaves it out (draft D: no room), and so does a session without a ticket (it has no results).
const LIVE_SHELF_EMPTY = 'Nothing yet. Pictures, pages and tables show up here.';
function liveShelfOn(sess, n) {
  return !!(sess && !sess.kind && sess.id && n === 1 && !snapshot && typeof resultsHost === 'function' && typeof window === 'object' && window.UI?.result);
}
function liveShelfWrap(body, sess, label, n) {
  if (!liveShelfOn(sess, n)) return body;
  return h('div', {className:'live-pbw', 'data-key':'live-pbw'}, body,
    h('aside', {className:'live-shelf', 'aria-label':'Results', 'data-key':'live-shelf'},
      h('div', {className:'live-shelf-top'}, h('h2', {className:'live-shelf-h'}, 'Results'), liveFoldBtn('right')),
      resultsHost(sess.id, {key:'shelf-results-' + sess.id, cls:'live-shelf-list', empty:LIVE_SHELF_EMPTY, label:'Results of ' + label, own:true})));
}
// A repaint draws the panel anew; the shelf a pane already showed is put back as it was, so its widgets do not flash
// empty while they load again (the paint gives the keyboard back to a widget that had it).
function liveShelfKeep(old, host) {
  old.forEach(el => {
    if (!el.dataset.key) return;
    const fresh = host.querySelector(`[data-results-host][data-key="${el.dataset.key.replace(/["\\]/g, '')}"]`);
    if (fresh && fresh !== el) fresh.replaceWith(el);
  });
}
// A compact pane's header is one row of icon buttons beside the title (draft D, ORCH-1328): each button keeps its word
// for the screen reader and its tooltip; the row wraps under the title only where even the icons do not fit (a phone).
function liveIconRow(head, compact) {
  if (!compact) return head;
  for (const b of head.querySelectorAll('.live-ctl > .live-pbtn')) {
    b.classList.add('icon');
    b.querySelector('.live-word')?.classList.add('sr-only');
  }
  return head;
}
// The body of a pane: the History tab, the Start choice, or the session itself with its message box (ORCH-345).
function livePaneBody(key, sess, label) {
  if (sess?.running) liveWasRunning.add(sess.id);
  return typeof liveHistShown === 'function' && liveHistShown(sess) ? h('div', {className:'live-pb live-pb-hist'}, liveHistBody(sess))
      : sess && !sess.kind && !sess.running && typeof window.liveStartBody === 'function' ? h('div', {className:'live-pb live-pb-start'}, liveEndedNote(sess), window.liveStartBody(sess))
      : sess?.ended ? h('div', {className:'live-pb live-pb-start'}, liveEndedBody(sess, label))
      : sess ? h('div', {className:'live-pb', 'data-live-body':key, 'data-live-kind':sess.kind || null},
      h('p', {className:'live-now', 'data-live-now':''}),
      // tool, model, open time and Open ticket in one line at the top, as in draft D: the room above the message box
      // stays the chat's, so its newest message is whole (ORCH-1361)
      h('div', {className:'live-info'},
        h('p', {className:'meta live-meta', 'data-live-meta':''}),
        sess.kind ? null : h('a', {className:'btn ghost sm', href:'#ticket/' + encodeURIComponent(sess.id), 'data-key':'live-open-ticket', 'data-live-ticket':'', 'aria-label':'Open ticket ' + label}, 'Open ticket')),
      sess.kind ? null : h('div', {className:'live-ask', 'data-live-ask':'', role:'group', 'aria-label':'Question for you', hidden:true}),
      sess.kind === 'terminal' ? null : h('div', {className:'live-end-idle', 'data-live-idle':'', role:'status', hidden:true}),
      typeof liveChatBox === 'function' ? liveChatBox(sess, label) : null,
      // the helper's browser, small and live (ORCH-1494): under the conversation, its newest line
      !sess.kind && typeof browsePeekHost === 'function' ? browsePeekHost(sess.id, 'pane') : null,
      sess.kind ? null : h('p', {className:'meta', 'data-live-log-note':'', 'data-key':'live-log-note', hidden:true}),  // a one-step helper's log instead of its screen (ORCH-1797)
      h('pre', {className:'live-lines', 'data-live-lines':'', 'aria-label':'Last lines of ' + label, tabindex:'0', hidden:true}),
      typeof liveMsgBox === 'function' ? liveMsgBox(sess) : null)
      : h('div', {className:'live-pb'}, h('p', {}, 'This session is no longer in the list.'));
}
// ORCH-1664 (technical finding 4): a session that ends while its pane is open says so plainly above the Start choice,
// instead of the pane quietly turning into it. Only for a session this page saw working (a ticket opened without a
// helper shows the Start choice alone).
const liveWasRunning = new Set();
function liveEndedNote(sess) {
  if (!liveWasRunning.has(sess.id)) return null;
  return h('div', {className:'live-ended', role:'status', 'data-key':'live-ended-note'},
    h('h3', {}, 'This session ended.'),
    h('p', {className:'meta'}, 'Its messages and results stay on the ticket. Start a helper below to go on, or open History to read it again.'));
}
// An ended helper without a ticket (ORCH-817): Start again goes on with the same conversation (`session.new`), and
// History lists the earlier conversations with Reopen (pages/live-history.js, `orch run history` of its hidden ticket).
function liveEndedBody(sess, label) {
  return h('div', {className:'live-ended'},
    h('h3', {}, label + ' has ended'),
    h('p', {className:'meta'}, 'Its conversation is kept. Continue where it stopped, or reopen an earlier conversation.'),
    h('div', {className:'row'}, h('button', {type:'button', className:'btn outline sm', 'data-live-again':sess.kind, 'data-key':'live-start-again'}, 'Continue')),
    typeof liveHistBody === 'function' ? liveHistBody(sess) : null);
}
async function liveStartAgain(kind, b) {
  if (b) b.disabled = true;
  const r = await act('session.new', {kind}, {quiet:true});
  if (b) b.disabled = false;
  if (r.ok) window.orch?.toast?.('It goes on with the same conversation.', 'ok');
  else (window.liveFail || ((t, f) => window.orch?.toast?.(t || f, 'error')))(r.text, 'Could not start it again.', () => liveStartAgain(kind));
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('#live-dock [data-live-again]');
  if (!b || b.disabled) return;
  liveStartAgain(b.dataset.liveAgain, b);
});
// The waiting question of a ticket's pane: its words, one button per option and a field for an own answer, so it is
// answered where it is shown (ORCH-675). Written only when the question changes, so a typed answer stays.
const liveAskDrafts = new Map();
// With answer buttons the own answer is folded away behind "Write an answer", as draft D shows only the buttons
// (ORCH-1568): a short split pane keeps its buttons in sight. Opened once (or with typed words) it stays open.
const liveAskOpen = new Set();
// ORCH-1616: the screen question last answered per session, so its card does not come back before the helper moves on
const liveAskSaid = new Map();
// An answer waits LIVE_ASK_UNDO_MS with Undo on its toast before it is sent (as on Home, ORCH-1359); meanwhile the
// question is hidden in every pane. Leaving the page sends it at once, so it is not lost.
const LIVE_ASK_UNDO_MS = 5200, liveAskPending = new Map();  // ticket/question → send now
addEventListener('pagehide', () => { for (const now of [...liveAskPending.values()]) now(); });
function liveAskFill(box, id) {
  // a session that waits on a question its ticket does not carry here (yet) still shows the card, with the way to answer
  // it on the ticket (ORCH-1328: a split pane or the phone sheet showed only the bold words, nothing to press)
  // (a question the ticket answered already is not shown again while the sessions answer still names it)
  const live = window.LiveSessions?.get(id) || null, t = ticketOf(id), words = x => String(x || '').split(/\s+/).join(' ').trim();
  const asked = live?.status === 'needs-you' ? words(live.question) : '';
  if (liveAskSaid.has(id) && liveAskSaid.get(id) !== asked) liveAskSaid.delete(id);  // the helper moved on: a new ask shows again
  const known = asked && Array.isArray(t?.questions) && t.questions.some(x => x && words(x.text).slice(0, 300) === asked.slice(0, 300));  // orch sends the first 300 characters
  // ORCH-1616: one question card everywhere: a question the helper asks on its screen gets the same card, its own answer
  // goes straight to that helper (lone), never a lone "Answer on the ticket" button
  const lone = asked && !known ? {id:'', digest:'', text:asked, options:[], plain:true, lone:true} : null;
  // ORCH-1616 (owner's look stop): the suggested answer looks the same in every pane, split or not, and on the phone:
  // the design system's suggested look (as on Home); ORCH-1643: only the recommended one, and only with its reason
  // an answer still in its Undo window is not shown again (ORCH-1359)
  const found = snapshot ? null : liveAskModel(t) || (lone && liveAskSaid.get(id) !== lone.text ? lone : null), q = found && !liveAskPending.has(id + '/' + found.id) ? found : null;
  const sig = q ? [q.id, q.digest, q.text, q.options.join('|')].join('\u0001') : '';
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig; box.textContent = ''; box.hidden = !q;
  if (!q) return;
  const send = async answer => {
    const text = String(answer || '').trim(), slot = id + '/' + q.id; if (!text || box.dataset.busy || liveAskPending.has(slot)) return;
    // a disabled or removed button drops the keyboard to the page, where Esc no longer reaches the layer (ORCH-709):
    // it goes back into the pane (the next question or Open ticket)
    const had = box.contains(document.activeElement) && !!box.closest('#live-dock');  // on the Review page (ORCH-1643) the keyboard stays where it is
    let toast = null, over = false;
    const undone = await new Promise(done => {
      const timer = setTimeout(() => finish(false), LIVE_ASK_UNDO_MS);
      // once the window ends the answer goes out: a later Undo (the toast kept open by the keyboard or the mouse) does nothing
      const finish = back => { clearTimeout(timer); if (over) return; over = true; if (back) liveAskPending.delete(slot); done(back); };
      liveAskPending.set(slot, () => finish(false));
      liveLayerFill();
      if (had) { liveLayerWant = {id, until:Date.now() + 5000, ask:true}; liveLayerTake(); requestAnimationFrame(liveLayerTake); }
      toast = window.orch?.toast?.('Answered: ' + text, 'ok', () => { finish(true); liveLayerFill(); });
    });
    if (undone) return;
    for (const b of toast?.isConnected ? toast.querySelectorAll('button') : []) if (b.textContent === 'Undo') b.remove();
    const r = q.lone ? await act('run.send', {ticket:id, text}) : await act('answer', {ticket:id, question:q.id, digest:q.digest, answer:text});
    if (r.ok && q.lone && typeof liveChatNote === 'function') liveChatNote(id, text);  // it shows in the chat at once
    if (r.ok && q.lone) liveAskSaid.set(id, q.text);  // answered: not shown again while the sessions answer still names it
    liveAskPending.delete(slot);
    if (r.ok) liveAskDrafts.delete(slot);
    else (window.liveFail || ((t, f) => window.orch?.toast?.(t || f, 'error')))(r.text, 'Could not send your answer.', () => { if (q.lone || liveAskModel(ticketOf(id))?.id === q.id) send(text); }, 'Send again');  // the question and the typed words come back; Send again only while that question still waits
    liveLayerFill();
    // the answer redraws the pane: the keyboard goes back into it again unless the person moved it out meanwhile
    const now = document.activeElement;
    if (had && (!now || now === document.body || now.closest?.('#live-dock'))) { liveLayerWant = {id, until:Date.now() + 5000, ask:true}; liveLayerTake(); requestAnimationFrame(liveLayerTake); }
  };
  box.append(h('p', {className:'live-ask-q'}, q.text));
  const why = liveAskWhy(q);
  if (why) box.append(h('p', {className:'meta live-ask-why', 'data-key':'live-ask-why'}, why));
  const fill = on => 'btn outline sm' + (on ? ' suggested' : '');
  if (!q.plain) { box.append(h('a', {className:'btn outline sm', href:'#ticket/' + encodeURIComponent(id), 'data-key':'live-ask-open'}, 'Answer on the ticket')); return; }
  const row = h('div', {className:'live-ask-opts'});
  // at most one filled button per pane, as in draft D (ORCH-1357): the suggested choice when it has a reason (ORCH-1643);
  // the own answer's Send stays outlined (the message box's Send is always outlined)
  q.options.forEach((o, i) => { const b = h('button', {type:'button', className:fill(!!q.suggest && o === q.suggest), 'data-key':'live-ask-option-' + i}, o); b.addEventListener('click', () => send(o)); row.append(b); });
  const input = h('input', {type:'text', className:'input', 'data-key':'live-ask-text', placeholder:q.options.length ? 'Or write an answer' : 'Write an answer', 'aria-label':'Your answer', value:liveAskDrafts.get(id + '/' + q.id) || ''});
  input.addEventListener('input', () => liveAskDrafts.set(id + '/' + q.id, input.value));  // a redraw of the pane keeps it
  const go = h('button', {type:'button', className:'btn outline sm', 'data-key':'live-ask-send'}, 'Send');
  go.addEventListener('click', () => send(input.value)); input.addEventListener('keydown', e => { if (e.key === 'Enter') send(input.value); });
  const line = h('div', {className:'live-ask-line'}, input, go), slot = id + '/' + q.id;
  if (q.options.length && !liveAskOpen.has(slot) && !input.value) {
    line.hidden = true;
    const write = h('button', {type:'button', className:'btn ghost sm', 'data-key':'live-ask-write', 'aria-expanded':'false'}, 'Write an answer');
    write.addEventListener('click', () => { liveAskOpen.add(slot); line.hidden = false; write.remove(); input.focus(); });
    row.append(write);
  }
  if (q.options.length) box.append(row);
  box.append(line);
}
// The live part of a pane, written in place on every answer of the sessions API: no repaint, so the keyboard place,
// an open menu and the scroll of the lines stay.
function liveLayerFill() {
  for (const body of document.querySelectorAll('#live-dock [data-live-body]')) {
    const live = window.LiveSessions?.get(body.dataset.liveBody) || null;
    const now = body.querySelector('[data-live-now]'), pre = body.querySelector('[data-live-lines]'), meta = body.querySelector('[data-live-meta]');
    const kind = body.dataset.liveKind || '';  // a session without a ticket (ORCH-364)
    // a sign-in card's window in front (ORCH-865): the pane is titled Sign-in and needs no line about the terminal
    const text = kind === 'terminal' ? (live?.signin ? '' : 'A plain terminal in this workspace, no helper.')
      : !window.LiveSessions?.ready ? 'Loading…' : live ? liveNow(live) : kind ? 'This helper is not on right now.' : 'No helper is working on this ticket right now.';
    if (now.textContent !== text) now.textContent = text;
    // the line is the waiting question when the card has no answers to show: the chat keeps it in sight (ORCH-1361)
    now.toggleAttribute('data-live-q', live?.status === 'needs-you');
    const askBox = liveAskPlace(body);
    if (askBox) liveAskFill(askBox, body.dataset.liveBody);
    const idle = body.querySelector('[data-live-idle]');
    if (idle && typeof window.liveEndIdleFill === 'function') window.liveEndIdleFill(idle, body.dataset.liveBody);
    // the question card or the stuck line says it already (ORCH-687); a quiet helper shows only its pill (ORCH-2201)
    now.hidden = (!!askBox && !askBox.hidden) || (!!idle && !idle.hidden) || (live?.status === 'idle' && kind !== 'terminal');
    if (!text) now.hidden = true;  // a sign-in in front: no line about the terminal (ORCH-865)
    const lines = live && Array.isArray(live.lines) ? live.lines.join('\n') : '';
    if (pre.textContent !== lines) {
      const end = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 8;  // following the end: keep following it
      pre.textContent = lines;
      if (end) pre.scrollTop = pre.scrollHeight;
    }
    pre.hidden = !lines;
    if (typeof liveViewApply === 'function') liveViewApply(body);
    const m = live && kind !== 'terminal' ? liveMeta(live).join(' · ') : '';
    if (meta.textContent !== m) { meta.textContent = m; meta.title = m; }  // a split pane shortens it to one row (ORCH-1568)
    meta.hidden = !m;
    if (typeof liveTermApply === 'function') liveTermApply(body, live);  // the real screen (pages/liveterm.js)
  }
}
// ORCH-1600 (owner): in the Terminal view the waiting question sits at the top of the Results column on the right, so
// the terminal keeps its full height; with Results folded, a strip, or no Results at all it stays above the screen.
function liveAskPlace(body) {
  const pane = body.closest?.('.live-pane'), box = pane?.querySelector('[data-live-ask]') || body.querySelector('[data-live-ask]');
  if (!box) return null;
  const shelf = pane?.querySelector('.live-shelf'), id = body.dataset.liveBody;
  const side = !!shelf && !pane.hasAttribute('data-fold-right') && typeof liveViewOf === 'function' && liveViewOf(id) === 'term'
    && getComputedStyle(shelf).flexDirection === 'column';
  if (side && box.parentNode !== shelf) shelf.querySelector('.live-shelf-top')?.after(box);
  else if (!side && box.parentNode !== body) body.insertBefore(box, body.querySelector('[data-live-idle]') || body.querySelector('[data-live-chat]') || null);
  return box;
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
  return h('div', {className:'live-bar', role:'group', 'aria-label':name + ' bar', 'data-key':'live-bar', 'data-toast-clear':''},
    h('a', {className:'live-home', href:'#addon/' + encodeURIComponent(liveLayerPage()?.name || ''), title:name + ' start page'}, name),
    h('div', {className:'live-bar-sessions', 'data-key':'live-bar-sessions'}),
    liveBarEnd(where, s));
}
function liveLayerTree(s, where) {
  if (where === 'side') {
    const name = liveLayerName();
    return h('button', {type:'button', className:'live-edge', 'data-live':s.panes.length ? 'reopen' : 'place', 'data-mode':'bar', 'data-key':'live-edge', 'data-toast-clear':'', 'aria-label':'Open ' + name + ' again'}, liveIc('dock-side'), h('span', {}, name));
  }
  const bar = liveBarShared() ? null : liveBar(where, s);
  if (where === 'bar' || !s.panes.length) return bar;
  const dim = where === 'right' ? 'width' : 'height', px = s[dim], v = liveLayerView(s, where);
  const panel = h('div', {className:'live-panel', 'data-mode':where, 'data-n':String(v.shown.length), 'data-key':'live-panel', 'data-toast-clear':''},
    where === 'full' ? null : h('div', {className:'live-grip', role:'separator', tabindex:'0', 'data-live-grip':dim,
      'aria-orientation':dim === 'width' ? 'vertical' : 'horizontal', 'aria-label':dim === 'width' ? 'Width of the panel' : 'Height of the panel',
      ...liveGripValues(dim, px), title:'Drag or use the arrow keys to resize'}),
    v.shown.map(k => livePane(k, where, s, {...v, fresh:!!liveLayerWasPanes.length && !liveLayerWasPanes.includes(k)})));
  return fragment(panel, bar);
}
// A focusable separator must say its size (ARIA): smallest, largest and now, in px. Without a kept size the CSS default
// (45% of the height, 42% of the width up to 760 px) stands in until liveLayerPad writes the measured one.
function liveGripValues(dim, px) {
  const [lo, share] = LIVE_SIZE[dim], room = dim === 'width' ? window.innerWidth : window.innerHeight;
  const hi = Math.max(lo, Math.round(room * share)), def = dim === 'width' ? Math.min(room * 0.42, 760) : room * 0.45;
  const now = Math.round(Math.min(hi, Math.max(lo, px || def)));
  return {'aria-valuemin':String(lo), 'aria-valuemax':String(hi), 'aria-valuenow':String(now)};
}
// What the panel shows: on a phone only the selected session; whether the panes are narrow; what Add beside opens.
// ORCH-261 ship stop: the page behind has cards to answer (Review or Home with something waiting on the person), so
// the bottom panel keeps them in reach and quiet panes fold to the bar.
function liveLayerAnswering() {
  // THE needs-you number (pages/home.js): what Review's heading and Home's cards count
  const kind = typeof route === 'function' ? route().kind : '';
  return (kind === 'review' || kind === 'home') && typeof needsYouTotal === 'function' && needsYouTotal() > 0;
}
// The open ticket sessions with nothing in their chat yet: no finished step, no message, no question, not waiting on
// the person. Sessions without a ticket (plain terminal, Manager, chat helper) never count as quiet.
function liveLayerQuiet(panes) {
  if (typeof liveChatModel !== 'function' || typeof state !== 'object' || !state) return [];
  return array(panes).filter(k => {
    const t = array(state.tickets).find(x => x.id === k);
    if (!t || window.LiveSessions?.get(k)?.status === 'needs-you') return false;
    const sent = typeof liveChatSent === 'object' ? liveChatSent.get(k) : null;
    return liveChatModel(t, state.me || '', liveChatMine(state.runs?.[k], sent)).length === 0;
  });
}
function liveLayerView(s, where) {
  const phone = liveLayerPhone();
  const host = document.getElementById('live-dock');
  const room = where === 'right' ? Math.min(s.width || Math.min(window.innerWidth * 0.42, 760), liveLayerRightMax(document.documentElement.clientWidth, liveLayerSide())) : (host?.offsetWidth || window.innerWidth);
  const shown = liveLayerFit(s.panes, s.cur, where, room, phone, liveLayerAnswering() ? liveLayerQuiet(s.panes) : []);
  const others = liveLayerOthers(s.panes);
  return {shown, n:shown.length, total:s.panes.length, phone, narrow:liveLayerNarrow(where, shown.length, room, phone),
    compact:liveLayerCompact(where, shown.length, room, phone), tight:liveLayerTight(where, shown.length, room, phone), crowded:liveLayerCrowded(where, shown.length, room, phone), pins:liveLayerPins(), others, next:others[0] || ''};
}
// Paints the dock when something it shows changed; a state poll that changes nothing leaves it alone (no flicker, the
// keyboard place and any open menu stay).
function liveLayerPaint() {
  const host = liveDockHost(), s = liveLayerModel(), where = liveLayerWhere(s, liveLayerPhone());
  const shown = s.panes.map(liveLayerSession).map(x => x && [x.key, x.title, x.running, x.pill?.textContent || '', !!x.ended, x.live?.status || '', typeof liveEndModel === 'function' ? (m => [m.busy, m.hung])(liveEndModel(x.live)) : null, x.ended && typeof liveHistData === 'object' ? JSON.stringify(liveHistData.get(x.id)?.data || null) : '']);
  const v = s.panes.length && where !== 'bar' && where !== 'side' ? liveLayerView(s, where) : null;
  const key = JSON.stringify([where, s.menu, s.panes, s.cur, shown, liveRen, v && [v.shown, v.narrow, v.compact, v.tight, v.crowded, v.pins.filter(k => s.panes.includes(k)), v.others], liveLayerName(), liveLayerPage()?.name, typeof liveHistKey === 'function' ? liveHistKey() : null, typeof window.liveStartKey === 'function' ? window.liveStartKey() : null, typeof window.liveModelKey === 'function' ? window.liveModelKey(s.panes) : null, typeof window.livePermKey === 'function' ? window.livePermKey() : null, typeof liveGroupKey === 'function' ? liveGroupKey(s.panes) : null, typeof window.liveVoiceKey === 'function' ? window.liveVoiceKey() : null, typeof window.liveEndKey === 'function' ? window.liveEndKey() : null]);
  host.dataset.mode = where;
  const cap = where === 'bottom' && !s.height && !liveLayerPhone() ? liveLayerBottomCap(window.innerHeight, liveLayerAnswering()) : null;
  host.style.setProperty('--live-h', s.height ? s.height + 'px' : cap ? cap + 'px' : '');
  host.style.setProperty('--live-w', s.width ? Math.min(s.width, liveLayerRightMax(document.documentElement.clientWidth, liveLayerSide())) + 'px' : '');
  if (!s.height && !cap) host.style.removeProperty('--live-h');
  if (!s.width) host.style.removeProperty('--live-w');
  if (key !== liveLayerPainted) {
    // the panel animates only when it appears or moves, not on every repaint
    if (where === liveLayerWas) host.dataset.still = ''; else delete host.dataset.still;
    const shared = liveBarShared(), keepBar = shared ? document.getElementById('live-bar') : null;
    const typing = document.activeElement?.closest?.('#live-dock [data-live-msg-text]')?.dataset.liveMsgText;  // the message box keeps the keyboard
    const renaming = !!document.activeElement?.closest?.('#live-dock [data-live-ren]');
    // only real shelves: the leaving picture of a pane (motion.js) has no data-key and is never put back
    const shelves = [...host.querySelectorAll('.live-shelf [data-results-host][data-key]')];
    const shelfFocus = shelves.some(el => el.contains(document.activeElement)) ? document.activeElement : null;
    // motion (draft D): where each pane and the panel were, so they can move from there (pages/live-layer.js liveLayerMove)
    const was = liveLayerMotionBefore(host, where);
    host.replaceChildren(...[liveLayerTree(s, where)].filter(Boolean), ...(keepBar ? [keepBar] : []));
    liveShelfKeep(shelves, host);
    if (shelfFocus?.isConnected) shelfFocus.focus({preventScroll:true});  // a taken-out node loses the keyboard; give it back
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
    liveLayerMove(host, where, was);
    liveLayerPainted = key;
    liveLayerWas = where;
    // the panes in sight: one that comes into sight (a pane closed and one that did not fit takes its room) slides in
    liveLayerWasPanes = where === 'bar' || where === 'side' ? [] : [...(v?.shown || s.panes)];
  }
  // the room for the layer first (ORCH-1686): a part below that fails must not leave the page's last row and the
  // Review answers under the bar
  document.body.dataset.liveLayer = where;
  liveLayerInert(where === 'full');
  liveLayerPad();
  liveLayerFill();
  if (typeof resultsFillAll === 'function') resultsFillAll(host);  // the Results shelf of each pane
  window.liveStartMount?.();  // the Start choice of a pane with no helper (pages/live-start.js)
  if (typeof mountLiveBrowse === 'function') mountLiveBrowse();  // the helper's browser, small and live (ORCH-1494)
  // the parts above may change the layer's height
  liveLayerPad();
  liveLayerTake();
}
// The keyboard goes into a pane a ticket's button or address opened (ORCH-677). The pane is drawn again when its live
// data or Start choice arrives and that drops the keyboard to the page, so every paint puts it back until the person
// presses a key or clicks somewhere (or 5 seconds pass). After an answer in the pane (`ask`) it goes to the next
// question's first choice when there is one, else to Open ticket (ORCH-709).
// Motion of the layer (draft D, ORCH-1329), on the master motion helpers (kit/motion.js: orch.flip, orch.leave), so
// reduced motion keeps all of it still. The panel's own entry (up from the bottom, in from the right, full screen) is
// CSS (widgets.css .live-panel); here: a pane grows out of the wall tile it was opened from, panes that stay slide and
// resize to their new place when one is added or closed, and the panel leaves for --dur-exit when it closes to the bar.
function liveLayerMotionBefore(host, where) {
  const m = window.orch;
  if (!m?.flip || Date.now() - liveLayerActed > 1000) { liveLayerFrom = null; return null; }
  const panel = host.querySelector(':scope > .live-panel');
  const from = liveLayerFrom && Date.now() - liveLayerFrom.at < 1000 ? liveLayerFrom : null;
  liveLayerFrom = null;
  return {panel, rect:panel?.getBoundingClientRect() || null, panes:m.rects(host, ':scope > .live-panel > .live-pane', 'data-session'), from, where:liveLayerWas};
}
function liveLayerMove(host, where, was) {
  const m = window.orch;
  if (!was || !m?.flip) return;
  const open = where !== 'bar' && where !== 'side';
  if (!open) {
    // closed to the bar or the side: the old panel fades out where it was instead of vanishing
    if (was.panel && was.rect && was.where !== 'bar' && was.where !== 'side') {
      // ORCH-1662: the leaving picture loses its ids and keys. The message boxes are kept per session and come back
      // on the next opening: the picture gets copies of them, else every reopen added one more microphone
      if (typeof liveMsgBoxes === 'object') for (const kept of liveMsgBoxes.values()) if (was.panel.contains(kept.root)) kept.root.replaceWith(kept.root.cloneNode(true));
      m.leave(was.panel, was.rect, host);
    }
    return;
  }
  const panes = [...host.querySelectorAll(':scope > .live-panel > .live-pane')];
  const grown = was.from && panes.find(p => p.dataset.session === was.from.id && !was.panes.has(p.dataset.session));
  if (grown) {
    // zoom: the pane grows out of its tile; the panel does not slide in at the same time (one move at a time)
    delete grown.dataset.new;
    host.dataset.still = '';
    m.flip(grown, was.from.rect);
  }
  if (was.where !== where) return;  // the panel moved place: its own entry is the one move
  for (const p of panes) if (p !== grown && was.panes.has(p.dataset.session)) m.flip(p, was.panes.get(p.dataset.session));
}
function liveLayerFromTile(id) {
  const tile = document.querySelector('main [data-tile="' + String(id).replace(/["\\]/g, '') + '"]');
  const r = tile?.getBoundingClientRect();
  liveLayerFrom = r && r.width && r.height ? {id, rect:r, at:Date.now()} : null;
}
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
  for (const el of document.querySelectorAll('body > *, .shell > *, .shell-body > *')) {  // .shell > *: the side menu too (ORCH-1360)
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
  // ORCH-1616: beside the right panel a page under 900 px takes its narrow rules (top bar icons only, one column),
  // so its header and rows read normally instead of being squeezed
  const pageRoom = where === 'right' && panel ? document.documentElement.clientWidth - liveLayerSide() - panel.offsetWidth : Infinity;
  if (pageRoom < 900) document.body.dataset.liveNarrow = ''; else delete document.body.dataset.liveNarrow;
  // ORCH-1643: under 1100 px (the side split at 1920) a page with a rail beside its list stacks the rail above it
  if (pageRoom < 1100) document.body.dataset.liveStack = ''; else delete document.body.dataset.liveStack;
  // Tab scrolls the next link of the page clear of the layer, never under it (ORCH-1360).
  const root = document.documentElement.style;
  root.setProperty('scroll-padding-bottom', (pad + tb + (pad ? 12 : 0)) + 'px');  // the phone's tab bar sits under the layer; the grip sticks out 8 px above it
  root.setProperty('scroll-padding-right', where === 'right' && panel ? panel.offsetWidth + 'px' : '0px');
  const grip = panel?.querySelector('[data-live-grip]');
  if (grip) {
    const v = liveGripValues(grip.dataset.liveGrip, grip.dataset.liveGrip === 'width' ? panel.offsetWidth : panel.offsetHeight);
    for (const [k, x] of Object.entries(v)) if (grip.getAttribute(k) !== x) grip.setAttribute(k, x);
  }
  window.UI?.toastPlace?.();  // a toast already shown moves with the bar and the message box (ORCH-1359)
}
function liveLayerOff() {
  liveLayerInert(false);
  document.getElementById('live-dock')?.remove();
  delete document.body.dataset.liveLayer;
  document.body.style.removeProperty('--live-pad');
  document.body.style.removeProperty('--live-padr');
  delete document.body.dataset.liveNarrow;
  delete document.body.dataset.liveStack;
  document.documentElement.style.removeProperty('scroll-padding-bottom');
  document.documentElement.style.removeProperty('scroll-padding-right');
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
    liveLayerFromTile(id);
    liveLayerDo({type:'open', key:id});
    if (into) { liveLayerWant = {id, until:Date.now() + 5000}; liveLayerTake(); }
  },
  place(mode) { liveLayerDo({type:'place', mode}); },
  beside(key) { const id = liveLayerSession(key)?.id || key; liveLayerFromTile(id); liveLayerDo({type:liveLayerPhone() ? 'open' : 'beside', key:id}); },  // a wall tile's Add beside
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
  if (e.target.closest?.('#live-dock :is([data-live-ticket], [data-key="term-settings"])')) liveLayerDo({type:'to-ticket'});
  const b = e.target.closest?.('#live-dock [data-live]');
  if (!b) {
    if (liveLayer?.menu && !e.target.closest?.('#live-dock .live-pop')) liveLayerDo({type:'menu', menu:liveLayer.menu});
    return;
  }
  const act = b.dataset.live;
  if (act === 'menu') liveLayerDo({type:'menu', menu:b.dataset.menu}, b.dataset.key === 'live-more-beside'
    ? '.live-pop :is([data-live="beside-pick"], .live-opt, a)' : `[data-menu="${b.dataset.menu}"]`);  // Add beside from More (ORCH-1600): its trigger is gone, the keyboard goes into the choice
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
  else if (act === 'fold') {  // ORCH-1600: fold or open a side; the question card moves with the Results column
    const side = b.dataset.side === 'left' ? 'left' : 'right', host = document.getElementById('live-dock');
    liveFoldSet(side, !liveFold()[side]);
    liveFoldApply(host);
    liveLayerFill();
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
  const before = typeof sess?.live?.name === 'string' && sess.live.name.trim() ? sess.live.name.trim() : null;
  if (own === (before || '')) { liveRenEnd(key, false); return; }  // nothing changed: no toast
  const saved = window.LiveSessions?.rename(key, own);  // an empty name, or the title itself, goes back to the title
  liveRenEnd(key, true, before);
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
  if (e.key === 'Tab' && !e.defaultPrevented && !document.querySelector('dialog[open]') && liveLayerModel().mode === 'full') {
    liveLayerTabWrap(e);
    return;
  }
  if (e.key !== 'Escape' || e.defaultPrevented || document.querySelector('dialog[open]')) return;
  const inside = !!e.target.closest?.('#live-dock'), s = liveLayerModel();
  if (!inside && s.mode !== 'full' && !s.menu) return;
  const was = s.menu;
  liveLayerDo({type:'escape', inside}, was ? (liveBesideFromMore(was) ? `.live-pane[data-session="${was.slice(7).replace(/["\\]/g, '')}"] [data-key="live-pane-more"]` : `[data-menu="${was}"]`) : s.mode === 'full' ? LIVE_BACK_FROM_FULL : '[data-key="live-open"]');
});
// ORCH-1661: in full screen Tab and Shift+Tab go round inside the layer. The page behind is inert, but past the last
// button the browser handed the keyboard to the page's body (2 in 40 presses), out of the layer.
function liveLayerTabWrap(e) {
  const panel = document.querySelector('#live-dock .live-panel');
  if (!panel) return;
  const all = [...panel.querySelectorAll('a[href], button, input, select, textarea, [tabindex]')]
    .filter(el => !el.disabled && el.tabIndex >= 0 && !el.closest('[hidden], [inert]') && el.getClientRects().length);
  if (!all.length) return;
  const first = all[0], last = all[all.length - 1], at = document.activeElement;
  const out = !panel.contains(at);
  if (e.shiftKey && (out || at === first)) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && (out || at === last)) { e.preventDefault(); first.focus(); }
}
// Add beside opened from More (ORCH-1600, a crowded pane): the header has no Add beside button, so Esc goes back to More.
const liveBesideFromMore = menu => menu.startsWith('beside:') && !document.querySelector(`#live-dock [data-key="live-beside"][data-menu="${menu.replace(/["\\]/g, '')}"]`);
// The message box sticks to the bottom of a pane: Tab onto a message or result behind it scrolls the pane until it is
// clear (ORCH-1360); something taller than the room above the box keeps its top in view.
document.addEventListener('focusin', e => {
  const body = e.target.closest?.('#live-dock .live-pb[data-live-body]'), msg = body?.querySelector(':scope > .live-msg');
  if (!msg || msg.contains(e.target)) return;
  const r = e.target.getBoundingClientRect(), over = r.bottom - msg.getBoundingClientRect().top + 8, room = r.top - body.getBoundingClientRect().top;
  if (over > 8 && room > 0) body.scrollTop += Math.min(over, room);
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
    host.style.setProperty(dim === 'width' ? '--live-w' : '--live-h', (dim === 'width' ? Math.min(px, liveLayerRightMax(document.documentElement.clientWidth, liveLayerSide())) : px) + 'px');
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
  let frame = 0, phone = null, crowd = null;  // crowd: wide enough for the whole header (ORCH-1600)
  window.addEventListener('resize', () => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      if (!document.getElementById('live-dock')) return;
      const now = liveLayerPhone(), wide = window.innerWidth >= LIVE_CROWDED;
      if (now !== phone || wide !== crowd) { phone = now; crowd = wide; liveLayerPainted = ''; liveLayerPaint(); } else liveLayerPaint();  // unchanged: only the sizes (the bottom cap too) and the padding; the keyboard place and the open menu stay
    });
  });
}

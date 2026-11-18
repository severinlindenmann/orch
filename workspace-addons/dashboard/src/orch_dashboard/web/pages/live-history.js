'use strict';
// ORCH-363: the History tab of a session pane in the layer (pages/live-layer.js, draft D "Earlier sessions").
// orch keeps the last 10 sessions per ticket on this computer (`orch run history`, GET /api/sessions/<ticket>);
// Reopen starts the helper on that conversation (`session.reopen` = `orch run start <ticket> --session <id>`).
// The Start choice (continue or fresh start, pages/live-start.js) shows the same list under its choices.

// --- the model (plain data, tested in tests/live_history.test.js) ---
const LIVE_HIST_MAX = 10;
// Why the list can be empty: a helper that goes on with the same conversation (a daily run) keeps ONE session.
const LIVE_HIST_EMPTY = 'Nothing earlier to reopen. This helper goes on with the same conversation each time; a session is added here when it starts a fresh one. orch keeps the last ' + LIVE_HIST_MAX + '.';
const liveHistPlural = (n, one, many) => n + ' ' + (n === 1 ? one : many);
// One row as the list shows it: when, what it was about, a fact line; whether Reopen is offered.
function liveHistRow(r, now, when) {
  const at = r.last_used ? new Date(r.last_used) : null;
  const day = at && !isNaN(at) ? (when ? when(at, now) : at.toISOString().slice(0, 16).replace('T', ' ')) : 'Earlier';
  const facts = [r.turns ? liveHistPlural(r.turns, 'message', 'messages') : (r.reopenable || r.current ? 'No messages' : 'Not on this computer'), r.label].filter(Boolean);
  return {id:r.id, day, title:r.title || 'No first message', facts:facts.join(' · '), current:!!r.current, reopen:!!r.reopenable};
}
// The list: newest first, at most 10, and a plain line when there is nothing earlier yet.
function liveHistView(data, now, when) {
  if (!data) return {state:'loading', rows:[]};
  if (data.available === false) return {state:'error', rows:[]};
  const rows = (Array.isArray(data.sessions) ? data.sessions : []).slice(0, LIVE_HIST_MAX).map(r => liveHistRow(r, now, when));
  return {state:rows.some(r => !r.current) ? 'list' : 'empty', rows};
}

// --- the page ---
const liveHistOpen = new Set();  // panes whose History tab is open (this page only)
const liveHistData = new Map();  // ticket id -> {at, data}
const liveHistBusy = new Set();
function liveHistKey() { return [...liveHistOpen].map(k => [k, JSON.stringify(liveHistData.get(k)?.data || null), liveHistBusy.has(k)]); }
function liveHistRepaint(focus) {
  if (typeof liveLayerPaint !== 'function') return;
  liveLayerPaint();
  if (focus) document.querySelector('#live-dock ' + focus)?.focus({preventScroll:true});
}
function liveHistLoad(id) {
  const hit = liveHistData.get(id);
  if (hit && Date.now() - hit.at < 15000) return;
  liveHistData.set(id, {at:Date.now(), data:hit?.data || null});
  fetch('/api/sessions/' + encodeURIComponent(id)).then(r => r.ok ? r.json() : {available:false}).catch(() => ({available:false})).then(data => {
    liveHistData.set(id, {at:Date.now(), data});
    liveHistRepaint();  // the History tab, or the Start choice's list (the dock repaints only when what it shows changed)
  });
}
// The History button of a pane header (a toggle: the pane shows the list instead of the session).
function liveHistButton(sess, label) {
  if (!sess || sess.kind === 'terminal') return null; // a plain terminal has no helper, so no earlier sessions
  const on = liveHistOpen.has(sess.id);
  return h('button', {type:'button', className:'btn sm ghost', 'data-live-hist':'toggle', 'data-session':sess.id, 'data-key':'live-history',
    'aria-pressed':String(on), title:'Earlier sessions of ' + label}, 'History');
}
// The same toggle in the More menu of a narrow pane (draft D: History sits in More when the pane is narrow).
function liveHistMenuItem(key) {
  const sess = liveLayerSession(key);
  if (!sess || sess.kind === 'terminal') return null;
  const on = liveHistOpen.has(key);
  return h('button', {type:'button', className:'live-opt', 'data-live-hist':'toggle', 'data-session':key, 'data-key':'live-history-item', 'aria-pressed':String(on)},
    liveIc('clock'), h('span', {}, on ? 'Hide history' : 'History'));
}
function liveHistShown(sess) { return !!sess && liveHistOpen.has(sess.id); }
// The pane body while History is open: the earlier sessions with Reopen.
function liveHistBody(sess) {
  liveHistLoad(sess.id);
  const v = liveHistView(liveHistData.get(sess.id)?.data, new Date(), window.UI?.stamp ? (at, now) => window.UI.stamp(at.toISOString(), {now:now.toISOString()}) : null);
  const busy = liveHistBusy.has(sess.id), working = !!sess.running;
  const head = h('h3', {className:'live-hist-h', id:'live-hist-h-' + sess.id}, 'Earlier sessions');
  if (v.state === 'loading') return h('div', {className:'live-hist', 'aria-busy':'true'}, head, h('p', {className:'meta'}, 'Loading the earlier sessions…'));
  if (v.state === 'error') return h('div', {className:'live-hist'}, head, h('p', {className:'meta'}, 'The earlier sessions could not be loaded.'));
  if (v.state === 'empty') return h('div', {className:'live-hist'}, head,
    v.rows.length ? liveHistRows(sess, v, working, busy, 'live-hist-h-' + sess.id) : null,
    h('p', {className:'meta'}, LIVE_HIST_EMPTY));
  return h('div', {className:'live-hist'}, head,
    working ? h('p', {className:'meta'}, 'Stop the helper to reopen an earlier session.') : null,
    liveHistRows(sess, v, working, busy, 'live-hist-h-' + sess.id),
    h('p', {className:'meta'}, 'orch keeps the last ' + LIVE_HIST_MAX + ' sessions of this ticket on this computer.'));
}
function liveHistRows(sess, v, working, busy, labelledby) {
  return h('ul', {className:'live-hist-list', 'aria-labelledby':labelledby}, v.rows.map(r => h('li', {className:'live-hist-row', 'data-current':r.current ? '' : null},
    h('span', {className:'live-hist-day'}, r.day),
    h('span', {className:'live-hist-t', title:r.title}, r.title),
    h('span', {className:'meta live-hist-f'}, r.facts),
    r.current ? h('span', {className:'chip'}, 'In use')
      : r.reopen ? h('button', {type:'button', className:'btn outline sm', 'data-live-hist':'reopen', 'data-session':sess.id, 'data-id':r.id,
        disabled:working || busy, 'aria-label':'Reopen the session from ' + r.day}, 'Reopen')
      : null)));
}
// The earlier sessions under the Start choice (pages/live-start.js, ORCH-362): the same rows, Reopen included.
function liveHistList(sess, v, working, busy) {
  return h('div', {className:'live-hist', 'data-key':'live-start-earlier'},
    h('h4', {className:'live-hist-h', id:'live-start-h-' + sess.id}, 'Or reopen an earlier session'),
    liveHistRows(sess, v, working, busy, 'live-start-h-' + sess.id),
    h('p', {className:'meta'}, 'orch keeps the last ' + LIVE_HIST_MAX + ' sessions of this ticket on this computer.'));
}
document.addEventListener('click', async e => {
  const b = e.target.closest?.('#live-dock [data-live-hist]');
  if (!b) return;
  const id = b.dataset.session;
  if (b.dataset.liveHist === 'toggle') {
    if (liveHistOpen.has(id)) liveHistOpen.delete(id); else liveHistOpen.add(id);
    const menu = typeof liveLayerModel === 'function' ? liveLayerModel().menu : '';
    if (menu) liveLayerDo({type:'menu', menu});  // the More menu closes after its choice
    liveHistRepaint(`.live-pane[data-session="${id.replace(/["\\]/g, '')}"] :is([data-key="live-history"], [data-key="live-pane-more"])`);
    return;
  }
  if (b.dataset.liveHist !== 'reopen' || liveHistBusy.has(id)) return;
  liveHistBusy.add(id);
  liveHistRepaint();
  const r = await act('session.reopen', {ticket:id, session:b.dataset.id});
  liveHistBusy.delete(id);
  if (r.ok) {
    liveHistOpen.delete(id);
    liveHistData.delete(id);
    window.orch?.toast?.('The helper continues that conversation.', 'ok');
  } else window.orch?.toast?.(r.text || 'Could not reopen that session.', 'error');
  liveHistRepaint(`.live-pane[data-session="${id.replace(/["\\]/g, '')}"] :is([data-key="live-history"], [data-key="live-pane-more"])`);
});

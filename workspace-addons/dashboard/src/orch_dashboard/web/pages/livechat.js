'use strict';
// The chat view of a ticket's session in Focus (ORCH-687, draft D feature 5): the helper's messages and the ticket's
// events as one plain conversation, oldest first, with the waiting question answered right above the message box.
// No transcript exists: everything comes from the ticket the page already polls.
//   step events     a done step ("Step 2 done: <its words>") at the time of its newest evidence
//   helper messages the one-line summary of a done step, with its links (pull request, address); a question the
//                   helper asked; a Chat or group line an agent wrote (chat_message)
//   your messages   the answer to a question; a Chat line a person wrote; a message sent from this page
//   other events    the helper started, stopped or finished, and a person moved the ticket
// The open question is not a message: the pane shows it as its question card (live-layer.js liveAskFill).
// Each pane chooses Chat or Terminal (its last lines until the terminal comes); the choice is kept per browser.
const LIVE_CHAT_MAX = 60;       // rows kept, the newest
const LIVE_CHAT_TEXT = 600;     // characters of one message; a longer question reads in full on the ticket
const LIVE_VIEW_KEY = 'orch.live.view';

function liveChatTime(at) {
  const ms = Date.parse(at || '');
  return Number.isFinite(ms) ? ms : NaN;
}
function liveChatCut(text) {
  const s = String(text ?? '').replace(/\s+\n/g, '\n').trim();
  return s.length > LIVE_CHAT_TEXT ? s.slice(0, LIVE_CHAT_TEXT - 1).trimEnd() + '…' : s;
}
function liveChatWho(by) {
  const m = /^(?:human|agent):(.+)$/.exec(String(by || ''));
  return m ? m[1].charAt(0).toUpperCase() + m[1].slice(1) : '';
}
// The other events worth a line in a conversation, in plain words; every other history line stays on the ticket.
const LIVE_CHAT_STATUS = {review:'Review', done:'Done', active:'Working', todo:'To do', ready:'To do', blocked:'Blocked'};
function liveChatEvent(e) {
  const text = String(e.text || '').trim(), by = String(e.by || '');
  if (/^(?:[A-Z][a-z]+|The agent) started$/.test(text) || /^Automation started an agent run/i.test(text)) return 'The helper started';
  if (/finished the work and sent it to /i.test(text)) return 'The helper finished and sent it for review';
  if (/^The agent stopped before the work was finished/i.test(text)) return 'The helper stopped before the work was finished';
  if (/^Sent the helper on\b/i.test(text)) return 'The helper was sent on: it had stopped with open steps';
  const st = /^Status \S+ -> (\S+)$/.exec(text);
  if (st && /^human:/.test(by) && LIVE_CHAT_STATUS[st[1]]) return 'Moved to ' + LIVE_CHAT_STATUS[st[1]] + ' by ' + (liveChatWho(by) || 'a person');
  return '';
}
// The links of a step's evidence that open by themselves: a pull request or an address (files come with the results).
function liveChatLinks(evidence) {
  return evidence.filter(v => v && (v.type === 'pr' || v.type === 'url') && /^https?:\/\//.test(String(v.ref || '')))
    .map(v => {
      const ref = String(v.ref), pr = /\/pull\/(\d+)/.exec(ref);
      return {href:ref, label:clean0(v.title) || (v.type === 'pr' ? (pr ? 'Pull request ' + pr[1] : 'Pull request') : ref.replace(/^https?:\/\//, '').slice(0, 60))};
    });
}
function clean0(s) { return typeof s === 'string' ? s.trim() : ''; }
// rows: {w: 'e' | 'h' | 'y', text, at, who?, links?}; me: the person looking ("human:<name>"), whose lines say You.
function liveChatModel(t, me = '', sent = []) {
  if (!t || typeof t !== 'object') return [];
  const rows = [], mine = by => !!by && by === me;
  const steps = Array.isArray(t.checklist) ? t.checklist.filter(c => c && typeof c === 'object') : [];
  steps.forEach((c, i) => {
    if (c.done !== true) return;
    const ev = Array.isArray(c.evidence) ? c.evidence.filter(v => v && typeof v === 'object') : [];
    const at = ev.map(v => v.at).filter(a => Number.isFinite(liveChatTime(a))).sort().pop() || c.done_at || '';
    if (!Number.isFinite(liveChatTime(at))) return;
    rows.push({w:'e', text:'Step ' + (i + 1) + ' done: ' + liveChatCut(c.text), at});
    const said = ev.find(v => clean0(v.summary));
    const links = liveChatLinks(ev);
    // a file the step proved or a check run is a result too: it shows as a widget inside the message (ORCH-687, ORCH-697)
    const made = ev.some(v => (v.type === 'file' && /^\.orch\/tickets\/[^/]+\/(evidence|artifacts)\//.test(String(v.ref || ''))) || (v.type === 'command' && (typeof v.exit === 'number' || v.output_tail)));
    if (said || links.length || made) rows.push({w:'h', text:said ? liveChatCut(said.summary) : '', at, links, step:typeof c.id === 'string' ? c.id : ''});
  });
  for (const q of Array.isArray(t.questions) ? t.questions : []) {
    if (!q || typeof q !== 'object' || q.answer == null) continue;  // the open one is the question card
    if (Number.isFinite(liveChatTime(q.asked_at))) rows.push({w:'h', text:liveChatCut(q.text), at:q.asked_at, question:true});
    const at = q.answered_at || q.at;
    if (!Number.isFinite(liveChatTime(at))) continue;
    const who = String(q.answered_by || '');
    rows.push(/^human:/.test(who)
      ? {w:'y', text:liveChatCut(q.answer), at, who:mine(who) ? '' : liveChatWho(who)}
      : {w:'e', text:'Answered for you: ' + liveChatCut(q.answer), at});
  }
  for (const e of Array.isArray(t.history) ? t.history : []) {
    if (!e || typeof e !== 'object' || !Number.isFinite(liveChatTime(e.at))) continue;
    const by = String(e.by || '');
    if (e.chat_message === true && clean0(e.text)) {
      rows.push(/^human:/.test(by) ? {w:'y', text:liveChatCut(e.text), at:e.at, who:mine(by) ? '' : liveChatWho(by)} : {w:'h', text:liveChatCut(e.text), at:e.at});
      continue;
    }
    const line = liveChatEvent(e);
    if (line) rows.push({w:'e', text:line, at:e.at});
  }
  for (const m of Array.isArray(sent) ? sent : []) if (m && clean0(m.text) && Number.isFinite(liveChatTime(m.at))) rows.push({w:'y', text:liveChatCut(m.text), at:m.at, sent:true});
  // oldest first; at the same moment the step goes before what the helper said about it (the order pushed)
  return rows.map((r, n) => [r, n]).sort((a, b) => (liveChatTime(a[0].at) - liveChatTime(b[0].at)) || (a[1] - b[1]))
    .map(x => x[0]).slice(-LIVE_CHAT_MAX);
}
// Chat or Terminal per session, kept per browser: {<session id>: 'term'}; chat is the default and is not stored.
function liveViewRead(store) {
  try {
    const v = JSON.parse(store?.getItem(LIVE_VIEW_KEY) || '{}');
    return v && typeof v === 'object' && !Array.isArray(v) ? Object.fromEntries(Object.entries(v).filter(([k, x]) => k && x === 'term').slice(-50)) : {};
  } catch { return {}; }
}
function liveViewWrite(store, views) {
  try { store?.setItem(LIVE_VIEW_KEY, JSON.stringify(views)); } catch { /* private window: the choice lasts this page */ }
}
// --- the page ---
let liveViews = null;
const liveChatSent = new Map();  // messages sent from this page, per session, until the page reloads
function liveViewsNow() {
  if (!liveViews) liveViews = liveViewRead(typeof liveLayerStore === 'function' ? liveLayerStore() : null);
  return liveViews;
}
function liveViewOf(id) { return liveViewsNow()[id] === 'term' ? 'term' : 'chat'; }
function liveViewSet(id, view) {
  const v = {...liveViewsNow()};
  if (view === 'term') v[id] = 'term'; else delete v[id];
  liveViews = v;
  liveViewWrite(typeof liveLayerStore === 'function' ? liveLayerStore() : null, v);
}
function liveChatNote(id, text) {
  const list = liveChatSent.get(id) || [];
  list.push({text, at:new Date().toISOString()});
  liveChatSent.set(id, list.slice(-20));
}
// Chat | Terminal in a ticket pane's header (draft D's segmented switch)
function liveViewSwitch(sess) {
  if (!sess || sess.kind) return null;
  const view = liveViewOf(sess.id), b = (v, word) => h('button', {type:'button', className:'btn sm', 'data-live-view':v, 'data-session':sess.id,
    'data-key':'live-view-' + v, 'aria-pressed':String(view === v)}, word);
  return h('span', {className:'segmented live-view', role:'group', 'aria-label':'View'}, b('chat', 'Chat'), b('term', 'Terminal'));
}
// The log the fill writes into; empty until the first fill
function liveChatBox(sess, label) {
  if (!sess || sess.kind) return null;
  return h('div', {className:'live-chat', 'data-live-chat':sess.id, role:'log', 'aria-label':'Messages and ticket events of ' + label, tabindex:'0',
    hidden:liveViewOf(sess.id) !== 'chat'});
}
function liveChatRow(r, tid = '') {
  const stamp = typeof time === 'function' ? time(r.at) : '';
  if (r.w === 'e') return h('p', {className:'live-ev meta'}, h('span', {'aria-hidden':'true'}, '✓'), ' ' + r.text + (stamp ? ' · ' + stamp : ''));
  // the step's results as small widgets (pages/results-feed.js); plain links only where no widget can be drawn
  const widgets = !!(r.step && tid && typeof resultsHost === 'function' && typeof window === 'object' && window.UI?.result);
  const links = widgets ? [] : (r.links || []).map(l => h('a', {className:'live-link', href:l.href, target:'_blank', rel:'noopener'}, l.label));
  return h('div', {className:'live-chat-msg', 'data-w':r.w},
    h('span', {className:'meta'}, (r.w === 'y' ? r.who || 'You' : 'Helper') + (stamp ? ' · ' + stamp : '')),
    r.text ? h('p', {}, r.text) : null,
    links.length ? h('div', {className:'live-links'}, links) : null,
    widgets ? resultsHost(tid, {key:'chat-results-' + tid + '-' + r.step, step:r.step, cls:'live-results', label:'Results of this step'}) : null);
}
// Written only when the rows change, so the scroll and a selection stay; follows the end while it is at the end.
function liveChatFill(box) {
  const id = box.dataset.liveChat, t = typeof ticketOf === 'function' ? ticketOf(id) : null;
  const rows = liveChatModel(t, typeof state === 'object' && state ? state.me || '' : '', liveChatSent.get(id));
  const sigs = rows.map(r => [r.w, r.at, r.text, (r.links || []).map(l => l.href).join(' '), r.step || ''].join('\u0001'));
  const was = box.liveChatSigs, sig = sigs.join('\u0002');
  if (was && was.join('\u0002') === sig && box.dataset.sig) return;
  const end = !box.dataset.sig || box.scrollHeight - box.scrollTop - box.clientHeight < 8;
  box.dataset.sig = '1';
  box.liveChatSigs = sigs;
  // new rows at the end only: they are added, so a focused link or a selection in the older rows stays
  if (was && was.length && sigs.length > was.length && was.every((x, i) => x === sigs[i])) for (const r of rows.slice(was.length)) box.append(liveChatRow(r, id));
  else {
    box.textContent = '';
    if (!rows.length) box.append(h('p', {className:'meta live-chat-empty'}, 'No messages yet. Steps the helper finishes and its questions show here.'));
    else for (const r of rows) box.append(liveChatRow(r, id));
  }
  if (typeof resultsFillAll === 'function') resultsFillAll(box);
  if (end) box.scrollTop = box.scrollHeight;
}
// Shows the chosen view in a pane's body: the chat, or the last lines (the terminal's place until it comes).
function liveViewApply(body) {
  const box = body.querySelector('[data-live-chat]');
  if (!box) return;
  const term = liveViewOf(box.dataset.liveChat) === 'term', pre = body.querySelector('[data-live-lines]');
  box.hidden = term;
  body.dataset.liveView = term ? 'term' : 'chat';
  if (pre && !term) pre.hidden = true;
  if (!term) liveChatFill(box);
}
if (typeof window === 'object' && typeof document === 'object' && !(typeof module === 'object' && module.exports)) {
  document.addEventListener('click', e => {
    const b = e.target.closest?.('#live-dock [data-live-view]');
    if (!b) return;
    const id = b.dataset.session, view = b.dataset.liveView === 'term' ? 'term' : 'chat';
    liveViewSet(id, view);
    const pane = b.closest('.live-pane');
    pane?.querySelectorAll('[data-live-view]').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.liveView === view)));
    if (typeof liveLayerFill === 'function') liveLayerFill();  // shows the view in place: no repaint, the keyboard stays
  });
}

'use strict';
// Groups on the new live page (ORCH-345, draft A on draft D, ORCH-344): an epic or a run order whose helpers work
// on its sub-tickets. The live sessions API sends them (sessions.py `groups`: the top ticket of a parent chain, its
// open sub-tickets in tree order, the small helpers each helper started inside its session).
//   Wall: the group is ONE tile in its band ("5 helpers · 2 small helpers · 1 needs you") with a small tree; one helper
//         that needs you turns the whole tile orange. The filter finds a group by any of its helpers.
//   Bar:  the group is one chip; its number is the same helper count as the tile says.
//   Pane: a session of a group shows the group as a switcher beside it (a strip on top when the pane is narrow or on a
//         phone): main helper, its tickets, small helpers (watch only), earlier sessions. A click swaps the session in
//         that pane. The message box names who receives the message.
// Words: "Main helper" and "Small helper" (owner, 17 Nov); "In line", "Step n of m" as draft D says them.
const LIVE_GROUP_RANK = {'needs-you':0, working:1, idle:2, 'in-line':3, closed:4};
const LIVE_GROUP_LIVE = ['needs-you', 'working', 'idle'];
const LIVE_GROUP_PREVIEW = 5;  // tree rows on a wall tile
const LIVE_MSG_MAX = 2000;  // run.send's limit (actions.MAX_TEXT)

// --- the model: plain data, no page (tested in tests/live_groups.test.js) ---
const liveGroupList = groups => (Array.isArray(groups) ? groups : []).filter(g => g && typeof g.id === 'string' && Array.isArray(g.members) && g.members.length);
// The group a session belongs to (as the main helper or a helper of one of its tickets), or null.
function liveGroupOf(groups, id) {
  return liveGroupList(groups).find(g => g.members.some(m => m && m.id === id)) || null;
}
// The status of the whole group: the most urgent of its members.
function liveGroupStatus(g) {
  let best = 'closed';
  for (const m of g?.members || []) if (m && LIVE_GROUP_RANK[m.status] != null && LIVE_GROUP_RANK[m.status] < LIVE_GROUP_RANK[best]) best = m.status;
  return best;
}
// Counts: helpers = members with a live session (main helper included); small = small helpers inside them.
function liveGroupCounts(g) {
  const ms = (g?.members || []).filter(Boolean);
  return {
    helpers:ms.filter(m => LIVE_GROUP_LIVE.includes(m.status)).length,
    small:ms.reduce((n, m) => n + (Array.isArray(m.small) ? m.small.length : 0), 0),
    need:ms.filter(m => m.status === 'needs-you').length,
    line:ms.filter(m => m.status === 'in-line').length,
  };
}
const livePlural = (n, one, many) => n + ' ' + (n === 1 ? one : many);
// "5 helpers · 2 small helpers · 1 needs you" (the tile, the chip's title and the switcher's head say the same)
function liveGroupLine(g) {
  const c = liveGroupCounts(g);
  return [livePlural(c.helpers, 'helper', 'helpers'), c.small ? livePlural(c.small, 'small helper', 'small helpers') : '',
    c.line ? c.line + ' in line' : '', c.need ? c.need + (c.need === 1 ? ' needs you' : ' need you') : ''].filter(Boolean).join(' · ');
}
// What a click on the group opens: the helper that needs you, else the main helper's session, else the first live one.
function liveGroupFocus(g) {
  const ms = (g?.members || []).filter(Boolean);
  const pick = ms.find(m => m.status === 'needs-you') || ms.find(m => m.main && m.status !== 'closed')
    || ms.find(m => LIVE_GROUP_LIVE.includes(m.status)) || ms.find(m => m.status !== 'closed') || ms[0];
  return pick ? pick.id : '';
}
// Does the filter text find this group? By the group's key or title, or any helper's key, title, word or small helper.
function liveGroupMatch(g, f) {
  const q = String(f || '').trim().toLowerCase();
  if (!q) return true;
  const words = [g.key, g.title];
  for (const m of g.members || []) if (m) words.push(m.key, m.title, m.word, ...(Array.isArray(m.small) ? m.small.map(x => x && x.what) : []));
  return words.filter(Boolean).join(' ').toLowerCase().includes(q);
}
// The sessions with every group folded into ONE entry where its first member stood (the API's order: the most urgent
// first). The entry is a session-like row the wall and the bar draw as the group: id = the top ticket (a pin of the
// group is the pin of its main helper), opens = what a click opens, group = the group.
function liveGroupFold(sessions, groups) {
  // ORCH-1358: a member whose session is idle or closed but asks (`needs`) counts as needs you in the group too, as the
  // flat list does in the bar and on the wall
  const asks = new Set((Array.isArray(sessions) ? sessions : []).filter(s => s && s.needs === true && (s.status === 'idle' || s.status === 'closed')).map(s => s.id));
  const gs = liveGroupList(groups).map(g => g.members.some(m => m && asks.has(m.id))
    ? {...g, members:g.members.map(m => m && asks.has(m.id) ? {...m, status:'needs-you', word:'Needs you'} : m)} : g), of = new Map();
  for (const g of gs) for (const m of g.members) if (m && !of.has(m.id)) of.set(m.id, g);
  const out = [], placed = new Set();
  for (const s of Array.isArray(sessions) ? sessions : []) {
    if (!s || typeof s.id !== 'string') continue;
    const g = of.get(s.id);
    if (!g) { out.push(s); continue; }
    if (placed.has(g.id)) continue;
    placed.add(g.id);
    const status = liveGroupStatus(g), main = g.members.find(m => m.main) || g.members[0];
    const need = g.members.find(m => m.status === 'needs-you');
    out.push({id:g.id, key:g.key || '', title:g.title || '', status, kind:'',
      word:{'needs-you':'Needs you', working:'Working', idle:'Idle', 'in-line':'In line', closed:'No session'}[status],
      question:need ? 'Needs you: ' + (need.key ? need.key + ' ' : '') + need.title : null,
      detail:liveGroupLine(g), lines:[], waiting_on:[], opens:liveGroupFocus(g), group:g, main:main.id});
  }
  return out;
}
// The rows of the switcher: every member (depth for the indent), its small helpers under it, then the earlier
// sessions of the session shown. cur = the session shown in the pane.
function liveGroupRows(g, cur) {
  const rows = [];
  for (const m of (g?.members || []).filter(Boolean)) {
    rows.push({type:'helper', id:m.id, key:m.key || '', title:m.title || '', depth:Math.max(0, Math.min(4, m.depth | 0)), main:!!m.main,
      status:m.status, word:m.status === 'needs-you' ? 'Needs you' : m.status === 'in-line' ? 'In line' : m.word || '', cur:m.id === cur});
    for (const x of Array.isArray(m.small) ? m.small : []) {
      if (x && x.what) rows.push({type:'small', of:m.id, ofTitle:m.title || m.key || '', title:x.what, seconds:Number.isFinite(x.seconds) ? x.seconds : null,
        depth:Math.max(0, Math.min(4, m.depth | 0)) + 1});
    }
  }
  return rows;
}
// The line above the message box: who receives it. Inside a group the main helper is named for a sub-ticket's helper.
function liveMsgTo(sess, g) {
  if (!sess) return '';
  const who = (sess.title || sess.key || 'this session') + (sess.key && sess.title ? ' (' + sess.key + ')' : '');
  if (!g) return 'Message to: ' + who + '.';
  const m = g.members.find(x => x && x.id === sess.id);
  return 'Message to: ' + who + (m?.main ? ', the main helper.' : '. Only this helper gets it.');
}

if (typeof module === 'object' && module.exports) {
  module.exports = {liveGroupOf, liveGroupStatus, liveGroupCounts, liveGroupLine, liveGroupFocus, liveGroupMatch, liveGroupFold, liveGroupRows, liveMsgTo, LIVE_GROUP_PREVIEW, LIVE_MSG_MAX};
}

// --- the page ---
const LIVE_GROUP_SYM = {'needs-you':'◆', working:'●', 'in-line':'◷', idle:'◐', closed:'○'};
function liveGroups() { return (typeof window === 'object' && window.LiveSessions?.groups) || []; }
// The small tree on a wall tile: the first rows, then "and n more".
function liveGroupPreview(g) {
  const rows = liveGroupRows(g, '').filter(r => r.type === 'helper'), more = rows.length - LIVE_GROUP_PREVIEW;
  return h('span', {className:'gtree', 'data-mode':'preview', 'aria-hidden':'true'},
    rows.slice(0, LIVE_GROUP_PREVIEW).map(r => h('span', {className:'gtree-row', 'data-s':r.status, 'data-depth':String(Math.min(r.depth, 2))},
      h('span', {className:'gtree-sym'}, LIVE_GROUP_SYM[r.status] || ''), h('span', {className:'gtree-t'}, r.title), h('span', {className:'gtree-w'}, r.word))),
    more > 0 ? h('span', {className:'gtree-row meta'}, 'and ' + more + ' more') : null);
}
// The switcher beside a pane: the group's tree; a click on a helper swaps the session in this pane.
function liveGroupSwitcher(g, key, narrow) {
  const rows = liveGroupRows(g, key), id = 'gsw-' + key;
  return h('nav', {className:'gtree', 'data-mode':narrow ? 'strip' : 'tree', 'aria-labelledby':id, 'data-key':'live-group'},
    h('p', {className:'gtree-h', id},
      h('span', {className:'gtree-gt'}, g.title || g.key), h('span', {className:'meta'}, liveGroupLine(g))),
    h('ul', {className:'gtree-list', role:'list'}, rows.map(r => r.type === 'helper'
      ? h('li', {'data-depth':String(r.depth)},
        h('button', {type:'button', className:'gtree-row', 'data-s':r.status, 'data-live':'swap', 'data-session':key, 'data-to':r.id,
          'aria-current':r.cur ? 'true' : null, 'data-key':'live-group-' + r.id,
          'aria-label':(r.main ? 'Main helper: ' : '') + r.title + (r.key ? ' (' + r.key + ')' : '') + ', ' + (r.word || '')},
          h('span', {className:'gtree-sym', 'aria-hidden':'true'}, LIVE_GROUP_SYM[r.status] || ''),
          h('span', {className:'gtree-b'}, h('span', {className:'gtree-t', title:r.title}, r.title),
            h('span', {className:'gtree-m'}, r.main ? h('span', {className:'chip gtree-tag'}, 'Main helper') : null, h('span', {className:'gtree-w'}, r.word)))))
      : h('li', {'data-depth':String(r.depth), 'data-small':''},
        h('button', {type:'button', className:'gtree-row', 'data-s':'small', 'data-live':'swap', 'data-session':key, 'data-to':r.of,
          'data-key':'live-group-small-' + r.of + '-' + r.title,
          'aria-label':'Small helper ' + r.title + ' of ' + r.ofTitle + ', watch only. Go to its helper'},
          h('span', {className:'gtree-sym', 'aria-hidden':'true'}, '·'),
          h('span', {className:'gtree-b'}, h('span', {className:'gtree-t', title:r.title}, r.title),
            h('span', {className:'gtree-m'}, h('span', {className:'chip gtree-tag', 'data-small':''}, 'Small helper'),
              h('span', {className:'gtree-w'}, 'watch only' + (r.seconds != null && typeof liveDur === 'function' ? ' · ' + liveDur(r.seconds) : ''))))))),
      typeof liveHistButton === 'function' && liveLayerSession(key) && !liveLayerSession(key).kind
        ? h('li', {'data-depth':'0'}, h('button', {type:'button', className:'gtree-row', 'data-s':'earlier', 'data-live-hist':'toggle', 'data-session':key,
          'aria-pressed':String(typeof liveHistShown === 'function' && liveHistShown(liveLayerSession(key))), 'data-key':'live-group-earlier'},
          h('span', {className:'gtree-sym', 'aria-hidden':'true'}, '↺'),
          h('span', {className:'gtree-b'}, h('span', {className:'gtree-t'}, 'Earlier sessions'),
            h('span', {className:'gtree-m'}, h('span', {className:'gtree-w'}, 'of ' + (liveLayerSession(key).key || liveLayerSession(key).title)))))) : null));
}
// What the dock's repaint key needs of the groups in its panes: the rows the switchers show.
function liveGroupKey(panes) {
  return (panes || []).map(k => { const g = liveGroupOf(liveGroups(), k); return g ? [k, g.id, liveGroupRows(g, k).map(r => [r.id || r.of, r.status, r.word, r.title])] : null; });
}
// The message box of a pane with a working helper (draft D feature 13, ORCH-695): who receives it, then the one shared
// composer (kit/composer.js, layout 'row'): previews of the added files and screenshots above one line of clip, words
// and Send. Files are added by the clip, by pasting into the box or by dropping them anywhere on the pane; each shows
// as a picture thumbnail or a file chip that can be removed before Send. Send goes the ticket page's one way
// (ticketTalkSend: ticket.attach for the files, then run.send naming them), so there is no second upload path.
// The composer itself is kept per session, so what is typed and added stays across repaints of the dock.
// With the relay on, a microphone puts spoken words into the box (pages/livevoice.js, ORCH-696): the strip while
// listening above the composer, the microphone in its line before Send, the line after the words under it.
const liveMsgDraft = new Map();
const liveMsgBoxes = new Map();  // session id -> {root, composer}
const LIVE_MSG_HINT = 'Paste a screenshot or drop files here · up to 10 files, 25 MB each';
function liveMsgComposer(sess) {
  const was = liveMsgBoxes.get(sess.id);
  if (was) return was;
  const root = h('div', {id:'live-msg-' + sess.id.replace(/[^A-Za-z0-9_-]/g, '_'), 'data-key':'live-msg-box'});
  const box = typeof FEEDBACK_BOX === 'object' ? FEEDBACK_BOX : {};
  const who = () => { const s = liveLayerSession(sess.id); return s?.key || s?.title || 'the helper'; };
  const composer = window.UI.composer(root, {...box, voice:false, layout:'row', interrupt:false, enterSends:true,
    label:'Message to ' + (sess.key || sess.title || 'the helper'), placeholder:'Message the helper', attachLabel:'Add files',
    sendStyle:'outline',  // a pane keeps one filled button: a question's first choice, the page's own (draft D, ORCH-1357)
    maxLength:typeof TALK_TYPED_MAX === 'number' ? TALK_TYPED_MAX : LIVE_MSG_MAX, hint:LIVE_MSG_HINT, sendLabel:'Send',
    emptyError:'Write something or add a file.', dropLabel:'Drop to add to ' + (sess.key || sess.title || 'this ticket'), sendingText:'Sending…',
    draft:liveMsgDraft.get(sess.id) || '', onDraft:v => { if (v) liveMsgDraft.set(sess.id, v); else liveMsgDraft.delete(sess.id); },
    fieldAttrs:{'data-live-msg-text':sess.id}, sendAttrs:{'data-key':'live-msg-send'},
    onSend:async message => {
      // a session without a ticket (ORCH-817) takes words only: files are kept on a ticket
      if (sess.kind && (message.files || []).length) return {ok:false, text:'Files go only to a ticket\'s helper. Remove them and send the words.'};
      const r = sess.kind ? await act('run.send', {ticket:sess.id, text:String(message.text || '').trim()}) : await ticketTalkSend(sess.id, message);
      if (!r.ok) return r;
      if (typeof liveChatNote === 'function') { liveChatNote(sess.id, r.said || message.text); if (typeof liveLayerFill === 'function') liveLayerFill(); }  // shows in the chat at once
      window.orch?.toast?.('Sent to ' + who() + '.', 'ok');
      return {ok:true, text:''};
    }});
  const kept = {root, composer};
  liveMsgBoxes.set(sess.id, kept);
  return kept;
}
function liveMsgBox(sess) {
  // a helper without a ticket (Manager, empty or chat helper) gets one too (ORCH-817); a plain terminal has no helper
  if (!sess || sess.kind === 'terminal' || !sess.running || snapshot || !window.UI?.composer) return null;
  const g = liveGroupOf(liveGroups(), sess.id), {root} = liveMsgComposer(sess);
  const voice = what => typeof window[what] === 'function' ? window[what](sess) : null;
  // the composer is kept per session, so its line gets the microphone of this paint (or none) each time
  const line = root.querySelector('.composer-line'), mic = voice('liveVoiceMic');
  line?.querySelector('[data-key="live-voice"]')?.remove();
  if (line && mic) line.insertBefore(mic, line.querySelector('[data-key="live-msg-send"]'));
  return h('div', {className:'live-msg', 'data-live-msg':sess.id, 'data-key':'live-msg', 'data-toast-clear':''},
    h('label', {className:'live-to', for:root.id + '-message', 'data-key':'live-msg-to'}, liveMsgTo(sess, g)),
    voice('liveVoiceStrip'), root, voice('liveVoiceHint'));
}
if (typeof window === 'object' && typeof document === 'object' && !(typeof module === 'object' && module.exports)) {
  // Files dropped anywhere on a pane with a message box go into its box (the box itself takes its own drops).
  const paneOf = e => [...(e.dataTransfer?.types || [])].includes('Files') ? e.target.closest?.('#live-dock .live-pane') : null;
  const boxOf = pane => pane && liveMsgBoxes.get(pane.querySelector('[data-live-msg]')?.dataset.liveMsg || '');
  let over = null;
  const mark = pane => { if (over && over !== pane) delete over.dataset.drop; over = pane; if (pane) pane.dataset.drop = ''; };
  document.addEventListener('dragover', e => { const pane = paneOf(e); if (!boxOf(pane)) return mark(null); e.preventDefault(); mark(pane); });
  document.addEventListener('dragleave', e => { if (over && !over.contains(e.relatedTarget)) mark(null); });
  document.addEventListener('drop', e => {
    const pane = paneOf(e), kept = boxOf(pane);
    mark(null);
    if (!kept || e.defaultPrevented) return;
    e.preventDefault();
    kept.composer.add(e.dataTransfer.files);
  });
}

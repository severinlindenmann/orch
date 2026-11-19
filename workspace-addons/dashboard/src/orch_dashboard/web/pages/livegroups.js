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
  const gs = liveGroupList(groups), of = new Map();
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
// The message box of a pane with a working helper: who receives it, the words, Send (run.send). What is typed is
// kept per session across repaints of the dock. With the relay on, a microphone puts spoken words into the box
// (pages/livevoice.js, ORCH-696): the strip while listening above the row, the line after the words under it.
const liveMsgDraft = new Map();
const liveMsgBusy = new Set();
function liveMsgBox(sess) {
  if (!sess || sess.kind || !sess.running || snapshot) return null;
  const g = liveGroupOf(liveGroups(), sess.id), id = 'live-msg-' + sess.id, busy = liveMsgBusy.has(sess.id);
  const voice = what => typeof window[what] === 'function' ? window[what](sess) : null;
  return h('form', {className:'live-msg', 'data-live-msg':sess.id, 'data-key':'live-msg'},
    h('label', {className:'live-to', for:id, 'data-key':'live-msg-to'}, liveMsgTo(sess, g)),
    voice('liveVoiceStrip'),
    h('div', {className:'live-msg-row'},
      h('textarea', {className:'input', id, rows:'1', maxlength:String(LIVE_MSG_MAX), placeholder:'Write to this helper', 'data-live-msg-text':sess.id}, liveMsgDraft.get(sess.id) || ''),
      voice('liveVoiceMic'),
      h('button', {type:'submit', className:'btn sm primary', disabled:busy, 'data-key':'live-msg-send'}, busy ? 'Sending…' : 'Send')),
    voice('liveVoiceHint'));
}
if (typeof window === 'object' && typeof document === 'object' && !(typeof module === 'object' && module.exports)) {
  document.addEventListener('input', e => {
    const box = e.target.closest?.('#live-dock [data-live-msg-text]');
    if (box) liveMsgDraft.set(box.dataset.liveMsgText, box.value);
  });
  document.addEventListener('keydown', e => {  // Enter sends, Shift+Enter is a new line (as in the ticket's box)
    const box = e.target.closest?.('#live-dock [data-live-msg-text]');
    if (box && e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); box.form?.requestSubmit(); }
  });
  document.addEventListener('submit', async e => {
    const form = e.target.closest?.('#live-dock [data-live-msg]');
    if (!form) return;
    e.preventDefault();
    const id = form.dataset.liveMsg, text = String(liveMsgDraft.get(id) || '').trim();
    if (!text || liveMsgBusy.has(id)) return;
    const sess = liveLayerSession(id), who = sess?.key || sess?.title || 'the helper';
    liveMsgBusy.add(id);
    const btn = form.querySelector('[data-key="live-msg-send"]');
    if (btn) { btn.disabled = true; btn.textContent = 'Sending…'; }
    const r = await act('run.send', {ticket:id, text});
    liveMsgBusy.delete(id);
    // only what was sent is cleared: words typed while it was on its way stay in the box
    const sent = r.ok && String(liveMsgDraft.get(id) || '').trim() === text;
    if (sent) liveMsgDraft.delete(id);
    if (r.ok && typeof liveChatNote === 'function') { liveChatNote(id, text); if (typeof liveLayerFill === 'function') liveLayerFill(); }  // shows in the chat at once
    const box = document.querySelector(`#live-dock [data-live-msg-text="${id.replace(/["\\]/g, '')}"]`);
    if (box && sent) box.value = '';
    if (btn) { btn.disabled = false; btn.textContent = 'Send'; }
    window.orch?.toast?.(r.ok ? 'Sent to ' + who + '.' : r.text || 'Could not send the message.', r.ok ? 'ok' : 'error');
  });
}

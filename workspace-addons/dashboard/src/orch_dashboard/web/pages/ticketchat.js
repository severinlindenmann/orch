'use strict';
// Ticket chats on the Chats page (team chat step 1, ORCH-1168; draft picked in ORCH-1098). Every ticket with chat
// lines or an open question is a row under "Ticket chats" (state.ticket_chats, `orch chat list`, newest first, with
// this dashboard's unread count). Opening one shows the ticket's chat lines (its history lines with in_chat), its
// questions as cards to answer in place, a box to write to its helper, and the ticket beside the chat: what was
// asked, Done when, its sub-tickets or tasks, and Decided (the answered questions). One thread per ticket, keyed by
// the ticket id; no second store. Built on chat.js the same way the workspace chats are (wrapping its functions).
const tcId = id => typeof id === 'string' && /^t_[a-z0-9]{6,16}$/.test(id);
const tcRows = () => chatObjects(state?.ticket_chats).filter(r => tcId(r.id));
// Opened on this page: {ticket id: its newest line then}. Its unread count stays hidden until the next full build has
// the read mark, and only while nothing newer came in (a newer line counts again).
const tcReadNow = new Map();
function tcUnread(r) {
  if (chatUi.open === r.id) return 0;
  const seen = tcReadNow.get(r.id);
  if (seen !== undefined && (!chatCount(r.unread) || r.last_at !== seen)) tcReadNow.delete(r.id);
  return tcReadNow.has(r.id) ? 0 : chatCount(r.unread);
}
const tcOpen = () => tcId(chatUi.open) ? ticketOf(chatUi.open) : null;
// The address of a ticket's chat (the ticket page's Open chat links here).
const tcHash = id => '#chat/' + encodeURIComponent(String(id || ''));

// Today's time as "14:19", an older one as its day, with a time inside a thread (the list stays one short word).
const tcToday = at => at && chatLocalDay(new Date(at)) === chatLocalDay(new Date(state?.now || Date.now()));
const tcWhen = (at, inThread = false) => !at ? '' : tcToday(at) && window.UI?.clock ? window.UI.clock(at) : inThread ? time(at) : date(at);
function tcRow(r) {
  const unread = tcUnread(r);
  return h('button', {type:'button', className:'chat-list-row', 'data-chat-action':'select-ticket', 'data-id':r.id, 'data-key':'row-' + r.id,
    'aria-current':chatUi.open === r.id ? 'true' : null},
    h('span', {className:'avatar chat-avatar', 'aria-hidden':'true'}, '#'),
    h('span', {className:'chat-row-text'}, chatText('strong', '', r.title || r.key),
      chatText('small', 'chat-row-meta', [r.key, chatPreview(r.last?.text)].filter(Boolean).join(' · ')),
      r.open_questions ? chip('Needs you', 'attn') : null),
    h('span', {className:'chat-row-time'}, tcWhen(r.last_at), unread ? h('span', {className:'count', 'aria-label':unread + ' unread'}, unread) : null));
}

// The list: "Ticket chats" first (as in the draft), then the workspace chats chat.js draws.
const tcListWithoutTickets = chatList;
chatList = function () {
  const aside = tcListWithoutTickets(), rows = tcRows();
  if (!rows.length) return aside;
  const query = chatUi.search.toLowerCase(), history = chatUi.open === 'history', drawn = rows.map(tcRow);
  drawn.forEach(row => { row.hidden = !history && !row.textContent.toLowerCase().includes(query); });
  const first = aside.querySelector('h2') || aside.querySelector('.chat-list-row');
  const heading = drawn.some(row => !row.hidden) ? h('h2', {'data-key':'ticket-chats-heading'}, 'Ticket chats') : null;
  if (tcId(chatUi.open)) aside.querySelectorAll('.chat-list-row[aria-current]').forEach(row => row.removeAttribute('aria-current'));
  aside.insertBefore(fragment(heading, ...drawn), first);
  // chat.js said "No chats match." looking only at its own rows
  if (drawn.some(row => !row.hidden)) aside.querySelector(':scope > p.chat-muted:last-child')?.remove();
  return aside;
};
const tcRichWithoutTickets = chatRich;
chatRich = () => tcRichWithoutTickets() || tcRows().length > 0 || tcId(chatUi.open);
const tcBadgeWithoutTickets = chatBadge;
chatBadge = function () {
  const own = tcBadgeWithoutTickets(), count = (own ? Number(own.textContent) || 0 : 0) + tcRows().reduce((n, r) => n + tcUnread(r), 0);
  return count ? h('span', {className:'count', 'aria-label':count + ' unread'}, count) : null;
};

// One thread: chat lines and questions in time order. A question still open is a card to answer here; an answered
// one is the helper's line with the question, then the answer as a line of whoever answered (also under Decided).
function tcItems(t) {
  const lines = array(t.history).filter(e => e && e.in_chat === true && typeof e.text === 'string' && e.text.trim())
    .map((e, i) => ({kind:'line', at:e.at, key:e.id || 'h-' + i + '-' + (e.at || ''), e}));
  const asks = array(t.questions).filter(q => q && typeof q.text === 'string' && (q.kind == null || q.kind === 'plain'));
  const asked = asks.map(q => ({kind:'question', at:q.asked_at || t.updated_at, key:'q-' + q.id, q, e:{by:'helper', at:q.asked_at}}));
  const answers = asks.filter(q => q.answer != null && !q.taken_back)
    .map(q => ({kind:'answer', at:q.answered_at || q.asked_at || t.updated_at, key:'a-' + q.id, q, e:{by:q.answered_by, at:q.answered_at}}));
  return [...lines, ...asked, ...answers].sort((a, b) => (Date.parse(a.at) || 0) - (Date.parse(b.at) || 0));
}
// Who wrote a line: the person ("You", or the name typed on the dashboard, marked not signed in), else the helper.
function tcWho(e) {
  const person = /^human:/.test(String(e.by || ''));
  if (person) return {mine:true, name:'You', typed:clean(e.by_name || '')};
  const label = name(e.by);
  return {mine:false, name:/^(relay|phone|ph_)/.test(label) ? 'Your phone' : CHAT_HELPER, typed:''};
}
// One line of the thread (the master's .thread-line): avatar, name and time, then the text. A line within five
// minutes of one by the same writer drops its name row.
const TC_GROUP_MS = 5 * 60 * 1000;
function tcLineShell(item, previous, ...body) {
  const e = item.e, who = tcWho(e), prev = previous ? tcWho(previous.e) : null;
  const near = previous && Math.abs((Date.parse(item.at) || 0) - (Date.parse(previous.at) || 0)) < TC_GROUP_MS;
  const grouped = prev && near && prev.mine === who.mine && prev.name === who.name && previous.kind !== 'question' && item.kind !== 'answer';
  const helper = !who.mine && who.name === CHAT_HELPER;
  const label = who.mine ? (who.typed ? who.typed + ' (not signed in)' : 'You') : who.name;
  return h('article', {className:'thread-line' + (grouped ? ' cont' : ''), 'data-key':'message-' + item.key, 'data-message-id':e.id || null, tabindex:'-1'},
    chatAvatar(helper ? 'Helper' : who.mine ? (who.typed || 'You') : who.name, helper),
    h('div', {className:'thread-line-body'},
      grouped ? null : h('div', {className:'thread-line-head'}, label,
        chatText('span', 'meta', [tcWhen(e.at, true), e.via === 'phone' ? 'from your phone' : ''].filter(Boolean).join(' · '))),
      ...body));
}
function tcLine(item, previous) {
  return tcLineShell(item, previous, chatText('div', 'thread-line-text chat-message-text', item.e.text));
}
function tcQuestion(t, item, previous) {
  const q = item.q;
  if (q.answer != null || snapshot) return tcLineShell(item, previous, chatText('div', 'thread-line-text', q.text));
  // the kit's question card, mounted by the page after drawing (app.js mounts every [data-question] host)
  return tcLineShell(item, previous, h('div', {'data-key':'question-' + q.id, 'data-question':q.id, 'data-ticket':t.id}));
}
function tcAnswer(item, previous) {
  const q = item.q;
  return tcLineShell(item, previous, chatText('div', 'thread-line-text', q.answer), chatText('p', 'meta', 'Answer to: ' + clean(q.text)));
}
function tcHeader(t) {
  return h('header', {className:'chat-thread-head', 'data-key':'thread-head'},
    h('div', {className:'chat-head-top'}, chatButton('‹ Chats', 'back', {className:'chat-button chat-back'}),
      h('div', {className:'chat-head-text'}, chatText('p', 'chat-eyebrow', (t.key || '') + ' · You and your helper'),
        h('h1', {'data-key':'chat-title', tabindex:'-1'}, clean(t.title)))));
}
function tcComposer(t) {
  if (snapshot) return chatText('p', 'chat-readonly', 'This is a shared copy.');
  if (['done', 'dropped'].includes(t.status)) return chatText('div', 'chat-archive-banner', 'This ticket is closed · you can read, not reply');
  const draft = chatUi.drafts[t.id] || '', sending = chatUi.sending.has(t.id);
  const label = typeof ticketTalkLabel === 'function' ? ticketTalkLabel(t, state?.runs?.[t.id]) : 'Send';
  return h('form', {className:'chat-compose', 'data-key':'form-' + t.id},
    h('textarea', {rows:1, maxLength:2000, className:'chat-draft', 'data-key':'draft-' + t.id, 'data-chat-input':'draft', 'data-thread':t.id,
      'aria-label':'Message your helper about ' + clean(t.title), placeholder:'Message your helper'}, draft),
    h('button', {type:'submit', className:'chat-button chat-primary', 'data-key':'ticket-chat-send', disabled:sending || !draft.trim()}, sending ? 'Sending…' : label));
}
function tcThread(t) {
  const items = tcItems(t);
  return h('div', {className:'chat-main', 'data-key':'ticket-chat-' + t.id}, tcHeader(t),
    h('div', {className:'chat-log', 'data-key':'log-' + t.id, role:'log', 'aria-live':'polite', 'aria-label':'Ticket chat'},
      items.length ? items.map((item, i) => item.kind === 'line' ? tcLine(item, items[i - 1]) : item.kind === 'answer' ? tcAnswer(item, items[i - 1]) : tcQuestion(t, item, items[i - 1]))
        : chatText('p', 'chat-empty', 'No messages yet. Write to your helper below.')),
    tcComposer(t));
}

// The ticket beside the chat (the draft's right column; below the chat on a narrow screen): everyone in the chat sees it.
function tcPanelSection(title, key, ...body) {
  return h('section', {className:'stack', 'data-key':'ticket-chat-' + key}, h('h3', {}, title), ...body);
}
function tcDecided(t) {
  const rows = array(t.questions).filter(q => q && q.answer != null && !q.taken_back);
  return tcPanelSection('Decided', 'decided', rows.length ? rows.map(q => h('div', {className:'card-row', 'data-key':'decided-' + q.id},
    h('div', {className:'grow'}, h('p', {}, clean(q.answer)), h('p', {className:'meta'}, [clean(q.text), (typeof chatDmName === 'function' && chatDmName(q.answered_by)) || name(q.answered_by), date(q.answered_at)].filter(Boolean).join(' · ')))))
    : h('p', {className:'meta'}, 'Nothing decided yet.'));
}
function tcWork(t) {
  const kids = window.DashHelpers.childrenOf(tickets(), t);
  if (kids.length) return tcPanelSection('Sub-tickets', 'parts', kids.map(k => h('a', {className:'card-row', href:href(k.id), 'data-key':'part-' + k.id},
    h('span', {className:'grow'}, clean(k.title)), statusChip(k))));
  const tasks = array(t.checklist);
  if (!tasks.length) return null;
  const done = tasks.filter(window.DashHelpers.resolved).length;
  return tcPanelSection('Tasks', 'tasks', h('p', {className:'meta'}, done + ' of ' + tasks.length + ' done'),
    tasks.map((c, i) => h('div', {className:'card-row', 'data-key':'task-' + (c.id || i)}, h('span', {className:'grow'}, clean(c.text)), c.done ? chip('Done', 'success') : c.wont_do ? chip("Won't do") : null)));
}
function tcPanel(t, hidden = false) {
  return h('aside', {className:'pane-side', 'aria-label':'The ticket', 'data-key':'ticket-chat-panel', hidden},
    h('div', {className:'stack'}, h('p', {className:'meta'}, 'The ticket · everyone in this chat sees it'),
      h('h3', {}, h('a', {href:href(t.id), 'data-key':'ticket-chat-panel-title'}, [t.key, clean(t.title)].filter(Boolean).join(' · '))),
      t.description ? h('p', {className:'preserve-lines'}, clean(t.description)) : null),
    t.done_when ? tcPanelSection('Done when', 'done-when', h('p', {}, clean(t.done_when))) : null,
    tcWork(t), tcDecided(t));
}

const tcPageWithoutTickets = chatPage;
chatPage = function () {
  const t = tcOpen();
  if (!t) return tcPageWithoutTickets();
  // the master's panes: the list, the chat and the ticket in one frame (stacked under 900 px; the open list hides the
  // ticket, and the frame drops its column)
  const page = h('section', {className:'chat-page panes' + (chatUi.listOpen ? ' chat-list-open' : ' chat-thread-open'), 'data-key':'chat-page'},
    chatList(), tcThread(t), tcPanel(t, chatUi.listOpen));
  page.addEventListener('click', chatClick); page.addEventListener('input', chatInput); page.addEventListener('keydown', chatKeydown);
  // only the chat box: a question card's own answer form submits by itself
  page.addEventListener('submit', e => { if (e.target.matches('.chat-compose')) { e.preventDefault(); chatSend(); } });
  page.addEventListener('scroll', event => {
    if (event.target.matches('.chat-log')) chatScroll.set(event.target, {near:event.target.scrollHeight - event.target.scrollTop - event.target.clientHeight < 80, stamp:chatLogStamp(event.target)});
  }, true);
  return fragment(heading('Chat'), page);
};

async function tcMarkRead(id) {
  if (snapshot || !tcId(id)) return;
  const row = tcRows().find(r => r.id === id);
  if (row && !chatCount(row.unread)) return;  // nothing new: no write
  if (row) tcReadNow.set(id, row.last_at);
  try { await act('chat.read', {ticket:id}, {quiet:true}); } catch { /* the count comes back on the next build */ }
}
function tcSelect(id) {
  if (!tcId(id)) return;
  chatUi.agentConversation = false; chatUi.newConversation = false;
  chatUi.open = id; chatUi.day = null; chatUi.listOpen = false; chatUi.sheet = null; chatUi.menu = false;
  history.replaceState(null, '', tcHash(id));
  render(); chatFocus('[data-key="chat-title"]');
  tcMarkRead(id);
}
const tcClickWithoutTickets = chatClick;
chatClick = async function (event) {
  const control = event.target.closest('[data-chat-action]');
  if (control && !control.disabled && control.dataset.chatAction === 'select-ticket') return tcSelect(control.dataset.id);
  if (control && !control.disabled && ['select', 'select-dm', 'history'].includes(control.dataset.chatAction) && tcId(chatUi.open)) history.replaceState(null, '', '#chat');
  return tcClickWithoutTickets(event);
};

// Send: a chat line on the ticket, handed to its helper (orch chat say --ticket). Nothing works on the ticket: the
// one starter starts a helper that reads it first, as Add to this ticket does (pages/ticket.js ticketTalkSend).
const tcSendWithoutTickets = chatSend;
chatSend = async function () {
  const t = tcOpen();
  if (!t) return tcSendWithoutTickets();
  const id = t.id, text = (chatUi.drafts[id] || '').trim();
  if (snapshot || !text || chatUi.sending.has(id) || ['done', 'dropped'].includes(t.status)) return;
  const original = chatUi.drafts[id];
  chatUi.sending.add(id); render();
  let said = null;
  try { said = await act('chat.say', {ticket:id, text}); } catch { said = null; }
  chatUi.sending.delete(id);
  if (!said?.ok) { render(); window.orch.toast('Could not send your message. Try again.', 'error'); return; }
  if (chatUi.drafts[id] === original) chatUi.drafts[id] = '';
  const r = said.state?.send_result;
  if (r && r.state === 'none' && !r.delivered) {
    const starter = window.UI?.startStarter;
    const started = starter ? await starter.start(id, [['run.start', {ticket:id}]]) : await act('run.start', {ticket:id});
    window.orch.toast(started?.ok || started?.again || started?.queued ? 'Sent. A helper starts and reads it first.' : 'Saved in the chat. Start the helper to go on.', started?.ok || started?.again || started?.queued ? 'ok' : 'info');
  }
  render(); chatFocus('.chat-draft');
};

// #chat/<ticket id> opens that ticket's chat (the ticket page's Open chat, a shared link).
function tcRoute() {
  const id = decodeURIComponent(location.hash.slice(6));
  if (!location.hash.startsWith('#chat/') || !tcId(id)) return;
  if (chatUi.open !== id) { chatUi.open = id; chatUi.listOpen = false; chatUi.day = null; chatUi.sheet = null; if (route().kind === 'chat') { render(); tcMarkRead(id); } }
}
window.addEventListener('hashchange', tcRoute);
window.addEventListener('orch:state', tcRoute);
window.addEventListener('DOMContentLoaded', tcRoute);

// The ticket page's Open chat (in the ticket's strip, next to its other actions).
function ticketChatButton(t) {
  if (snapshot || !t || !tcId(t.id) || !(state?.chat || state?.general || Array.isArray(state?.ticket_chats))) return null;
  return h('a', {className:'btn outline sm', href:tcHash(t.id), 'data-key':'ticket-open-chat'}, iconEl('chat'), 'Open chat');
}

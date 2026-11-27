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
  const unread = tcUnread(r), last = chatPreview(tcPlain(r.last?.text));
  return h('button', {type:'button', className:'chat-list-row', 'data-chat-action':'select-ticket', 'data-id':r.id, 'data-key':'row-' + r.id,
    'aria-current':chatUi.open === r.id ? 'true' : null},
    h('span', {className:'avatar chat-avatar chat-ticket-pic', 'aria-hidden':'true'}, iconEl('ticket')),
    h('span', {className:'chat-row-text'}, chatText('strong', '', r.title || r.key),
      // "Needs you" is written in the row (option A), with what it is about
      r.open_questions ? chatText('small', 'chat-row-preview chat-needs-you', ['Needs you', last].filter(Boolean).join(' · '))
        : chatText('small', 'chat-row-preview', last || r.key)),
    h('span', {className:'chat-row-time'}, tcWhen(r.last_at), unread ? h('span', {className:'count', 'aria-label':unread + ' unread'}, unread) : null));
}
// The list: your helper on top, then "Tickets", then the workspace chats chat.js draws.
const tcListWithoutTickets = chatList;
chatList = function () {
  const aside = tcListWithoutTickets(), rows = tcRows();
  if (!rows.length) return aside;
  const query = chatUi.search.toLowerCase(), drawn = rows.map(tcRow);
  drawn.forEach(row => { row.hidden = !row.textContent.toLowerCase().includes(query); });
  const after = aside.querySelector('.chat-list-rule');
  const heading = drawn.some(row => !row.hidden) ? h('h2', {'data-key':'ticket-chats-heading'}, 'Tickets') : null;
  if (tcId(chatUi.open)) aside.querySelectorAll('.chat-list-row[aria-current]').forEach(row => row.removeAttribute('aria-current'));
  tcInsertAfter(aside, after, fragment(heading, ...drawn));
  // chat.js said "No chats match." looking only at its own rows
  if (drawn.some(row => !row.hidden)) aside.querySelector(':scope > p.chat-muted:last-child')?.remove();
  return aside;
};
// After the rule under your helper (a real page: insertBefore; the tests' small tree: its children list).
function tcInsertAfter(aside, after, node) {
  if (aside.insertBefore && after) return aside.insertBefore(node, after.nextSibling);
  const list = aside.children, i = after ? list.indexOf(after) : -1;
  list.splice(i + 1, 0, node);
}
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
  return [...lines, ...asked, ...answers, ...tcMemberEvents(t)].sort((a, b) => (Date.parse(a.at) || 0) - (Date.parse(b.at) || 0));
}
// Who wrote a line: the person ("You", or the name typed on the dashboard, marked not signed in), else the helper.
// With other workspaces in the chat (team chat step 2) each line also names its workspace: a member's helper writes
// as "agent:<member name>" (chat_groups.py), every other helper line is this workspace's own helper.
function tcWho(e, g = null) {
  const person = /^human:/.test(String(e.by || '')), own = tcShared(g) ? chatWorkspace() : '';
  if (person) return {mine:true, name:'You', typed:clean(e.by_name || ''), ws:own};
  const label = name(e.by);
  if (/^(relay|phone|ph_)/.test(label)) return {mine:false, name:'Your phone', typed:'', ws:''};
  const member = g ? chatObjects(g.members).find(m => !m.host && clean(m.name) === label) : null;
  if (member) return {mine:false, name:tcHelperName(member.name), typed:'', ws:clean(member.name), member, helper:true};
  return {mine:false, name:own ? tcHelperName(own) : CHAT_HELPER, typed:'', ws:own, helper:true};
}
// One line of the thread (the master's .thread-line): avatar, name (with its workspace when other workspaces are in
// the chat) and time, then the text. A line within five minutes of one by the same writer drops its name row.
const TC_GROUP_MS = 5 * 60 * 1000;
function tcLineShell(item, previous, g, ...body) {
  const e = item.e, who = tcWho(e, g), prev = previous && previous.e ? tcWho(previous.e, g) : null;
  const near = previous && Math.abs((Date.parse(item.at) || 0) - (Date.parse(previous.at) || 0)) < TC_GROUP_MS;
  const grouped = prev && near && prev.mine === who.mine && prev.name === who.name && prev.typed === who.typed && previous.kind !== 'question' && previous.kind !== 'event' && item.kind !== 'answer';
  const label = who.mine ? (who.typed ? who.typed + ' (not signed in)' : 'You') : who.name;
  return h('article', {className:'thread-line' + (grouped ? ' cont' : ''), 'data-key':'message-' + item.key, 'data-message-id':e.id || null, tabindex:'-1'},
    chatAvatar(who.mine ? (who.typed || 'You') : who.member || (who.name === CHAT_HELPER ? 'Helper' : who.name), !!who.helper),
    h('div', {className:'thread-line-body'},
      grouped ? null : h('div', {className:'thread-line-head', 'data-key':'who-' + item.key}, label,
        who.ws ? chatText('span', 'chat-ws-label', who.ws) : null,
        chatText('span', 'meta', [tcWhen(e.at, true), e.via === 'phone' ? 'from your phone' : ''].filter(Boolean).join(' · '))),
      ...body));
}
function tcLine(item, previous, g = null) {
  return tcLineShell(item, previous, g, chatText('div', 'thread-line-text chat-message-text', tcPlain(item.e.text)));
}
function tcQuestion(t, item, previous, g = null) {
  const q = item.q;
  if (q.answer != null || snapshot) return tcLineShell(item, previous, g, chatText('div', 'thread-line-text', q.text));
  // the kit's question card, mounted by the page after drawing (app.js mounts every [data-question] host)
  return tcLineShell(item, previous, g, h('div', {'data-key':'question-' + q.id, 'data-question':q.id, 'data-ticket':t.id}));
}
function tcAnswer(item, previous, g = null) {
  const q = item.q;
  return tcLineShell(item, previous, g, chatText('div', 'thread-line-text', q.answer), chatText('p', 'meta', 'Answer to: ' + clean(q.text)));
}
function tcHeader(t) {
  const g = tcGroupOf(t), others = tcOthers(g).length;
  const who = !others ? 'You and your helper' : others === 1 ? 'You and one other workspace' : 'You and ' + others + ' other workspaces';
  return h('header', {className:'chat-thread-head', 'data-key':'thread-head'},
    h('div', {className:'chat-head-top'}, chatButton('‹ Chats', 'back', {className:'chat-button chat-back'}),
      h('span', {className:'avatar chat-avatar chat-ticket-pic', 'aria-hidden':'true'}, iconEl('ticket')),
      h('div', {className:'chat-head-text'}, h('h2', {'data-key':'chat-title', tabindex:'-1'}, clean(t.title)),
        chatText('p', 'chat-head-meta', [t.key || '', who].filter(Boolean).join(' · '))),
      tcCanAdd(t) ? chatButton('+ Add', 'ticket-add', {className:'btn outline sm', 'data-key':'ticket-chat-add', 'aria-label':'Add a workspace to this chat', 'aria-haspopup':'dialog'}) : null,
      h('a', {className:'btn outline sm', href:href(t.id), 'data-key':'ticket-chat-open-ticket'}, 'Open the ticket')),
    others ? tcChips(g) : null);
}
function tcComposer(t) {
  if (snapshot) return chatText('p', 'chat-readonly', 'This is a shared copy.');
  if (['done', 'dropped'].includes(t.status)) return chatText('div', 'chat-archive-banner', 'This ticket is closed · you can read, not reply');
  const shared = tcShared(tcGroupOf(t));
  // the one message box (option A); into a group no files (they go through the ticket page)
  return h('div', {className:'chat-composer-area', 'data-key':'composer-' + t.id},
    chatBox(t.id, {label:shared ? 'Message everyone in this chat' : 'Message your helper about this ticket', attach:!shared, max:2000}));
}
function tcThread(t) {
  const items = tcItems(t), g = tcGroupOf(t);
  return h('div', {className:'chat-main', 'data-key':'ticket-chat-' + t.id}, tcHeader(t),
    h('div', {className:'chat-log', 'data-key':'log-' + t.id, role:'log', 'aria-live':'polite', 'aria-label':'Ticket chat'},
      items.length ? items.map((item, i) => fragment(item.at && (!items[i - 1]?.at || chatDayWord(items[i - 1].at) !== chatDayWord(item.at)) ? chatDayLine(chatDayWord(item.at), item.key) : null, item.kind === 'line' ? tcLine(item, items[i - 1], g) : item.kind === 'answer' ? tcAnswer(item, items[i - 1], g) : item.kind === 'event' ? chatText('div', 'chat-system', item.text) : tcQuestion(t, item, items[i - 1], g)))
        : chatText('p', 'chat-empty', 'No messages yet. Write to your helper below.')),
    typeof browsePeekHost === 'function' ? browsePeekHost(t.id, 'chat') : null,  // the helper's browser, small and live (ORCH-1494)
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
    tcWork(t), tcDecided(t), tcInfo(t));
}

const tcPageWithoutTickets = chatPage;
chatPage = function () {
  const t = tcOpen();
  if (!t) return tcPageWithoutTickets();
  // the master's panes: the list, the chat and the ticket in one frame (stacked under 900 px; the open list hides the
  // ticket, and the frame drops its column)
  const page = h('section', {className:'chat-page chat-frame chat-with-side' + (chatUi.listOpen ? ' chat-list-open' : ' chat-thread-open'), 'data-key':'chat-page'},
    chatList(), tcThread(t), tcPanel(t, chatUi.listOpen));
  page.addEventListener('click', chatClick); page.addEventListener('input', chatInput); page.addEventListener('keydown', chatKeydown);
  // only the chat box: a question card's own answer form submits by itself
  page.addEventListener('submit', e => { if (e.target.matches('.chat-compose')) { e.preventDefault(); chatSend(); } });
  page.addEventListener('scroll', chatOnScroll, true);
  return fragment(page);
};

async function tcMarkRead(id) {
  if (snapshot || !tcId(id)) return;
  const row = tcRows().find(r => r.id === id);
  if (row && (!chatCount(row.unread) || tcReadNow.get(id) === row.last_at)) return;  // nothing new, or sent: no write
  if (row) tcReadNow.set(id, row.last_at);
  try { await act('chat.read', {ticket:id}, {quiet:true}); } catch { /* the count comes back on the next build */ }
}
function tcSelect(id) {
  if (!tcId(id)) return;
  chatUi.agentConversation = false; chatUi.newConversation = false;
  chatUi.open = id; chatUi.day = null; chatUi.listOpen = false; chatUi.sheet = null; chatUi.menu = false;
  history.replaceState(null, '', tcHash(id));
  render(); chatFocus('[data-key="chat-title"]');
  tcMarkRead(id); tcContacts();
}
const tcClickWithoutTickets = chatClick;
chatClick = async function (event) {
  const control = event.target.closest('[data-chat-action]');
  if (control && !control.disabled && control.dataset.chatAction === 'select-ticket') return tcSelect(control.dataset.id);
  if (control && !control.disabled && control.dataset.chatAction === 'ticket-add' && tcOpen()) return tcAddDialog(tcOpen());
  if (control && control.dataset.chatAction === 'ticket-info') return tcInfoFocus();
  if (control && !control.disabled && ['select', 'select-dm', 'history'].includes(control.dataset.chatAction) && tcId(chatUi.open)) history.replaceState(null, '', '#chat');
  return tcClickWithoutTickets(event);
};

// Send: a chat line on the ticket, handed to its helper (orch chat say --ticket). Nothing works on the ticket: the
// one starter starts a helper that reads it first, as Add to this ticket does (pages/ticket.js ticketTalkSend).
const tcSendWithoutTickets = chatSend;
chatSend = async function () {
  const t = tcOpen();
  if (!t) return tcSendWithoutTickets();
  const id = t.id, typed = (chatUi.drafts[id] || '').trim(), files = array(chatUi.outFiles);
  if (snapshot || (!typed && !files.length) || chatUi.sending.has(id) || ['done', 'dropped'].includes(t.status)) return {ok:false, text:''};
  const original = chatUi.drafts[id];
  chatUi.sending.add(id); render();
  const r = await tcSay(t, typed, files);
  chatUi.sending.delete(id);
  if (r.ok && chatUi.drafts[id] === original) chatUi.drafts[id] = '';
  render(); return r;
};
// The one send of a ticket chat line ({ok, text}), for the Chats page and Review's side panel (ORCH-2185): into a
// shared chat everyone gets it (orch relay group say --dashboard, a line on the ticket too, no files); else files go
// onto the ticket first (ticket.attach), the words name them, and a helper starts when none was there to read it.
async function tcSay(t, typed, files = []) {
  const id = t.id;
  if (tcShared(tcGroupOf(t)) && !tcGroupOf(t).closed) {
    const ok = await chatOperation('group.say', {ticket:id, text:typed}, 'Could not send your message.');
    return ok ? {ok:true, text:''} : {ok:false, text:'Not sent. Try again.'};
  }
  let text = typed;
  if (files.length && typeof ticketAttachFiles === 'function') {
    const kept = await ticketAttachFiles(id, files);
    if (!kept.ok) return {ok:false, text:kept.text};
    text = ticketTalkText(typed, kept.names);
  }
  let said = null;
  try { said = await act('chat.say', {ticket:id, text}); } catch { said = null; }
  if (!said?.ok) return {ok:false, text:'Not sent. Check the connection and try again.'};
  const r = said.state?.send_result;
  if (r && r.state === 'none' && !r.delivered) {
    const starter = window.UI?.startStarter;
    const started = starter ? await starter.start(id, [['run.start', {ticket:id}]]) : await act('run.start', {ticket:id});
    window.orch.toast(started?.ok || started?.again || started?.queued ? 'Sent. A helper starts and reads it first.' : 'Saved in the chat. Start the helper to go on.', started?.ok || started?.again || started?.queued ? 'ok' : 'info');
  }
  return {ok:true, text:''};
}

// #chat/<ticket id> opens that ticket's chat (the ticket page's Open chat, a shared link).
function tcRoute() {
  const id = decodeURIComponent(location.hash.slice(6));
  if (!location.hash.startsWith('#chat/') || !tcId(id)) return;
  if (chatUi.open !== id) { chatUi.open = id; chatUi.listOpen = false; chatUi.day = null; chatUi.sheet = null; if (route().kind === 'chat') { render(); tcMarkRead(id); tcContacts(); } }
}
window.addEventListener('hashchange', tcRoute);
window.addEventListener('orch:state', tcRoute);
// New lines that arrive while a ticket chat stays open are read: they do not come back as unread on leaving it.
window.addEventListener('orch:state', () => {
  if (tcId(chatUi.open) && route().kind === 'chat' && document.visibilityState === 'visible') tcMarkRead(chatUi.open);
});
window.addEventListener('DOMContentLoaded', tcRoute);

// The ticket page's Open chat (in the ticket's strip, next to its other actions).
function ticketChatButton(t) {
  if (snapshot || !t || !tcId(t.id) || !(state?.chat || state?.general || Array.isArray(state?.ticket_chats))) return null;
  return h('a', {className:'btn outline sm', href:tcHash(t.id), 'data-key':'ticket-open-chat'}, iconEl('chat'), 'Open chat');
}

// ---- Other workspaces in a ticket chat (team chat step 2, ORCH-1174; draft picked in ORCH-1098) ----
// The ticket's group (chat_groups.py, held by this workspace: grp_<ticket id>) is the same chat: its members are in
// the header, a member's helper writes into it, + Add puts in another connected workspace (orch relay group add) and
// "In this chat" beside it shows who added whom and removes a workspace (orch relay group remove). Only the ticket's
// workspace changes members; a group this workspace was invited to stays under Groups.
// a closed group still names who wrote what; it only takes no new members
const tcGroupOf = t => (t ? chatObjects(state?.groups?.hosted).find(g => g.ticket === t.id) : null) || null;
const tcActive = g => chatObjects(g?.members).filter(m => !m.left_at);
const tcOthers = g => tcActive(g).filter(m => !m.host);
const tcShared = g => tcOthers(g).length > 0;
const tcHelperName = ws => clean(ws) + ' helper';
// A group line on the ticket starts with "Group: " (chat_groups.py); the chat shows the words only.
const tcPlain = text => String(text ?? '').replace(/^Group: /, '');
// One ticket chat, one row: a hosted group of a ticket that has a ticket chat is not listed again under Groups, unless
// it gave a workspace a task (its task cards and Ask / Task actions live in the group view only, for now).
const tcGroupsWithTickets = chatGroups;
chatGroups = () => {
  const rows = new Set(tcRows().map(r => r.id)), tasked = new Set(chatObjects(state?.groups?.hosted).filter(g => chatObjects(g.tasks).length).map(g => g.id));
  return tcGroupsWithTickets().filter(g => g.readOnly || tasked.has(g.id) || !rows.has(g.ticket));
};

// Who may still be added: the group's own list once it exists, else the connected workspaces chat.js read
// (orch chat contacts); the relay is off or nothing is connected: no + Add at all.
function tcAddable(t) {
  const g = tcGroupOf(t), held = new Set(tcActive(g).map(m => m.ws));
  const list = g ? chatObjects(g.connectable) : chatDm.contacts.filter(c => c?.can?.chat).map(c => ({ws:c.ws, name:c.name, look:c.look}));
  return list.filter(c => chatDmId(c.ws) && !held.has(c.ws));
}
const tcCanAdd = t => !snapshot && !!t && !['done', 'dropped'].includes(t.status) && !tcGroupOf(t)?.closed && (!!tcGroupOf(t) || chatDm.contacts.some(c => c?.can?.chat));
function tcContacts() { if (!snapshot && !chatDm.loaded && !chatDm.loading) chatDmLoad(true); }

// Who changed the members (contract v2 added_by / removed_by): "you", or this workspace (its helper).
function tcByWord(by, g) {
  if (by === 'you') return 'you';
  if (by && g && by === g.host) return 'your helper';
  return '';
}
function tcMemberEvents(t) {
  const g = tcGroupOf(t);
  if (!g) return [];
  const out = [];
  chatObjects(g.members).filter(m => !m.host).forEach(m => {
    const n = clean(m.name) || 'A workspace', by = tcByWord(m.added_by, g);
    if (m.joined_at) out.push({kind:'event', at:m.joined_at, key:'joined-' + m.ws,
      text:(by ? capitalise(by) + ' added ' + n : n + ' joined') + '. They see this ticket and the whole chat.'});
    if (m.left_at) {
      const gone = tcByWord(m.removed_by, g);
      out.push({kind:'event', at:m.left_at, key:'left-' + m.ws, text:m.reason === 'left' ? n + ' left this chat.'
        : (gone ? capitalise(gone) + ' removed ' + n : n + ' was removed') + '. What it already got stays with it.'});
    }
  });
  return out;
}

// The header's member chips (the draft: "Marketing you + helper", "Sales helper"); a click goes to In this chat.
function tcChips(g) {
  const own = chatWorkspace();
  return h('button', {type:'button', className:'chat-member-chips chat-button', 'data-chat-action':'ticket-info', 'data-key':'ticket-chat-chips',
    'aria-label':'In this chat: you, ' + [own, ...tcOthers(g).map(m => clean(m.name))].map(tcHelperName).join(', ')},
    h('span', {className:'chat-member-chip', 'data-key':'chip-own'}, chatAvatar(own), own + ' · you and helper'),
    tcOthers(g).map(m => h('span', {className:'chat-member-chip', 'data-key':'chip-' + m.ws}, chatAvatar(m, true), tcHelperName(m.name))));
}
function tcInfoFocus() {
  const box = document.querySelector('[data-key="ticket-chat-info"]');
  if (!box) return;
  box.scrollIntoView({block:'nearest', behavior:window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
  box.querySelector('h3')?.focus({preventScroll:true});
}

// Older orch: a member that reported no chat groups version 2 gets no @ routing (chat-groups.md v2). Only said once
// any member reported a version, so a group from before version 2 is not all marked.
function tcOlder(g, m) {
  const told = chatObjects(g.members).some(x => !x.host && Number.isInteger(x.chat_groups));
  return told && !m.host && !(Number(m.chat_groups) >= 2);
}
// Chat info beside the chat: who is in it, who added whom and when, Remove (only the ticket's workspace can).
function tcInfo(t) {
  const g = tcGroupOf(t);
  if (!g || !chatObjects(g.members).some(m => !m.host)) return null;
  const own = chatWorkspace(), closed = snapshot || g.closed || ['done', 'dropped'].includes(t.status);
  const past = chatObjects(g.members).filter(m => !m.host && m.left_at);
  const row = (key, avatar, title, meta, ...extra) => h('div', {className:'card-row', 'data-key':key}, avatar,
    h('div', {className:'grow'}, h('p', {}, title), meta ? h('p', {className:'meta'}, meta) : null), ...extra);
  return h('section', {className:'stack', 'data-key':'ticket-chat-info'}, h('h3', {tabindex:'-1'}, 'In this chat'),
    row('info-you', chatAvatar('You'), 'You', own + ' · this ticket lives here'),
    row('info-helper', chatAvatar(own, true), tcHelperName(own), own),
    tcOthers(g).map(m => {
      const by = tcByWord(m.added_by, g);
      return row('info-' + m.ws, chatAvatar(m, true), tcHelperName(m.name),
        [clean(m.name), (by ? 'added by ' + by : 'joined') + (m.joined_at ? ' ' + date(m.joined_at) : '')].join(' · '),
        tcOlder(g, m) ? chip('older orch') : null,
        closed ? null : h('button', {type:'button', className:'btn outline sm', 'data-key':'remove-' + m.ws, 'aria-label':'Remove ' + clean(m.name) + ' from this chat'}, 'Remove'));
    }),
    past.length ? h('p', {className:'meta', 'data-key':'info-past'}, 'Earlier: ' + past.map(m => clean(m.name) + ' ' + (m.reason === 'left' ? 'left' : 'removed') + (m.left_at ? ' ' + date(m.left_at) : '')).join(' · ')) : null,
    h('p', {className:'meta'}, 'The ticket lives in ' + own + '. Others write here; only ' + own + ' changes the ticket and who is in this chat.'));
}
// Remove asks once (no typed word): what it already got stays with it.
function tcRemove(t, ws) {
  const g = tcGroupOf(t), m = tcOthers(g).find(x => x.ws === ws);
  if (!m || snapshot) return;
  const n = clean(m.name) || 'this workspace';
  const {d, actions} = dialog('Remove ' + n + ' from this chat?');
  d.setAttribute('data-key', 'ticket-chat-remove-dialog');
  actions.append(button('Remove', 'danger', async () => {
    window.orch.close(d);
    if (await chatOperation('group.remove', {ticket:t.id, workspace:ws}, 'Could not remove ' + n + '.')) window.orch.toast(n + ' was removed from this chat.', 'ok');
    render();
  }));
  d.append(h('div', {className:'stack'}, h('p', {}, n + ' stops getting new messages from this chat. What it already got stays with it.')), actions);
  d.showModal();
}
document.addEventListener('click', event => {
  const b = event.target.closest?.('[data-key="ticket-chat-info"] button[data-key^="remove-"]');
  const t = b && tcOpen();
  if (t && !b.disabled) tcRemove(t, b.dataset.key.slice(7));
});

// + Add: the Workspaces list (adding people comes in a later step). One line says what they see before Add.
function tcAddDialog(t) {
  if (!tcCanAdd(t)) return;
  const {d, actions} = dialog('Add to this chat');
  d.setAttribute('data-key', 'ticket-chat-add-dialog');
  const picks = new Set(), list = tcAddable(t);
  const add = button('Add', 'primary', async () => {
    if (!picks.size) return;
    add.disabled = true;
    const names = [], chosen = list.filter(c => picks.has(c.ws));
    for (const c of chosen) {
      if (await chatOperation('group.add', {ticket:t.id, workspace:c.ws}, 'Could not add ' + (clean(c.name) || 'the workspace') + '.')) names.push(clean(c.name));
    }
    window.orch.close(d);
    if (names.length) window.orch.toast('Added ' + names.join(' and ') + '. Its helper joins the chat.', 'ok');
    render();
  });
  add.disabled = true; add.setAttribute('data-key', 'ticket-chat-add-confirm');
  const label = () => { add.textContent = picks.size > 1 ? 'Add ' + picks.size : 'Add'; add.disabled = !picks.size; };
  const rows = list.map(c => {
    const box = h('input', {type:'checkbox', value:c.ws, 'data-key':'add-' + c.ws});
    box.addEventListener('change', () => { if (box.checked) picks.add(c.ws); else picks.delete(c.ws); label(); });
    return h('label', {className:'check-label', 'data-key':'add-row-' + c.ws}, box, chatAvatar(c, true),
      h('span', {className:'grow'}, clean(c.name) || 'Workspace', h('span', {className:'meta'}, ' · its helper joins')));
  });
  actions.append(add);
  d.append(h('div', {className:'stack'},
    h('p', {'data-key':'ticket-chat-share-notice'}, 'They see this ticket and the earlier messages in this chat, including places, voice notes and file names.'),
    h('p', {className:'eyebrow'}, 'Workspaces'),
    rows.length ? h('div', {className:'stack', role:'group', 'aria-label':'Workspaces'}, rows)
      : h('p', {className:'meta', 'data-key':'ticket-chat-add-none'}, 'No other workspace is connected to this one yet.'),
    h('p', {className:'meta'}, 'You can remove a workspace later; what it already got stays with it.')), actions);
  d.showModal();
  d.querySelector('input[type=checkbox]')?.focus();
}

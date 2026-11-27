'use strict';
// Classic-script page: rendering is side-effect free; events own requests and UI state.
// The thread is open by default (on a narrow screen "‹ Chats" goes back to the list).
let chatUi = {open:'chat', agentConversation:false, newConversation:false, day:null, listOpen:false, sheet:null, filter:'all', search:'', historySearch:'', menu:false,
  drafts:Object.create(null), sending:new Set(), pending:new Map(), files:new Set(), historyFocus:null, past:[], failed:[], outFiles:[]};
let chatDays = {status:'idle', rows:[]}, chatArchive = new Map();
const chatScroll = new WeakMap();
const chatObjects = value => array(value).filter(v => v && typeof v === 'object');
// Groups come from state.groups = {hosted:[...], joined:[...]} (the group list). A hosted group's talk is the
// host ticket's history, its tasks are task cards; a joined group shows the log this workspace stored. Only the host can write.
const chatGroupMembers = (rows, tasks) => chatObjects(rows).filter(m => !m.left_at).map(m => ({...m, task:chatObjects(tasks).find(t => t.ws === m.ws && t.key)}));
// Groups carry no start or end time: started = the first join or message, finished = the last thing that happened.
const chatTimes = values => values.filter(v => Number.isFinite(Date.parse(v))).sort((a, b) => Date.parse(a) - Date.parse(b));
function chatHostedGroup(g) {
  const ticket = ticketOf(g.ticket), members = chatGroupMembers(g.members, g.tasks), host = members.find(m => m.host);
  const nameOf = ws => clean(members.find(m => m.ws === ws)?.name);
  const talk = array(ticket?.history).filter(e => e && typeof e.text === 'string' && e.in_chat === true).map((e, i) => {
    const mine = String(e.by || '').startsWith('human:'), who = name(e.by);
    return {id:'h-' + i + '-' + (e.at || ''), at:e.at, by:mine ? 'you' : who, name:mine ? 'You' : /helper$/.test(who) ? who : who + ' helper', text:e.text};
  });
  const tasks = chatObjects(g.tasks).filter(t => t.delegate).map(t => ({id:'task-' + t.delegate, text:'', by:host?.ws || 'host', name:clean(host?.name) + ' helper', task:{...t, name:nameOf(t.ws) || 'Workspace'}}));
  const messages = [...talk, ...tasks], last = talk[talk.length - 1], times = chatTimes([...chatObjects(g.members).map(m => m.joined_at), ...talk.map(m => m.at)]);
  // A group whose ticket is done or dropped is finished too, even before the group itself is closed.
  return {id:g.id, ticket:g.ticket, host:host?.ws, title:g.title || ticket?.title, key:typeof ticket?.key === 'string' ? ticket.key : '', closed:g.closed,
    done:!!g.closed || ['done', 'dropped'].includes(ticket?.status),
    members, messages, last:last?.text || '', last_at:last?.at, unread:0, connectable:array(g.connectable),
    started:times[0], finished:chatTimes([...times, ticket?.updated_at]).at(-1)};
}
function chatJoinedGroup(g) {
  const members = chatGroupMembers(g.members), nameOf = ws => clean(members.find(m => m.ws === ws)?.name);
  const messages = chatObjects(g.log).map(x => ({id:x.id, at:x.at, by:'ws', name:clean(x.shown), text:x.text || '',
    group_event:x.event ? {...x.event, name:x.event.name || nameOf(x.event.ws)} : null, task:x.task ? {...x.task, name:nameOf(x.task.ws) || 'Workspace'} : null,
    share:x.file ? {kind:'file', title:x.file.title || x.file.name} : null}));
  const last = messages.filter(m => m.text).pop(), card = g.card, times = chatTimes([...chatObjects(g.members).map(m => m.joined_at), ...messages.map(m => m.at)]);
  return {id:g.id, host:g.host, title:g.title, key:'', closed:g.closed || g.left, done:g.closed || g.left, readOnly:true, members, messages, last:last?.text || '', last_at:last?.at, unread:0,
    shared_ticket:card && typeof card === 'object' ? card : null, started:times[0], finished:times.at(-1)};
}
// let: the Chats page's ticket chats (pages/ticketchat.js) show a ticket's own group inside its ticket chat.
let chatGroups = () => [...chatObjects(state?.groups?.hosted).map(chatHostedGroup), ...chatObjects(state?.groups?.joined).map(chatJoinedGroup)];
const chatGroup = () => chatGroups().find(g => g.id === chatUi.open);
// One rule for both places: a finished group is only under Earlier → Finished groups, a live one only under Groups.
const chatFinished = g => !!(g.done || g.closed);
// The name people see: look name when the switcher has one, else the workspace name with a capital.
const chatWorkspace = () => { const n = clean(state?.look?.workspaces?.find(w => w.here)?.name || state?.workspace) || 'Workspace'; return n.charAt(0).toUpperCase() + n.slice(1); };
const chatHost = g => clean(chatObjects(g.members).find(m => m.ws === g.host)?.name || g.host_name) || chatWorkspace();
const chatCount = n => Math.max(0, Number(n) || 0);
const chatText = (tag, cls, text) => h(tag, {className:cls}, clean(text));
// A one-line preview (sidebar, Earlier): the first line that says something, without its bullet. A lead-in such as
// "Still open this week:" is skipped, so a preview never ends on a colon.
function chatPreview(text) {
  const lines = String(text ?? '').split(/\r?\n/).map(line => line.replace(/^\s*(?:[-*•·–]|\d+[.)])\s+/, '').trim()).filter(Boolean);
  return (lines.find(line => !/:$/.test(line)) || lines[0] || '').replace(/\s*:$/, '');
}
const chatLink = id => '#ticket/' + encodeURIComponent(String(id || ''));
function chatHttp(value) { try { const url = new URL(value); return /^https?:$/.test(url.protocol) ? url.href : null; } catch { return null; } }
function chatBadge() {
  const count = chatGroups().reduce((sum, g) => sum + chatCount(g.unread), 0);
  return count ? h('span', {className:'count', 'aria-label':count + ' unread'}, count) : null;
}
function chatButton(text, action, attrs = {}) {
  return h('button', {type:'button', className:'chat-button', 'data-chat-action':action, 'data-key':action, ...attrs}, clean(text));
}
function chatAvatar(member, helper = false) {
  const label = clean(member?.name || member || 'Workspace');
  const palette = ['var(--brand)', 'var(--warning)', 'var(--info)', 'var(--chart-4)'];
  const hash = [...label].reduce((n, c) => n + c.charCodeAt(0), 0);
  const initials = member?.look?.letter ? clean(member.look.letter).slice(0, 1) : label.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase();
  // your own helper is a sparkle (option A pictures); another workspace's helper keeps its letters and look
  if (label === 'Helper') return h('span', {className:'avatar chat-avatar chat-helper-pic', 'aria-hidden':'true'}, iconEl('spark'));
  const badge = h('span', {className:'avatar chat-avatar', 'aria-hidden':'true'}, initials, helper ? h('span', {className:'avatar-spark'}, '✦') : null);
  const color = member?.look?.color;
  badge.style.color = palette[hash % palette.length];
  badge.style.backgroundColor = 'color-mix(in srgb, ' + palette[hash % palette.length] + ' 14%, transparent)';
  if (typeof color === 'string' && CSS.supports('color', color)) { badge.style.backgroundColor = color; badge.style.color = 'var(--text)'; }
  return badge;
}
// One search box at a time: the list's while chatting, Earlier's own while Earlier is open.
function chatSearch(history = false) {
  return h('input', {type:'search', className:'chat-search', 'data-key':history ? 'history-search' : 'chat-search',
    'data-chat-input':history ? 'historySearch' : 'search', 'aria-label':history ? 'Search earlier chats' : 'Search chats',
    placeholder:history ? 'Search earlier chats' : 'Search chats', value:history ? chatUi.historySearch : chatUi.search});
}
// The thread title and the Chat row carry the workspace name; body text and labels call the AI "your helper".
const CHAT_HELPER = 'Your helper';
const chatLocalDay = d => [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')].join('-');
const chatToday = () => state?.chat?.day || chatLocalDay(new Date(state?.now || Date.now()));
// A time today reads "09:11" (as in ticket chats); an older one reads as its day, with its time inside a thread.
const chatWhen = (at, withTime = false) => !at ? '' : chatLocalDay(new Date(at)) === chatLocalDay(new Date(state?.now || Date.now())) && window.UI?.clock ? window.UI.clock(at) : withTime ? time(at) : date(at);
const chatHelpers = g => { const n = chatObjects(g.members).length; return n + (n === 1 ? ' helper' : ' helpers'); };
function chatListRow(g) {
  const id = g?.id || 'chat', messages = chatObjects(state?.chat?.messages), last = messages[messages.length - 1];
  const preview = g ? chatPreview(g.last) : last ? (last.by === 'you' ? 'You: ' : '') + (chatPreview(last.text) || chatFilesWord(last.files)) : 'No messages yet.';
  return h('button', {type:'button', className:'chat-list-row' + (g ? '' : ' chat-pinned'), 'data-key':'row-' + id, 'data-chat-action':'select', 'data-id':id,
    'aria-current':(chatUi.open === id || (id === 'chat' && !chatGroup() && !chatDmId(chatUi.open))) ? 'true' : null},
    g ? h('span', {className:'chat-stack'}, chatObjects(g.members).slice(0, 3).map(m => chatAvatar(m))) : chatHelperPic(),
    h('span', {className:'chat-row-text'}, chatText('strong', '', g ? g.title : CHAT_HELPER),
      g ? chatText('small', 'chat-row-meta', [chatHelpers(g), g.started ? 'started ' + chatWhen(g.started) : ''].filter(Boolean).join(' · ')) : null,
      chatText('small', 'chat-row-preview', preview)),
    h('span', {className:'chat-row-time'}, chatWhen(g ? g.last_at : last?.at), g && chatCount(g.unread) ? h('span', {className:'count', 'aria-label':chatCount(g.unread) + ' unread'}, chatCount(g.unread)) : null));
}
// With other workspaces or groups: one list grouped as the draft — This workspace (your helper), Other workspaces (direct chats), Groups.
function chatDmRow(c) {
  const last = chatDmMessages(c.ws).at(-1);
  return h('button', {type:'button', className:'chat-list-row', 'data-chat-action':'select-dm', 'data-id':c.ws, 'data-key':'row-' + c.ws,
    'aria-current':chatUi.open === c.ws ? 'true' : null}, chatAvatar(c),
    h('span', {className:'chat-row-text'}, chatText('strong', '', c.name), chatText('small', 'chat-row-preview', (last?.by === 'you' ? 'You: ' : '') + chatPreview(last?.text))),
    h('span', {className:'chat-row-time'}, chatWhen(last?.shown_at || last?.at || c.last_at)));
}
const chatGroupTime = g => Date.parse(g.last_at || g.finished || g.started) || 0;
// Other workspaces keep their place above the groups while the contacts load (or fail), instead of appearing later.
function chatDmPending() {
  if (snapshot || chatDm.loaded) return null;
  return h('div', {className:'chat-dm-pending', 'data-key':'dm-pending'}, h('h2', {}, 'Workspaces'),
    chatDm.error ? chatButton('Could not load · Try again', 'retry-dm') : chatSkeleton());
}
// The master loading shape (rows) where the dashboard's skeleton exists; the plain line when this file runs alone.
const chatSkeleton = () => typeof skeletonFor === 'function' ? skeletonFor('section') : chatText('p', 'chat-muted', 'Loading…');
// The master empty state (UI.state) with its one next step; a plain line when the kit is not loaded.
const chatEmpty = (title, text) => typeof stateNote === 'function' ? stateNote(title, text) : chatText('p', 'chat-muted', title);
// The list (option A of lane chat-messenger): "Chats" with New chat, search, your helper pinned on top with its status
// dot, then Tickets (pages/ticketchat.js), Workspaces, Groups and Finished groups; each row with two preview lines.
function chatList() {
  // Newest group first, so an old group never sits above a fresh one.
  const byTime = (a, b) => chatGroupTime(b) - chatGroupTime(a), query = chatUi.search.toLowerCase();
  const groups = chatGroups().filter(g => !chatFinished(g)).sort(byTime), finished = chatGroups().filter(chatFinished).sort(byTime);
  const dms = chatDm.contacts.filter(c => c.count > 0 || chatDmMessages(c.ws).length || chatUi.open === c.ws)
    .sort((a, b) => (Date.parse(b.last_at) || 0) - (Date.parse(a.last_at) || 0));
  const helperRow = chatListRow(null), dmRows = dms.map(chatDmRow), groupRows = groups.map(chatListRow), doneRows = finished.map(chatListRow);
  const rows = [helperRow, ...dmRows, ...groupRows, ...doneRows];
  rows.forEach(row => { row.hidden = !row.textContent.toLowerCase().includes(query); });
  const heading = (text, list) => list.length && list.some(row => !row.hidden) ? h('h2', {}, text) : null;
  return h('aside', {className:'chat-list', 'aria-label':'Chats', 'data-key':'chat-list'},
    h('div', {className:'chat-list-head'}, h('h1', {className:'chat-list-title', 'data-key':'chat-list-title'}, 'Chats'),
      snapshot ? null : h('button', {type:'button', className:'btn outline sm', 'data-chat-action':'contacts', 'data-key':'new-chat'}, iconEl('plus'), 'New chat')),
    chatSearch(), helperRow, h('hr', {className:'chat-list-rule'}),
    heading('Workspaces', dmRows), dmRows, dmRows.length ? null : chatDmPending(), heading('Groups', groupRows), groupRows,
    heading('Finished groups', doneRows), doneRows,
    rows.every(row => row.hidden) ? chatText('p', 'chat-muted', 'No chats match.') : null);
}
// The grouped list shows only when there is something besides the helper chat (a live group or a workspace chat); an open
// group or workspace chat (a deep link) always keeps it, so nothing becomes unreachable.
// let: pages/ticketchat.js adds the ticket chats
let chatRich = () => true;
function chatOpenAgent() {
  if (snapshot) return;
  chatUi.agentConversation = false; chatUi.newConversation = false; // the existing helper conversation, with its history
  chatUi.open = 'chat'; chatUi.day = null; chatUi.listOpen = false; chatUi.sheet = null; chatUi.filter = 'all';
  location.hash = '#chat'; render();
}
function chatConversation() {
  const messages = chatObjects(state?.chat?.messages);
  if (chatUi.newConversation) return [];
  if (!chatUi.agentConversation) return messages;
  const start = messages.findLastIndex(m => m.convo_start);
  return messages.slice(Math.max(0, start));
}
function chatMovedBanner(moved) {
  return h('div', {className:'chat-archive-banner'}, 'This conversation now belongs to ticket ', clean(moved.key), ' · ',
    h('a', {href:chatLink(moved.id)}, 'Open ticket'));
}
// "New chat" picks who to talk to: your helper, a workspace or your phone (no checkbox in the page any more).
function chatNewChatPick(who) {
  if (who === 'phone') { chatOpenAgent(); chatUi.filter = 'phone'; }
  else { chatOpenAgent(); chatUi.filter = 'all'; }
  render();
}
function chatNewChatRows(onPick) {
  return [['helper', 'Your helper'], ['phone', 'Your phone']].map(([who, label]) => {
    const row = h('button', {type:'button', className:'chat-contact', 'data-key':'pick-' + who}, chatText('strong', '', label));
    row.addEventListener('click', () => { chatNewChatPick(who); if (onPick) onPick(); });
    return row;
  });
}
// What your helper is doing (option A): one line under its name, the same dot on its picture in the list. Starting a
// helper stays a small outlined button, never the filled one.
function chatPresence() {
  const blocked = chatHelperBlocked();
  if (blocked) return {state:'stopped', text:'Stopped · ' + blocked.replace(/\.$/, ''), action:'fix'};
  if (array(state?.services).some(x => x && x.running === false)) return {state:'off', text:'Not running', action:'start'};
  let rows = [];
  try { rows = array(window.DashHelpers?.helperRows?.(tickets(), state?.runs)).filter(r => r.state === 'working' && !r.finished); } catch { rows = []; }
  if (state?.chat?.running) return {state:'working', text:'Writing an answer'};
  if (rows.length === 1) return {state:'working', text:'Working on ' + chatPlainTitle(rows[0].ticket?.title, rows[0].ticket?.key)};
  if (rows.length) return {state:'working', text:'Working on ' + rows.length + ' tickets'};
  return {state:'ready', text:'Ready to answer'};
}
function chatHelperPic() {
  const p = chatPresence();
  return h('span', {className:'presence', 'data-key':'helper-pic'}, chatAvatar('Helper', true), h('span', {className:'presence-dot' + (p.state === 'off' ? '' : ' ' + p.state), 'aria-hidden':'true'}));
}
function chatPresenceLine() {
  const p = chatPresence();
  return h('p', {className:'chat-head-meta', 'data-key':'helper-status'}, clean(p.text),
    p.action === 'start' && !snapshot ? h('button', {type:'button', className:'btn outline sm', 'data-action':'start', 'data-key':'helper-start'}, 'Start helper') : null,
    p.action === 'fix' ? h('a', {className:'btn outline sm', href:'#settings/helper'}, 'See what to fix') : null);
}
function chatHeader(g) {
  const agent = !g && chatUi.agentConversation, moved = !g ? chatConversation().at(-1)?.moved_to : null;
  const title = g?.title || (!g && chatUi.filter === 'phone' ? 'Your phone' : (agent && !chatConversation().length ? 'New conversation with your helper' : CHAT_HELPER));
  const helper = !g, others = g ? chatObjects(g.members).filter(m => m.ws !== 'you').length : 0;
  return h('header', {className:'chat-thread-head', 'data-key':'thread-head'},
    h('div', {className:'chat-head-top'}, chatButton('‹ Chats', 'back', {className:'chat-button chat-back'}),
      helper ? chatHelperPic() : null,
      h('div', {className:'chat-head-text'}, h('h2', {'data-key':'chat-title', tabindex:'-1'}, clean(title)),
        g ? chatText('p', 'chat-head-meta', 'Group · ' + others + (others === 1 ? ' workspace' : ' workspaces')) : chatPresenceLine()),
      g ? chatButton('Members', 'members', {id:'chat-members-button'}) : null,
      g && ticketOf(g.ticket) ? h('a', {className:'btn outline sm', href:chatLink(g.ticket)}, 'Open the ticket') : null),
    agent ? chatText('p', 'chat-muted', 'Talk it through first. When you are ready, the helper can make the ticket.') : null,
    moved ? h('a', {className:'chat-ticket-link', href:chatLink(moved.id)}, 'Ticket ', h('span', {className:'chat-member-chip'}, clean(moved.key)), ' · ', clean(chatPlainTitle(moved.title, moved.key))) : null,
    g ? h('div', {className:'chat-member-chips'}, chatObjects(g.members).map(m =>
      h('span', {className:'chat-member-chip' + (m.running === false ? ' chat-stopped' : '')}, chatAvatar(m), clean(m.name), m.running === false ? ' · not running' : ''))) : null);
}
// "From my phone": what you sent from your phone and the answers to it.
function chatPhoneOnly(messages) {
  const sent = new Set(messages.filter(m => m.via === 'phone').map(m => m.id));
  return messages.filter(m => m.via === 'phone' || sent.has(m.reply_to));
}
function chatRefs(refs, prefix, mid, readOnly = false) {
  return chatObjects(refs).map((ref, i) => {
    const key = prefix + '-ref-' + i;
    // A made proposal is a ticket like any other: the same card, with its status and actions.
    if (ref.kind === 'proposal' && ref.made?.id) return chatTicketCard({kind:'ticket', id:ref.made.id, key:ref.made.key, title:ref.title}, key, readOnly, true);
    if (ref.kind === 'proposal') return ref.made ? null : chatButton('Make ticket: ' + clean(ref.title).slice(0, 80), 'make-ticket', {className:'btn outline', 'data-key':key, 'data-id':mid, disabled:snapshot || readOnly || chatUi.pending.has(mid)});
    if (ref.kind === 'ticket' && ref.id) return chatTicketCard(ref, key, readOnly);
    if (ref.kind === 'reference' && chatHttp(ref.url)) return h('a', {className:'chat-card', 'data-key':key, href:chatHttp(ref.url), target:'_blank', rel:'noopener noreferrer'}, chatText('strong', '', ref.title || 'Reference'), chatText('small', '', new URL(ref.url).hostname));
    if (ref.kind === 'file') return h('div', {'data-key':key, className:'chat-file-ref'}, chatButton(clean(ref.title || 'File') + ' · ' + clean(String(ref.path || '').split('/').pop()), 'file', {className:'file-card', 'data-id':key, 'aria-expanded':String(chatUi.files.has(key)), 'aria-controls':key + '-path'}), h('small', {className:'chat-file-path', id:key + '-path', hidden:!chatUi.files.has(key)}, clean(ref.path)));
    return null;
  });
}
// Ticket cards (option A): the ticket picture, its key and Open on top, the plain title (with when it is due), then
// one line with a dot: what the ticket is doing, how many steps are done. No Details toggle: the facts are shown.
const CHAT_CODE = '\\b(?=[0-9A-F-]*\\d)[0-9A-F]{4,}-[0-9A-F]{6,}\\b';
const CHAT_DAY = /,?\s+(?:on\s+)?(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+\d{1,2}\s+[A-Z][a-z]{2,}\.?$/;
// Machine ids leave the shown title too (Details keeps the full one): a tag such as "[0911]", and a lowercase
// generated name such as "mwbzgkii" or "mwbvn2j7" (five consonants up front, or letters with a digit inside).
const CHAT_TAG = /\s*\[[A-Za-z0-9_-]{1,16}\]/g;
const CHAT_ID = /\s*\b(?=[a-z0-9]{6,16}\b)(?:[bcdfghjklmnpqrstvwxz]{5}[a-z0-9]*|(?=(?:\d*[a-z]){4})[a-z]+\d[a-z0-9]*[a-z])\b/g;
function chatPlainTitle(title, key = '', due = false) {
  let text = clean(title).split(/(?<=[.!?])\s+(?=[A-Z])/)[0];
  if (key) text = text.split(key).join('');
  text = text.replace(CHAT_TAG, '').replace(CHAT_ID, '');
  text = text.replace(new RegExp('\\s*\\([^()]*' + CHAT_CODE + '[^()]*\\)', 'g'), '')
    .replace(new RegExp('\\s*[–—-]\\s+[^,–—()]*?' + CHAT_CODE, 'g'), '').replace(new RegExp('\\s*' + CHAT_CODE, 'g'), '');
  if (due) text = text.replace(CHAT_DAY, '');
  return text.replace(/^[\s,;:·–—-]+|[\s,;:·–—.-]+$/g, '') || clean(title);
}
function chatDue(due, status = '') {
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(String(due || ''))) return window.DashHelpers.dueWords(due, status, new Date(state?.now || Date.now()));
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(due || ''))) return '';
  const shift = n => { const d = new Date(state?.now || Date.now()); d.setDate(d.getDate() + n); return chatLocalDay(d); };
  return due === shift(0) ? 'today' : due === shift(1) ? 'tomorrow' : due === shift(-1) ? 'yesterday' : date(due);
}
function chatTicketCard(ref, key, readOnly, made = false) {
  const ticket = ticketOf(ref.id), due = chatDue(ticket?.due, ticket?.status), title = chatPlainTitle(ref.title || ticket?.title, ref.key || ticket?.key, !!due);
  const open = chatObjects(ticket?.questions).filter(q => q.answer == null), q = open[0];
  // A person's OK is the one status that gets the accent colour.
  const word = open.length ? 'Needs your OK' : ticket?.status ? window.DashHelpers.statusWord(ticket.status) : '';
  const steps = array(ticket?.checklist), done = steps.filter(c => window.DashHelpers.resolved ? window.DashHelpers.resolved(c) : c?.done).length;
  const fact = open.length ? clean(q?.text) : steps.length ? done + ' of ' + steps.length + (steps.length === 1 ? ' step' : ' steps') + ' done' : '';
  const pending = q ? chatUi.pending.has('answer-' + ticket.id + '-' + q.id) : false;
  // Only actions the ticket already offers: a plain question's options (one tap, like Home), else Answer on
  // the ticket; a ticket to check gets Looks good / Send back. Nothing in a day you can only read.
  const actions = readOnly || snapshot || !ticket ? null : q ? q.kind == null && array(q.options).length
    ? array(q.options).slice(0, 4).map((option, i) => chatButton(option, 'answer', {'data-key':key + '-answer-' + i, 'data-ticket':ticket.id, 'data-q':q.id, 'data-digest':q.digest, 'data-answer':option, disabled:pending}))
    : h('a', {className:'chat-button', href:chatLink(ticket.id)}, 'Answer')
    : ticket.status === 'review' && typeof reviewActions === 'function' ? reviewActions(ticket) : null;
  // ORCH-1812: Make ticket only makes it; until a helper ran, the made card has the dashboard's one Start (pages/start.js).
  const start = made && !actions && ticket && !readOnly && !snapshot && typeof startHost === 'function'
    && !['review', 'done', 'dropped', 'superseded'].includes(ticket.status)
    && window.DashHelpers.agentLine?.(ticket, state?.runs?.[ticket.id], Date.now(), null, state?.settings)?.state === 'new'
    ? startHost(ticket, key + '-start') : null;
  const tone = open.length ? ' chat-needs-ok' : ticket?.status === 'active' ? ' chat-working' : ticket?.status === 'done' ? ' chat-done' : '';
  return h('article', {className:'chat-card chat-ticket', 'data-key':key},
    h('div', {className:'chat-ticket-top'}, iconEl('ticket'), chatText('span', 'chat-ticket-key', ref.key || ticket?.key || ''),
      h('a', {className:'chat-ticket-open', href:chatLink(ref.id), 'aria-label':'Open ' + clean(title)}, 'Open ›')),
    h('a', {className:'chat-ticket-title', href:chatLink(ref.id)}, chatText('strong', '', [title, due].filter(Boolean).join(' · '))),
    word ? h('p', {className:'chat-ticket-state' + tone}, chatText('span', 'chat-status' + (open.length ? ' chat-needs-ok' : ''), word), fact ? ' · ' + fact : '') : null,
    actions || start ? h('div', {className:'chat-actions'}, actions || start) : null);
}
function chatTask(task, g, readOnly) {
  const member = chatObjects(g.members).find(m => m.ws === task.ws) || {name:task.name};
  const who = clean(task.name || member.name) || 'Workspace';
  const labels = {waiting_start:'Waiting for ' + who + ' to start', waiting_approval:'Waiting for approval', queued:'Queued', working:'Working', 'done':'Done', failed:'Failed', denied:'Said no'};
  return h('div', {className:'chat-card chat-task'}, chatText('strong', '', 'Task for ' + who),
    h('div', {className:'chat-task-title'}, chatAvatar(member), chatText('strong', '', [task.key, task.title].filter(Boolean).join(' · '))),
    h('span', {className:'chat-status ' + (task.status === 'working' ? 'chat-working' : '')}, clean(labels[task.status] || task.status || 'Queued'), task.status === 'done' && task.result?.text ? ' · ' + clean(task.result.text) : ''),
    chatText('small', '', [task.at ? 'Started ' + time(task.at) : '', who + ' helper'].filter(Boolean).join(' · ')),
    chatObjects(task.result?.files).map(file => chatText('span', 'chat-file-chip', file.title)),
    h('div', {className:'chat-actions'}, task.can_open && chatHttp(task.url) ? h('a', {className:'chat-button', href:chatHttp(task.url), target:'_blank', rel:'noopener noreferrer'}, 'Open ', clean(task.key), ' ›') : null,
      null));
}
const chatTaskWord = status => ({waiting_start:'waiting to start', waiting_approval:'waiting for approval', queued:'queued', working:'working', done:'done', failed:'failed', denied:'said no'}[status] || '');
function chatApproval(m, g, index, readOnly) {
  const ev = m.group_event, member = m.member || ev.member || ev, ws = member.ws || ev.ws || m.task?.ws;
  const delegate = member.delegate || ev.delegate || m.task?.delegate || m.delegate;
  const resolved = chatObjects(g.messages).slice(index + 1).some(next => ['approved', 'denied'].includes(next.group_event?.kind) && (next.group_event.ws || next.member?.ws) === ws && (next.group_event.delegate || next.member?.delegate || next.delegate) === delegate);
  if (resolved) return null;
  const who = clean(member.name || ev.name || m.task?.name) || 'Workspace';
  const key = 'approval-' + g.id + '-' + (m.id || index);
  const pending = chatUi.pending.get(key) === JSON.stringify(m);
  return h('article', {className:'chat-card chat-approval', 'data-key':key}, chatText('strong', '', who + ': let ' + chatHost(g) + ' give tasks?'),
    chatText('small', '', 'Answer on your phone or in ' + who));
}
function chatEvent(ev, g) {
  const who = clean(ev.name) || 'Workspace';
  const words = {created:'Group started from ticket ' + clean(g.key) + ' · ' + clean(g.title), member_added:chatHost(g) + ' helper added ' + who + ' to this group', member_left:who + ' left the group', approved:'You allowed ' + who + ' ' + clean(ev.mode || 'once') + ' · ' + who + ' joined', denied:'You said no to ' + who, closed:'This group is finished. You find it under Earlier.'};
  return clean(ev.text || words[ev.kind] || '');
}
// The files a person added to a Chat message (ORCH-2171): small cards that open the file from the Chat ticket.
const chatFileSize = n => !Number.isFinite(n) || n <= 0 ? '' : n < 1048576 ? Math.max(1, Math.round(n / 1024)) + ' KB' : (n / 1048576).toFixed(1) + ' MB';
const chatFilesWord = files => { const n = chatObjects(files).length; return !n ? '' : n === 1 ? clean(files[0].name) : n + ' files'; };
function chatFileCards(files, key) {
  const list = chatObjects(files).filter(f => typeof f.name === 'string' && f.name), gid = state?.chat?.ticket;
  if (!list.length) return null;
  return h('div', {className:'file-cards', 'data-key':key + '-files'}, list.map((f, i) => {
    const body = [iconEl(/\.(png|jpe?g|gif|webp|heic)$/i.test(f.name) ? 'image' : 'file'), clean(f.name), chatText('span', 'meta', chatFileSize(f.size))];
    return gid ? h('a', {className:'file-card', 'data-key':key + '-file-' + i, target:'_blank', rel:'noopener',
      href:'/api/file?t=' + encodeURIComponent(gid) + '&k=artifacts&n=' + encodeURIComponent(f.name)}, ...body) : h('span', {className:'file-card'}, ...body);
  }));
}
// One plain line under your own message when it says something (accepted with lane chat-messenger): the answer is on
// its way, it did not go out (Try again), or it waits because your helper is not running.
function chatState(kind, text, retry) {
  return h('p', {className:'msg-state' + (kind ? ' ' + kind : ''), role:'status', 'data-key':'msg-state'}, clean(text),
    retry ? chatButton('Try again', 'retry-say', {className:'btn outline sm', 'data-id':retry}) : null);
}
const CHAT_GROUP_MS = 5 * 60 * 1000;
function chatMessage(m, previous, g, index, readOnly, lastMine, after = null) {
  const key = 'message-' + (m.id || index), mine = m.by === 'you';
  if (g && m.group_event) return m.group_event.kind === 'approval_needed' ? chatApproval(m, g, index, readOnly) : chatText('div', 'chat-system', chatEvent(m.group_event, g));
  const member = g ? chatObjects(g.members).find(item => item.ws === m.by) || {name:m.name} : {name:'Helper'};
  const sender = mine ? 'You' : clean(g ? m.name || (member.name ? member.name + ' helper' : 'Helper') : CHAT_HELPER);
  // Rows (option A): picture, name and time once; the next message by the same writer within five minutes joins it.
  const near = previous && Math.abs((Date.parse(m.at) || 0) - (Date.parse(previous.at) || 0)) < CHAT_GROUP_MS;
  const grouped = previous && !previous.group_event && previous.by === m.by && near;
  const delivered = mine && index === lastMine && g?.delivered?.text ? chatState('', g.delivered.text) : null;
  return h('article', {className:'thread-line chat-message' + (mine ? ' chat-out' : '') + (grouped ? ' cont chat-grouped' : ''), 'data-key':key, 'data-message-id':m.id, tabindex:'-1'},
    mine ? chatAvatar('You') : chatAvatar(member, true),
    h('div', {className:'thread-line-body'},
      grouped ? null : h('div', {className:'thread-line-head'}, sender, g && member.ws && !mine ? chatText('span', 'chat-ws-label', member.name + ' workspace') : null,
        chatText('span', 'meta' + (m.via === 'phone' ? ' chat-from-phone' : ''), [chatWhen(m.at, true), m.via === 'phone' ? 'from your phone' : '', m.to_everyone ? 'to everyone' : ''].filter(Boolean).join(' · '))),
      m.question_to ? chatText('small', 'chat-question', 'Question to ' + clean(m.question_to)) : null,
      m.text ? chatText('div', 'thread-line-text chat-message-text', m.text) : null, chatRefs(m.refs, key, m.id, readOnly),
      chatFileCards(m.files, key),
      g && m.task ? chatTask(m.task, g, readOnly) : null,
      g && m.added_to ? h('a', {className:'chat-card', href:chatLink(g.ticket)}, 'Added to ', clean(m.added_to.key), ' › ', clean(m.added_to.label)) : null,
      m.share ? chatText('span', 'chat-file-chip', m.share.title || m.share.kind) : null,
      delivered, after));
}
const CHAT_PROMPTS = [['Plan something', 'Help me plan my week'], ['Compare options', 'Help me compare two options'], ['Check a result', 'What is still open this week?']];
// Empty chat in the new frame: the three starters, drawn as a first message from your helper.
function chatWelcome() {
  return h('article', {className:'thread-line chat-welcome', 'data-key':'welcome'}, chatAvatar('Helper', true),
    h('div', {className:'thread-line-body'}, h('div', {className:'thread-line-head'}, 'Talk it through with your helper'),
      chatText('p', 'chat-muted', 'Nothing written today. Start with one of these or write your own.'),
      h('div', {className:'chat-prompts'}, CHAT_PROMPTS.map(([kind, text]) => h('button', {type:'button', className:'chat-prompt', 'data-chat-action':'prompt', 'data-prompt':text, 'data-key':'prompt-' + kind},
        chatText('span', '', kind), clean(text))))));
}
const CHAT_STALL_MS = 60000;
// A group member's helper on its way (contract words, the same on the phone): its picture and one plain line.
function chatThinking(who, plain = false) {
  const label = plain || / helper$/.test(who) ? who : who + ' helper';
  return h('div', {className:'thread-line chat-message', 'data-key':'thinking-' + who}, chatAvatar(who, true),
    h('div', {className:'thread-line-body'}, h('p', {className:'msg-state'}, h('span', {className:'chat-dots', 'aria-hidden':'true'}, h('i'), h('i'), h('i')), clean(label) + ' is thinking…')));
}
function chatSharedTicket(g) {
  const ticket = g.shared_ticket;
  if (!ticket) return null;
  return h('details', {className:'chat-shared-ticket', 'data-key':'shared-ticket'}, h('summary', {}, chatText('small', '', 'From ' + chatHost(g) + ' · ' + clean(ticket.key)), chatText('strong', '', ticket.title), chatText('span', 'chat-status', ticket.status)),
    chatText('p', '', ticket.summary), ticket.question?.text ? chatText('p', '', ticket.question.text) : null,
    h('ul', {}, chatObjects(ticket.checklist).slice(0, 6).map(item => h('li', {}, h('span', {'aria-hidden':'true'}, item.wont_do ? '– ' : window.DashHelpers.resolved(item) ? '☑ ' : '☐ '), h('span', {className:'chat-sr'}, item.wont_do ? "Won't do: " : window.DashHelpers.resolved(item) ? 'done: ' : 'open: '), clean(item.text)))));
}
// Day lines: "Today", "Yesterday" or the date, whenever the day changes between two messages.
function chatDayWord(at) {
  const day = chatLocalDay(new Date(at)), now = new Date(state?.now || Date.now()), y = new Date(now); y.setDate(y.getDate() - 1);
  return day === chatLocalDay(now) ? 'Today' : day === chatLocalDay(y) ? 'Yesterday' : date(at);
}
const chatDayLine = (word, key) => h('div', {className:'day-line', 'data-key':'day-' + key}, h('span', {}, clean(word)));
// Earlier days (option A): one conversation. Scrolling up (or the button at the top) brings yesterday back under its
// own day line, read only; the Today line says once that your helper starts each day fresh.
const chatPastDays = () => chatDays.status !== 'ready' ? [] : chatObjects(chatDays.rows).map(d => d.day).filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d || '') && d !== chatToday());
function chatPast() {
  if (chatDays.status === 'idle' && !snapshot) setTimeout(() => { if (chatDays.status === 'idle') chatLoad(); }, 0);
  const days = chatPastDays(), shown = chatUi.past.filter(d => days.includes(d)), more = days.length > shown.length;
  const busy = shown.some(d => chatArchive.get(d)?.status === 'loading'), failed = shown.find(d => chatArchive.get(d)?.status === 'error');
  const top = failed ? h('div', {className:'chat-history-status', role:'status'}, 'Could not load earlier messages.', chatButton('Try again', 'retry-day', {'data-day':failed}))
    : busy ? chatHistoryStatus('loading') : more ? chatButton('Show earlier messages', 'older', {className:'btn ghost sm chat-older'}) : null;
  return fragment(top, [...shown].reverse().map(day => {
    const archive = chatArchive.get(day), messages = archive?.status === 'ready' ? chatObjects(archive.data.messages) : [];
    return fragment(chatDayLine(chatDayLabel(day), day), messages.map((m, i) => chatMessage(m, messages[i - 1], null, i, true, -1)));
  }));
}
function chatThread(g) {
  const all = chatObjects(g ? g.messages : chatConversation());
  const phoneOnly = !g && chatUi.filter === 'phone', messages = phoneOnly ? chatPhoneOnly(all) : all;
  const readOnly = snapshot || !!(g?.done || g?.closed || g?.readOnly), last = messages[messages.length - 1];
  const lastMine = messages.reduce((found, m, i) => m.by === 'you' ? i : found, -1);
  const since = Date.now() - Date.parse(last?.at);
  const waiting = !g && !state?.chat?.running && last?.by === 'you' && since >= 0 && since < 600000;
  const stopped = !g && array(state?.services).some(x => x && x.running === false);
  const stalled = !readOnly && waiting && since >= CHAT_STALL_MS; // no helper picked the message up: never "writing" for ever
  const writing = !g && !readOnly && !stopped && !stalled && (state?.chat?.running || waiting) && last?.by === 'you';
  const thinking = readOnly || !g ? [] : array(g.thinking).filter(n => typeof n === 'string');
  // what happened to your last message, said once under it
  const said = g || lastMine !== messages.length - 1 || readOnly ? null : writing ? chatState('', 'Your helper is writing…')
    : stopped && waiting ? chatState('saved', 'Saved. Your helper reads it when it starts.')
    : stalled ? chatState('saved', 'Your helper has not answered yet. It may be busy or still starting.') : null;
  const failed = g || readOnly ? [] : chatUi.failed;
  const pastDays = !g && !phoneOnly ? chatPastDays() : [];
  const logKey = 'log-' + (g?.id || 'chat');
  const rows = [];
  messages.forEach((m, i) => {
    const prev = messages[i - 1], word = g && m.at ? chatDayWord(m.at) : '';
    if (g && word && (!prev?.at || chatDayWord(prev.at) !== word)) rows.push(chatDayLine(word, (m.id || i)));
    if (m.moved_to && m.moved_to.id !== prev?.moved_to?.id) rows.push(chatMovedBanner(m.moved_to));
    rows.push(chatMessage(m, prev, g, i, readOnly, lastMine, i === lastMine ? said : null));
  });
  return fragment(g ? chatSharedTicket(g) : null,
    g?.done || g?.closed ? chatText('div', 'chat-archive-banner', 'Finished · you can read, not reply') : g?.readOnly ? chatText('div', 'chat-archive-banner', 'You can read here. Write in ' + chatHost(g) + '.') : null,
    h('div', {className:'chat-log', 'data-key':logKey, role:'log', 'aria-live':'polite', 'aria-label':g ? 'Group messages' : 'Chat messages'},
      !g && !phoneOnly ? chatPast() : null,
      g ? null : chatDayLine('Today', 'today'),
      !g && pastDays.length ? chatText('p', 'day-line-note', 'Your helper starts each day without yesterday’s conversation.') : null,
      !g && state && !state.chat ? chatHistoryStatus('loading') :
      messages.length || failed.length ? rows : !g && !phoneOnly && !readOnly ? chatWelcome() : chatText('p', 'chat-empty', phoneOnly ? 'Nothing from your phone today.' : readOnly ? 'No messages.' : 'No messages yet. Say hello below.'),
      failed.map(f => chatMessage({id:f.id, by:'you', at:f.at, text:f.text, files:f.files.map(x => ({name:x.name, size:x.size}))}, null, null, 0, true, 0,
        chatState('failed', 'Not sent. Check the connection.', f.id))),
      thinking.map(w => chatThinking(w))),
    readOnly ? snapshot ? chatText('p', 'chat-readonly', 'This is a shared copy.') : null : chatComposer(g));
}
const chatHelperBlocked = () => window.DashHelpers?.helperStartReason?.(state?.logins) || '';
// The message box (option A): the master's composer in its box layout, the same in every chat. Built once per chat
// after the page is drawn (mountChatBoxes, a mount: polling never replaces it, so typing is not interrupted).
function chatComposer(g) {
  const id = g?.id || 'chat', blocked = !g ? chatHelperBlocked() : '';
  const banner = blocked ? h('div', {className:'banner error', role:'status', id:'chat-helper-unavailable'}, h('p', {className:'grow'}, blocked), h('a', {className:'btn outline sm', href:'#settings/helper'}, 'See what to fix')) : null;
  const menu = g ? fragment(chatUi.menu ? h('div', {className:'chat-menu', id:'chat-compose-menu', role:'menu'}, [['Ask a workspace','ask'], ['Give a workspace a task','task'], ['Add a workspace','add']].map(([label, action]) => chatButton(label, action, {role:'menuitem'}))) : null,
    h('div', {className:'chat-box-tools'}, chatButton('+ Add to conversation', 'menu', {className:'btn ghost sm', 'aria-haspopup':'menu', 'aria-expanded':String(chatUi.menu), 'aria-controls':'chat-compose-menu'}))) : null;
  return h('div', {className:'chat-composer-area', 'data-key':'composer-' + id}, menu, banner,
    chatBox(id, {label:g ? 'Message the group' : 'Message your helper', attach:!g, max:g ? 2000 : 20000, blocked:!!blocked}),
    g ? chatText('p', 'chat-context', "Everyone in this group sees what you write here. Members see the group's messages from when they joined, not the rest of the " + chatHost(g) + ' ticket.') : null);
}
// The box host: the composer fills it after drawing. Without the kit (a shared copy, tests) a plain form does the same.
function chatBox(id, o) {
  if (window.UI?.composer && typeof mounts === 'object') return h('div', {className:'chat-box-host', 'data-chat-box':id, 'data-key':'chat-box-' + id + (o.blocked ? '-blocked' : ''),
    'data-label':o.label, 'data-attach':o.attach ? 'yes' : 'no', 'data-max':String(o.max || 2000), 'data-blocked':o.blocked ? 'yes' : 'no'});
  const draft = chatUi.drafts[id] || '', sending = chatUi.sending.has(id);
  return h('form', {className:'chat-compose', 'data-key':'form-' + id},
    h('textarea', {rows:1, maxLength:o.max || 2000, className:'chat-draft', 'data-key':'draft-' + id, 'data-chat-input':'draft', 'data-thread':id, 'aria-label':o.label, placeholder:o.label}, draft),
    h('button', {type:'submit', className:'chat-button chat-primary', 'data-key':'send', disabled:sending || o.blocked || !draft.trim(), 'aria-describedby':o.blocked ? 'chat-helper-unavailable' : null, 'data-state':sending ? 'sending' : draft.trim() ? 'ready' : 'empty'}, sending ? h('span', {className:'spinner', 'aria-hidden':'true'}) : iconEl('send'), sending ? 'Sending' : 'Send'));
}
function mountChatBoxes(main) {
  for (const [host, m] of mounts) if (m?.chatBox && !host.isConnected) { m.destroy(); mounts.delete(host); }
  main.querySelectorAll('[data-chat-box]').forEach(host => {
    if (mounts.has(host)) return;
    const id = host.dataset.chatBox, attach = host.dataset.attach === 'yes', box = typeof FEEDBACK_BOX === 'object' ? FEEDBACK_BOX : {};
    host.id = 'chat-box-' + String(id).replace(/[^A-Za-z0-9_-]/g, '_');
    const composer = window.UI.composer(host, {...box, voice:false, layout:'box', attach, interrupt:false, enterSends:true, sendLabel:'Send', hint:'Enter to send',
      label:host.dataset.label, placeholder:host.dataset.label, maxLength:Number(host.dataset.max) || 2000, attachLabel:'Attach',
      emptyError:attach ? 'Write something or add a file.' : 'Write something first.', dropLabel:'Drop to add to your message', sendingText:'',
      draft:chatUi.drafts[id] || '', onDraft:v => { chatUi.drafts[id] = v; }, sendAttrs:{'data-key':'send'}, fieldAttrs:{'data-thread':id},
      onSend:message => chatBoxSend(id, message)});
    if (host.dataset.blocked === 'yes') host.querySelector('[type=submit]')?.setAttribute('disabled', '');
    mounts.set(host, {chatBox:true, update() {}, destroy() { composer.destroy?.(); }});
  });
}
// The box hands its words and files to the one send of the open chat (helper, ticket, workspace or group).
async function chatBoxSend(id, message) {
  chatUi.drafts[id] = message.text; chatUi.outFiles = array(message.files);
  let r;
  try { r = await chatSend(); } finally { chatUi.outFiles = []; }
  return r && r.ok === false ? {ok:false, text:r.text || 'Not sent. Try again.'} : {ok:true, text:''};
}
function chatDayLabel(day) {
  const today = new Date((state?.chat?.day || new Date().toISOString().slice(0, 10)) + 'T12:00:00');
  today.setDate(today.getDate() - 1);
  return date(day) === date(today.toISOString()) ? 'Yesterday' : date(day);
}
function chatHistoryStatus(status, retry) {
  return h('div', {className:'chat-history-status', role:'status'}, status === 'error' ? fragment('Could not load earlier messages.', chatButton('Try again', retry)) : typeof skeletonFor === 'function' ? skeletonFor('section') : 'Loading…');
}
function chatSheet(g, readOnly) {
  const host = chatHost(g), adding = chatUi.sheet === 'add';
  const members = chatObjects(g.members), connectable = chatObjects(g.connectable);
  return h('aside', {className:'chat-sheet', role:'dialog', 'aria-modal':'true', 'aria-label':'Group members', 'data-key':'sheet-' + g.id},
    h('header', {}, h('h2', {}, adding ? 'Add a workspace' : 'Members'), chatButton('Close', 'close-sheet')),
    adding ? connectable.length ? connectable.map(m => h('div', {className:'chat-member-row', 'data-key':m.ws}, chatAvatar(m), chatText('strong', '', m.name),
      !readOnly ? chatButton('Add to group', 'add-member', {'data-ws':m.ws, 'aria-label':'Add ' + clean(m.name) + ' to group', disabled:members.some(member => member.ws === m.ws)}) : null)) : chatText('p', 'chat-muted', 'No other connected workspace.') : fragment(
      h('div', {className:'chat-member-row'}, chatAvatar('You'), h('strong', {}, 'You'), h('p', {}, 'owner')),
      !members.some(m => m.ws === g.host) ? h('div', {className:'chat-member-row'}, chatAvatar(host), chatText('strong', '', host), chatText('p', '', 'started the group from ' + clean(g.key))) : null,
      members.map(m => h('div', {className:'chat-member-row', 'data-key':m.ws}, chatAvatar(m), chatText('strong', '', m.name),
        chatText('p', '', m.ws === g.host ? 'started the group from ' + clean(g.key) : ['joined ' + time(m.joined_at), m.task ? 'task ' + clean(m.task.key) + ' ' + chatTaskWord(m.task.status) : ''].filter(Boolean).join(' · ')),
        chatText('p', 'chat-muted', 'Sees the group from ' + (time(m.joined_at) || 'when it joined')), m.running === false ? chatText('p', 'chat-muted', 'not running') : null,
        !readOnly && m.ws !== g.host && m.ws !== 'you' ? chatButton('Remove from group', 'remove', {'data-ws':m.ws, 'aria-label':'Remove ' + clean(m.name) + ' from group'}) : null)),
      !readOnly ? chatButton('Add a workspace', 'add') : null),
    chatText('footer', 'chat-muted', 'Only workspaces connected to ' + host + ' can be added. A removed workspace keeps what it already received.'));
}
// The frame (option A): the list beside the open conversation, full height, no page title; the message box stays at
// the bottom. On a phone the list and the conversation are two screens ("‹ Chats" goes back).
function chatPage() {
  const g = chatGroup();
  const page = h('section', {className:'chat-page chat-frame' + (chatUi.listOpen ? ' chat-list-open' : ' chat-thread-open'), 'data-key':'chat-page'}, chatList(),
    h('div', {className:'chat-main', 'data-key':'chat-main'}, chatHeader(g), chatThread(g),
      g && chatUi.sheet ? chatSheet(g, snapshot || g.done || g.closed || g.readOnly) : null));
  page.addEventListener('click', chatClick);
  page.addEventListener('input', chatInput);
  page.addEventListener('submit', event => { if (event.target.matches('.chat-compose')) { event.preventDefault(); chatSend(); } });
  page.addEventListener('keydown', chatKeydown);
  page.addEventListener('scroll', chatOnScroll, true);
  return fragment(page);
}
function chatOnScroll(event) {
  const log = event.target;
  if (!log.matches?.('.chat-log')) return;
  chatScroll.set(log, {near:log.scrollHeight - log.scrollTop - log.clientHeight < 80, stamp:chatLogStamp(log)});
  if (log.scrollTop < 40 && !chatGroup() && !chatDmId(chatUi.open) && !tcIdOpen()) chatOlder();
}
const tcIdOpen = () => /^t_[a-z0-9]{6,16}$/.test(String(chatUi.open || ''));
// The next earlier day, added on top without moving what you are reading.
async function chatOlder() {
  const next = chatPastDays().find(d => !chatUi.past.includes(d));
  if (!next || chatUi.past.some(d => chatArchive.get(d)?.status === 'loading')) return;
  const log = document.querySelector('.chat-page .chat-log'), from = log ? log.scrollHeight - log.scrollTop : 0;
  chatUi.past.push(next);
  await chatLoad(next);
  if (log && log.isConnected) log.scrollTop = log.scrollHeight - from;
}
function chatFocus(selector) { document.querySelector('.chat-page ' + selector)?.focus(); }
function chatSelect(id) {
  chatUi.agentConversation = false; chatUi.newConversation = false;
  chatUi.open = id; chatUi.day = null; chatUi.listOpen = false; chatUi.sheet = null; chatUi.menu = false;
  render(); chatFocus('[data-key="chat-title"]');
}
async function chatLoad(day) {
  const cache = day ? chatArchive.get(day) : chatDays;
  if (cache?.status === 'loading' || cache?.status === 'ready') return;
  if (day && !/^\d{4}-\d{2}-\d{2}$/.test(day)) return;
  const entry = {status:'loading', rows:[]};
  if (day) chatArchive.set(day, entry); else chatDays = entry;
  render();
  try {
    const result = await fetch(day ? '/api/chat/day/' + day : '/api/chat/days');
    if (!result.ok) throw new Error('History');
    const data = await result.json();
    if (day ? !data || !Array.isArray(data.messages) : !Array.isArray(data)) throw new Error('History');
    entry.status = 'ready'; if (day) entry.data = data; else entry.rows = data;
  } catch { entry.status = 'error'; }
  render();
}
async function chatOperation(op, args, failure) {
  let why = '';
  try {
    const result = await window.orchAct(op, args);
    if (result?.ok) return true;
    try { why = String(JSON.parse(result?.text || '{}').error || ''); } catch { why = ''; }  // the server's own reason
  } catch { /* Keep drafts and controls available after failure. */ }
  const base = failure || 'Could not update the group.';
  const said = why && why.length <= 160 ? base.replace(/\.$/, '') + ': ' + why.replace(/[.\s]*$/, '.') : base;
  // R8.4: the server's reason may say what to do; else the toast ends with the one next step there is
  window.orch.toast(/\b(try|run|orch [a-z]|ask|open|turn|start|pick|add|reload)\b/i.test(why) ? said : said + ' Try again.', 'error'); return false;
}
// Send: the words (and, in the helper chat, the files) of the open chat. A message that did not go out stays in the
// conversation with "Not sent" and Try again; the box is free for the next one.
async function chatSend() {
  const g = chatGroup(), id = g?.id || 'chat';
  if (snapshot || g?.done || g?.closed || chatUi.sending.has(id) || (!g && chatHelperBlocked())) return {ok:false, text:''};
  const text = String(chatUi.drafts[id] || '').trim(), files = g ? [] : array(chatUi.outFiles);
  if (!text && !files.length) return {ok:false, text:''};
  chatUi.sending.add(id); render();
  const ok = g ? await chatOperation('group.say', {ticket:g.ticket, text}, 'Could not send to the group.') : await chatSay(text, files);
  chatUi.sending.delete(id);
  if (!g && !ok) chatUi.failed.push({id:'f' + Date.now().toString(36), text, files, at:new Date().toISOString()});
  if (ok || !g) {
    if (ok && !g) chatUi.newConversation = false;
    chatUi.drafts[id] = '';
    const field = document.querySelector('.chat-page .chat-draft'); if (field) { field.value = ''; field.style.height = ''; }
  }
  render();
  return ok || !g ? {ok:true, text:''} : {ok:false, text:'Not sent. Try again.'};
}
// The helper chat's own send: the files go onto the Chat ticket first (ticket.attach, as on the ticket page), then the
// words name them (chat.say files). Any failure is "Not sent" (no toast: the line under the message says it).
async function chatSay(text, files) {
  const args = {text, ...(chatUi.newConversation || chatConversation().at(-1)?.moved_to ? {new:true} : {})};
  try {
    if (files.length) {
      const gid = state?.chat?.ticket;
      if (!gid || typeof ticketAttachFiles !== 'function') return false;
      const kept = await ticketAttachFiles(gid, files);
      if (!kept.ok) return false;
      args.files = kept.names;
    }
    const r = await window.orchAct('chat.say', args);
    return !!r?.ok;
  } catch { return false; }
}
function chatInput(event) {
  const field = event.target, kind = field.dataset.chatInput;
  if (!kind) return;
  if (kind === 'draft') {
    chatUi.drafts[field.dataset.thread] = field.value;
    field.style.height = 'auto'; field.style.height = Math.min(124, field.scrollHeight) + 'px';
    field.closest('form').querySelector('[type="submit"]').disabled = !field.value.trim() || chatUi.sending.has(field.dataset.thread) || (field.dataset.thread === 'chat' && !!chatHelperBlocked());
  } else { chatUi[kind] = field.value; render(); }
}
async function chatClick(event) {
  const control = event.target.closest('[data-chat-action]');
  if (!control || control.disabled) return;
  const action = control.dataset.chatAction, g = chatGroup();
  if (action === 'select') return chatSelect(control.dataset.id);
  if (action === 'back') { chatUi.listOpen = true; render(); return chatFocus('[data-key="chat-search"]'); }
  if (action === 'older') return chatOlder();
  if (action === 'retry-day') { chatArchive.delete(control.dataset.day); return chatLoad(control.dataset.day); }
  if (action === 'retry-say') {
    const f = chatUi.failed.find(x => x.id === control.dataset.id);
    if (!f || chatUi.sending.has('chat')) return;
    chatUi.failed = chatUi.failed.filter(x => x !== f);
    chatUi.drafts.chat = f.text; chatUi.outFiles = f.files;
    try { await chatSend(); } finally { chatUi.outFiles = []; }
    return;
  }
  if (action === 'prompt') {
    chatUi.drafts.chat = control.dataset.prompt || ''; render();
    const field = document.querySelector('.chat-page .chat-draft, .chat-page [data-thread="chat"]');
    if (field) { field.value = chatUi.drafts.chat; field.dispatchEvent(new Event('input', {bubbles:true})); field.focus(); } return;
  }
  if (action === 'filter') { chatUi.filter = control.dataset.id === 'phone' ? 'phone' : 'all'; return render(); }
  if (action === 'answer') {
    // The same answer a question card sends (op "answer"); the buttons wait while it is on its way.
    const {ticket, q, digest, answer} = control.dataset, id = 'answer-' + ticket + '-' + q;
    if (snapshot || chatUi.pending.has(id)) return;
    chatUi.pending.set(id, true); render();
    if (await chatOperation('answer', {ticket, question:q, digest, answer}, 'Could not send your answer.')) window.orch.toast('Answered: ' + clean(answer), 'ok');
    chatUi.pending.delete(id); render(); return;
  }
  if (action === 'file') { const id = control.dataset.id; chatUi.files.has(id) ? chatUi.files.delete(id) : chatUi.files.add(id); return render(); }
  if (action === 'make-ticket') {
    if (snapshot || chatUi.open === 'history' || chatUi.pending.has(control.dataset.id)) return;
    const id = control.dataset.id; chatUi.pending.set(id, true); render();
    await chatOperation('chat.make_ticket', {id}, 'Could not make the ticket.');
    chatUi.pending.delete(id); render(); return;
  }
  if (!g) return;
  if (action === 'members' || action === 'add') { if (action === 'add' && (snapshot || g.done || g.closed)) return; chatUi.sheet = action === 'add' ? 'add' : 'members'; chatUi.menu = false; render(); return chatFocus('[data-chat-action="close-sheet"]'); }
  if (action === 'close-sheet') { chatUi.sheet = null; render(); return chatFocus('#chat-members-button'); }
  if (snapshot || g.done || g.closed) return;
  if (action === 'menu') { chatUi.menu = !chatUi.menu; render(); return chatFocus(chatUi.menu ? '[role="menuitem"]' : '[data-chat-action="menu"]'); }
  if (action === 'ask' || action === 'task') {
    const who = clean(chatObjects(g.members).find(m => m.ws !== g.host && m.ws !== 'you')?.name) || 'Workspace';
    chatUi.drafts[g.id] = action === 'ask' ? who + ', ' : 'Task for ' + who + ': '; chatUi.menu = false; render();
    const field = document.querySelector('.chat-page .chat-draft, .chat-page [data-thread="' + CSS.escape(g.id) + '"]'); if (field) { field.value = chatUi.drafts[g.id]; field.dispatchEvent(new Event('input', {bubbles:true})); field.focus(); } return;
  }
  const ops = {remove:'group.remove', 'add-member':'group.add'};
  if (ops[action]) { control.disabled = true; await chatOperation(ops[action], {ticket:g.ticket, workspace:control.dataset.ws}); control.disabled = false; render(); }
}
function chatKeydown(event) {
  if (event.target.matches('.chat-draft') && event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) { event.preventDefault(); chatSend(); }
  if (event.key === 'Escape' && (chatUi.sheet || chatUi.menu)) {
    const sheet = chatUi.sheet; chatUi.sheet = null; chatUi.menu = false; render(); chatFocus(sheet ? '#chat-members-button' : '[data-chat-action="menu"]');
  }
  const menu = event.target.closest('[role="menu"]'), sheet = event.target.closest('.chat-sheet');
  if (menu && ['ArrowDown', 'ArrowUp'].includes(event.key)) {
    const items = [...menu.querySelectorAll('button')], i = items.indexOf(document.activeElement);
    event.preventDefault(); items[(i + (event.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length].focus();
  }
  if (sheet && event.key === 'Tab') {
    const items = [...sheet.querySelectorAll('button:not(:disabled),a[href]')], first = items[0], last = items[items.length - 1];
    if (event.shiftKey && event.target === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && event.target === last) { event.preventDefault(); first?.focus(); }
  }
}
// Observe committed DOM, not speculative render trees. Preserve readers' scroll position.
function chatLogStamp(log) { return log.textContent; }
// The welcome block is read from its top (on a phone it is taller than the log): never scroll it to the bottom.
function chatFollowLog(log) {
  const previous = chatScroll.get(log), stamp = chatLogStamp(log);
  if (!previous || (previous.near && previous.stamp !== stamp)) log.scrollTop = log.scrollHeight;
  chatScroll.set(log, {stamp, near:log.scrollHeight - log.scrollTop - log.clientHeight < 80});
}
new MutationObserver(() => {
  const field = document.querySelector('.chat-page .chat-draft');
  if (field) { field.style.height = 'auto'; field.style.height = Math.min(124, Math.max(44, field.scrollHeight)) + 'px'; }
  const log = document.querySelector('.chat-page .chat-log');
  if (!log || !log.clientHeight) return;
  chatFollowLog(log);
}).observe(document.documentElement, {childList:true, subtree:true, characterData:true, attributes:true, attributeFilter:['class']});

// Workspace DMs are a separate layer, so group/Chat changes can merge independently.
const chatDm = {contacts:[], threads:new Map(), pending:new Map(), loading:false, loaded:false, picker:null, error:false, lastFetch:-Infinity, timer:null};
// How often an open workspace thread looks for new texts (relay delivery is ~1 s; R8.3 wants the screen within 2 s).
const CHAT_DM_POLL = 2000;
const chatDmId = id => typeof id === 'string' && /^ws_[a-z0-9]{10}$/.test(id);
const chatDmContact = ws => chatDm.contacts.find(c => c.ws === ws);
// "Send a message" on Contacts already knows the name: the thread opens with it, before the contacts have loaded.
const chatDmNames = new Map();
const chatDmHint = (ws, name) => { if (chatDmId(ws) && typeof name === 'string' && name.trim()) chatDmNames.set(ws, name.trim().slice(0, 80)); };
// A contact's name for a raw workspace id ("agent:ws_..." as who answered): known contacts first, read once if none is
// loaded yet (the next render shows the name), else the plain "Another workspace" - never the id.
let chatDmNamesAsked = false;
function chatDmName(id) {
  const ws = String(id ?? '').replace(/^(agent|human):/, '');
  if (!chatDmId(ws)) return '';
  const c = chatDmContact(ws);
  if (c?.name) return clean(c.name);
  if (!chatDm.loaded && !chatDmNamesAsked && !snapshot) {
    chatDmNamesAsked = true;
    fetch('/api/chat/contacts').then(r => r.ok ? r.json() : null).then(list => {
      if (!Array.isArray(list) || chatDm.loaded) return;
      chatDm.contacts = chatObjects(list).filter(x => chatDmId(x.ws)); chatDm.loaded = true; render();
    }).catch(() => {});
  }
  return 'Another workspace';
}
function chatDmMessages(ws) {
  const saved = chatObjects(chatDm.threads.get(ws)?.messages), ids = new Set(saved.map(m => m.id));
  return [...saved, ...array(chatDm.pending.get(ws)).filter(m => !ids.has(m.id))];
}
async function chatDmLoad(force = false) {
  if (snapshot || route().kind !== 'chat' || document.hidden) return;  // a hidden tab does not poll
  if (chatDm.loading) return;  // a thread opened meanwhile is picked up when this load ends (see finally)
  const delay = force || (!chatDm.loaded && !chatDm.contacts.length) ? 0 : CHAT_DM_POLL - (Date.now() - chatDm.lastFetch);
  if (delay > 0) {
    if (!chatDm.timer) chatDm.timer = setTimeout(() => { chatDm.timer = null; chatDmLoad(); }, delay);
    return;
  }
  if (chatDm.timer) { clearTimeout(chatDm.timer); chatDm.timer = null; }
  chatDm.lastFetch = Date.now();
  chatDm.loading = true;
  let fetched = null;
  try {
    // The server imports new messages itself before it answers (no separate slow sync step in front of the read).
    const response = await fetch('/api/chat/contacts');
    if (!response.ok) throw new Error('Contacts');
    const contacts = await response.json();
    if (!Array.isArray(contacts)) throw new Error('Contacts');
    chatDm.contacts = chatObjects(contacts).filter(c => chatDmId(c.ws));
    chatDm.loaded = true;
    const ws = chatUi.open;  // read now: the person may have opened another thread while the contacts loaded
    if (chatDmId(ws) && chatDmContact(ws)) {
      const response = await fetch('/api/chat/thread/' + ws);
      if (!response.ok) throw new Error('Thread');
      const thread = await response.json();
      if (!Array.isArray(thread?.messages)) throw new Error('Thread');
      chatDm.threads.set(ws, thread); fetched = ws;
      const stored = new Set(thread.messages.map(m => m.id));
      chatDm.pending.set(ws, array(chatDm.pending.get(ws)).filter(m => !stored.has(m.id)));
    }
    chatDm.error = false;
  } catch { chatDm.error = true; }
  finally {
    chatDm.loading = false;
    if (chatDm.picker) chatDm.picker();
    if (route().kind === 'chat') {
      render();
      // The person opened another thread while this load ran: read that one now, not on the next 5 s tick.
      if (!chatDm.error && chatDmId(chatUi.open) && chatUi.open !== fetched && chatDmContact(chatUi.open)) chatDmLoad(true);
      else if (chatDmId(chatUi.open) && !chatDm.timer) chatDm.timer = setTimeout(() => { chatDm.timer = null; chatDmLoad(); }, CHAT_DM_POLL);
    }
  }
}
// Factory's idea box hands text to the helper chat by postMessage (same origin, from the shown shipped add-on frame only,
// never from a URL). The text lands in the draft; you press Send. A draft you already typed is kept.
function chatSayRequest(e) {
  const data = e && e.data;
  if (!data || typeof data !== 'object' || data.type !== 'orch.say' || typeof data.text !== 'string') return null;
  const chan = e.origin === 'null' && !!e.data?.chan && e.data.chan === globalThis.orchFrameChan?.();  // sandboxed frame: its code
  if ((e.origin !== location.origin && !chan) || snapshot) return null;
  const r = route();
  if (r.kind !== 'page' || !state?.addons?.find?.(a => a.name === r.id)?.shipped) return null;
  const frame = document.querySelector('iframe.embed[data-key="embed"]');
  if (!frame || !frame.contentWindow || e.source !== frame.contentWindow) return null;
  const text = data.text.replace(/[\u0000-\u001f\u007f]+/g, ' ').trim().slice(0, 500);
  return text ? {text} : null;
}
window.addEventListener('message', e => {
  const req = chatSayRequest(e); if (!req) return;
  if (!(chatUi.drafts.chat || '').trim()) chatUi.drafts.chat = req.text;
  chatUi.open = 'chat'; chatUi.listOpen = false; chatUi.filter = 'all';
  location.hash = '#chat';
});
function chatDmRoute() {
  const ws = location.hash.slice(6);
  if (chatDmId(ws)) { chatUi.open = ws; chatUi.listOpen = false; chatUi.day = null; }
  if (route().kind === 'chat') { render(); chatDmLoad(); }
}
document.addEventListener?.('visibilitychange', () => { if (!document.hidden && chatDmId(chatUi.open)) chatDmLoad(); });
window.addEventListener('hashchange', chatDmRoute);
window.addEventListener('orch:state', chatDmRoute);
window.addEventListener('DOMContentLoaded', chatDmRoute);

function chatDmContacts() {
  const {d, actions} = dialog('New chat', 'dialog');
  d.classList.add('chat-page', 'chat-contacts');
  const body = h('div', {className:'chat-contact-list'});
  const paint = () => {
    const rows = [...chatNewChatRows(() => window.orch.close(d))];
    for (const c of chatDm.loaded ? chatDm.contacts : []) {
      const can = c.can || {}, allowed = can.chat || can.tasks || can.files;
      const row = h('button', {type:'button', className:'chat-contact', disabled:!allowed}, chatText('strong', '', c.name),
        h('span', {className:'chat-member-chips'},
          can.chat ? chatText('small', 'chat-member-chip', can.files ? 'Can read and send messages and files' : 'Can read and send messages') : null,
          can.files && !can.chat ? chatText('small', 'chat-member-chip', 'Files') : null,
          can.tasks ? chatText('small', 'chat-member-chip', 'Give tasks') : null,
          !allowed ? chatText('small', 'chat-member-chip', 'No access') : null));
      row.addEventListener('click', async () => { chatDm.picker = null; await window.orch.close(d); chatDmSelect(c.ws); });
      rows.push(row);
    }
    if (!chatDm.loaded) {
      if (chatDm.error && !chatDm.loading) {
        const retry = h('button', {type:'button', className:'chat-button'}, 'Try again');
        retry.addEventListener('click', () => { chatDm.error = false; paint(); chatDmLoad(true); });
        rows.push(chatText('p', 'chat-muted', 'Could not load contacts.'), retry);
      } else rows.push(chatSkeleton());
    } else if (!chatDm.contacts.length) rows.push(chatEmpty('No contacts yet', 'Other workspaces show up here once your admin has paired them with yours.'));
    body.replaceChildren(...rows);
  };
  chatDm.picker = paint; paint();
  d.addEventListener('close', () => { if (chatDm.picker === paint) chatDm.picker = null; });
  d.append(body, actions); window.orch.open(d);
}
function chatDmSelect(ws) {
  if (!chatDmId(ws)) return;
  chatUi.open = ws; chatUi.listOpen = false; chatUi.sheet = null;
  location.hash = '#chat/' + ws; render(); chatDmLoad();
  chatFocus('[data-key="chat-title"]');
}
function chatDmThread() {
  const ws = chatUi.open, c = chatDmContact(ws), title = c?.name || chatDmNames.get(ws) || 'Workspace', messages = chatDmMessages(ws);
  return h('div', {className:'chat-main', 'data-key':'dm-' + ws},
    h('header', {className:'chat-thread-head'}, h('div', {className:'chat-head-top'}, chatButton('‹ Chats', 'back', {className:'chat-button chat-back'}), chatAvatar(c || title),
      // The name once; under it ONE line about the workspace (its description, then small tags). No repeated name.
      h('div', {className:'chat-head-text'}, h('h2', {'data-key':'chat-title', tabindex:'-1'}, clean(title)),
        c?.description ? chatText('p', 'chat-muted chat-head-meta chat-desc', clean(c.description)) : null,
        array(c?.tags).length ? h('p', {className:'chat-member-chips chat-tags'}, array(c.tags).slice(0, 6).map(t => chatText('small', 'chat-member-chip', clean(t)))) : null))),
    chatDm.error ? chatButton('Could not load messages · Try again', 'retry-dm') : null,
    h('div', {className:'chat-log', 'data-key':'log-' + ws, role:'log', 'aria-live':'polite'}, !c && !messages.length && !chatDm.error ?
      (chatDm.loaded ? chatEmpty('This workspace is not in your contacts', 'Go back to your chats and pick one from the list.') : chatSkeleton()) : null, messages.map((m, i) => {
        const mine = m.by === 'you', prev = messages[i - 1], at = m.shown_at || m.at;
        const grouped = prev && prev.by === m.by && Math.abs((Date.parse(at) || 0) - (Date.parse(prev.shown_at || prev.at) || 0)) < CHAT_GROUP_MS;
        return h('article', {className:'thread-line chat-message' + (mine ? ' chat-out' : '') + (grouped ? ' cont' : ''), 'data-key':'message-' + m.id},
          mine ? chatAvatar('You') : chatAvatar(c || title),
          h('div', {className:'thread-line-body'}, grouped ? null : h('div', {className:'thread-line-head'}, mine ? 'You' : clean(title), chatText('span', 'meta', at ? time(at) : '')),
            chatText('div', 'thread-line-text chat-message-text', m.text),
            mine && m.state === 'failed' ? h('p', {className:'msg-state failed chat-delivery'}, 'Not sent. Check the connection.', chatButton('Try again', 'retry-send', {className:'btn outline sm', 'data-id':m.id})) :
            mine && m.state !== 'delivered' ? h('p', {className:'msg-state chat-delivery'}, 'Sending…') :
            mine && i === messages.length - 1 ? h('p', {className:'msg-state chat-delivery'}, 'Delivered') : null));
      })),
    !snapshot && c?.can?.chat ? h('div', {className:'chat-composer-area', 'data-key':'composer-' + ws}, chatBox(ws, {label:'Message ' + title, attach:false, max:2000})) : null);
}
const chatPageWithoutDm = chatPage;
chatPage = function () {
  if (!chatDmId(chatUi.open)) return chatPageWithoutDm();
  const page = h('section', {className:'chat-page chat-frame' + (chatUi.listOpen ? ' chat-list-open' : ' chat-thread-open'), 'data-key':'chat-page'}, chatList(), chatDmThread());
  page.addEventListener('click', chatClick); page.addEventListener('input', chatInput); page.addEventListener('keydown', chatKeydown);
  page.addEventListener('submit', e => { e.preventDefault(); chatSend(); });
  return fragment(page);
};
const chatClickWithoutDm = chatClick;
chatClick = async function (event) {
  const control = event.target.closest('[data-chat-action]');
  if (!control || control.disabled) return;
  const action = control.dataset.chatAction;
  if (action === 'contacts') { chatDmContacts(); return chatDmLoad(true); }
  if (action === 'select-dm') return chatDmSelect(control.dataset.id);
  if (action === 'retry-dm') { chatDm.error = false; return chatDmLoad(true); }
  if (action === 'retry-send') {
    const message = chatDmMessages(chatUi.open).find(m => m.id === control.dataset.id);
    if (message?.state === 'failed') return chatDmSend(message.text, message.id);
    return;
  }
  if (action === 'select' || action === 'history') {
    // Update the hash without a second selection event that could discard the chosen group.
    history.replaceState(null, '', '#chat');
  }
  return chatClickWithoutDm(event);
};
const chatSendWithoutDm = chatSend;
chatSend = async function () {
  if (!chatDmId(chatUi.open)) return chatSendWithoutDm();
  const text = (chatUi.drafts[chatUi.open] || '').trim();
  if (text) await chatDmSend(text);
  return {ok:true, text:''};
};
function chatDmClientId() {
  const alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let id = 'm_';
  while (id.length < 18) {
    for (const byte of crypto.getRandomValues(new Uint8Array(24))) {
      if (byte < 252 && id.length < 18) id += alphabet[byte % 36];
    }
  }
  return id;
}
async function chatDmSend(text, retryId) {
  const ws = chatUi.open;
  if (snapshot || !chatDmContact(ws)?.can?.chat || chatUi.sending.has(ws) || !text || text.length > 2000) return;
  const pending = chatDm.pending.get(ws) || [];
  const stored = chatObjects(chatDm.threads.get(ws)?.messages).find(m => m.id === retryId);
  const previous = !stored && pending.find(m => m.id === retryId);
  const entry = previous || {id:chatDmClientId(), by:'you', text, state:'sending', ...(stored ? {retry:retryId} : {})};
  entry.state = 'sending';
  if (!previous) pending.push(entry);
  chatDm.pending.set(ws, pending);
  if (stored) {
    const saved = chatDm.threads.get(ws);
    saved.messages = saved.messages.filter(m => m.id !== retryId);
  }
  if (!retryId) {
    chatUi.drafts[ws] = '';
    const field = document.querySelector('.chat-page .chat-draft');
    if (field) { field.value = ''; field.style.height = ''; }
  }
  chatUi.sending.add(ws); render();
  let accepted = false;
  try {
    const result = await window.orchAct('chat.send_ws', {workspace:ws, text, client_id:entry.id, ...(entry.retry ? {retry:entry.retry} : {})});
    const saved = result?.state?.chat_dm_result;
    if (result?.ok && saved?.id) { Object.assign(entry, saved); accepted = true; }
  } catch { /* Reconcile a possibly stored send before reporting failure. */ }
  finally {
    // Accepted: show "Delivered" now and refresh in the background. Unknown: read the thread first (it may be stored).
    if (!accepted) { await chatDmLoad(true); entry.state = 'failed'; }
    chatUi.sending.delete(ws); render();
    if (accepted) chatDmLoad(true);
  }
}


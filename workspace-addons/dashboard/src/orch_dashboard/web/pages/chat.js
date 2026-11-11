'use strict';
// Classic-script page: rendering is side-effect free; events own requests and UI state.
// The thread is open by default (on a narrow screen "‹ Chats" goes back to the list).
let chatUi = {open:'chat', agentConversation:false, newConversation:false, day:null, listOpen:false, sheet:null, filter:'all', search:'', historySearch:'', menu:false,
  drafts:Object.create(null), sending:new Set(), pending:new Map(), files:new Set(), historyFocus:null};
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
  return {id:g.id, ticket:g.ticket, host:host?.ws, title:g.title || ticket?.title, key:typeof ticket?.key === 'string' ? ticket.key : '', closed:g.closed, done:g.closed,
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
const chatGroups = () => [...chatObjects(state?.groups?.hosted).map(chatHostedGroup), ...chatObjects(state?.groups?.joined).map(chatJoinedGroup)];
const chatGroup = () => chatGroups().find(g => g.id === chatUi.open);
// The name people see: look name when the switcher has one, else the workspace name with a capital.
const chatWorkspace = () => { const n = clean(state?.look?.workspaces?.find(w => w.here)?.name || state?.workspace) || 'Workspace'; return n.charAt(0).toUpperCase() + n.slice(1); };
const chatHost = g => clean(chatObjects(g.members).find(m => m.ws === g.host)?.name || g.host_name) || chatWorkspace();
const chatCount = n => Math.max(0, Number(n) || 0);
const chatText = (tag, cls, text) => h(tag, {className:cls}, clean(text));
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
  const badge = h('span', {className:'chat-avatar', 'aria-hidden':'true'}, clean(member?.look?.letter || label[0]).slice(0, 1), helper ? h('span', {className:'chat-spark'}, '✦') : null);
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
// One name for the AI a person talks to: "your helper" (the workspace name stays on the avatar only).
const CHAT_HELPER = 'Your helper';
const chatLocalDay = d => [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')].join('-');
const chatToday = () => state?.chat?.day || chatLocalDay(new Date(state?.now || Date.now()));
// A time today reads "09:11"; an older one reads as its day.
const chatWhen = at => !at ? '' : chatLocalDay(new Date(at)) === chatLocalDay(new Date(state?.now || Date.now())) ? time(at) : date(at);
const chatHelpers = g => { const n = chatObjects(g.members).length; return n + (n === 1 ? ' helper' : ' helpers'); };
function chatListRow(g) {
  const id = g?.id || 'chat', messages = chatObjects(state?.chat?.messages), last = messages[messages.length - 1];
  return h('button', {type:'button', className:'chat-list-row', 'data-key':'row-' + id, 'data-chat-action':'select', 'data-id':id,
    'aria-current':(chatUi.open === id || (id === 'chat' && chatUi.open !== 'history' && !chatGroup())) ? 'true' : null},
    g ? h('span', {className:'chat-stack'}, chatObjects(g.members).slice(0, 3).map(m => chatAvatar(m))) : chatAvatar(chatWorkspace()),
    h('span', {className:'chat-row-text'}, chatText('strong', '', g ? g.title : CHAT_HELPER),
      g ? chatText('small', 'chat-row-meta', [chatHelpers(g), g.started ? 'started ' + chatWhen(g.started) : ''].filter(Boolean).join(' · ')) : null,
      chatText('small', '', g ? g.last : last?.text || 'No messages yet.')),
    h('span', {className:'chat-row-time'}, time(g ? g.last_at : last?.at), g && chatCount(g.unread) ? h('span', {className:'count', 'aria-label':chatCount(g.unread) + ' unread'}, chatCount(g.unread)) : null));
}
function chatList() {
  const groups = chatGroups(), query = chatUi.search.toLowerCase(), history = chatUi.open === 'history';
  const rows = [chatListRow(null), ...groups.filter(g => !g.done && !g.closed).map(chatListRow)];
  rows.forEach(row => { row.hidden = !history && !row.textContent.toLowerCase().includes(query); });
  return h('aside', {className:'chat-list', 'aria-label':'Chats', 'data-key':'chat-list'}, h('h1', {className:'chat-list-title', 'data-key':'chat-list-title'}, 'Chats'), history ? null : chatSearch(), rows[0],
    rows.length > 1 ? h('h2', {}, 'Groups') : null, rows.slice(1),
    rows.every(row => row.hidden) ? chatText('p', 'chat-muted', 'No chats match.') : null);
}
function chatOpenAgent() {
  if (snapshot) return;
  chatUi.agentConversation = true; chatUi.newConversation = true; chatUi.drafts.chat = '';
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
// "Show: All | From my phone" replaces the old counter chips; "Working on N tickets" shows only when N > 0.
function chatFilter() {
  return h('div', {className:'chat-filter', role:'group', 'aria-label':'Show', 'data-key':'chat-filter'}, chatText('span', 'chat-filter-label', 'Show:'),
    [['all', 'All'], ['phone', 'From my phone']].map(([id, label]) => chatButton(label, 'filter', {className:'chat-button chat-seg', 'data-key':'filter-' + id, 'data-id':id, 'aria-pressed':String(chatUi.filter === id)})));
}
function chatHeader(g, history) {
  const agent = !g && !history && chatUi.agentConversation, moved = !g && !history ? chatConversation().at(-1)?.moved_to : null;
  const running = !g && !history && !agent ? chatCount(state?.chat?.activity?.running) : 0;
  const title = history ? (chatUi.day ? chatDayLabel(chatUi.day) : 'Earlier') : g?.title || (agent ? 'New conversation with your helper' : CHAT_HELPER);
  return h('header', {className:'chat-thread-head', 'data-key':'thread-head'},
    h('div', {className:'chat-head-top'}, chatButton('‹ Chats', 'back', {className:'chat-button chat-back'}),
      h('h1', {'data-key':'chat-title', tabindex:'-1'}, clean(title)),
      g ? chatButton('Members', 'members', {id:'chat-members-button'}) : null,
      history ? chatUi.day ? chatButton('Earlier', 'all-history') : chatButton('Back to today', 'today') : g ? null : chatButton('Earlier', 'history')),
    !g && !history && !agent ? chatFilter() : null,
    running ? chatText('p', 'chat-muted chat-running', 'Working on ' + running + (running === 1 ? ' ticket' : ' tickets')) : null,
    agent ? chatText('p', 'chat-muted', 'Talk it through first. When you are ready, the helper can make the ticket.') : null,
    moved ? h('a', {className:'chat-ticket-link', href:chatLink(moved.id)}, 'Ticket ', h('span', {className:'chat-member-chip'}, clean(moved.key)), ' · ', clean(moved.title)) : null,
    g ? h('div', {className:'chat-member-chips'}, chatObjects(g.members).map(m =>
      h('span', {className:'chat-member-chip' + (m.running === false ? ' chat-stopped' : '')}, chatAvatar(m), clean(m.name), m.running === false ? ' · not running' : ''))) : null,
    g && ticketOf(g.ticket) ? h('a', {className:'chat-ticket-link', href:chatLink(g.ticket)}, 'Open the ticket ›') : null);
}
// "From my phone": what you sent from your phone and the answers to it.
function chatPhoneOnly(messages) {
  const sent = new Set(messages.filter(m => m.via === 'phone').map(m => m.id));
  return messages.filter(m => m.via === 'phone' || sent.has(m.reply_to));
}
function chatRefs(refs, prefix, mid, readOnly = false) {
  return chatObjects(refs).map((ref, i) => {
    const key = prefix + '-ref-' + i;
    if (ref.kind === 'proposal') return ref.made ? h('a', {className:'chat-member-chip', 'data-key':key, href:chatLink(ref.made.id)}, clean(ref.made.key)) : chatButton('Make ticket: ' + clean(ref.title).slice(0, 80), 'make-ticket', {className:'btn outline', 'data-key':key, 'data-id':mid, disabled:snapshot || readOnly || chatUi.pending.has(mid)});
    if (ref.kind === 'ticket' && ref.id) return chatTicketCard(ref, key, readOnly);
    if (ref.kind === 'reference' && chatHttp(ref.url)) return h('a', {className:'chat-card', 'data-key':key, href:chatHttp(ref.url), target:'_blank', rel:'noopener noreferrer'}, chatText('strong', '', ref.title || 'Reference'), chatText('small', '', new URL(ref.url).hostname));
    if (ref.kind === 'file') return h('div', {'data-key':key}, chatButton(clean(ref.title || 'File') + ' · ' + clean(String(ref.path || '').split('/').pop()), 'file', {className:'chat-card', 'data-id':key, 'aria-expanded':String(chatUi.files.has(key)), 'aria-controls':key + '-path'}), h('small', {className:'chat-file-path', id:key + '-path', hidden:!chatUi.files.has(key)}, clean(ref.path)));
    return null;
  });
}
// Ticket cards: the plain title and when it is due first; the key and the full title sit behind Details.
// Codes such as "planter 0142-FFE2A659" and the ticket's own key leave the shown title; a second sentence
// (often an instruction to the helper) and a trailing date that the due word repeats do too.
const CHAT_CODE = '\\b(?=[0-9A-F-]*\\d)[0-9A-F]{4,}-[0-9A-F]{6,}\\b';
const CHAT_DAY = /,?\s+(?:on\s+)?(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+\d{1,2}\s+[A-Z][a-z]{2,}\.?$/;
function chatPlainTitle(title, key = '', due = false) {
  let text = clean(title).split(/(?<=[.!?])\s+(?=[A-Z])/)[0];
  if (key) text = text.split(key).join('');
  text = text.replace(new RegExp('\\s*\\([^()]*' + CHAT_CODE + '[^()]*\\)', 'g'), '')
    .replace(new RegExp('\\s*[–—-]\\s+[^,–—()]*?' + CHAT_CODE, 'g'), '').replace(new RegExp('\\s*' + CHAT_CODE, 'g'), '');
  if (due) text = text.replace(CHAT_DAY, '');
  return text.replace(/^[\s,;:·–—-]+|[\s,;:·–—.-]+$/g, '') || clean(title);
}
function chatDue(due) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(due || ''))) return '';
  const shift = n => { const d = new Date(state?.now || Date.now()); d.setDate(d.getDate() + n); return chatLocalDay(d); };
  return due === shift(0) ? 'today' : due === shift(1) ? 'tomorrow' : due === shift(-1) ? 'yesterday' : date(due);
}
function chatTicketCard(ref, key, readOnly) {
  const ticket = ticketOf(ref.id), due = chatDue(ticket?.due), title = chatPlainTitle(ref.title || ticket?.title, ref.key || ticket?.key, !!due);
  const open = chatObjects(ticket?.questions).filter(q => q.answer == null), q = open[0];
  // A person's OK is the one status that gets the accent colour.
  const word = open.length ? 'Needs your OK' : ticket?.status ? window.DashHelpers.statusWord(ticket.status) : '';
  const pending = q ? chatUi.pending.has('answer-' + ticket.id + '-' + q.id) : false;
  // Only actions the ticket already offers: a plain question's options (one tap, like Home), else Answer on
  // the ticket; a ticket ready for review gets Mark done / Send back. Nothing in a day you can only read.
  const actions = readOnly || snapshot || !ticket ? null : q ? q.kind == null && array(q.options).length
    ? array(q.options).slice(0, 4).map((option, i) => chatButton(option, 'answer', {'data-key':key + '-answer-' + i, 'data-ticket':ticket.id, 'data-q':q.id, 'data-answer':option, disabled:pending}))
    : h('a', {className:'chat-button', href:chatLink(ticket.id)}, 'Answer')
    : ticket.status === 'review' && typeof reviewActions === 'function' ? reviewActions(ticket) : null;
  return h('article', {className:'chat-card chat-ticket', 'data-key':key},
    h('a', {className:'chat-ticket-title', href:chatLink(ref.id)}, chatText('strong', '', [title, due].filter(Boolean).join(' · '))),
    word ? chatText('span', 'chat-status' + (open.length ? ' chat-needs-ok' : ''), word) : null,
    actions ? h('div', {className:'chat-actions'}, actions) : null,
    h('details', {className:'chat-ticket-more'}, h('summary', {}, 'Details'), chatText('small', '', [ref.key || ticket?.key, ref.title || ticket?.title].filter(Boolean).join(' · '))));
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
function chatMessage(m, previous, g, index, readOnly, lastMine) {
  const key = 'message-' + (m.id || index), mine = m.by === 'you';
  if (g && m.group_event) return m.group_event.kind === 'approval_needed' ? chatApproval(m, g, index, readOnly) : chatText('div', 'chat-system', chatEvent(m.group_event, g));
  const member = g ? chatObjects(g.members).find(item => item.ws === m.by) || {name:m.name} : {name:chatWorkspace()};
  const sender = mine ? 'You' : clean(g ? m.name || (member.name ? member.name + ' helper' : 'Helper') : CHAT_HELPER);
  const grouped = previous && !previous.group_event && previous.by === m.by;
  return h('article', {className:'chat-message' + (mine ? ' chat-out' : '') + (grouped ? ' chat-grouped' : ''), 'data-key':key, 'data-message-id':m.id, tabindex:'-1'},
    !mine && !grouped ? h('div', {className:'chat-who'}, chatAvatar(member, true), sender) : null,
    h('div', {className:'chat-bubble'}, m.question_to ? chatText('small', 'chat-question', 'Question to ' + clean(m.question_to)) : null,
      chatText('div', 'chat-message-text', m.text), chatRefs(m.refs, key, m.id, readOnly),
      g && m.task ? chatTask(m.task, g, readOnly) : null,
      g && m.added_to ? h('a', {className:'chat-card', href:chatLink(g.ticket)}, 'Added to ', clean(m.added_to.key), ' › ', clean(m.added_to.label)) : null,
      m.share ? chatText('span', 'chat-file-chip', m.share.title || m.share.kind) : null),
    // How a message travelled is shown only when it came from your phone ("13:00 · helper" said nothing).
    chatText('small', 'chat-message-time' + (m.via === 'phone' ? ' chat-from-phone' : ''), [mine ? 'You' : '', time(m.at), m.via === 'phone' ? 'from your phone' : '', m.to_everyone ? 'to everyone' : ''].filter(Boolean).join(' · ')),
    mine && index === lastMine && g?.delivered?.text ? chatText('small', 'chat-delivery', g.delivered.text) : null);
}
function chatThinking(who, plain = false) {
  const label = plain || / helper$/.test(who) ? who : who + ' helper';
  return h('div', {className:'chat-message', 'data-key':'thinking-' + who}, h('div', {className:'chat-bubble chat-muted'}, h('span', {className:'chat-dots', 'aria-hidden':'true'}, h('i'), h('i'), h('i')), clean(label) + ' is thinking…'));
}
function chatSharedTicket(g) {
  const ticket = g.shared_ticket;
  if (!ticket) return null;
  return h('details', {className:'chat-shared-ticket', 'data-key':'shared-ticket'}, h('summary', {}, chatText('small', '', 'From ' + chatHost(g) + ' · ' + clean(ticket.key)), chatText('strong', '', ticket.title), chatText('span', 'chat-status', ticket.status)),
    chatText('p', '', ticket.summary), ticket.question?.text ? chatText('p', '', ticket.question.text) : null,
    h('ul', {}, chatObjects(ticket.checklist).slice(0, 6).map(item => h('li', {}, h('span', {'aria-hidden':'true'}, item.wont_do ? '– ' : window.DashHelpers.resolved(item) ? '☑ ' : '☐ '), h('span', {className:'chat-sr'}, item.wont_do ? "Won't do: " : window.DashHelpers.resolved(item) ? 'done: ' : 'open: '), clean(item.text)))));
}
function chatThread(g, archived) {
  const all = chatObjects(archived ? archived.messages : g ? g.messages : chatConversation());
  const phoneOnly = !g && !archived && chatUi.filter === 'phone', messages = phoneOnly ? chatPhoneOnly(all) : all;
  const readOnly = snapshot || !!archived || !!(g?.done || g?.closed || g?.readOnly), last = messages[messages.length - 1];
  const lastMine = messages.reduce((found, m, i) => m.by === 'you' ? i : found, -1);
  const since = Date.now() - Date.parse(last?.at);
  const thinking = readOnly ? [] : g ? array(g.thinking).filter(n => typeof n === 'string') : state?.chat?.running || (last?.by === 'you' && since >= 0 && since < 600000) ? [CHAT_HELPER] : [];
  const logKey = 'log-' + (archived ? chatUi.day : g?.id || 'chat');
  return fragment(g ? chatSharedTicket(g) : null,
    g?.done || g?.closed ? chatText('div', 'chat-archive-banner', 'Finished · you can read, not reply') : g?.readOnly ? chatText('div', 'chat-archive-banner', 'You can read here. Write in ' + chatHost(g) + '.') : null,
    h('div', {className:'chat-log', 'data-key':logKey, role:'log', 'aria-live':'polite', 'aria-label':g ? 'Group messages' : 'Chat messages'},
      h('div', {className:'chat-divider'}, archived ? date(chatUi.day) : 'Today'),
      messages.length ? messages.map((m, i) => fragment(m.moved_to && m.moved_to.id !== messages[i - 1]?.moved_to?.id ? chatMovedBanner(m.moved_to) : null, chatMessage(m, messages[i - 1], g, i, readOnly, lastMine))) : chatUi.agentConversation && !g && !archived ? null : chatText('p', 'chat-empty', phoneOnly ? 'Nothing from your phone today.' : readOnly ? 'No messages.' : 'No messages yet. Say hello below.'), thinking.map(w => chatThinking(w, !g))),
    readOnly ? snapshot ? chatText('p', 'chat-readonly', 'This is a shared copy.') : null : chatComposer(g));
}
function chatComposer(g) {
  const id = g?.id || 'chat', draft = chatUi.drafts[id] || '', sending = chatUi.sending.has(id);
  return h('div', {className:'chat-composer-area', 'data-key':'composer-' + id},
    chatUi.menu && g ? h('div', {className:'chat-menu', id:'chat-compose-menu', role:'menu'}, [['Ask a workspace','ask'], ['Give a workspace a task','task'], ['Add a workspace','add']].map(([label, action]) => chatButton(label, action, {role:'menuitem'}))) : null,
    h('form', {className:'chat-compose', 'data-key':'form-' + id},
      g ? chatButton('+', 'menu', {'aria-label':'Add to conversation', 'aria-haspopup':'menu', 'aria-expanded':String(chatUi.menu), 'aria-controls':'chat-compose-menu'}) : null,
      h('textarea', {rows:1, className:'chat-draft', 'data-key':'draft-' + id, 'data-chat-input':'draft', 'data-thread':id, 'aria-label':g ? 'Message the group' : 'Message your helper', placeholder:g ? 'Message the group' : 'Message your helper'}, draft),
      h('button', {type:'submit', className:'chat-button chat-primary', 'data-key':'send', disabled:sending || !draft.trim(), 'data-state':sending ? 'sending' : draft.trim() ? 'ready' : 'empty'}, sending ? h('span', {className:'spinner', 'aria-hidden':'true'}) : iconEl('send'), sending ? 'Sending' : 'Send')),
    !g && chatUi.agentConversation ? null : h('div', {className:'chat-context'}, g ? 'Everyone in this group sees what you write here · ' : 'Starts fresh each day at 04:00 · ',
      h('details', {'data-key':'context-details'}, h('summary', {}, 'Details'), h('p', {}, g ? "Members see the group's messages from when they joined. They do not see the rest of the " + chatHost(g) + ' ticket.' : "Every night at 04:00 your helper starts fresh. Today's messages move to Earlier; nothing is deleted."))));
}
function chatDayLabel(day) {
  const today = new Date((state?.chat?.day || new Date().toISOString().slice(0, 10)) + 'T12:00:00');
  today.setDate(today.getDate() - 1);
  return date(day) === date(today.toISOString()) ? 'Yesterday' : date(day);
}
// Earlier: past days first (today is the live thread, never repeated here), then finished groups.
function chatHistory() {
  if (chatUi.day) {
    const archive = chatArchive.get(chatUi.day);
    return fragment(h('div', {className:'chat-archive-banner'}, chatText('span', '', chatDayLabel(chatUi.day) + ' · you can read, not reply'), chatButton('Back to today', 'today')),
      archive?.status === 'ready' ? chatThread(null, archive.data) : chatHistoryStatus(archive?.status, 'retry-day'));
  }
  const groups = chatGroups().filter(g => g.done || g.closed), query = chatUi.historySearch.toLowerCase(), today = chatToday();
  const dayRows = chatObjects(chatDays.rows).filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d.day || '') && d.day !== today).map(d => h('button', {type:'button', className:'chat-day-row', 'data-chat-action':'day', 'data-day':d.day, 'data-key':'day-' + d.day}, chatDayLabel(d.day) + ' · ' + chatCount(d.count) + ' messages', chatText('small', '', d.last)));
  const groupRows = groups.map(g => chatButton([g.title, g.finished ? 'finished ' + chatWhen(g.finished) : 'finished'].filter(Boolean).join(' · '), 'select', {className:'chat-day-row', 'data-key':'history-' + g.id, 'data-id':g.id}));
  [...dayRows, ...groupRows].forEach(row => { row.hidden = !row.textContent.toLowerCase().includes(query); });
  const ready = chatDays.status === 'ready';
  return h('div', {className:'chat-history', 'data-key':'history-list'}, chatSearch(true),
    h('h2', {}, 'Earlier days'), ready ? dayRows.length ? dayRows : chatText('p', 'chat-muted', 'No earlier days yet.') : chatHistoryStatus(chatDays.status, 'retry-days'),
    groups.length ? h('h2', {}, 'Finished groups') : null, groupRows,
    ready && query && [...dayRows, ...groupRows].every(row => row.hidden) ? chatText('p', 'chat-muted', 'Nothing matches.') : null);
}
function chatHistoryStatus(status, retry) {
  return h('div', {className:'chat-history-status', role:'status'}, status === 'error' ? fragment('Could not load earlier chats.', chatButton('Try again', retry)) : 'Loading…');
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
function chatPage() {
  const g = chatGroup(), history = chatUi.open === 'history';
  const page = h('section', {className:'chat-page' + (chatUi.listOpen ? ' chat-list-open' : ' chat-thread-open'), 'data-key':'chat-page'}, chatList(),
    h('div', {className:'chat-main', 'data-key':'chat-main'}, chatHeader(g, history), history ? chatHistory() : chatThread(g, null),
      g && chatUi.sheet ? chatSheet(g, snapshot || g.done || g.closed || g.readOnly) : null));
  page.addEventListener('click', chatClick);
  page.addEventListener('input', chatInput);
  page.addEventListener('submit', event => { if (event.target.matches('.chat-compose')) { event.preventDefault(); chatSend(); } });
  page.addEventListener('keydown', chatKeydown);
  page.addEventListener('scroll', event => {
    if (event.target.matches('.chat-log')) chatScroll.set(event.target, {near:event.target.scrollHeight - event.target.scrollTop - event.target.clientHeight < 80, stamp:chatLogStamp(event.target)});
  }, true);
  return fragment(page);
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
  window.orch.toast(why && why.length <= 160 ? base.replace(/\.$/, '') + ': ' + why : base, 'error'); return false;
}
async function chatSend() {
  const g = chatGroup(), id = g?.id || 'chat';
  if (snapshot || chatUi.open === 'history' || g?.done || g?.closed || chatUi.sending.has(id)) return;
  const field = document.querySelector('.chat-page .chat-draft'), text = field?.value.trim();
  if (!text) return;
  const original = field.value;
  chatUi.drafts[id] = original; chatUi.sending.add(id); render();
  const ok = await chatOperation(g ? 'group.say' : 'chat.say', g ? {ticket:g.ticket, text} : {text, ...(chatUi.newConversation || chatConversation().at(-1)?.moved_to ? {new:true} : {})}, g ? 'Could not send to the group.' : 'Could not send your message.');
  if (ok && !g) chatUi.newConversation = false;
  chatUi.sending.delete(id);
  if (ok && chatUi.drafts[id] === original) { chatUi.drafts[id] = ''; if (field.isConnected) { field.value = ''; field.style.height = ''; } }
  render(); if (field.isConnected) field.focus();
}
function chatInput(event) {
  const field = event.target, kind = field.dataset.chatInput;
  if (!kind) return;
  if (kind === 'draft') {
    chatUi.drafts[field.dataset.thread] = field.value;
    field.style.height = 'auto'; field.style.height = Math.min(124, field.scrollHeight) + 'px';
    field.closest('form').querySelector('[type="submit"]').disabled = !field.value.trim() || chatUi.sending.has(field.dataset.thread);
  } else { chatUi[kind] = field.value; render(); }
}
async function chatClick(event) {
  const control = event.target.closest('[data-chat-action]');
  if (!control || control.disabled) return;
  const action = control.dataset.chatAction, g = chatGroup();
  if (action === 'select') return chatSelect(control.dataset.id);
  if (action === 'history') { chatSelect('history'); return chatLoad(); }
  if (action === 'back') { chatUi.listOpen = true; render(); return chatFocus('[data-key="chat-search"]'); }
  if (action === 'day') { chatUi.day = control.dataset.day; chatUi.historyFocus = 'day-' + chatUi.day; render(); chatFocus('[data-chat-action="all-history"]'); return chatLoad(chatUi.day); }
  if (action === 'all-history') { chatUi.day = null; render(); return chatFocus('[data-key="' + (chatUi.historyFocus || 'history-search') + '"]'); }
  if (action === 'retry-days') { chatDays.status = 'idle'; return chatLoad(); }
  if (action === 'retry-day') { chatArchive.delete(chatUi.day); return chatLoad(chatUi.day); }
  if (action === 'today') { chatSelect('chat'); return; }
  if (action === 'filter') { chatUi.filter = control.dataset.id === 'phone' ? 'phone' : 'all'; return render(); }
  if (action === 'answer') {
    // The same answer a question card sends (op "answer"); the buttons wait while it is on its way.
    const {ticket, q, answer} = control.dataset, id = 'answer-' + ticket + '-' + q;
    if (snapshot || chatUi.pending.has(id)) return;
    chatUi.pending.set(id, true); render();
    if (await chatOperation('answer', {ticket, question:q, answer}, 'Could not send your answer.')) window.orch.toast('Answered: ' + clean(answer), 'ok');
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
    const field = document.querySelector('.chat-page .chat-draft'); if (field) { field.value = chatUi.drafts[g.id]; field.focus(); } return;
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
new MutationObserver(() => {
  const field = document.querySelector('.chat-page .chat-draft');
  if (field) { field.style.height = 'auto'; field.style.height = Math.min(124, Math.max(44, field.scrollHeight)) + 'px'; }
  const log = document.querySelector('.chat-page .chat-log');
  if (!log || !log.clientHeight) return;
  const previous = chatScroll.get(log), stamp = chatLogStamp(log);
  if (!previous || (previous.near && previous.stamp !== stamp)) log.scrollTop = log.scrollHeight;
  chatScroll.set(log, {stamp, near:log.scrollHeight - log.scrollTop - log.clientHeight < 80});
}).observe(document.documentElement, {childList:true, subtree:true, characterData:true, attributes:true, attributeFilter:['class']});

// Workspace DMs are a separate layer, so group/Chat changes can merge independently.
const chatDm = {contacts:[], threads:new Map(), pending:new Map(), loading:false, loaded:false, picker:null, error:false, lastFetch:-Infinity, timer:null};
const chatDmId = id => typeof id === 'string' && /^ws_[a-z0-9]{10}$/.test(id);
const chatDmContact = ws => chatDm.contacts.find(c => c.ws === ws);
function chatDmMessages(ws) {
  const saved = chatObjects(chatDm.threads.get(ws)?.messages), ids = new Set(saved.map(m => m.id));
  return [...saved, ...array(chatDm.pending.get(ws)).filter(m => !ids.has(m.id))];
}
async function chatDmLoad(force = false) {
  if (snapshot || route().kind !== 'chat' || chatDm.loading) return;
  const delay = force || (!chatDm.loaded && !chatDm.contacts.length) ? 0 : 5000 - (Date.now() - chatDm.lastFetch);
  if (delay > 0) {
    if (!chatDm.timer) chatDm.timer = setTimeout(() => { chatDm.timer = null; chatDmLoad(); }, delay);
    return;
  }
  if (chatDm.timer) { clearTimeout(chatDm.timer); chatDm.timer = null; }
  chatDm.lastFetch = Date.now();
  chatDm.loading = true;
  const ws = chatUi.open;
  try {
    const synced = await window.orchAct('chat.sync_ws', {});
    if (!synced?.ok) throw new Error('Sync');
    const response = await fetch('/api/chat/contacts');
    if (!response.ok) throw new Error('Contacts');
    const contacts = await response.json();
    if (!Array.isArray(contacts)) throw new Error('Contacts');
    chatDm.contacts = chatObjects(contacts).filter(c => chatDmId(c.ws));
    chatDm.loaded = true;
    if (chatDmId(ws) && chatDmContact(ws)) {
      const response = await fetch('/api/chat/thread/' + ws);
      if (!response.ok) throw new Error('Thread');
      const thread = await response.json();
      if (!Array.isArray(thread?.messages)) throw new Error('Thread');
      chatDm.threads.set(ws, thread);
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
      if (chatDmId(chatUi.open) && !chatDm.timer) chatDm.timer = setTimeout(() => { chatDm.timer = null; chatDmLoad(); }, 5000);
    }
  }
}
function chatDmRoute() {
  const ws = location.hash.slice(6);
  if (chatDmId(ws)) { chatUi.open = ws; chatUi.listOpen = false; chatUi.day = null; }
  if (route().kind === 'chat') { render(); chatDmLoad(); }
}
window.addEventListener('hashchange', chatDmRoute);
window.addEventListener('orch:state', chatDmRoute);
window.addEventListener('DOMContentLoaded', chatDmRoute);

const chatListWithoutDm = chatList;
chatList = function () {
  const list = chatListWithoutDm();
  if (!snapshot) list.prepend(chatButton('New chat', 'contacts', {'data-key':'new-chat'}));
  const rows = chatDm.contacts.filter(c => c.count > 0 || chatDmMessages(c.ws).length || chatUi.open === c.ws)
    .sort((a, b) => (Date.parse(b.last_at) || 0) - (Date.parse(a.last_at) || 0));
  if (rows.length) {
    list.append(h('h2', {}, 'Workspaces'));
    rows.filter(c => c.name.toLowerCase().includes(chatUi.search.toLowerCase())).forEach(c => {
      const last = chatDmMessages(c.ws).at(-1);
      list.append(h('button', {type:'button', className:'chat-list-row', 'data-chat-action':'select-dm', 'data-id':c.ws, 'data-key':'row-' + c.ws,
        'aria-current':chatUi.open === c.ws ? 'true' : null}, chatAvatar(c),
        h('span', {className:'chat-row-text'}, chatText('strong', '', c.name), chatText('small', '', last?.text || ''))));
    });
  }
  if (chatDmId(chatUi.open)) list.querySelector('[data-id="chat"]')?.removeAttribute('aria-current');
  return list;
};
function chatDmContacts() {
  const {d, actions} = dialog('Contacts', 'dialog');
  d.classList.add('chat-page', 'chat-contacts');
  const body = h('div', {className:'chat-contact-list'});
  const paint = () => {
    const rows = [];
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
      } else rows.push(chatText('p', 'chat-muted', 'Loading…'));
    } else if (!chatDm.contacts.length) rows.push(chatText('p', 'chat-muted', 'No contacts.'));
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
  const ws = chatUi.open, c = chatDmContact(ws), title = c?.name || 'Workspace', messages = chatDmMessages(ws);
  const draft = chatUi.drafts[ws] || '';
  return h('div', {className:'chat-main', 'data-key':'dm-' + ws},
    h('header', {className:'chat-thread-head'}, chatButton('‹ Chats', 'back', {className:'chat-button chat-back'}), h('h1', {'data-key':'chat-title', tabindex:'-1'}, clean(title))),
    chatDm.error ? chatButton('Could not load messages · Try again', 'retry-dm') : null,
    h('div', {className:'chat-log', 'data-key':'log-' + ws, role:'log', 'aria-live':'polite'}, messages.map(m =>
      h('article', {className:'chat-message' + (m.by === 'you' ? ' chat-out' : ''), 'data-key':'message-' + m.id},
        chatText('div', 'chat-bubble chat-message-text', m.text),
        m.by !== 'you' && (m.shown_at || m.at) ? chatText('small', 'chat-message-time', time(m.shown_at || m.at)) : null,
        m.by === 'you' ? h('small', {className:'chat-delivery'},
          m.state === 'failed' ? fragment('Not sent · ', chatButton('Try again', 'retry-send', {'data-id':m.id})) :
          m.state === 'delivered' ? 'Delivered to ' + clean(title) : 'Sending…') : null))),
    !snapshot && c?.can?.chat ? h('form', {className:'chat-compose', 'data-key':'form-' + ws},
      h('textarea', {rows:1, maxLength:2000, className:'chat-draft', 'data-key':'draft-' + ws, 'data-chat-input':'draft', 'data-thread':ws,
        'aria-label':'Message ' + title, placeholder:'Message ' + title}, draft),
      h('button', {type:'submit', className:'chat-button chat-primary', disabled:chatUi.sending.has(ws) || !draft.trim()}, 'Send')) : null);
}
const chatPageWithoutDm = chatPage;
chatPage = function () {
  if (!chatDmId(chatUi.open)) return chatPageWithoutDm();
  const page = h('section', {className:'chat-page' + (chatUi.listOpen ? ' chat-list-open' : ' chat-thread-open'), 'data-key':'chat-page'}, chatList(), chatDmThread());
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
  if (action === 'retry-dm') return chatDmLoad();
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
  if (text) return chatDmSend(text);
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
    await chatDmLoad(true);
    if (!accepted) entry.state = 'failed';
    chatUi.sending.delete(ws); render();
  }
}

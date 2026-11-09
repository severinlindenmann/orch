'use strict';
// Classic-script page: rendering is side-effect free; events own requests and UI state.
let chatUi = {open:'chat', day:null, listOpen:true, sheet:null, panel:null, search:'', historySearch:'', menu:false,
  drafts:Object.create(null), sending:new Set(), pending:new Map(), files:new Set(), historyFocus:null};
let chatDays = {status:'idle', rows:[]}, chatArchive = new Map();
const chatScroll = new WeakMap();
const chatObjects = value => array(value).filter(v => v && typeof v === 'object');
// Groups come from state.groups = {hosted:[...], joined:[...]} (the group list). A hosted group's talk is the
// host ticket's history, its tasks are task cards; a joined group shows the log this workspace stored. Only the host can write.
const chatGroupMembers = (rows, tasks) => chatObjects(rows).filter(m => !m.left_at).map(m => ({...m, task:chatObjects(tasks).find(t => t.ws === m.ws && t.key)}));
function chatHostedGroup(g) {
  const ticket = ticketOf(g.ticket), members = chatGroupMembers(g.members, g.tasks), host = members.find(m => m.host);
  const nameOf = ws => clean(members.find(m => m.ws === ws)?.name);
  const talk = array(ticket?.history).filter(e => e && typeof e.text === 'string' && e.in_chat === true).map((e, i) => {
    const mine = String(e.by || '').startsWith('human:'), who = name(e.by);
    return {id:'h-' + i + '-' + (e.at || ''), at:e.at, by:mine ? 'you' : who, name:mine ? 'You' : /helper$/.test(who) ? who : who + ' helper', text:e.text};
  });
  const tasks = chatObjects(g.tasks).filter(t => t.delegate).map(t => ({id:'task-' + t.delegate, text:'', by:host?.ws || 'host', name:clean(host?.name) + ' helper', task:{...t, name:nameOf(t.ws) || 'Workspace'}}));
  const messages = [...talk, ...tasks], last = talk[talk.length - 1];
  return {id:g.id, ticket:g.ticket, host:host?.ws, title:g.title || ticket?.title, key:typeof ticket?.key === 'string' ? ticket.key : '', closed:g.closed, done:g.closed,
    members, messages, last:last?.text || '', last_at:last?.at, unread:0, connectable:array(g.connectable)};
}
function chatJoinedGroup(g) {
  const members = chatGroupMembers(g.members), nameOf = ws => clean(members.find(m => m.ws === ws)?.name);
  const messages = chatObjects(g.log).map(x => ({id:x.id, at:x.at, by:'ws', name:clean(x.shown), text:x.text || '',
    group_event:x.event ? {...x.event, name:x.event.name || nameOf(x.event.ws)} : null, task:x.task ? {...x.task, name:nameOf(x.task.ws) || 'Workspace'} : null,
    share:x.file ? {kind:'file', title:x.file.title || x.file.name} : null}));
  const last = messages.filter(m => m.text).pop(), card = g.card;
  return {id:g.id, host:g.host, title:g.title, key:'', closed:g.closed || g.left, done:g.closed || g.left, readOnly:true, members, messages, last:last?.text || '', last_at:last?.at, unread:0,
    shared_ticket:card && typeof card === 'object' ? card : null};
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
function chatSearch(history = false) {
  return h('input', {type:'search', className:'chat-search', 'data-key':history ? 'history-search' : 'chat-search',
    'data-chat-input':history ? 'historySearch' : 'search', 'aria-label':history ? 'Search History' : 'Search chats',
    placeholder:history ? 'Search History' : 'Search chats', value:history ? chatUi.historySearch : chatUi.search});
}
function chatListRow(g) {
  const id = g?.id || 'chat', messages = chatObjects(state?.chat?.messages), last = messages[messages.length - 1];
  return h('button', {type:'button', className:'chat-list-row', 'data-key':'row-' + id, 'data-chat-action':'select', 'data-id':id,
    'aria-current':(chatUi.open === id || (id === 'chat' && chatUi.open !== 'history' && !chatGroup())) ? 'true' : null},
    g ? h('span', {className:'chat-stack'}, chatObjects(g.members).slice(0, 3).map(m => chatAvatar(m))) : chatAvatar(chatWorkspace()),
    h('span', {className:'chat-row-text'}, chatText('strong', '', g ? g.title : 'Chat · ' + chatWorkspace()),
      chatText('small', '', g ? g.last : last?.text || 'No messages yet.'), g ? chatText('small', '', g.key) : null),
    h('span', {className:'chat-row-time'}, time(g ? g.last_at : last?.at), g && chatCount(g.unread) ? h('span', {className:'count', 'aria-label':chatCount(g.unread) + ' unread'}, chatCount(g.unread)) : null));
}
function chatList() {
  const groups = chatGroups(), query = chatUi.search.toLowerCase();
  const rows = [chatListRow(null), ...groups.filter(g => !g.done && !g.closed).map(chatListRow)];
  rows.forEach(row => { row.hidden = !row.textContent.toLowerCase().includes(query); });
  return h('aside', {className:'chat-list', 'aria-label':'Chats', 'data-key':'chat-list'}, h('h1', {className:'chat-list-title', 'data-key':'chat-list-title'}, 'Chat · ', chatWorkspace()), chatSearch(), rows[0],
    groups.length || chatGroup() ? h('h2', {}, 'Groups') : null, rows.slice(1),
    rows.every(row => row.hidden) ? chatText('p', 'chat-muted', 'No chats match.') : null,
    groups.length ? chatButton('Done groups → History', 'history', {className:'chat-button chat-list-footer'}) : null);
}
function chatHeader(g, history) {
  return h('header', {className:'chat-thread-head', 'data-key':'thread-head'},
    h('div', {className:'chat-head-top'}, chatButton('‹ Chats', 'back', {className:'chat-button chat-back'}),
      h('h1', {'data-key':'chat-title', tabindex:'-1'}, clean(history ? 'History' : g?.title || 'Chat · ' + chatWorkspace())),
      g ? chatButton('Members', 'members', {id:'chat-members-button'}) : null,
      history ? null : chatButton('History', 'history')),
    history ? null : h('div', {className:'chat-member-chips'}, (g ? chatObjects(g.members) : [{name:chatWorkspace()}]).map(m =>
      h('span', {className:'chat-member-chip' + (m.running === false ? ' chat-stopped' : '')}, chatAvatar(m), clean(m.name), m.running === false ? ' · not running' : ''))),
    g ? h(ticketOf(g.ticket) ? 'a' : 'span', {className:'chat-ticket-link', href:ticketOf(g.ticket) ? chatLink(g.ticket) : null}, 'From ticket ', clean(g.key), ' ›') : null);
}
function chatActivity() {
  const activity = state?.chat?.activity || {}, entries = Object.entries(activity.from_workspaces || {});
  const toggles = [['phone', 'From phone · ' + chatCount(activity.phone_today) + ' today'], ...entries.map(([n, count]) => ['from:' + n, 'From ' + clean(n) + ' · ' + chatCount(count)]), ['running', 'Running · ' + chatCount(activity.running) + ' tickets']];
  let body = null;
  if (chatUi.panel === 'phone') body = chatObjects(state?.chat?.messages).filter(m => m.via === 'phone').slice(0, 5).map((m, i) => chatButton(time(m.at) + ' ' + clean(m.text), 'jump', {'data-key':'phone-' + (m.id || i), 'data-id':m.id}));
  else if (chatUi.panel === 'running') body = chatObjects(state?.tickets).filter(t => state?.runs?.[t.id]?.running).slice(0, 6).map(t => h('a', {className:'chat-card', href:chatLink(t.id)}, clean(t.key) + ' · ' + clean(t.title)));
  else if (chatUi.panel?.startsWith('from:')) body = chatText('p', '', chatCount(activity.from_workspaces?.[chatUi.panel.slice(5)]) + ' messages today');
  return fragment(h('div', {className:'chat-activity', 'data-key':'activity'}, toggles.map(([id, label]) => chatButton(label, 'activity', {'data-key':id, 'data-id':id, 'aria-expanded':String(chatUi.panel === id), 'aria-controls':'chat-activity-panel'}))),
    chatUi.panel ? h('div', {className:'chat-panel', id:'chat-activity-panel'}, body?.length === 0 ? chatText('p', 'chat-muted', 'Nothing here today.') : body) : null);
}
function chatRefs(refs, prefix) {
  return chatObjects(refs).map((ref, i) => {
    const key = prefix + '-ref-' + i;
    if (ref.kind === 'ticket' && ref.id) {
      const ticket = ticketOf(ref.id);
      return h('a', {className:'chat-card', 'data-key':key, href:chatLink(ref.id)}, chatText('strong', '', [ref.key, ref.title].filter(Boolean).join(' · ')), ticket?.status ? chatText('small', '', window.DashHelpers.statusWord(ticket.status)) : null);
    }
    if (ref.kind === 'reference' && chatHttp(ref.url)) return h('a', {className:'chat-card', 'data-key':key, href:chatHttp(ref.url), target:'_blank', rel:'noopener noreferrer'}, chatText('strong', '', ref.title || 'Reference'), chatText('small', '', new URL(ref.url).hostname));
    if (ref.kind === 'file') return h('div', {'data-key':key}, chatButton(clean(ref.title || 'File') + ' · ' + clean(String(ref.path || '').split('/').pop()), 'file', {className:'chat-card', 'data-id':key, 'aria-expanded':String(chatUi.files.has(key)), 'aria-controls':key + '-path'}), h('small', {className:'chat-file-path', id:key + '-path', hidden:!chatUi.files.has(key)}, clean(ref.path)));
    return null;
  });
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
  const words = {created:'Group started from ticket ' + clean(g.key) + ' · ' + clean(g.title), member_added:chatHost(g) + ' helper added ' + who + ' to this group', member_left:who + ' left the group', approved:'You allowed ' + who + ' ' + clean(ev.mode || 'once') + ' · ' + who + ' joined', denied:'You said no to ' + who, closed:'This group is done. It is in History.'};
  return clean(ev.text || words[ev.kind] || '');
}
function chatMessage(m, previous, g, index, readOnly, lastMine) {
  const key = 'message-' + (m.id || index), mine = m.by === 'you';
  if (g && m.group_event) return m.group_event.kind === 'approval_needed' ? chatApproval(m, g, index, readOnly) : chatText('div', 'chat-system', chatEvent(m.group_event, g));
  const member = g ? chatObjects(g.members).find(item => item.ws === m.by) || {name:m.name} : {name:chatWorkspace()};
  const sender = mine ? 'You' : clean(g ? m.name || (member.name ? member.name + ' helper' : 'Helper') : state?.chat?.helper || chatWorkspace() + ' helper');
  const grouped = previous && !previous.group_event && previous.by === m.by;
  return h('article', {className:'chat-message' + (mine ? ' chat-out' : '') + (grouped ? ' chat-grouped' : ''), 'data-key':key, 'data-message-id':m.id, tabindex:'-1'},
    !mine && !grouped ? h('div', {className:'chat-who'}, chatAvatar(member, true), sender) : null,
    h('div', {className:'chat-bubble'}, m.question_to ? chatText('small', 'chat-question', 'Question to ' + clean(m.question_to)) : null,
      chatText('div', 'chat-message-text', m.text), chatRefs(m.refs, key),
      g && m.task ? chatTask(m.task, g, readOnly) : null,
      g && m.added_to ? h('a', {className:'chat-card', href:chatLink(g.ticket)}, 'Added to ', clean(m.added_to.key), ' › ', clean(m.added_to.label)) : null,
      m.share ? chatText('span', 'chat-file-chip', m.share.title || m.share.kind) : null),
    chatText('small', 'chat-message-time', [mine ? 'You' : '', time(m.at), m.via, m.to_everyone ? 'to everyone' : ''].filter(Boolean).join(' · ')),
    mine && index === lastMine && g?.delivered?.text ? chatText('small', 'chat-delivery', g.delivered.text) : null);
}
function chatThinking(who) {
  const label = / helper$/.test(who) ? who : who + ' helper';
  return h('div', {className:'chat-message', 'data-key':'thinking-' + who}, h('div', {className:'chat-bubble chat-muted'}, h('span', {className:'chat-dots', 'aria-hidden':'true'}, h('i'), h('i'), h('i')), clean(label) + ' is thinking…'));
}
function chatSharedTicket(g) {
  const ticket = g.shared_ticket;
  if (!ticket) return null;
  return h('details', {className:'chat-shared-ticket', 'data-key':'shared-ticket'}, h('summary', {}, chatText('small', '', 'From ' + chatHost(g) + ' · ' + clean(ticket.key)), chatText('strong', '', ticket.title), chatText('span', 'chat-status', ticket.status)),
    chatText('p', '', ticket.summary), ticket.question?.text ? chatText('p', '', ticket.question.text) : null,
    h('ul', {}, chatObjects(ticket.checklist).slice(0, 6).map(item => h('li', {}, h('span', {'aria-hidden':'true'}, item.done ? '☑ ' : '☐ '), h('span', {className:'chat-sr'}, item.done ? 'done: ' : 'open: '), clean(item.text)))));
}
function chatThread(g, archived) {
  const messages = chatObjects(archived ? archived.messages : g ? g.messages : state?.chat?.messages);
  const readOnly = snapshot || !!archived || !!(g?.done || g?.closed || g?.readOnly), last = messages[messages.length - 1];
  const lastMine = messages.reduce((found, m, i) => m.by === 'you' ? i : found, -1);
  const since = Date.now() - Date.parse(last?.at);
  const thinking = readOnly ? [] : g ? array(g.thinking).filter(n => typeof n === 'string') : state?.chat?.running || (last?.by === 'you' && since >= 0 && since < 600000) ? [clean(state?.chat?.helper) || chatWorkspace() + ' helper'] : [];
  const logKey = 'log-' + (archived ? chatUi.day : g?.id || 'chat');
  return fragment(g ? chatSharedTicket(g) : null,
    g?.done || g?.closed ? chatText('div', 'chat-archive-banner', 'Done · read only') : g?.readOnly ? chatText('div', 'chat-archive-banner', 'Read only here. Write in ' + chatHost(g) + '.') : null,
    h('div', {className:'chat-log', 'data-key':logKey, role:'log', 'aria-live':'polite', 'aria-label':g ? 'Group messages' : 'Chat messages'},
      h('div', {className:'chat-divider'}, archived ? date(chatUi.day) : 'Today'),
      messages.length ? messages.map((m, i) => chatMessage(m, messages[i - 1], g, i, readOnly, lastMine)) : chatText('p', 'chat-empty', readOnly ? 'No messages.' : 'No messages yet. Say hello below.'), thinking.map(chatThinking)),
    readOnly ? snapshot ? chatText('p', 'chat-readonly', 'This is a shared copy.') : null : chatComposer(g));
}
function chatComposer(g) {
  const id = g?.id || 'chat', draft = chatUi.drafts[id] || '', sending = chatUi.sending.has(id);
  return h('div', {className:'chat-composer-area', 'data-key':'composer-' + id},
    chatUi.menu && g ? h('div', {className:'chat-menu', id:'chat-compose-menu', role:'menu'}, [['Ask a workspace','ask'], ['Give a workspace a task','task'], ['Add a workspace','add']].map(([label, action]) => chatButton(label, action, {role:'menuitem'}))) : null,
    h('form', {className:'chat-compose', 'data-key':'form-' + id},
      g ? chatButton('+', 'menu', {'aria-label':'Add to conversation', 'aria-haspopup':'menu', 'aria-expanded':String(chatUi.menu), 'aria-controls':'chat-compose-menu'}) : null,
      h('textarea', {rows:1, className:'chat-draft', 'data-key':'draft-' + id, 'data-chat-input':'draft', 'data-thread':id, 'aria-label':g ? 'Message the group' : 'Message ' + chatWorkspace(), placeholder:g ? 'Message the group' : 'Message ' + chatWorkspace()}, draft),
      h('button', {type:'submit', className:'chat-button chat-primary', 'data-key':'send', disabled:sending || !draft.trim()}, sending ? 'Sending…' : 'Send')),
    h('div', {className:'chat-context'}, g ? 'Everyone in this group sees what you write here · ' : 'Context cleared daily at 04:00 · ',
      h('details', {'data-key':'context-details'}, h('summary', {}, 'Details'), h('p', {}, g ? "Members see the group's messages from when they joined. They do not see the rest of the " + chatHost(g) + ' ticket.' : "Every night at 04:00 the helper starts fresh. Today's messages move to History; nothing is deleted."))));
}
function chatDayLabel(day) {
  const today = new Date((state?.chat?.day || new Date().toISOString().slice(0, 10)) + 'T12:00:00');
  today.setDate(today.getDate() - 1);
  return date(day) === date(today.toISOString()) ? 'Yesterday' : date(day);
}
function chatHistory() {
  if (chatUi.day) {
    const archive = chatArchive.get(chatUi.day);
    return fragment(h('div', {className:'chat-archive-banner'}, date(chatUi.day) + ' · read only', chatButton('All History', 'all-history')),
      archive?.status === 'ready' ? chatThread(null, archive.data) : chatHistoryStatus(archive?.status, 'retry-day'));
  }
  const groups = chatGroups().filter(g => g.done || g.closed), query = chatUi.historySearch.toLowerCase();
  const groupRows = groups.map(g => chatButton(g.title, 'select', {className:'chat-day-row', 'data-key':'history-' + g.id, 'data-id':g.id}));
  const dayRows = chatObjects(chatDays.rows).filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d.day || '')).map(d => h('button', {type:'button', className:'chat-day-row', 'data-chat-action':'day', 'data-day':d.day, 'data-key':'day-' + d.day}, chatDayLabel(d.day) + ' · ' + chatCount(d.count) + ' messages', chatText('small', '', d.last)));
  [...groupRows, ...dayRows].forEach(row => { row.hidden = !row.textContent.toLowerCase().includes(query); });
  return h('div', {className:'chat-history', 'data-key':'history-list'}, chatText('p', 'chat-muted', 'Done groups and past days of Chat.'), chatSearch(true),
    groups.length ? h('h2', {}, 'Done groups') : null, groupRows, h('h2', {}, 'Chat · ', chatWorkspace()), dayRows,
    chatDays.status !== 'ready' ? chatHistoryStatus(chatDays.status, 'retry-days') : [...groupRows, ...dayRows].every(row => row.hidden) ? chatText('p', 'chat-muted', 'No history matches.') : null);
}
function chatHistoryStatus(status, retry) {
  return h('div', {className:'chat-history-status', role:'status'}, status === 'error' ? fragment('Could not load History.', chatButton('Retry', retry)) : 'Loading…');
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
    h('div', {className:'chat-main', 'data-key':'chat-main'}, chatHeader(g, history), history ? chatHistory() : fragment(g ? null : chatActivity(), chatThread(g, null)),
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
  chatUi.open = id; chatUi.day = null; chatUi.listOpen = false; chatUi.sheet = null; chatUi.menu = false; chatUi.panel = null;
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
  const ok = await chatOperation(g ? 'group.say' : 'chat.say', g ? {ticket:g.ticket, text} : {text}, g ? 'Could not send to the group.' : 'Could not send your message.');
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
  if (action === 'activity') { chatUi.panel = chatUi.panel === control.dataset.id ? null : control.dataset.id; return render(); }
  if (action === 'jump') { const node = [...document.querySelectorAll('.chat-page [data-message-id]')].find(n => n.dataset.messageId === control.dataset.id); node?.scrollIntoView({block:'center'}); node?.focus(); return; }
  if (action === 'file') { const id = control.dataset.id; chatUi.files.has(id) ? chatUi.files.delete(id) : chatUi.files.add(id); return render(); }
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

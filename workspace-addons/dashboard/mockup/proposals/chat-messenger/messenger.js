'use strict';
// Draft only (lane chat-messenger): the Chat page as a messenger. One page, the options are picked in the address:
//   frame=full|card  msg=rows|bubbles  list=a|b|c  composer=a|b  presence=a|b|c  history=scroll|button
//   view=helper|ticket  state=working|ready|stopped|error  screen=list|thread (phone)  relay  staged
//   demo=day|empty|sent|failed (what the conversation holds)
// Layout is set inline from the master's tokens (no sheet of its own, no colour literal). The build moves it into
// the master (widgets.css) with a gallery entry per part; nothing here is product code.
(() => {
const q = new URLSearchParams(location.search), P = (k, d) => q.get(k) || d;
const V = {frame:P('frame', 'full'), msg:P('msg', 'rows'), list:P('list', 'a'), composer:P('composer', 'a'), presence:P('presence', 'a'),
  history:P('history', 'scroll'), view:P('view', 'helper'), state:P('state', 'working'), screen:P('screen', 'thread'), demo:P('demo', 'day'), relay:q.has('relay'), staged:q.has('staged')};
const phone = matchMedia('(max-width:720px)').matches;

function el(tag, css, attrs, ...kids) {
  const n = document.createElement(tag);
  if (css) n.style.cssText = css;
  for (const [k, v] of Object.entries(attrs || {})) { if (v == null || v === false) continue; if (k === 'class') n.className = v; else n.setAttribute(k, v === true ? '' : v); }
  for (const kid of kids.flat(9)) if (kid != null && kid !== false) n.append(kid);
  return n;
}
const NS = 'http://www.w3.org/2000/svg';
function icon(d, size = 16) {
  const s = document.createElementNS(NS, 'svg'); s.setAttribute('class', 'ic'); s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true');
  s.style.cssText = 'width:' + size + 'px;height:' + size + 'px;flex:none';
  for (const part of d.split('|')) { const p = document.createElementNS(NS, 'path'); p.setAttribute('d', part); s.append(p); }
  return s;
}
const I = {
  plus:'M12 5v14M5 12h14', clip:'M20 11.5 12 19.5a5 5 0 0 1-7-7l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7L9.8 17a1.7 1.7 0 0 1-2.4-2.4L15 7',
  send:'m4 12 16-8-6 16-3-7z', search:'M11 4a7 7 0 1 1 0 14 7 7 0 0 1 0-14z|m20 20-4-4', ticket:'M4 5h16v14H4z|M9 5v14m6-14v14',
  back:'m15 5-7 7 7 7', file:'M7 3h7l5 5v13H7z|M14 3v5h5', clock:'M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18z|M12 7v5l3 2', group:'M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm8 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6z|M2 19c0-3 3-5 6-5s6 2 6 5m2-5c3 0 6 2 6 5',
  x:'M6 6l12 12M18 6 6 18', spark:'m12 3 2 6 7 3-7 2-2 7-2-7-7-2 7-3z', live:'M8 3H3v5m13-5h5v5M3 16v5h5m8 0h5v-5',
};
const T = {
  line:'1px solid var(--border)', one:'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0',
  meta:'font-size:12px;line-height:16px;color:var(--text-faint)', strong:'font-weight:600;color:var(--text)',
};

// ---- sample data: the same small Pilatus workspace as the "Now" pictures --------------------------------------------------
const HELPER_STATE = {
  working:{dot:'dot working', text:'Working on Plan the team lunch on Friday', short:'Working', link:'Watch live'},
  ready:{dot:'dot ok', text:'Ready to answer', short:'Ready'},
  stopped:{dot:'dot-off', text:'Not running. Your message waits until it starts.', short:'Not running', button:'Start helper'},
  error:{dot:'dot bad', text:'Stopped: it could not sign in to its account.', short:'Stopped', fix:'See what to fix'},
}[V.state];
const CHATS = [
  {id:'helper', kind:'helper', title:'Your helper', last:'Draft for the invitation: Quarterly review, Thursday 3 December…', at:'11:53', sort:5},
  {id:'PIL-2', kind:'ticket', title:'Answer the supplier about the delivery date', last:'Tuesday or Thursday? Which day?', at:'10:20', unread:1, needs:true, sort:4},
  {id:'PIL-1', kind:'ticket', title:'Plan the team lunch on Friday', last:'Yes, they have a long table by the window.', at:'09:31', unread:1, sort:3},
  {id:'PIL-3', kind:'ticket', title:'Monthly sales report for October', last:'Looks good, thanks.', who:'You', at:'Mon', sort:1},
  ...(V.relay ? [
    {id:'shop', kind:'ws', title:'Shop', sub:'Lea', last:'The gift boxes arrive on Thursday.', who:'Lea', at:'10:05', unread:2, sort:3.5},
    {id:'marketing', kind:'ws', title:'Marketing', sub:'Max', last:'Sent you the newsletter text.', who:'You', at:'Tue', sort:0.5},
    {id:'xmas', kind:'group', title:'Christmas campaign', sub:'3 workspaces', last:'Photos are in the shared folder.', who:'Max', at:'Tue', sort:0.4},
  ] : []),
];
const OPEN = V.view === 'ticket' ? 'PIL-1' : 'helper';
const HELPER_DAY = [
  {day:'Yesterday'},
  {who:'helper', at:'16:40', items:[{text:'The supplier answered: delivery is possible on Tuesday or Thursday. I asked you which day in the ticket.'}]},
  {day:'Today', note:'New day: your helper starts without yesterday’s conversation. You can still read it here.'},
  {who:'you', at:'09:02', items:[{text:'Morning! What is still open this week?'}]},
  {who:'helper', at:'09:02', items:[{text:'Good morning Anna. Still open this week:', list:['Team lunch on Friday: two of three steps are done, the table is not booked yet.', 'Supplier delivery date: waiting for your answer (Tuesday or Thursday).', 'Meeting room for the quarterly review: not started.']}]},
  {who:'you', at:'09:14', items:[{text:'Book the Linde for Friday at noon, twelve people.'}, {text:'And ask them for a vegetarian menu.'}]},
  {who:'helper', at:'09:15', items:[{text:'I will ask the Linde for a table for twelve on Friday at noon, with a vegetarian menu.'}, {ticket:{key:'PIL-1', title:'Plan the team lunch on Friday', state:'working', label:'Working', fact:'2 of 3 steps done'}}]},
  {who:'helper', at:'11:40', items:[{text:'The October sales report is ready for you to look at.'}, {ticket:{key:'PIL-3', title:'Monthly sales report for October', state:'done', label:'Done', fact:'Sales up 8% on September'}}, {file:{name:'sales-october.pdf', size:'240 KB'}}]},
  {who:'you', at:'11:52', items:[{text:'Thanks. Can you also draft the invitation for the quarterly review? The agenda is attached.'}, {file:{name:'agenda-q4.docx', size:'18 KB'}}]},
  {who:'helper', at:'11:53', items:[{text:'Draft for the invitation: Quarterly review, Thursday 3 December, 14:00 to 16:00, room Rigi. Shall I make a ticket for sending it?'}, {make:'Send the invitation for the quarterly review'}]},
];
const TICKET_DAY = [
  {day:'Today'},
  {who:'you', at:'09:30', items:[{text:'Is the Linde okay with twelve people?'}]},
  {who:'helper', at:'09:31', items:[{text:'Yes, they have a long table by the window.'}, {text:'I am booking it now for Friday at noon.'}]},
];

// ---- small parts -------------------------------------------------------------------------------------------------------
function avatar(kind, size = 32, presence = false) {
  const box = 'position:relative;flex:none;width:' + size + 'px;height:' + size + 'px;font-size:' + (size > 30 ? 14 : 12) + 'px';
  let a;
  if (kind === 'helper') a = el('span', box, {class:'avatar helper', 'aria-hidden':'true'}, icon(I.spark, size > 30 ? 18 : 14));
  else if (kind === 'you') a = el('span', box + ';background:var(--warning-soft);color:var(--warning)', {class:'avatar', 'aria-hidden':'true'}, 'A');
  else if (kind === 'ticket') a = el('span', box + ';border-radius:var(--r1)', {class:'avatar', 'aria-hidden':'true'}, icon(I.ticket, size > 30 ? 18 : 14));
  else if (kind === 'group') a = el('span', box + ';border-radius:var(--r1)', {class:'avatar', 'aria-hidden':'true'}, icon(I.group, size > 30 ? 18 : 14));
  else a = el('span', box + ';background:var(--brand-soft);color:var(--brand)', {class:'avatar', 'aria-hidden':'true'}, kind.slice(0, 1).toUpperCase());
  if (presence) a.append(el('span', 'position:absolute;right:-3px;bottom:-3px;width:12px;height:12px;box-shadow:0 0 0 2px var(--bg)' + (V.state === 'stopped' ? ';background:var(--bg)' : ''), {class:HELPER_STATE.dot}));
  return a;
}
const count = n => n ? el('span', '', {class:'count', 'aria-label':n + ' unread'}, String(n)) : null;
function statusLine(compact, dot = true) {
  return el('span', 'display:flex;align-items:center;gap:var(--s2);min-width:0;' + T.meta + ';color:var(--text-muted)', {role:'status'},
    dot ? el('span', '', {class:HELPER_STATE.dot}) : null, el('span', T.one, {}, compact ? HELPER_STATE.short : HELPER_STATE.text),
    !compact && HELPER_STATE.link ? el('a', 'flex:none;color:var(--brand)', {href:'../../focus/focus-v4d.html'}, HELPER_STATE.link + ' ›') : null);
}

// ---- the list of chats -------------------------------------------------------------------------------------------------
function listRow(c, dense) {
  const current = c.id === OPEN && !(phone && V.screen === 'list'); if (current) c = {...c, unread:0}; const unread = !!c.unread;
  const base = 'display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:var(--s3);align-items:center;width:100%;text-align:left;border:0;border-radius:var(--r1);color:inherit;font:inherit;cursor:pointer;background:' + (current ? 'var(--surface-2)' : 'transparent');
  const kind = c.kind === 'ws' ? c.title : c.kind;
  if (dense) return el('button', base + ';padding:var(--s1) var(--s2);min-height:32px;gap:var(--s2)', {type:'button', 'aria-current':current ? 'true' : null},
    avatar(kind, 20, c.kind === 'helper'), el('span', T.one + ';font-size:14px;' + (unread ? T.strong : 'color:var(--text-muted)'), {}, c.title), count(c.unread));
  const two = 'display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;font-size:12px;line-height:16px;';
  const preview = c.needs ? el('span', 'display:flex;align-items:flex-start;gap:6px;color:var(--warning)', {}, el('span', 'margin-top:4px', {class:'dot needs'}), el('span', two, {}, 'Needs you · ' + c.last))
    : el('span', two + 'color:' + (unread ? 'var(--text)' : 'var(--text-muted)'), {}, (c.who ? c.who + ': ' : '') + c.last);
  return el('button', base + ';padding:var(--s2);min-height:56px', {type:'button', 'aria-current':current ? 'true' : null},
    avatar(kind, 36, c.kind === 'helper'),
    el('span', 'display:grid;gap:2px;min-width:0', {},
      el('span', 'display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;font-size:14px;line-height:20px;' + (unread ? T.strong : 'font-weight:500'), {}, c.title, V.list === 'b' && c.kind !== 'helper' ? el('span', T.meta + ';font-weight:400', {}, '  ' + ({ticket:c.id, ws:'Workspace', group:'Group'}[c.kind])) : null),
      preview),
    el('span', 'display:grid;gap:var(--s1);justify-items:end;align-self:start;padding-top:2px', {}, el('span', T.meta, {}, c.at), count(c.unread)));
}
function section(title, rows, dense, n) {
  if (!rows.length) return null;
  return el('section', 'display:grid;gap:2px', {'aria-label':title},
    el('h2', 'margin:var(--s3) var(--s2) var(--s1);font-size:12px;line-height:16px;font-weight:500;color:var(--text-faint)', {}, title, n ? ' · ' + rows.length : ''), rows.map(c => listRow(c, dense)));
}
function chatList() {
  const of = k => CHATS.filter(c => c.kind === k);
  const head = el('div', 'display:flex;align-items:center;gap:var(--s2);padding:0 var(--s2)', {},
    el(phone ? 'h1' : 'h2', 'flex:1;margin:0;font-size:20px;line-height:28px;font-weight:600', {}, 'Chats'),
    el('button', '', {class:'btn outline sm', type:'button'}, icon(I.plus), 'New chat'));
  const search = el('label', 'position:relative;display:block;margin:0 var(--s2)', {},
    el('span', '', {class:'sr-only'}, 'Search chats and messages'),
    el('span', 'position:absolute;left:var(--s3);top:50%;transform:translateY(-50%);display:grid;color:var(--text-faint)', {}, icon(I.search)),
    el('input', 'width:100%;padding-left:var(--s6)', {class:'input', type:'search', placeholder:'Search chats and messages'}));
  let body;
  if (V.list === 'b') {
    const chip = (t, n, on) => el('button', on ? 'background:var(--surface-3);color:var(--text)' : '', {class:'chip', type:'button', 'aria-pressed':String(!!on)}, t, n ? ' ' + n : '');
    const unread = CHATS.reduce((s, c) => s + (c.unread || 0), 0);
    body = [el('div', 'display:flex;gap:var(--s2);padding:0 var(--s2);flex-wrap:wrap', {role:'group', 'aria-label':'Show'}, chip('All', 0, true), chip('Unread', unread), chip('Needs you', 1)),
      el('div', 'display:grid;gap:2px', {}, [...CHATS].sort((a, b) => b.sort - a.sort).map(c => listRow(c)))];
  } else {
    const dense = V.list === 'c';
    body = [el('div', 'display:grid;gap:2px' + (dense ? '' : ';padding-bottom:var(--s1);border-bottom:' + T.line), {}, dense ? section('Helper', of('helper'), true) : of('helper').map(c => listRow(c))),
      section('Tickets', of('ticket'), dense, dense), section('Workspaces', of('ws'), dense, dense), section('Groups', of('group'), dense, dense)];
  }
  return el('aside', 'display:flex;flex-direction:column;gap:var(--s3);min-height:0;overflow:auto;padding:var(--s4) var(--s2)' + (phone ? '' : ';border-right:' + T.line), {id:'pane-list', 'aria-label':'Chats'}, head, search, body);
}

// ---- messages ----------------------------------------------------------------------------------------------------------
function ticketCard(t) {
  return el('a', 'display:grid;gap:var(--s1);max-width:420px;padding:var(--s3);border:' + T.line + ';border-radius:var(--r2);background:var(--surface);color:inherit;text-decoration:none', {href:'../../ticket/ticket.html'},
    el('span', 'display:flex;gap:var(--s2);align-items:center;' + T.meta, {}, icon(I.ticket, 14), t.key, el('span', 'margin-left:auto;color:var(--brand)', {}, 'Open ›')),
    el('strong', 'font-size:14px;line-height:20px;font-weight:600', {}, t.title),
    el('span', 'display:flex;gap:var(--s2);align-items:center;' + T.meta, {}, el('span', '', {class:'dot ' + (t.state === 'done' ? 'ok' : 'working')}), t.label + ' · ' + t.fact));
}
function fileChip(f) {
  return el('a', 'display:inline-flex;align-items:center;gap:var(--s2);max-width:100%;padding:var(--s2) var(--s3);border:' + T.line + ';border-radius:var(--r1);background:var(--surface);color:inherit;text-decoration:none;font-size:14px', {href:'#'},
    icon(I.file), el('span', T.one, {}, f.name), el('span', T.meta + ';flex:none', {}, f.size));
}
function item(it, mine) {
  if (it.ticket) return ticketCard(it.ticket);
  if (it.file) return el('div', mine && V.msg === 'bubbles' ? 'justify-self:end' : '', {}, fileChip(it.file));
  if (it.make) return el('div', '', {}, el('button', 'white-space:normal;text-align:left;height:auto;min-height:var(--h)', {class:'btn outline sm', type:'button'}, icon(I.plus), 'Make ticket: ' + it.make));
  return el('div', 'font-size:14px;line-height:22px;max-width:var(--reading-width);overflow-wrap:anywhere', {}, it.text,
    it.list ? el('ul', 'margin:var(--s1) 0 0;padding-left:var(--s5);display:grid;gap:2px', {}, it.list.map(x => el('li', '', {}, x))) : null);
}
const who = g => g.who === 'you' ? 'You' : 'Your helper';
function divider(g) {
  return el('div', 'display:grid;gap:var(--s1);justify-items:center;margin:var(--s3) 0 var(--s1)', {},
    el('div', 'display:flex;align-items:center;gap:var(--s3);width:100%', {role:'separator', 'aria-label':g.day},
      el('span', 'flex:1;border-top:' + T.line), el('span', 'font-size:12px;line-height:16px;font-weight:500;color:var(--text-muted);padding:2px var(--s3);border:' + T.line + ';border-radius:var(--r3,12px)', {}, g.day), el('span', 'flex:1;border-top:' + T.line)),
    g.note && V.history === 'scroll' ? el('p', 'font-size:12px;line-height:16px;color:var(--text-muted);margin:0;text-align:center', {}, g.note) : null);
}
function rowGroup(g) {
  return el('article', 'display:grid;grid-template-columns:auto minmax(0,1fr);gap:var(--s3);padding:var(--s2) 0', {},
    avatar(g.who, 32),
    el('div', 'display:grid;gap:var(--s1);min-width:0', {},
      el('div', 'display:flex;gap:var(--s2);align-items:baseline', {}, el('strong', 'font-size:14px;line-height:20px;font-weight:600', {}, who(g)), el('time', T.meta, {}, g.at)),
      g.items.map(it => item(it)), sendNote(g)));
}
// What happened to a message that did not reach the helper: said in words next to it, with the one thing to do.
function sendNote(g) {
  if (g.note === 'failed') return el('div', 'display:flex;align-items:center;gap:var(--s2);font-size:12px;line-height:16px;color:var(--danger)', {role:'status'}, el('span', '', {class:'dot bad'}), 'Not sent. Check the connection.', el('button', '', {class:'btn outline sm', type:'button'}, 'Try again'));
  if (g.note === 'waits') return el('div', 'display:flex;align-items:center;gap:var(--s2);font-size:12px;line-height:16px;color:var(--text-muted)', {role:'status'}, el('span', '', {class:'dot-off'}), 'Saved. Your helper reads it when it starts.');
  return null;
}
function welcome() {
  const prompt = (kind, text) => el('button', 'display:grid;gap:var(--s1);text-align:left;padding:var(--s3);border:' + T.line + ';border-radius:var(--r2);background:var(--surface);color:var(--text);font:inherit;font-size:14px;cursor:pointer', {type:'button'}, el('span', T.meta, {}, kind), text);
  return el('div', 'display:grid;gap:var(--s3);padding:var(--s5) 0 var(--s4);max-width:640px', {},
    el('div', 'display:flex;gap:var(--s3);align-items:center', {}, avatar('helper', 36), el('div', 'display:grid;gap:2px', {}, el('strong', 'font-size:16px;line-height:24px', {}, 'Talk it through with your helper'), el('span', 'font-size:14px;color:var(--text-muted)', {}, 'Nothing written today. Start with one of these or write your own.'))),
    el('div', 'display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:var(--s2)', {}, prompt('Plan something', 'Help me plan my week'), prompt('Compare options', 'Help me compare two options'), prompt('Check a result', 'What is still open this week?')));
}
function bubbleGroup(g) {
  const mine = g.who === 'you';
  const bubble = (it, i, n) => {
    if (!it.text) return el('div', mine ? 'justify-self:end;max-width:100%' : 'max-width:100%', {}, item(it, mine));
    const r = 'var(--r3,12px)', tight = '4px';
    const corners = mine ? [r, i ? tight : r, i < n - 1 ? tight : r, r] : [i ? tight : r, r, r, i < n - 1 ? tight : r];
    return el('div', 'max-width:min(100%,560px);padding:var(--s2) var(--s3);border-radius:' + corners.join(' ') + ';background:' + (mine ? 'var(--brand-soft)' : 'var(--surface-2)') + (mine ? ';justify-self:end' : ''), {}, item(it, mine));
  };
  const col = el('div', 'display:grid;gap:3px;min-width:0;justify-items:' + (mine ? 'end' : 'start'), {},
    mine ? null : el('strong', 'font-size:12px;line-height:16px;font-weight:600;color:var(--text-muted);padding-left:var(--s1)', {}, who(g)),
    g.items.map((it, i) => bubble(it, i, g.items.length)),
    el('time', T.meta + ';padding:0 var(--s1)', {}, g.at));
  return el('article', 'display:grid;grid-template-columns:' + (mine ? 'minmax(0,1fr)' : 'auto minmax(0,1fr)') + ';gap:var(--s2);padding:var(--s2) 0;' + (mine ? 'padding-left:var(--s8)' : 'padding-right:var(--s8)'), {}, mine ? null : el('div', 'align-self:start;padding-top:var(--s5)', {}, avatar('helper', 28)), col);
}
function typing() {
  if (V.demo !== 'sent' || V.view === 'ticket' || ['stopped', 'error'].includes(V.state)) return null;
  const dots = el('span', 'display:inline-flex;gap:3px', {'aria-hidden':'true'}, [0, 1, 2].map(() => el('span', 'width:6px;height:6px;border-radius:50%;background:var(--text-faint)')));
  return el('div', 'display:flex;align-items:center;gap:var(--s3);padding:var(--s2) 0;' + T.meta + ';color:var(--text-muted)', {role:'status'}, avatar('helper', V.msg === 'rows' ? 32 : 28), dots, 'Your helper is writing…');
}
function messages() {
  let day = V.view === 'ticket' ? TICKET_DAY : V.history === 'scroll' ? HELPER_DAY : HELPER_DAY.slice(2);
  if (V.view !== 'ticket' && V.demo === 'empty') day = [{day:'Today'}];
  if (V.view !== 'ticket' && ['sent', 'failed'].includes(V.demo)) {
    const waits = ['stopped', 'error'].includes(V.state);
    day = [...day.slice(0, -1), {who:'you', at:'11:58', items:[{text:'Yes please, and send it to the whole team.'}], note:V.demo === 'failed' ? 'failed' : waits ? 'waits' : ''}];
  }
  const earlier = V.history === 'button' && V.view !== 'ticket' ? el('div', 'display:grid;justify-items:center;padding:var(--s2) 0', {}, el('button', '', {class:'btn ghost sm', type:'button'}, icon(I.clock), 'Earlier days')) : null;
  const log = el('div', 'flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column;padding:0 ' + (phone ? 'var(--s4)' : 'var(--s5)'), {role:'log', 'aria-label':'Messages', id:'log'},
    el('div', 'margin-top:auto;display:grid;width:100%;max-width:880px', {}, earlier, day.map(g => g.day ? divider(g) : V.msg === 'bubbles' ? bubbleGroup(g) : rowGroup(g)), V.demo === 'empty' && V.view !== 'ticket' ? welcome() : null, typing(), el('div', 'height:var(--s3)')));
  log.style.maskImage = 'linear-gradient(to bottom, transparent 0, black 28px)';
  requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; });
  return log;
}

// ---- header, message box, side panel ------------------------------------------------------------------------------------
function header() {
  const back = phone ? el('a', 'margin-left:calc(var(--s2) * -1)', {class:'btn ghost sm', href:'?screen=list'}, icon(I.back), 'Chats') : null;
  const ticket = V.view === 'ticket';
  const text = ticket
    ? [el('h1', 'margin:0;font-size:16px;line-height:24px;font-weight:600;' + T.one, {}, 'Plan the team lunch on Friday'),
       el('span', 'display:flex;align-items:center;gap:var(--s2);min-width:0;' + T.meta + ';color:var(--text-muted)', {}, el('span', '', {class:'dot working'}), el('span', T.one, {}, phone ? 'Working · 2 of 3 done' : 'PIL-1 · Your helper is working · 2 of 3 steps done'))]
    : [el('h1', 'margin:0;font-size:16px;line-height:24px;font-weight:600;' + T.one, {}, 'Your helper'), V.presence === 'a' ? statusLine(phone, false) : null];
  const actions = phone ? (ticket ? el('a', 'flex:none', {class:'btn outline sm', href:'../../ticket/ticket.html'}, 'Ticket') : null) : el('div', 'display:flex;gap:var(--s1);flex:none', {},
    HELPER_STATE.button && V.presence === 'a' && !ticket ? el('button', '', {class:'btn outline sm', type:'button'}, HELPER_STATE.button) : null,
    HELPER_STATE.fix && V.presence === 'a' && !ticket ? el('a', '', {class:'btn outline sm', href:'../../settings/settings.html'}, HELPER_STATE.fix) : null,
    ticket ? el('a', '', {class:'btn outline sm', href:'../../ticket/ticket.html'}, 'Open the ticket') : null,
    V.history === 'button' && !ticket ? el('button', '', {class:'btn ghost sm', type:'button'}, icon(I.clock), 'Earlier') : null);
  return el('header', 'display:flex;align-items:center;gap:var(--s3);min-height:64px;padding:var(--s2) ' + (phone ? 'var(--s4)' : 'var(--s5)') + ';border-bottom:' + T.line, {id:'thread-head'},
    back, avatar(ticket ? 'ticket' : 'helper', 36, !ticket), el('div', 'display:grid;gap:2px;min-width:0;flex:1', {}, text), actions);
}
function staged() {
  const tile = name => el('span', 'display:inline-flex;align-items:center;gap:var(--s2);padding:var(--s1) var(--s1) var(--s1) var(--s2);border-radius:var(--r1);background:var(--surface-2);font-size:12px', {},
    icon(I.file, 14), name, el('span', T.meta, {}, name.endsWith('pdf') ? '310 KB' : '1.2 MB'), el('button', '', {class:'btn ghost icon sm', type:'button', 'aria-label':'Remove ' + name, title:'Remove'}, icon(I.x, 14)));
  return el('div', 'display:flex;gap:var(--s2);flex-wrap:wrap', {}, tile('menu-linde.pdf'), tile('table-plan.png'));
}
function composer() {
  const ticket = V.view === 'ticket', label = ticket ? 'Message your helper about this ticket' : 'Message your helper';
  const strip = V.presence === 'c' && !ticket ? el('div', 'display:flex;align-items:center;gap:var(--s2);padding:0 var(--s1) var(--s2)', {}, statusLine(false),
    HELPER_STATE.button ? el('button', 'margin-left:auto', {class:'btn outline sm', type:'button'}, HELPER_STATE.button) : null) : null;
  const text = V.staged ? 'Here is their menu and the table plan.' : V.demo === 'typed' ? 'Yes please, and send it to the whole team.' : '';
  let box;
  if (V.composer === 'b') {
    box = el('form', 'display:flex;gap:var(--s2);align-items:flex-end', {},
      el('button', '', {class:'btn ghost icon', type:'button', 'aria-label':'Attach a file', title:'Attach a file'}, icon(I.clip, 18)),
      el('div', 'flex:1;min-width:0;display:grid;gap:var(--s2)', {}, V.staged ? staged() : null,
        el('textarea', 'width:100%;resize:none;min-height:var(--h);height:auto;padding:var(--s2) var(--s3);line-height:20px', {class:'input', rows:'1', 'aria-label':label, placeholder:label}, text)),
      el('button', '', {class:'btn primary', type:'submit', disabled:!text}, icon(I.send), 'Send'));
  } else {
    box = el('form', 'display:grid;gap:var(--s2);padding:var(--s3);border:1px solid var(--input);border-radius:var(--r2);background:var(--surface)', {},
      V.staged ? staged() : null,
      el('textarea', 'width:100%;resize:none;border:0;outline:0;background:transparent;color:var(--text);font:inherit;font-size:14px;line-height:22px;padding:0;min-height:' + (phone ? '22px' : '44px'), {rows:phone ? '1' : '2', 'aria-label':label, placeholder:label}, text),
      el('div', 'display:flex;align-items:center;gap:var(--s2)', {},
        el('button', '', {class:'btn ghost sm', type:'button'}, icon(I.clip), 'Attach'),
        phone ? null : el('span', 'font-size:12px;line-height:16px;color:var(--text-muted);margin-left:auto', {}, 'Enter to send'),
        el('button', phone ? 'margin-left:auto' : '', {class:'btn primary sm', type:'submit', disabled:!text}, icon(I.send), 'Send')));
  }
  return el('div', 'padding:var(--s2) ' + (phone ? 'var(--s4)' : 'var(--s5)') + ' var(--s4)', {id:'composer'}, el('div', 'max-width:880px', {}, strip, box));
}
function sidePanel() {
  const h = t => el('h3', 'margin:var(--s4) 0 var(--s2);font-size:12px;line-height:16px;font-weight:500;color:var(--text-faint)', {}, t);
  const row = (a, b) => el('div', 'display:flex;gap:var(--s2);align-items:center;padding:var(--s2) 0;border-top:' + T.line + ';font-size:14px', {}, el('span', 'flex:1;min-width:0', {}, a), b);
  const pill = t => el('span', '', {class:'pill', 'data-state':'done'}, t);
  if (V.view === 'ticket') return el('aside', 'min-height:0;overflow:auto;padding:var(--s4);border-left:' + T.line, {id:'pane-side', 'aria-label':'The ticket'},
    el('p', T.meta + ';margin:0 0 var(--s2)', {}, 'The ticket · everyone in this chat sees it'),
    el('strong', 'font-weight:600;color:var(--text)', {}, 'PIL-1 · Plan the team lunch on Friday'),
    el('p', 'margin:var(--s3) 0 0;font-size:14px;line-height:20px', {}, 'Twelve people, one table near the office, a vegetarian choice.'),
    h('Done when'), el('p', 'margin:0;font-size:14px;line-height:20px', {}, 'A table is booked and everyone has the address.'),
    h('Steps · 2 of 3 done'), row('Ask the team who comes', pill('Done')), row('Find three places near the office', pill('Done')), row('Book the table', el('span', 'display:flex;gap:6px;align-items:center;' + T.meta, {}, el('span', '', {class:'dot working'}), 'Working on it')));
  if (V.presence !== 'b') return null;
  return el('aside', 'min-height:0;overflow:auto;padding:var(--s4);border-left:' + T.line, {id:'pane-side', 'aria-label':'Your helper now'},
    el('div', 'display:flex;gap:var(--s3);align-items:center', {}, avatar('helper', 36, true), el('div', 'display:grid;gap:2px', {}, el('strong', 'font-size:14px', {}, 'Your helper'), statusLine(true, false))),
    h('Working on'),
    V.state === 'working' ? [ticketCard({key:'PIL-1', title:'Plan the team lunch on Friday', state:'working', label:'Working', fact:'2 of 3 steps done'}), el('a', 'margin-top:var(--s2)', {class:'btn outline sm', href:'../../focus/focus-v4d.html'}, icon(I.live), 'Watch live')]
      : el('p', T.meta + ';margin:0', {}, V.state === 'stopped' ? 'Nothing. Your helper is not running.' : 'Nothing right now.'),
    V.state === 'stopped' ? el('button', 'margin-top:var(--s2)', {class:'btn outline sm', type:'button'}, 'Start helper') : null,
    h('Waiting for you'), row('Supplier: Tuesday or Thursday?', el('a', 'color:var(--brand);flex:none', {href:'../../review/review.html'}, 'Answer ›')),
    h('Today'), row('Messages', el('span', T.meta, {}, '9')), row('Tickets moved on', el('span', T.meta, {}, '2')));
}

// ---- the page ----------------------------------------------------------------------------------------------------------
const main = document.getElementById('content'), root = document.getElementById('msgr');
const thread = () => el('section', 'display:flex;flex-direction:column;min-width:0;min-height:0', {id:'pane-thread', 'aria-label':'Conversation'}, header(), messages(), composer());
if (phone) {
  main.style.cssText = 'padding:0;max-width:none;height:calc(100dvh - 60px);display:flex;flex-direction:column';
  root.style.cssText = 'flex:1;min-height:0;display:grid';
  root.append(V.screen === 'list' ? chatList() : thread());
} else {
  const side = sidePanel(), cols = '344px minmax(0,1fr)' + (side ? ' 296px' : '');
  const grid = 'display:grid;grid-template-columns:' + cols + ';min-height:0;flex:1';
  if (V.frame === 'card') {
    main.style.cssText = 'max-width:none;height:calc(100dvh - 56px);display:flex;flex-direction:column;gap:var(--s4);padding:var(--s5) var(--page-gutter)';
    main.prepend(el('h1', 'margin:0;font-size:28px;line-height:36px;font-weight:600', {}, 'Chat'));
    root.style.cssText = grid + ';border:' + T.line + ';border-radius:var(--r2);background:var(--surface);overflow:hidden';
    document.querySelectorAll('#msgr h1').forEach(n => n.setAttribute('role', 'presentation'));
  } else {
    main.style.cssText = 'padding:0;max-width:none;height:calc(100dvh - 56px);display:flex;flex-direction:column';
    root.style.cssText = grid;
  }
  root.append(chatList(), thread()); if (side) root.append(side);
}
})();

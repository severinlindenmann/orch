const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function context() {
  const h = (tag, attrs, ...children) => ({tag, attrs, style:{}, children:children.flat(Infinity).filter(c => c != null),
    append(...nodes){this.children.push(...nodes);}, prepend(...nodes){this.children.unshift(...nodes);},
    addEventListener(){}, get textContent(){return this.children.map(c => typeof c === 'object' ? c.textContent : c).join('');}});
  const c = vm.createContext({h, heading:(title, sub = '') => h('header', {className:'page-heading'}, h('div', {}, h('h1', {}, title), sub ? h('p', {className:'muted'}, sub) : null)), fragment:(...children) => h('fragment', {}, children),
    array:v => Array.isArray(v) ? v : [], clean:v => String(v || ''), snapshot:false,
    state:{workspace:'Fish', chat:{messages:[]}}, ticketOf:() => null, time:() => '', date:v => v,
    MutationObserver:class {observe(){}}, document:{documentElement:{}}, CSS:{supports:() => false},
    iconEl:() => null, window:{addEventListener(){}}, location:{hash:''}, render(){}, setTimeout:() => 0});
  vm.runInContext(fs.readFileSync(require('node:path').join(__dirname, '../src/orch_dashboard/web/pages/chat.js'), 'utf8'), c);
  return c;
}
test('proposal offers a person Make ticket, then the same ticket card as every other ticket', () => {
  const c = context();
  const card = c.chatRefs([{kind:'proposal', title:'Fish'}], 'message-m_abcdefghij', 'm_abcdefghij')[0];
  assert.equal(card.tag, 'button');
  assert.equal(card.attrs['data-id'], 'm_abcdefghij');
  assert.match(JSON.stringify(card), /Make ticket: Fish/);
  c.window.DashHelpers = {statusWord:s => ({open:'Not started'}[s] || s)};
  c.ticketOf = id => id === 't_fish' ? {id:'t_fish', key:'FS-1', status:'open', title:'Fish', questions:[]} : null;
  const made = c.chatRefs([{kind:'proposal', title:'Fish', made:{id:'t_fish', key:'FS-1'}}], 'x')[0];
  const ticket = c.chatRefs([{kind:'ticket', id:'t_fish', key:'FS-1', title:'Fish'}], 'x')[0];
  assert.equal(made.tag, 'article'); assert.equal(made.attrs.className, ticket.attrs.className);
  assert.equal(nodes(made, n => n.tag === 'a')[0].attrs.href, '#ticket/t_fish');
  assert.equal(nodes(made, n => /chat-status/.test(n.attrs?.className || ''))[0].textContent, 'Not started');
  assert.equal(nodes(made, n => n.tag === 'details').length, 0, 'no Details toggle: the key is shown');
  assert.match(made.textContent, /FS-1/);
  c.snapshot = true;
  assert.equal(c.chatRefs([{kind:'proposal',title:'Fish'}], 'x')[0].attrs.disabled, true);
});
// ORCH-1812: Make ticket only makes a Backlog ticket; its card has the one Start (pages/start.js) until a helper ran.
test('a made ticket card offers Start helper until a helper ran', () => {
  const c = context(), real = require('../src/orch_dashboard/web/helpers.js');
  c.window.DashHelpers = {statusWord:s => s, agentLine:real.agentLine};
  c.startHost = (t, key) => c.h('span', {className:'start-host', 'data-start-host':t.id, 'data-key':key});
  let fish = {id:'t_fish', key:'FS-1', status:'open', title:'Fish', questions:[]};
  c.ticketOf = id => id === 't_fish' ? fish : null;
  const made = () => c.chatRefs([{kind:'proposal', title:'Fish', made:{id:'t_fish', key:'FS-1'}}], 'x')[0];
  const hosts = card => nodes(card, n => n.attrs?.['data-start-host'] === 't_fish');
  assert.equal(hosts(made()).length, 1);
  assert.equal(hosts(made())[0].attrs['data-key'], 'x-ref-0-start');
  c.state.runs = {t_fish:{running:true, state:'alive', claim:{}}};
  assert.equal(hosts(made()).length, 0);
  c.state.runs = {};
  fish = {...fish, sessions:[{id:'s1', last_used:new Date().toISOString()}]};
  assert.equal(hosts(made()).length, 0);
  fish = {...fish, sessions:[], status:'done'};
  assert.equal(hosts(made()).length, 0);
  fish = {...fish, status:'open'};
  assert.equal(hosts(c.chatRefs([{kind:'ticket', id:'t_fish', key:'FS-1', title:'Fish'}], 'x')[0]).length, 0);
  assert.equal(hosts(c.chatRefs([{kind:'proposal', title:'Fish', made:{id:'t_fish', key:'FS-1'}}], 'x', null, true)[0]).length, 0);
});
// Owner feedback 14 Nov, fb25: "Ask the helper" opened an empty chat; the history only showed after a reload.
test('Open helper shows the existing helper conversation with its history right away', () => {
  const c = context();
  c.state.chat.messages = [{id:'old', text:'Old'}, {id:'new', text:'Fish', convo_start:true}];
  c.chatOpenAgent();
  assert.equal(c.location.hash, '#chat');
  assert.deepEqual(Array.from(c.chatConversation(), m => m.id), ['old', 'new']);
  assert.doesNotMatch(JSON.stringify(c.chatHeader(null)), /New conversation/);
});
// fb16: "Your helper is thinking…" for ever when no helper started
test('the line under your message: writing, saved while the helper is not running, not answered yet', () => {
  const c = context();
  const at = new Date(Date.now() - 5 * 60000).toISOString();
  c.state.chat.messages = [{id:'m1', by:'you', text:'hi', at}];
  c.state.services = [{addon:'automation', running:false}];
  let thread = JSON.stringify(c.chatThread(null));
  assert.doesNotMatch(thread, /is writing/);
  assert.match(thread, /Saved\. Your helper reads it when it starts\./);
  assert.match(JSON.stringify(c.chatHeader(null)), /Not running.*"data-action":"start".*Start helper/, 'Start helper sits under the name, outlined');
  c.state.services = [];
  thread = JSON.stringify(c.chatThread(null));
  assert.doesNotMatch(thread, /is writing|"data-action":"start"/);
  assert.match(thread, /has not answered yet/);
  c.state.chat.messages = [{id:'m1', by:'you', text:'hi', at:new Date(Date.now() - 10000).toISOString()}];
  assert.match(JSON.stringify(c.chatThread(null)), /Your helper is writing…/);
  c.state.chat.messages = [{id:'m1', by:'you', text:'hi', at}]; c.state.chat.running = true;
  assert.match(JSON.stringify(c.chatThread(null)), /Your helper is writing…/);
});
test('moved conversation renders its banner and header ticket link', () => {
  const c = context();
  c.state.chat.messages = [{id:'m', by:'you', text:'Fish', moved_to:{id:'t_fish',key:'FS-1',title:'Fish'}}];
  const thread = JSON.stringify(c.chatThread(null, null));
  assert.match(thread, /This conversation now belongs to ticket/);
  assert.match(thread, /Open ticket/);
  assert.match(JSON.stringify(c.chatHeader(null)), /FS-1/);
});
test('New chat picker offers your helper, workspaces and your phone; Your phone shows the phone messages', async () => {
  const c = context();
  c.state.chat = {day:'2026-11-11', activity:{}, messages:[{id:'p1', by:'you', via:'phone', text:'From the phone'}, {id:'d1', by:'you', via:'dashboard', text:'At the desk'}]};
  const picker = JSON.stringify(c.chatNewChatRows());
  assert.match(picker, /Your helper/); assert.match(picker, /Your phone/);
  vm.runInContext("chatNewChatPick('phone')", c);
  assert.equal(vm.runInContext('chatUi.filter', c), 'phone');
  assert.match(JSON.stringify(c.chatHeader(null)), /Your phone/);
  vm.runInContext("chatNewChatPick('helper')", c);
  assert.equal(vm.runInContext('chatUi.filter', c), 'all');
});

test('General phone text is rendered before the helper answer', () => {
  const c = context();
  c.state = JSON.parse(fs.readFileSync(require('node:path').join(__dirname, 'fixtures/general-chat.json'), 'utf8'));
  c.state.workspace = 'General';
  const thread = JSON.stringify(c.chatThread(null, null));
  assert.ok(thread.indexOf('What is still open this week?') >= 0);
  assert.ok(thread.indexOf('What is still open this week?') < thread.indexOf('Two tasks remain.'));
  assert.doesNotMatch(thread, /orch relay send|waiting for you\. Answer it/);
});

function nodes(node, predicate) {
  return !node || typeof node !== 'object' ? [] : [
    ...(predicate(node) ? [node] : []), ...node.children.flatMap(child => nodes(child, predicate)),
  ];
}

for (const mode of ['Today', 'agent conversation', 'History day']) {
  test(`real Pilatus day renders every phone bubble before its reply in ${mode}`, async () => {
    const c = context();
    const day = JSON.parse(fs.readFileSync(require('node:path').join(__dirname, 'fixtures/chat-day-pilatus-2026-11-11.json'), 'utf8'));
    c.state = {workspace:'pilatus', chat:day};
    if (mode === 'agent conversation') vm.runInContext('chatUi.agentConversation = true', c);
    if (mode === 'History day') {  // yesterday, scrolled up into the same conversation
      c.fetch = async url => {
        assert.equal(url, '/api/chat/day/' + day.day);
        return {ok:true, json:async () => day};
      };
      c.state = {workspace:'pilatus', chat:{day:'2026-11-12', messages:[]}};
      vm.runInContext('chatDays = {status:"ready", rows:[{day:"' + day.day + '", count:2}]}; chatUi.past = ["' + day.day + '"]', c);
      await c.chatLoad(day.day);
    }
    const page = c.chatPage();
    const logs = nodes(page, n => n.attrs?.role === 'log' && n.attrs['aria-label'] === 'Chat messages');
    assert.equal(logs.length, 1);
    const bubbles = nodes(logs[0], n => n.attrs?.className?.split(' ').includes('chat-message'));
    const ids = bubbles.map(n => n.attrs['data-message-id']);
    const phone = bubbles.find(n => n.attrs['data-message-id'] === 'm_74jdus1swo0w0dsc');
    assert.ok(phone, 'phone message is an ordinary Chat bubble');
    assert.match(phone.attrs.className, /chat-out/);
    assert.ok(nodes(phone, n => /chat-message-text/.test(n.attrs?.className || ''))
      .some(n => n.textContent === 'What is still open this week? [1203]'));
    assert.equal(ids.indexOf('m_kudgohd14g8qumf5'), ids.indexOf('m_74jdus1swo0w0dsc') + 1);
    const expected = mode === 'agent conversation' ? day.messages.slice(-2) : day.messages;
    assert.deepEqual(ids, expected.map(m => m.id));
  });
}

test('header reads Your helper once a message exists, and Send works while the helper is thinking', () => {
  const c = context();
  vm.runInContext('chatUi.agentConversation = true', c);
  c.state.chat.messages = [{id:'m1', by:'you', text:'hi', at:new Date(Date.now() - 10000).toISOString()}];
  assert.doesNotMatch(JSON.stringify(c.chatHeader(null)), /New conversation/);
  assert.match(JSON.stringify(c.chatHeader(null)), /Your helper/);
  c.state.chat.messages = [];
  assert.match(JSON.stringify(c.chatHeader(null)), /New conversation with your helper/);
  c.state.chat.messages = [{id:'m1', by:'you', text:'hi', at:new Date(Date.now() - 10000).toISOString()}];
  c.state.chat.running = true;
  vm.runInContext("chatUi.agentConversation = false; chatUi.drafts.chat = 'one more thing'", c);
  const thread = c.chatThread(null);
  assert.match(JSON.stringify(thread), /is writing/);
  const send = nodes(thread, n => n.attrs?.['data-key'] === 'send')[0];
  assert.equal(send.attrs.disabled, false);
});

test('orch.say from the shown add-on frame fills the draft; a URL does not; a typed draft is kept', () => {
  const c = context(), frameWin = {};
  c.location = {hash:'#addon/factory', origin:'http://x'};
  c.route = () => ({kind:'page', id:'factory'});
  c.state.addons = [{name:'factory', shipped:true}];
  c.document.querySelector = () => ({contentWindow:frameWin});
  const msg = (text, extra = {}) => ({data:{type:'orch.say', text}, origin:'http://x', source:frameWin, ...extra});
  assert.equal(c.chatSayRequest(msg('Factory: a page\nwith hours\u0007')).text, 'Factory: a page with hours');
  assert.equal(c.chatSayRequest(msg('x'.repeat(900))).text.length, 500);
  assert.equal(c.chatSayRequest(msg('hi', {origin:'http://evil'})), null);
  assert.equal(c.chatSayRequest(msg('hi', {source:{}})), null);
});

// ORCH-2065: Factory's Change in Chat only opens Chat. An empty composer gets the suggestion; a draft you typed stays
// and the suggestion is not added; nothing is ever sent.
test('Change in Chat from Factory opens Chat, keeps a typed draft and never sends', () => {
  const c = context(), frameWin = {}, sent = [];
  c.location = {hash:'#addon/factory', origin:'http://x'};
  c.route = () => ({kind:'page', id:'factory'});
  c.state.addons = [{name:'factory', shipped:true}];
  c.document.querySelector = () => ({contentWindow:frameWin});
  c.fetch = (...a) => { sent.push(a); return Promise.resolve({ok:true, json:async () => ({})}); };
  const ask = 'Factory: I would like Autopilot to answer routine pauses. What would it cover?';
  const msg = {data:{type:'orch.say', text:ask}, origin:'http://x', source:frameWin};
  c.chatSayOpen(msg);
  assert.equal(vm.runInContext('chatUi.drafts.chat', c), ask);
  assert.equal(c.location.hash, '#chat');
  vm.runInContext("chatUi.drafts.chat = 'Milk, eggs, bread'", c);
  c.location.hash = '#addon/factory';
  c.chatSayOpen(msg);
  assert.equal(vm.runInContext('chatUi.drafts.chat', c), 'Milk, eggs, bread');
  assert.equal(c.location.hash, '#chat');
  c.location.hash = '#addon/factory';
  c.chatSayOpen({...msg, origin:'http://evil'});
  assert.equal(c.location.hash, '#addon/factory', 'a foreign message opens nothing');
  assert.deepEqual(sent, []);
});

// ORCH-2171, lane chat-messenger option A: the list, the status line, files, message states, earlier days, empty chat.
test('the list: Chats with New chat, your helper pinned on top with its dot, then groups and finished groups', () => {
  const c = context();
  c.state.chat.messages = [{id:'m1', by:'helper', text:'Draft for the invitation: Thursday 3 December', at:new Date().toISOString()}];
  c.state.groups = {hosted:[], joined:[{id:'g1', title:'Launch', members:[{ws:'ws_a', name:'Sales'}], log:[{id:'x', text:'hi', at:'2026-11-01T10:00:00Z'}]},
    {id:'g2', title:'Old', closed:true, members:[], log:[]}]};
  const list = c.chatList(), text = list.textContent;
  assert.match(text, /^ChatsNew chat/);
  const rows = nodes(list, n => /chat-list-row/.test(n.attrs?.className || ''));
  assert.equal(rows[0].attrs['data-id'], 'chat', 'your helper is the first row');
  assert.match(rows[0].attrs.className, /chat-pinned/);
  assert.equal(nodes(rows[0], n => /presence-dot ready/.test(n.attrs?.className || '')).length, 1);
  assert.match(rows[0].textContent, /Draft for the invitation/);
  assert.ok(text.indexOf('Groups') < text.indexOf('Finished groups'));
  assert.doesNotMatch(text, /This workspace|Other workspaces|Earlier/);
});
test('the status line under Your helper: ready, working on a ticket, not running with Start helper, stopped with a fix', () => {
  const c = context();
  const line = () => nodes(c.chatHeader(null), n => n.attrs?.['data-key'] === 'helper-status')[0];
  assert.equal(line().textContent, 'Ready to answer');
  c.tickets = () => [{id:'t_a', key:'PIL-1', title:'Plan the team lunch on Friday', status:'active'}];
  c.window.DashHelpers = {helperRows:(ts) => ts.map(t => ({ticket:t, state:'working', finished:false}))};
  assert.equal(line().textContent, 'Working on Plan the team lunch on Friday');
  c.state.services = [{running:false}];
  assert.match(line().textContent, /^Not running/);
  assert.equal(nodes(line(), n => n.attrs?.['data-action'] === 'start')[0].attrs.className, 'btn outline sm', 'starting is never the filled button');
  c.window.DashHelpers.helperStartReason = () => 'The Claude sign-in stopped working.';
  assert.match(line().textContent, /^Stopped · The Claude sign-in stopped working/);
  assert.match(line().textContent, /See what to fix/);
});
test('files on a message are small cards that open the file from the Chat ticket', () => {
  const c = context();
  c.state.chat = {ticket:'t_chat01', messages:[{id:'m1', by:'you', text:'', files:[{name:'agenda q4.docx', size:18432}], at:new Date().toISOString()}]};
  const card = nodes(c.chatThread(null), n => n.attrs?.className === 'file-card')[0];
  assert.equal(card.attrs.href, '/api/file?t=t_chat01&k=artifacts&n=agenda%20q4.docx');
  assert.match(card.textContent, /agenda q4\.docx18 KB/);
  assert.match(c.chatListRow(null).textContent, /You: agenda q4\.docx/);
});
test('a message that did not go out stays with "Not sent" and Try again; the next send goes on', async () => {
  const c = context();
  c.window.orchAct = async () => ({ok:false});
  c.document.querySelector = () => null;
  vm.runInContext("chatUi.drafts.chat = 'Send it to the team'", c);
  const r = await c.chatSend();
  assert.deepEqual(JSON.parse(JSON.stringify(r)), {ok:true, text:''}, 'the box is free again');
  const thread = c.chatThread(null), text = JSON.stringify(thread);
  assert.match(text, /Send it to the team/);
  assert.match(text, /Not sent\. Check the connection\./);
  const retry = nodes(thread, n => n.attrs?.['data-chat-action'] === 'retry-say')[0];
  assert.ok(retry);
  let said = null;
  c.window.orchAct = async (op, args) => { said = [op, args]; return {ok:true}; };
  await c.chatClick({target:{closest:() => ({dataset:{chatAction:'retry-say', id:retry.attrs['data-id']}})}});
  assert.equal(said[0], 'chat.say'); assert.equal(said[1].text, 'Send it to the team');
  assert.doesNotMatch(JSON.stringify(c.chatThread(null)), /Not sent/);
});
test('files go onto the Chat ticket first, then the message names them', async () => {
  const c = context();
  c.state.chat.ticket = 't_chat01';
  const calls = [];
  c.ticketAttachFiles = async (tid, files) => { calls.push(['attach', tid, files.length]); return {ok:true, names:['agenda.docx']}; };
  c.window.orchAct = async (op, args) => { calls.push([op, args]); return {ok:true}; };
  c.document.querySelector = () => null;
  vm.runInContext("chatUi.drafts.chat = 'See attached'; chatUi.outFiles = [{name:'agenda.docx', url:'data:x;base64,AA=='}]", c);
  await c.chatSend();
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [['attach', 't_chat01', 1], ['chat.say', {text:'See attached', files:['agenda.docx']}]]);
});
test('earlier days come back by scrolling up: one button on top, the day under its own line, Today says the fresh start once', async () => {
  const c = context();
  c.state.chat = {day:'2026-11-25', messages:[{id:'m2', by:'you', text:'today', at:new Date().toISOString()}]};
  vm.runInContext('chatDays = {status:"ready", rows:[{day:"2026-11-24", count:1}, {day:"2026-11-20", count:1}]}', c);
  let text = JSON.stringify(c.chatThread(null));
  assert.match(text, /Show earlier messages/);
  assert.match(text, /Your helper starts each day without yesterday’s conversation\./);
  c.document.querySelector = () => null;
  c.fetch = async url => ({ok:true, json:async () => ({day:url.slice(-10), messages:[{id:'m1', by:'helper', text:'from ' + url.slice(-10), at:'2026-11-24T10:00:00Z'}]})});
  await c.chatOlder();
  text = JSON.stringify(c.chatThread(null));
  assert.match(text, /from 2026-11-24/);
  assert.ok(text.indexOf('from 2026-11-24') < text.indexOf('"Today"'));
  assert.match(text, /Show earlier messages/, 'one more day to go');
  await c.chatOlder();
  assert.doesNotMatch(JSON.stringify(c.chatThread(null)), /Show earlier messages/);
});
test('an empty chat is a first message from your helper with three starters, under the Today line', () => {
  const c = context();
  const thread = c.chatThread(null), welcome = nodes(thread, n => n.attrs?.['data-key'] === 'welcome')[0];
  assert.match(welcome.attrs.className, /thread-line/);
  assert.match(welcome.textContent, /Talk it through with your helper/);
  assert.equal(nodes(welcome, n => n.attrs?.['data-chat-action'] === 'prompt').length, 3);
  assert.doesNotMatch(JSON.stringify(thread), /04:00/);
});
test('messages are rows: name and time once, the next one by the same writer within five minutes joins it', () => {
  const c = context(), at = n => new Date(Date.now() - n * 60000).toISOString();
  c.state.chat.messages = [{id:'a', by:'helper', text:'one', at:at(20)}, {id:'b', by:'helper', text:'two', at:at(19)}, {id:'c', by:'helper', text:'three', at:at(5)}];
  const rows = nodes(c.chatThread(null), n => /chat-message/.test(n.attrs?.className || '') && n.tag === 'article');
  assert.deepEqual(rows.map(r => /\bcont\b/.test(r.attrs.className)), [false, true, false]);
  assert.match(rows[0].attrs.className, /thread-line/);
});

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function context() {
  const h = (tag, attrs, ...children) => ({tag, attrs, style:{}, children:children.flat(Infinity).filter(c => c != null),
    append(...nodes){this.children.push(...nodes);}, prepend(...nodes){this.children.unshift(...nodes);},
    addEventListener(){}, get textContent(){return this.children.map(c => typeof c === 'object' ? c.textContent : c).join('');}});
  const c = vm.createContext({h, fragment:(...children) => h('fragment', {}, children),
    array:v => Array.isArray(v) ? v : [], clean:v => String(v || ''), snapshot:false,
    state:{workspace:'Fish', chat:{messages:[]}}, ticketOf:() => null, time:() => '', date:v => v,
    MutationObserver:class {observe(){}}, document:{documentElement:{}}, CSS:{supports:() => false},
    iconEl:() => null, window:{addEventListener(){}}, location:{hash:''}, render(){}});
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
  assert.match(nodes(made, n => n.tag === 'details')[0].textContent, /FS-1/);
  c.snapshot = true;
  assert.equal(c.chatRefs([{kind:'proposal',title:'Fish'}], 'x')[0].attrs.disabled, true);
});
test('Open helper starts empty and shows only the latest conversation after sending', () => {
  const c = context();
  c.state.chat.messages = [{id:'old', text:'Old'}, {id:'new', text:'Fish', convo_start:true}];
  c.chatOpenAgent();
  assert.equal(c.location.hash, '#chat');
  assert.equal(c.chatConversation().length, 0);
  assert.match(JSON.stringify(c.chatHeader(null, false)), /New conversation with your helper/);
  assert.doesNotMatch(JSON.stringify(c.chatHeader(null, false)), /agent/);
  vm.runInContext('chatUi.newConversation = false', c);
  assert.deepEqual(Array.from(c.chatConversation(), m => m.id), ['new']);
});
test('moved conversation renders its banner and header ticket link', () => {
  const c = context();
  c.state.chat.messages = [{id:'m', by:'you', text:'Fish', moved_to:{id:'t_fish',key:'FS-1',title:'Fish'}}];
  const thread = JSON.stringify(c.chatThread(null, null));
  assert.match(thread, /This conversation now belongs to ticket/);
  assert.match(thread, /Open ticket/);
  assert.match(JSON.stringify(c.chatHeader(null, false)), /FS-1/);
});
test('"Your helper" is the thread title, the Chat row title, the bubble, the composer and the thinking line; the workspace name sits under the title', () => {
  const c = context();
  c.state.workspace = 'pilatus'; c.state.chat.helper = 'pilatus helper';
  c.state.chat.messages = [{id:'m1', by:'ws_x', via:'helper', text:'Hi', at:'2026-11-09T10:00:00Z'}, {id:'m2', by:'you', via:'phone', text:'Yo', at:'2026-11-09T10:01:00Z'}];
  const thread = JSON.stringify(c.chatThread(null, null));
  assert.match(thread, /Your helper/);
  assert.match(thread, /Message your helper/);
  assert.doesNotMatch(thread, /[Pp]ilatus helper|Message Pilatus/);
  const times = nodes(c.chatThread(null, null), n => /chat-message-time/.test(n.attrs?.className || '')).map(n => n.textContent);
  assert.ok(times.every(t => !/helper/.test(t)), 'the time line never says "helper"');
  assert.ok(times.some(t => /from your phone/.test(t)));
  assert.match(thread, /Starts fresh each day at 04:00/);
  assert.doesNotMatch(thread, /Context cleared/);
  const head = JSON.stringify(c.chatHeader(null, false));
  const title = nodes(c.chatHeader(null, false), n => n.attrs?.['data-key'] === 'chat-title')[0].textContent;
  assert.equal(title, 'Your helper'); assert.match(head, /Pilatus workspace/); assert.doesNotMatch(head, /[Pp]ilatus helper|Chat · /);
  const row = nodes(c.chatListRow(null), n => n.tag === 'strong')[0].textContent;
  assert.equal(row, 'Your helper');
  assert.match(JSON.stringify(c.chatThinking('Your helper', true)), /Your helper is thinking/);
});

test('the chip row is gone: one From my phone checkbox, and "Working on N tickets" only when N > 0', () => {
  const c = context();
  c.state.chat = {day:'2026-11-11', activity:{phone_today:2, from_workspaces:{Home:3}, running:0}, messages:[
    {id:'p1', by:'you', via:'phone', text:'From the phone'}, {id:'r1', by:'ws_x', via:'helper', text:'Reply to phone', reply_to:'p1'},
    {id:'d1', by:'you', via:'dashboard', text:'At the desk'}, {id:'r2', by:'ws_x', via:'helper', text:'Reply to desk', reply_to:'d1'}]};
  const page = JSON.stringify(c.chatPage());
  assert.doesNotMatch(page, /From phone · |From Home · |Running · /);
  assert.doesNotMatch(page, /Working on/);
  assert.match(page, /From my phone/); assert.match(page, /Phone & workspaces/);
  assert.doesNotMatch(page, /chat-list"/, 'relay off: no conversation list');
  c.state.chat.activity.running = 2;
  assert.match(JSON.stringify(c.chatHeader(null, false)), /Working on 2 tickets/);
  vm.runInContext("chatUi.filter = 'phone'", c);
  const ids = nodes(c.chatThread(null, null), n => n.attrs?.['data-message-id']).map(n => n.attrs['data-message-id']);
  assert.deepEqual(ids, ['p1', 'r1']);
});

test('ticket card: plain title and due first, "Needs your OK" in the accent, the option buttons, the key behind Details', () => {
  const c = context();
  c.state.now = '2026-11-11T10:00:00';
  c.window.DashHelpers = {statusWord:s => ({review:'Ready for review', waiting:'Needs you', ready:'Not started'}[s] || s)};
  const tickets = {
    t_plant1:{id:'t_plant1', key:'PIL-71', status:'waiting', due:'2026-11-11', title:'Water office plants – planter 0142-FFE2A659, Wed 11 Nov',
      questions:[{id:'q_water1', text:'Watered?', options:['Watered', 'Not yet']}]},
    t_lunch1:{id:'t_lunch1', key:'PIL-9', status:'ready', due:'2026-11-13', title:'Book a table for the team lunch. Ask me before you book.', questions:[]},
  };
  c.ticketOf = id => tickets[id] || null;
  const [plant, lunch] = c.chatRefs([{kind:'ticket', id:'t_plant1', key:'PIL-71', title:tickets.t_plant1.title}, {kind:'ticket', id:'t_lunch1', key:'PIL-9', title:tickets.t_lunch1.title}], 'm', 'm_x');
  const strong = n => nodes(n, x => x.tag === 'strong')[0].textContent;
  assert.equal(strong(plant), 'Water office plants · today');
  assert.equal(strong(lunch), 'Book a table for the team lunch · 2026-11-13');
  const status = nodes(plant, n => /chat-status/.test(n.attrs?.className || ''))[0];
  assert.equal(status.textContent, 'Needs your OK'); assert.match(status.attrs.className, /chat-needs-ok/);
  assert.doesNotMatch(JSON.stringify(nodes(lunch, n => /chat-status/.test(n.attrs?.className || ''))), /chat-needs-ok/);
  const answers = nodes(plant, n => n.attrs?.['data-chat-action'] === 'answer');
  assert.deepEqual(answers.map(b => b.attrs['data-answer']), ['Watered', 'Not yet']);
  assert.ok(answers.every(b => b.attrs['data-ticket'] === 't_plant1' && b.attrs['data-q'] === 'q_water1'));
  assert.equal(nodes(lunch, n => n.attrs?.['data-chat-action'] === 'answer').length, 0, 'no invented actions');
  const details = nodes(plant, n => n.tag === 'details')[0];
  assert.match(details.textContent, /PIL-71/);
  const outside = plant.children.filter(n => n !== details).map(n => typeof n === 'object' ? n.textContent : n).join(' ');
  assert.doesNotMatch(outside, /PIL-71|FFE2A659/);
  const readOnly = c.chatRefs([{kind:'ticket', id:'t_plant1', key:'PIL-71', title:'x'}], 'm', 'm_x', true)[0];
  assert.equal(nodes(readOnly, n => n.attrs?.['data-chat-action'] === 'answer').length, 0, 'a day you can only read has no buttons');
});

test('ticket card title: ids and tags leave the shown title, Details keeps the full one, the stored title is untouched', () => {
  const c = context();
  assert.equal(c.chatPlainTitle('Check the backups of server mwbzgkii on Friday 13 Nov'), 'Check the backups of server on Friday 13 Nov');
  assert.equal(c.chatPlainTitle('Check the backups of server mwbvn2j7 on Friday 13 Nov'), 'Check the backups of server on Friday 13 Nov');
  assert.equal(c.chatPlainTitle('Team lunch 20 Nov [0911]'), 'Team lunch 20 Nov');
  for (const plain of ['Schwarz strengths and lengths', 'covid19 test at 4pm, 2nd floor', 'Print 100x200 posters', 'Rhythm workshop']) assert.equal(c.chatPlainTitle(plain), plain);
  c.ticketOf = () => null;
  const ref = {kind:'ticket', id:'t_cbkk39', key:'PIL-85', title:'Check the backups of server mwbzgkii on Friday 13 Nov'};
  const card = c.chatRefs([ref], 'm', 'm_x')[0];
  const details = nodes(card, n => n.tag === 'details')[0];
  const outside = card.children.filter(n => n !== details).map(n => typeof n === 'object' ? n.textContent : n).join(' ');
  assert.doesNotMatch(outside, /mwbzgkii|PIL-85/);
  assert.match(details.textContent, /PIL-85 · Check the backups of server mwbzgkii on Friday 13 Nov/);
  assert.equal(ref.title, 'Check the backups of server mwbzgkii on Friday 13 Nov');
});

test('previews use the first line that says something, never a dangling colon', async () => {
  const c = context();
  const answer = 'Still open this week:\n• Today (Wed 11): 4 planters wait for your OK.\n• Fri 13: team lunch.';
  assert.equal(c.chatPreview(answer), 'Today (Wed 11): 4 planters wait for your OK.');
  assert.equal(c.chatPreview('\n\nThanks, all set for Monday.'), 'Thanks, all set for Monday.');
  assert.equal(c.chatPreview('Done:'), 'Done');
  assert.equal(c.chatPreview(''), '');
  c.state.chat = {day:'2026-11-11', messages:[{id:'m1', by:'ws_x', text:answer}]};
  const row = c.chatListRow(null);
  assert.match(row.textContent, /Today \(Wed 11\): 4 planters/); assert.doesNotMatch(row.textContent, /this week:/);
  c.fetch = async () => ({ok:true, json:async () => [{day:'2026-11-10', count:2, last:'Still open this week:\n• Fri 13: team lunch.'}]});
  vm.runInContext("chatUi.open = 'history'", c);
  await c.chatLoad();
  const day = nodes(c.chatHistory(), n => n.attrs?.['data-key'] === 'day-2026-11-10')[0];
  assert.match(day.textContent, /Fri 13: team lunch\.$/); assert.doesNotMatch(day.textContent, /:$/);
});

test('a finished group is only under Earlier, a live one only under Groups', () => {
  const c = context();
  c.state.chat = {day:'2026-11-11', messages:[]};
  const tickets = {t_live:{id:'t_live', status:'active'}, t_done:{id:'t_done', status:'done'}, t_closed:{id:'t_closed', status:'active'}};
  c.ticketOf = id => tickets[id] || null;
  const member = {ws:'ws_a', name:'Home', joined_at:'2026-11-10T09:11:00'};
  c.state.groups = {hosted:[{id:'g_live', ticket:'t_live', title:'Live group', closed:false, members:[member], tasks:[]},
    {id:'g_done', ticket:'t_done', title:'Ticket done group', closed:false, members:[member], tasks:[]},
    {id:'g_closed', ticket:'t_closed', title:'Closed group', closed:true, members:[member], tasks:[]}],
    joined:[{id:'g_left', title:'Left group', left:true, members:[member], log:[]}]};
  const list = c.chatList().textContent;
  vm.runInContext("chatUi.open = 'history'", c);
  const earlier = c.chatHistory().textContent;
  assert.match(list, /Live group/); assert.doesNotMatch(earlier, /Live group/);
  for (const finished of ['Ticket done group', 'Closed group', 'Left group']) {
    assert.doesNotMatch(list, new RegExp(finished)); assert.match(earlier, new RegExp(finished));
  }
});

test('thread header: helper title with workspace and "Working on N tickets", then the phone filter and workspace link (no extra row)', () => {
  const c = context();
  c.state.chat = {day:'2026-11-11', activity:{running:2}, messages:[]};
  const head = c.chatHeader(null, false);
  const top = nodes(head, n => n.attrs?.className === 'chat-head-top')[0];
  assert.deepEqual(top.children.map(n => n.textContent), ['✧', 'Your helperFish workspace · Working on 2 tickets', 'Earlier']);
  const row = nodes(head, n => n.attrs?.className === 'chat-head-row')[0];
  assert.equal(row.textContent, 'From my phonePhone & workspaces');
  assert.equal(head.children.length, 2, 'the title row and the filter row');
});

test('Earlier: one entry point, past days first without today, then finished groups with their day', async () => {
  const c = context();
  c.state.chat = {day:'2026-11-11', messages:[]};
  c.state.groups = {hosted:[{id:'g1', ticket:'t_g', title:'Team lunch', closed:true, members:[{ws:'ws_a', name:'Home', joined_at:'2026-11-10T09:11:00'}], tasks:[]},
    {id:'g2', ticket:'t_h', title:'Office move', closed:false, members:[{ws:'ws_a', name:'Home', joined_at:'2026-11-11T08:05:00'}, {ws:'ws_b', name:'Reports', joined_at:'2026-11-11T08:06:00'}], tasks:[]}]};
  const list = JSON.stringify(c.chatList());
  assert.doesNotMatch(list, /History/);
  assert.match(list, /Office move/); assert.match(list, /2 helpers · started/);
  assert.match(JSON.stringify(c.chatHeader(null, false)), /Earlier/);
  c.fetch = async () => ({ok:true, json:async () => [{day:'2026-11-11', count:4, last:'today'}, {day:'2026-11-10', count:3, last:'tue'}]});
  vm.runInContext("chatUi.open = 'history'", c);
  await c.chatLoad();
  const page = c.chatHistory(), text = JSON.stringify(page);
  assert.doesNotMatch(text, /day-2026-11-11/);
  assert.match(text, /day-2026-11-10/);
  assert.ok(text.indexOf('Earlier days') < text.indexOf('Finished groups'));
  assert.match(text, /Team lunch · finished/);
  assert.equal(nodes(c.chatPage(), n => n.attrs?.type === 'search').length, 1, 'one search box');
  vm.runInContext("chatUi.day = '2026-11-10'", c);
  assert.match(JSON.stringify(c.chatHistory()), /you can read, not reply/);
  assert.match(JSON.stringify(c.chatHistory()), /Back to today/);
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
    if (mode === 'History day') {
      c.fetch = async url => {
        assert.equal(url, '/api/chat/day/' + day.day);
        return {ok:true, json:async () => day};
      };
      vm.runInContext('chatUi.open = "history"; chatUi.day = state.chat.day', c);
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
    assert.ok(nodes(phone, n => n.attrs?.className === 'chat-message-text')
      .some(n => n.textContent === 'What is still open this week? [1203]'));
    assert.equal(ids.indexOf('m_kudgohd14g8qumf5'), ids.indexOf('m_74jdus1swo0w0dsc') + 1);
    const expected = mode === 'agent conversation' ? day.messages.slice(-2) : day.messages;
    assert.deepEqual(ids, expected.map(m => m.id));
  });
}

test('with groups or workspace chats: grouped list (This workspace, Other workspaces, Groups); otherwise the simple helper chat', () => {
  const c = context();
  c.state.chat = {day:'2026-11-11', messages:[]};
  c.ticketOf = () => ({id:'t_live', status:'active'});
  c.state.groups = {hosted:[{id:'g_live', ticket:'t_live', title:'Live group', members:[{ws:'ws_a', name:'Home office'}], tasks:[]}], joined:[]};
  assert.match(JSON.stringify(c.chatThread(null, null)), /Talk it through with your helper/);
  const page = c.chatPage().children[0];
  assert.doesNotMatch(page.attrs.className, /chat-simple/);
  const list = page.children[0].textContent;
  assert.ok(list.indexOf('This workspace') < list.indexOf('Your helper') && list.indexOf('Groups') < list.indexOf('Live group'));
  assert.equal(nodes(page.children[0], n => n.attrs?.className === 'chat-avatar' && n.textContent === 'HO').length, 1, 'workspace initials');
  vm.runInContext("chatUi.search = 'live'", c);
  assert.equal(nodes(c.chatList(), n => n.attrs?.['data-id'] === 'chat')[0].hidden, true);
  c.state.groups = {hosted:[], joined:[]};
  assert.match(c.chatPage().children[0].attrs.className, /chat-simple/, 'only the helper chat');
});

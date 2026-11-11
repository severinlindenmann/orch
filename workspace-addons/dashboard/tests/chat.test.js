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
test('proposal offers a person Make ticket, then a ticket chip', () => {
  const c = context();
  const card = c.chatRefs([{kind:'proposal', title:'Fish'}], 'message-m_abcdefghij', 'm_abcdefghij')[0];
  assert.equal(card.tag, 'button');
  assert.equal(card.attrs['data-id'], 'm_abcdefghij');
  assert.match(JSON.stringify(card), /Make ticket: Fish/);
  const made = c.chatRefs([{kind:'proposal', made:{id:'t_fish', key:'FS-1'}}], 'x')[0];
  assert.equal(made.tag, 'a'); assert.equal(made.attrs.href, '#ticket/t_fish');
  c.snapshot = true;
  assert.equal(c.chatRefs([{kind:'proposal',title:'Fish'}], 'x')[0].attrs.disabled, true);
});
test('Open agent starts empty and shows only the latest conversation after sending', () => {
  const c = context();
  c.state.chat.messages = [{id:'old', text:'Old'}, {id:'new', text:'Fish', convo_start:true}];
  c.chatOpenAgent();
  assert.equal(c.location.hash, '#chat');
  assert.equal(c.chatConversation().length, 0);
  assert.match(JSON.stringify(c.chatHeader(null, false)), /New conversation with your agent/);
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
test('the helper is shown by the workspace name only, no "helper" suffix', () => {
  const c = context();
  c.state.workspace = 'pilatus'; c.state.chat.helper = 'pilatus helper';
  c.state.chat.messages = [{id:'m1', by:'ws_x', text:'Hi', at:'2026-11-09T10:00:00Z'}];
  const thread = JSON.stringify(c.chatThread(null, null));
  assert.match(thread, /Pilatus/);
  assert.doesNotMatch(thread, /[Pp]ilatus helper/);
  assert.match(JSON.stringify(c.chatThinking('Pilatus', true)), /Pilatus is thinking/);
  assert.doesNotMatch(JSON.stringify(c.chatThinking('Pilatus', true)), /helper/);
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

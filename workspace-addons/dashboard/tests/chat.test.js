const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function context() {
  const h = (tag, attrs, ...children) => ({tag, attrs, style:{}, children:children.flat(Infinity).filter(c => c != null)});
  const c = vm.createContext({h, fragment:(...children) => h('fragment', {}, children),
    array:v => Array.isArray(v) ? v : [], clean:v => String(v || ''), snapshot:false,
    state:{workspace:'Fish', chat:{messages:[]}}, ticketOf:() => null, time:() => '',
    MutationObserver:class {observe(){}}, document:{documentElement:{}}, CSS:{supports:() => false},
    iconEl:() => null, window:{}, location:{hash:''}, render(){}});
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

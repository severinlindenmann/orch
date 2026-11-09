const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const WS = 'ws_abcdefghij';
function context() {
  const h = (tag, attrs = {}, ...children) => ({tag, attrs, children:children.flat(Infinity).filter(c => c != null),
    style:{}, classList:{add(){}}, append(...nodes){this.children.push(...nodes);}, prepend(...nodes){this.children.unshift(...nodes);},
    addEventListener(){}, querySelector(){return null;}, get textContent(){return JSON.stringify(this.children);}});
  const events = {};
  const c = vm.createContext({crypto:require('node:crypto').webcrypto, setTimeout:() => 1, clearTimeout(){}, h, fragment:(...children) => h('fragment', {}, ...children),
    array:v => Array.isArray(v) ? v : [], clean:v => String(v || ''), state:{}, snapshot:false,
    CSS:{supports:() => false}, time:() => '', date:() => '', ticketOf:() => null,
    location:{hash:'#chat/' + WS}, history:{replaceState(){}}, route:() => ({kind:'chat'}), render(){},
    MutationObserver:class {observe(){}}, document:{documentElement:{}, querySelector:() => null},
    window:{addEventListener:(name, fn) => events[name] = fn, orch:{open(){}, close:async () => {}, toast(){}}},
    fetch:async url => ({ok:true, json:async () => url.endsWith('contacts') ? [{ws:WS,name:'Home',can:{chat:true,files:true}}] : {ws:WS,messages:[]}}),
    dialog:() => ({d:h('dialog'), actions:h('div')})});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/chat.js'), 'utf8'), c);
  vm.runInContext(`chatDm.contacts = [{ws:'${WS}',name:'Home',can:{chat:true,files:true}}]; chatUi.open = '${WS}';`, c);
  return c;
}
test('DM renders safe text, delivery states, read-only permissions and workspace rows', () => {
  const c = context();
  vm.runInContext(`chatDm.threads.set('${WS}', {messages:[{id:'1',by:'you',text:'<script>hello</script>',state:'sending'},
    {id:'2',by:'you',text:'ok',state:'delivered'}, {id:'3',by:'you',text:'failed',state:'failed'}, {id:'4',by:'${WS}',text:'reply'}]});`, c);
  let view = JSON.stringify(c.chatDmThread());
  assert.match(view, /Sending…/); assert.match(view, /Delivered to Home/); assert.match(view, /Not sent · /);
  assert.match(view, /<script>hello<\/script>/); assert.match(view, /Try again/);
  assert.match(JSON.stringify(c.chatList()), /Workspaces/);
  vm.runInContext('chatDm.contacts[0].can.chat = false', c);
  assert.doesNotMatch(JSON.stringify(c.chatDmThread()), /textarea/);
});
test('send is optimistic and preserves drafts across thread switches', async () => {
  const c = context(); let finish;
  c.window.orchAct = op => op === 'chat.sync_ws' ? Promise.resolve({ok:true}) : new Promise(resolve => {finish = resolve;});
  vm.runInContext(`chatUi.drafts['${WS}'] = 'hello';`, c);
  const sending = c.chatSend();
  assert.match(JSON.stringify(c.chatDmThread()), /hello/);
  assert.match(JSON.stringify(c.chatDmThread()), /Sending…/);
  vm.runInContext(`chatUi.open = 'ws_0123456789'; chatUi.drafts[chatUi.open] = 'another draft';`, c);
  finish({ok:true,state:{chat_dm_result:{id:'m_accepted',by:'you',text:'hello',state:'delivered'}}});
  await sending;
  assert.equal(vm.runInContext('chatUi.drafts[chatUi.open]', c), 'another draft');
  assert.equal(vm.runInContext(`chatDmMessages('${WS}')[0].state`, c), 'delivered');
});
test('failed send offers retry, deep links select the workspace', async () => {
  const c = context();
  c.window.orchAct = async () => ({ok:false});
  await c.chatDmSend('hello');
  assert.equal(vm.runInContext(`chatDmMessages('${WS}')[0].state`, c), 'failed');
  vm.runInContext("chatUi.open = 'chat'", c);
  c.chatDmRoute();
  assert.equal(vm.runInContext('chatUi.open', c), WS);
});

test('DM refresh syncs before GET, fetches only the open thread, and throttles state events', async () => {
  const c = context(), calls = [], timers = [];
  let now = 10000;
  c.Date = {now:() => now};
  c.setTimeout = (fn, delay) => {timers.push({fn, delay}); return timers.length;};
  c.clearTimeout = () => {};
  c.window.orchAct = async (op, args) => {calls.push([op, args.workspace]); return {ok:true};};
  c.fetch = async url => {
    calls.push(url);
    return {ok:true, json:async () => url.endsWith('contacts') ?
      [{ws:WS,name:'Home'}, {ws:'ws_0123456789',name:'Other'}] : {ws:WS,messages:[]}};
  };
  await c.chatDmLoad();
  assert.deepEqual(calls, [['chat.sync_ws', undefined], '/api/chat/contacts', '/api/chat/thread/' + WS]);
  for (let i = 0; i < 20; i++) c.chatDmRoute();
  assert.equal(calls.length, 3);
  assert.equal(timers.length, 1);
  assert.equal(timers[0].delay, 5000);
  now += 5000;
  timers[0].fn();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length, 6);
});

test('retry sends the persisted failed id to the server', async () => {
  const c = context();
  let sent;
  vm.runInContext(`chatDm.threads.set('${WS}', {messages:[{id:'m_abcdefghijklmnop',by:'you',text:'again',state:'failed'}]}); chatDm.lastFetch = Date.now();`, c);
  c.window.orchAct = async (op, args) => {
    if (op === 'chat.sync_ws') return {ok:true};
    sent = {op, ...args};
    return {ok:true,state:{chat_dm_result:{id:'m_0123456789abcdef',by:'you',text:'again',state:'sending'}}};
  };
  await c.chatDmSend('again', 'm_abcdefghijklmnop');
  assert.equal(sent.op, 'chat.send_ws');
  assert.equal(sent.retry, 'm_abcdefghijklmnop');
  assert.equal(vm.runInContext(`chatDmMessages('${WS}').some(m => m.id === 'm_abcdefghijklmnop')`, c), false);
});

for (const stored of [false, true]) test(`lost response reconciles, stored=${stored}`, async () => {
  const c = context(); let sent;
  c.window.orchAct = async (op, args) => {
    if (op === 'chat.sync_ws') return {ok:true};
    sent = args;
    assert.equal(vm.runInContext(`chatDmMessages('${WS}')[0].id`, c), args.client_id);
    throw new Error('lost response');
  };
  c.fetch = async url => ({ok:true,json:async () => url.endsWith('contacts') ?
    [{ws:WS,name:'Home',can:{chat:true}}] : {messages:stored ? [{id:sent.client_id,text:'keep me',state:'delivered'}] : []}});
  await c.chatDmSend('keep me');
  assert.match(sent.client_id, /^m_[a-z0-9]{16}$/);
  if (stored) assert.equal(vm.runInContext(`chatDm.pending.get('${WS}').length`, c), 0);
  assert.equal(vm.runInContext(`chatDmMessages('${WS}').length`, c), 1);
  assert.equal(vm.runInContext(`chatDmMessages('${WS}')[0].state`, c), stored ? 'delivered' : 'failed');
  assert.equal(vm.runInContext(`chatDmMessages('${WS}')[0].text`, c), 'keep me');
  if (!stored) {
    const id = sent.client_id;
    await c.chatDmSend('keep me', id);
    assert.equal(sent.client_id, id);
    assert.equal(sent.retry, undefined);
  }
});
test('refused action retains text after clearing draft', async () => {
  const c = context();
  c.window.orchAct = async () => ({ok:false});
  vm.runInContext(`chatUi.drafts['${WS}'] = 'keep me'`, c);
  await c.chatSend();
  assert.equal(vm.runInContext(`chatUi.drafts['${WS}']`, c), '');
  assert.equal(vm.runInContext(`chatDmMessages('${WS}')[0].text`, c), 'keep me');
  assert.equal(vm.runInContext(`chatDmMessages('${WS}')[0].state`, c), 'failed');
});
test('contacts with stored count appear before opening a thread', () => {
  const c = context();
  vm.runInContext("chatUi.open = 'chat'; chatDm.contacts[0].count = 3", c);
  assert.match(JSON.stringify(c.chatList()), /Workspaces/);
});

test('Chat list route imports unopened conversations and sorts newest first', async () => {
  const c = context(), calls = [];
  c.location.hash = '#chat';
  vm.runInContext("chatUi.open = 'chat'", c);
  c.window.orchAct = async (op, args) => { calls.push(op); assert.equal(args.workspace, undefined); return {ok:true}; };
  c.fetch = async url => { calls.push(url); return {ok:true,json:async () => [
    {ws:WS,name:'Older',count:1,last_at:'2026-11-08T10:00:00Z'},
    {ws:'ws_0123456789',name:'Newer',count:2,last_at:'2026-11-09T10:00:00Z'}]}; };
  c.chatDmRoute();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['chat.sync_ws', '/api/chat/contacts']);
  const rows = c.chatList().children.filter(n => n.attrs?.['data-chat-action'] === 'select-dm');
  assert.deepEqual(Array.from(rows, n => n.attrs['data-id']), ['ws_0123456789', WS]);
});

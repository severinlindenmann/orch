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
  const c = vm.createContext({setTimeout:() => 1, clearTimeout(){}, h, fragment:(...children) => h('fragment', {}, ...children),
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
  c.window.orchAct = () => new Promise(resolve => {finish = resolve;});
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
  assert.deepEqual(calls, ['/api/chat/contacts', ['chat.sync_ws', WS], '/api/chat/thread/' + WS]);
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
    sent = {op, ...args};
    return {ok:true,state:{chat_dm_result:{id:'m_0123456789abcdef',by:'you',text:'again',state:'sending'}}};
  };
  await c.chatDmSend('again', 'm_abcdefghijklmnop');
  assert.equal(sent.op, 'chat.send_ws');
  assert.equal(sent.retry, 'm_abcdefghijklmnop');
  assert.equal(vm.runInContext(`chatDmMessages('${WS}').some(m => m.id === 'm_abcdefghijklmnop')`, c), false);
});

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
  const c = vm.createContext({h, fragment:(...children) => h('fragment', {}, ...children),
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

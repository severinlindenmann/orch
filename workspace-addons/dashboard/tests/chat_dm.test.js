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
  assert.match(view, /Sending…/); assert.match(view, /Delivered/); assert.doesNotMatch(view, /helper answers/); assert.match(view, /Not sent · /);
  assert.match(view, /<script>hello<\/script>/); assert.match(view, /Try again/);
  assert.match(JSON.stringify(c.chatList()), /Other workspaces/);
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

test('DM refresh reads contacts and only the open thread (the server imports first), and throttles state events', async () => {
  const c = context(), calls = [], timers = [];
  let now = 10000;
  c.Date = {now:() => now};
  c.setTimeout = (fn, delay) => {timers.push({fn, delay}); return timers.length;};
  c.clearTimeout = () => {};
  c.window.orchAct = async op => {calls.push(op); return {ok:true};};
  c.fetch = async url => {
    calls.push(url);
    return {ok:true, json:async () => url.endsWith('contacts') ?
      [{ws:WS,name:'Home'}, {ws:'ws_0123456789',name:'Other'}] : {ws:WS,messages:[]}};
  };
  await c.chatDmLoad();
  assert.deepEqual(calls, ['/api/chat/contacts', '/api/chat/thread/' + WS]);
  for (let i = 0; i < 20; i++) c.chatDmRoute();
  assert.equal(calls.length, 2);
  assert.equal(timers.length, 1);
  assert.equal(timers[0].delay, 2000);
  now += 2000;
  timers[0].fn();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length, 4);
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
  assert.match(JSON.stringify(c.chatList()), /Other workspaces/);
});

test('Chat list route imports unopened conversations and sorts newest first', async () => {
  const c = context(), calls = [];
  c.location.hash = '#chat';
  vm.runInContext("chatUi.open = 'chat'", c);
  c.window.orchAct = async op => { calls.push(op); return {ok:true}; };
  c.fetch = async url => { calls.push(url); return {ok:true,json:async () => [
    {ws:WS,name:'Older',count:1,last_at:'2026-11-08T10:00:00Z'},
    {ws:'ws_0123456789',name:'Newer',count:2,last_at:'2026-11-09T10:00:00Z'}]}; };
  c.chatDmRoute();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['/api/chat/contacts']);
  const rows = c.chatList().children.filter(n => n.attrs?.['data-chat-action'] === 'select-dm');
  assert.deepEqual(Array.from(rows, n => n.attrs['data-id']), ['ws_0123456789', WS]);
});
test('a received text shows the sender time (shown_at) when there is one, else the arrival time', () => {
  const c = context();
  c.time = value => '[' + value + ']';
  vm.runInContext(`chatDm.threads.set('${WS}', {messages:[{id:'1',by:'${WS}',text:'a',at:'2026-11-09T12:00:00Z',shown_at:'2026-11-09T11:59:00Z'},
    {id:'2',by:'${WS}',text:'b',at:'2026-11-09T12:01:00Z'}, {id:'3',by:'you',text:'c',at:'2026-11-09T12:02:00Z',state:'delivered'}]});`, c);
  const view = JSON.stringify(c.chatDmThread());
  assert.match(view, /\[2026-11-09T11:59:00Z\]/);
  assert.match(view, /\[2026-11-09T12:01:00Z\]/);
  assert.doesNotMatch(view, /\[2026-11-09T12:02:00Z\]/); // my own messages show their delivery state, not a time
});

test('workspace chat header: the name once, then one description line with tags; delivery line says who answers', () => {
  const c = context();
  vm.runInContext(`chatDm.contacts[0] = {ws:'${WS}',name:'Shop',can:{chat:true},description:'Online orders and opening hours.',tags:['orders','website']};
    chatDm.threads.set('${WS}', {messages:[{id:'2',by:'you',text:'hi',state:'delivered'}]});`, c);
  const view = JSON.stringify(c.chatDmThread());
  const texts = n => typeof n === 'string' ? [n] : (n && n.children ? n.children.flatMap(texts) : []);
  const head = texts(c.chatDmThread().children[0]).join('|');
  assert.equal((head.match(/Shop/g) || []).length, 1, 'the name appears once in the header');
  assert.doesNotMatch(view, /Workspace · Shop/);
  assert.doesNotMatch(view, /You \(.*\) · Shop/);
  assert.match(view, /Online orders and opening hours\./);
  assert.match(view, /orders/); assert.match(view, /website/);
  assert.match(view, /Delivered/); assert.doesNotMatch(view, /helper answers/);
});
test('workspace chat header without a description shows no empty line', () => {
  const c = context();
  vm.runInContext(`chatDm.contacts[0] = {ws:'${WS}',name:'Shop',can:{chat:true}}; chatDm.threads.set('${WS}', {messages:[]});`, c);
  assert.doesNotMatch(JSON.stringify(c.chatDmThread()), /chat-desc/);
});

// Issue 865: Home opened Pilatus' thread while a contacts load was running; the peer's texts (by = a workspace id) must show.
test('receiver: a thread opened while a load runs still renders the peer messages at once', async () => {
  const PEER = 'ws_w9pcj20gdf', c = context(), calls = [];
  vm.runInContext("chatDm.contacts = []; chatUi.open = 'chat';", c);
  let release;
  c.fetch = async url => {
    calls.push(url);
    if (url.endsWith('contacts')) { await new Promise(resolve => { release = resolve; }); return {ok:true, json:async () => [{ws:PEER,name:'Pilatus',can:{chat:true},count:2}]}; }
    return {ok:true, json:async () => ({ws:PEER, messages:[
      {id:'m_peer000000000001', by:PEER, text:'Hi Home, can you bring 2 extra chairs?', state:'delivered', at:'2026-11-15T18:21:24Z'},
      {id:'m_peer000000000002', by:PEER, text:'Second text', state:'delivered', at:'2026-11-15T18:22:24Z'}]})};
  };
  const first = c.chatDmLoad();                       // the Chat page load: nothing open yet
  vm.runInContext(`chatUi.open = '${PEER}'`, c);      // the person clicks the row while it runs
  c.chatDmLoad();                                     // returns at once (a load is running)
  release();
  await first;
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['/api/chat/contacts', '/api/chat/thread/' + PEER]);
  const view = JSON.stringify(c.chatDmThread());
  assert.match(view, /bring 2 extra chairs/); assert.match(view, /Second text/);
  assert.doesNotMatch(view, /chat-out/);              // both are the peer's, shown as received
});

test('an accepted send shows Delivered at once and refreshes in the background', async () => {
  const c = context(); let reloaded = 0, finishReload;
  c.fetch = async url => { if (url.endsWith('contacts')) { reloaded++; await new Promise(resolve => { finishReload = resolve; }); }
    return {ok:true, json:async () => url.endsWith('contacts') ? [{ws:WS,name:'Home',can:{chat:true}}] : {ws:WS,messages:[]}}; };
  c.window.orchAct = async () => ({ok:true, state:{chat_dm_result:{id:'m_accepted0000000a', by:'you', text:'hello', state:'delivered'}}});
  await c.chatDmSend('hello');                        // resolves although the background refresh has not finished
  assert.equal(reloaded, 1);
  assert.equal(vm.runInContext(`chatUi.sending.has('${WS}')`, c), false);
  assert.match(JSON.stringify(c.chatDmThread()), /Delivered/);
  finishReload();
});

// Issue 865 (b): Other workspaces keep their place above the groups, also while the contacts load; newest group first.
test('chat list: Other workspaces above Groups (placeholder while loading), newest group first', () => {
  const c = context();
  vm.runInContext(`chatUi.open = 'chat'; chatDm.contacts = []; chatDm.loaded = false;
    state.groups = {hosted:[{id:'g_old', title:'Old group', members:[{ws:'ws_a', name:'A', joined_at:'2026-11-10T09:00:00Z'}], tasks:[]},
      {id:'g_new', title:'New group', members:[{ws:'ws_a', name:'A', joined_at:'2026-11-14T09:00:00Z'}], tasks:[]}], joined:[]};`, c);
  const text = () => JSON.stringify(c.chatList());
  let view = text();
  assert.match(view, /Loading…/);
  assert.ok(view.indexOf('Other workspaces') < view.indexOf('"Groups"'), 'placeholder sits above Groups');
  assert.ok(view.indexOf('New group') < view.indexOf('Old group'), 'newest group first');
  vm.runInContext("chatDm.loaded = true; chatDm.contacts = [{ws:'" + WS + "',name:'Pilatus',count:2}]", c);
  view = text();
  assert.doesNotMatch(view, /Loading…/);
  assert.ok(view.indexOf('Pilatus') < view.indexOf('"Groups"'), 'the workspace chat is above the groups');
  vm.runInContext("chatDm.loaded = false; chatDm.contacts = []; chatDm.error = true", c);
  assert.match(text(), /Could not load · Try again/);
});

test('a raw workspace id as who answered reads as the contact name, never the id', () => {
  const c = context();
  assert.equal(c.chatDmName('agent:' + WS), 'Home');
  assert.equal(c.chatDmName('agent:ws_zzzzzzzzzz'), 'Another workspace');
  assert.equal(c.chatDmName('agent:codex'), '');
});

test('the helper rows show an initial in a circle, no stray glyph', () => {
  const c = context();
  const row = JSON.stringify(c.chatListRow(null));
  assert.doesNotMatch(row, /✧|chat-helper-mark/);
  assert.match(row, /avatar chat-avatar/);
});

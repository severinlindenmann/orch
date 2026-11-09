const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const WS = 'ws_abcdefghij';
function context(fetch) {
  const h = (tag, attrs = {}, ...children) => ({tag, attrs, children:children.flat(Infinity).filter(c => c != null),
    style:{}, classList:{add(){}}, append(...nodes){this.children.push(...nodes);}, prepend(...nodes){this.children.unshift(...nodes);},
    replaceChildren(...nodes){this.children = nodes.flat(Infinity).filter(c => c != null);},
    addEventListener(){}, querySelector(){return null;}, get textContent(){return JSON.stringify(this.children);}});
  let dialogNode = null, now = 1000;
  const c = vm.createContext({setTimeout:() => 1, clearTimeout(){}, Date:{now:() => now}, h, fragment:(...children) => h('fragment', {}, ...children),
    array:v => Array.isArray(v) ? v : [], clean:v => String(v || ''), state:{}, snapshot:false,
    CSS:{supports:() => false}, time:() => '', date:() => '', ticketOf:() => null,
    location:{hash:'#chat'}, history:{replaceState(){}}, route:() => ({kind:'chat'}), render(){},
    MutationObserver:class {observe(){}}, document:{documentElement:{}, querySelector:() => null},
    window:{orchAct:async () => ({ok:true}), addEventListener(){}, orch:{open(){}, close:async () => {}, toast(){}}}, fetch,
    dialog:() => (dialogNode = {d:h('dialog'), actions:h('div')})});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/chat.js'), 'utf8'), c);
  c.shown = () => JSON.stringify(dialogNode.d);
  return c;
}
test('the Contacts picker says Loading… first, then fills in when the contacts arrive', async () => {
  let release;
  const gate = new Promise(r => { release = r; });
  const c = context(async () => { await gate; return {ok:true, json:async () => [{ws:WS, name:'Home', can:{chat:true, files:true}}]}; });
  const loading = vm.runInContext("chatDmContacts(), chatDmLoad(true)", c);
  assert.match(c.shown(), /Loading…/);
  assert.doesNotMatch(c.shown(), /No contacts/);
  release();
  await loading;
  assert.doesNotMatch(c.shown(), /Loading…|No contacts/);
  assert.match(c.shown(), /Home/);
});
test('No contacts only after a real empty answer; a failure shows an error line, not "No contacts"', async () => {
  const empty = context(async () => ({ok:true, json:async () => []}));
  await vm.runInContext("chatDmContacts(), chatDmLoad(true)", empty);
  assert.match(empty.shown(), /No contacts\./);
  const failing = context(async () => ({ok:false, json:async () => ({})}));
  await vm.runInContext("chatDmContacts(), chatDmLoad(true)", failing);
  assert.match(failing.shown(), /Could not load contacts\./);
  assert.match(failing.shown(), /Try again/);
  assert.doesNotMatch(failing.shown(), /No contacts/);
});
test('opening the picker inside the 5 s throttle still loads (force) and does not stay empty', async () => {
  let calls = 0;
  const c = context(async () => { calls++; return {ok:true, json:async () => [{ws:WS, name:'Home', can:{chat:true}}]}; });
  await vm.runInContext("chatDmLoad(true)", c);
  vm.runInContext("chatDm.loaded = false", c); // as if the first answer had not arrived
  await vm.runInContext("chatDmContacts(), chatDmLoad(true)", c);
  assert.equal(calls, 2);
  assert.match(c.shown(), /Home/);
});

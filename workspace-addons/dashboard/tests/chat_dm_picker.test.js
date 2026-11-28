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
  const c = vm.createContext({iconEl:() => null, setTimeout:() => 1, clearTimeout(){}, Date:{now:() => now}, h, fragment:(...children) => h('fragment', {}, ...children),
    array:v => Array.isArray(v) ? v : [], clean:v => String(v || ''), state:{}, snapshot:false,
    CSS:{supports:() => false}, time:() => '', date:() => '', ticketOf:() => null,
    location:{hash:'#chat'}, history:{replaceState(){}}, route:() => ({kind:'chat'}), render(){},
    MutationObserver:class {observe(){}}, document:{documentElement:{}, querySelector:() => null},
    window:{orchAct:async () => ({ok:true}), addEventListener(){}, orch:{open(){}, close:async () => {}, toast(){}}}, fetch,
    stateNote:(title, text, kind, action) => h('state', {kind}, title, text, action ? action.label : null),
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
test('no workspace section without a connected workspace; a failure shows an error line', async () => {
  // O-17 (owner, 28 Nov): who with = your helper, a ticket, or a workspace only when the relay has connected one
  const empty = context(async () => ({ok:true, json:async () => []}));
  await vm.runInContext("chatDmContacts(), chatDmLoad(true)", empty);
  assert.match(empty.shown(), /Your helper/);
  assert.doesNotMatch(empty.shown(), /A workspace|No contacts|Loading…/);
  const failing = context(async () => ({ok:false, json:async () => ({})}));
  await vm.runInContext("chatDmContacts(), chatDmLoad(true)", failing);
  assert.match(failing.shown(), /Could not load the workspaces\./);
  assert.match(failing.shown(), /Try again/);
  assert.doesNotMatch(failing.shown(), /No contacts/);
});
test('New chat asks who with: your helper, a ticket, a workspace; search narrows; nothing is made by picking', async () => {
  const c = context(async () => ({ok:true, json:async () => [{ws:WS, name:'Sales', can:{chat:true}}]}));
  const acts = [];
  vm.runInContext(`window.orchAct = async (op, args) => { globalThis.__acts.push(op); return {ok:true}; }`, Object.assign(c, {__acts:acts}));
  c.Date.parse = text => Date.parse(text);   // this file's small clock has only now()
  c.tickets = () => [
    {id:'t_aaaaaa', key:'ORCH-1', title:'Autumn newsletter', status:'active', updated_at:'2026-11-28T10:00:00Z'},
    {id:'t_bbbbbb', key:'ORCH-2', title:'Price list', status:'todo', updated_at:'2026-11-28T11:00:00Z'},
    {id:'t_cccccc', key:'ORCH-3', title:'Old thing', status:'done', updated_at:'2026-11-28T12:00:00Z'},
    ...Array.from({length:8}, (_, i) => ({id:'t_more0' + i, key:'ORCH-1' + i, title:'Filler ' + i, status:'todo', updated_at:'2026-11-20T10:00:00Z'}))];
  await vm.runInContext("chatDmContacts(), chatDmLoad(true)", c);
  const shown = c.shown();
  assert.match(shown, /Who do you want to talk to\?/);
  assert.ok(shown.indexOf('Your helper') < shown.indexOf('A ticket') && shown.indexOf('A ticket') < shown.indexOf('A workspace'));
  assert.match(shown, /Price list/); assert.match(shown, /Autumn newsletter/); assert.match(shown, /Sales/);
  assert.doesNotMatch(shown, /Old thing/);                       // a finished ticket is not offered
  assert.doesNotMatch(shown, /Your phone/);                      // only when something came from the phone today
  assert.match(shown, /4 more tickets\. Search to find one\./);  // six newest shown, the rest by search
  assert.ok(shown.indexOf('Price list') < shown.indexOf('Autumn newsletter'));  // newest first
  assert.deepEqual(acts, []);                                    // opening and listing writes nothing
  assert.equal(vm.runInContext("JSON.stringify(chatPickTickets('filler 7').rows.map(t => t.key))", c), '["ORCH-17"]');
  assert.equal(vm.runInContext("chatPickTickets('zzz').rows.length", c), 0);
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

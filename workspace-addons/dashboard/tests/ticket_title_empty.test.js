// ORCH-185 (C6): clearing a ticket title and pressing Enter keeps the old title and says why (it was silent).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const block = src.slice(src.indexOf('function startInline'), src.indexOf('// A small calendar'));
function run(typed) {
  const saved = [], toasts = [], listeners = {};
  const input = {value:'', setAttribute() {}, focus() {}, addEventListener:(k, fn) => { listeners[k] = fn; }};
  const host = {dataset:{key:'title-host'}, replaceChildren() {}};
  const control = {dataset:{ticket:'t_one', field:'title'}, parentElement:host};
  const c = vm.createContext({MULTILINE:['note'], locks:new Set(), render() {}, capitalise:x => x, name:x => x,
    ticketOf:() => ({id:'t_one', title:'Old title'}), el:tag => tag === 'span' ? {} : input,
    saveField:async (t, f, v) => { saved.push([f, v]); }, window:{orch:{toast:(...x) => toasts.push(x)}}});
  vm.runInContext(block, c);
  c.startInline(control); input.value = typed;
  return {pressEnter:async () => { listeners.keydown({key:'Enter', preventDefault() {}}); await new Promise(r => setTimeout(r, 5)); }, saved, toasts};
}
test('an empty title is refused with a message and nothing is saved', async () => {
  const r = run('   '); await r.pressEnter();
  assert.deepEqual(r.saved, []);
  assert.match(r.toasts[0][0], /needs a title/);
});
test('a new title is saved without a message', async () => {
  const r = run('New title'); await r.pressEnter();
  assert.deepEqual(r.saved, [['title', 'New title']]);
  assert.deepEqual(r.toasts, []);
});

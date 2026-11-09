const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const start = src.indexOf('const PROOF_MARK'), end = src.indexOf('function ticketDoneLine');
function line(t, snapshot = false) {
  const h = (tag, attrs, ...children) => ({tag, attrs, children:children.flat(Infinity).filter(c => c != null)});
  const c = vm.createContext({h, array:v => Array.isArray(v) ? v : [], clean:v => v, snapshot});
  vm.runInContext(src.slice(start, end), c);
  return c.ticketProofLine(t);
}
const text = n => typeof n === 'string' ? n : (n.children || []).map(text).join('');
test('shows the core line, hint and details; nothing without proof data', () => {
  assert.equal(line({id:'t_1', checklist:[]}), null);
  const t = {id:'t_1', checklist:[{id:'c1', text:'Tests pass'}], proof:{line:'1 part of "Done when" has no task', uncovered:["Done when isn't linked to tasks"], per_item:{c1:'passed'}}};
  const out = text(line(t));
  assert.match(out, /1 part of "Done when" has no task/);
  assert.match(out, /isn't linked to tasks/);
  assert.match(out, /Details/);
  assert.match(out, /Check passed/);
  assert.doesNotMatch(text(line(t, true)), /Details/);
});
test('a failed check is a bad mark, no checks is neutral', () => {
  const json = JSON.stringify(line({id:'t_1', checklist:[], proof:{line:'1 check failed', uncovered:[], per_item:{}}}));
  assert.match(json, /proof-bad/);
  assert.match(JSON.stringify(line({id:'t_1', checklist:[], proof:{line:'No checks recorded', uncovered:[], per_item:{}}})), /proof-none/);
});

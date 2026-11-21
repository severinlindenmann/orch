// ORCH-903: an edit that meets a newer change keeps what the person typed and offers "Use mine".
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const block = src.slice(src.indexOf('async function saveField'), src.indexOf('function startInline'));
function run(first, current) {
  const toasts = [], calls = [];
  const c = vm.createContext({FIELD_LABEL:{owner:'the owner'}, name:x => x, clean:x => x, changeError:r => r.text,
    ticketOf:() => current, window:{orch:{toast:(...x) => toasts.push(x)}},
    actRetry:async (op, args) => { calls.push(args()); return calls.length === 1 ? first : {ok:true}; }});
  vm.runInContext(block, c);
  return {c, toasts, calls};
}
test('a conflict with a changed field keeps the typed value and offers Use mine', async () => {
  const r = run({ok:false, status:409, text:'x'}, {id:'t1', owner:'Claude', revision:7});
  await r.c.saveField({id:'t1', owner:'Sev', revision:5}, 'owner', 'Anna');
  assert.equal(r.toasts.length, 1);
  assert.match(r.toasts[0][0], /Claude/); assert.match(r.toasts[0][0], /Anna/);
  assert.equal(r.toasts[0][2].label, 'Use mine');
  await r.toasts[0][2]();
  assert.deepEqual(JSON.parse(JSON.stringify(r.calls[1])), {ticket:'t1', owner:'Anna', if_revision:7});
});
test('another error is shown as before', async () => {
  const r = run({ok:false, status:500, text:'boom'}, {id:'t1', owner:'Sev', revision:5});
  await r.c.saveField({id:'t1', owner:'Sev', revision:5}, 'owner', 'Anna');
  assert.deepEqual(r.toasts, [['boom', 'error']]);
});

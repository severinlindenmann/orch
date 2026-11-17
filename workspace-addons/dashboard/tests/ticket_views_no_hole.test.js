const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/tickets.js'), 'utf8');

// walk 14 Nov: "undefined is not iterable" on every Tickets view - a hole (",,") in the views list broke find(([id]) => ...)
test('TICKET_VIEWS has no holes, so find with a destructured entry never throws', () => {
  const line = src.split('\n').find(l => l.startsWith('const TICKET_VIEWS'));
  assert.ok(line);
  const ctx = vm.createContext({});
  vm.runInContext(line + '\nthis.V = TICKET_VIEWS;', ctx);
  assert.equal(ctx.V.length, 5);
  assert.ok(Array.from({length: ctx.V.length}, (_, i) => i in ctx.V).every(Boolean), 'no hole');
  assert.doesNotThrow(() => ctx.V.find(([id]) => id === 'nope'));
});

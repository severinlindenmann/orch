const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/date.js'), 'utf8');
const ctx = {window:{}};
vm.createContext(ctx); vm.runInContext(source, ctx);
const UI = ctx.window.UI;
const now = new Date(2026, 10, 14, 12, 0); // Sat 14 Nov 2026
test('one date and time format, 24 h', () => {
  assert.equal(UI.stamp(new Date(2026, 10, 14, 10, 32), {now}), 'today 10:32');
  assert.equal(UI.stamp(new Date(2026, 10, 13, 9, 5), {now}), 'yesterday 09:05');
  assert.equal(UI.stamp(new Date(2026, 10, 16, 8, 0), {now}), 'Mon 08:00');
  assert.equal(UI.stamp(new Date(2026, 10, 14, 15, 30), {now}), 'today 15:30', '24 h, never 3:30 pm');
  assert.equal(UI.stamp(new Date(2026, 9, 2, 8, 15), {now}), '2 Oct 2026, 08:15');
  assert.equal(UI.stamp('2026-11-25', {now}), '25 Nov 2026', 'date only drops the time');
  assert.equal(UI.stamp('2026-11-14', {now}), 'today');
  assert.equal(UI.stamp(new Date(2026, 10, 18, 8, 0), {now, time:false}), 'Wed');
  assert.equal(UI.stamp('nonsense', {now}), '');
  assert.equal(UI.clock(new Date(2026, 10, 14, 7, 4)), '07:04');
});

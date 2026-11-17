// ORCH-185 (C3): a day-only due date names the day ("Fri 20 Nov"), not a bare "Fri".
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/app.js'), 'utf8');
const parseSrc = src.slice(src.indexOf('const parse = value'), src.indexOf('const date = value'));
const dueSrc = src.slice(src.indexOf('const dueDay'), src.indexOf('const dueText'));
function ctx() {
  const c = vm.createContext({state:{now:'2026-11-17T09:00:00'}, window:{}});
  vm.runInContext(parseSrc + "const now = () => parse(state.now) || new Date(); const today = () => '2026-11-17';" + dueSrc + 'this.dueDay = dueDay;', c);
  return c;
}
test('a day within the week says weekday, day and month', () => {
  const c = ctx();
  assert.equal(c.dueDay('2026-11-20'), 'Fri 20 Nov');
  assert.equal(c.dueDay('2026-11-17'), 'today');
});
test('another year shows the year', () => assert.equal(ctx().dueDay('2027-01-05'), 'Tue 5 Jan 2027'));

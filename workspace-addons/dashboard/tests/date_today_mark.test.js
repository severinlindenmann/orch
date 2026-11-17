// ORCH-185 (C3): the shared date picker marks today (aria-current + data-today), so the person sees where they are.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/date.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/interaction.css'), 'utf8');
function stub() {
  const s = {dataset:{}, attrs:{}, kids:[], setAttribute(k, v) { s.attrs[k] = v; }, append(...n) { s.kids.push(...n); }, replaceChildren() { s.kids = []; },
    addEventListener() {}, focus() {}, showModal() {}, close() {}, dispatchEvent() {}, hidden:false};
  return s;
}
test('only today gets the mark in the month grid', () => {
  const parts = {}, dialog = stub();
  dialog.querySelector = sel => parts[sel] || (parts[sel] = stub());
  const document = {createElement:tag => tag === 'dialog' ? dialog : stub(), body:stub()};
  const c = vm.createContext({window:{}, document, Event:function () {}});
  vm.runInContext(source, c);
  const value = stub(); value.value = ''; const toggle = stub();
  c.window.UI.date(value, toggle, null, {});
  toggle.onclick();
  const days = parts['.ui-days'].kids.filter(b => b.dataset.date);
  const marked = days.filter(b => b.dataset.today === 'true');
  const t = new Date(), key = [t.getFullYear(), String(t.getMonth() + 1).padStart(2, '0'), String(t.getDate()).padStart(2, '0')].join('-');
  assert.equal(marked.length, 1);
  assert.equal(marked[0].dataset.date, key);
  assert.equal(marked[0].attrs['aria-current'], 'date');
  assert.match(css, /\.ui-days \[data-today=true\]/);
});

// "You: <name>" person switch (people.js): hidden without state.people, lists people with a tick on the chosen one, Add person asks for a name only.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load() {
  const mk = tag => ({tag, children:[], attrs:{}, className:'', hidden:false, textContent:'', dataset:{},
    append(...n) { this.children.push(...n.flat()); }, replaceChildren() { this.children = []; }, setAttribute(k, v) { this.attrs[k] = v; },
    querySelector() { return null; }, addEventListener() {}});
  const root = mk('div');
  const doc = {getElementById: id => id === 'side-person' ? root : null, createElement: mk};
  const win = {listeners:{}, addEventListener(n, f) { this.listeners[n] = f; }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/people.js'), 'utf8'), {document:doc, window:win, FormData: class {}, JSON});
  const texts = n => [n.textContent, ...(n.children || []).flatMap(c => typeof c === 'string' ? [c] : texts(c))].filter(Boolean).join(' ');
  return {root, texts, state: people => win.listeners['orch:state']({detail:{people}})};
}
test('nothing shown without people state (snapshot, old server)', () => {
  const c = load();
  c.state(null);
  assert.equal(c.root.hidden, true);
});
test('shows "You: <name>", every person and Add person', () => {
  const c = load();
  c.state({me:'Anna', people:['Anna', 'Ben']});
  assert.equal(c.root.hidden, false);
  const t = c.texts(c.root);
  assert.match(t, /You:\s+Anna/);
  assert.match(t, /Ben/);
  assert.match(t, /Add person/);
});
test('no person chosen yet: says so plainly and still offers Add person', () => {
  const c = load();
  c.state({me:null, people:[]});
  assert.match(c.texts(c.root), /You:\s+Not set/);
  assert.match(c.texts(c.root), /Add person/);
});

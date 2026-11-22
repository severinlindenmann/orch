// "You: <name>" person switch (people.js): hidden without state.people, lists people with a tick on the chosen one, Add person asks for a name only.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load(sessionState) {
  const mk = tag => ({tag, children:[], attrs:{}, className:'', hidden:false, textContent:'', dataset:{},
    append(...n) { this.children.push(...n.flat()); }, replaceChildren() { this.children = []; }, setAttribute(k, v) { this.attrs[k] = v; },
    querySelector() { return null; }, addEventListener() {}});
  const root = mk('div');
  const doc = {getElementById: id => id === 'side-person' ? root : null, createElement: mk, addEventListener() {}};
  const win = {listeners:{}, addEventListener(n, f) { this.listeners[n] = f; }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/people.js'), 'utf8'), {fetch: async () => ({ok: !!sessionState, json: async () => ({state: sessionState})}), document:doc, window:win, FormData: class {}, JSON});
  const texts = n => [n.textContent, ...(n.children || []).flatMap(c => typeof c === 'string' ? [c] : texts(c))].filter(Boolean).join(' ');
  return {root, texts, win, state: people => win.listeners['orch:state']({detail:{people}})};
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
  assert.match(c.texts(c.root), /Pick your name/);
  assert.doesNotMatch(c.texts(c.root), /Not set/);
  assert.match(c.texts(c.root), /Add person/);
});

for (const [st, word] of [['signed-in', /Signed in/], ['view-only', /View only/], ['helper', /A helper opened this page, so you can look but not change things\. To make changes, open the dashboard from orch yourself/]]) {
  test('badge for ' + st, async () => {
    const c = load(st);
    c.state({me:'Anna', people:['Anna']});
    await new Promise(r => setTimeout(r, 10));
    assert.match(c.texts(c.root), word);
  });
}

// The person block, look A (people.js, ORCH-1880): hidden without state.people, lists people with a tick on the chosen one, Add person asks for a name only.
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
const find = (n, f) => typeof n === 'string' ? [] : [...(f(n) ? [n] : []), ...(n.children || []).flatMap(k => find(k, f))];
const summary = c => find(c.root, n => n.tag === 'summary')[0];
test('shows the name (the label says "You: <name>"), every person and Add person', () => {
  const c = load();
  c.state({me:'Anna', people:['Anna', 'Ben']});
  assert.equal(c.root.hidden, false);
  const t = c.texts(c.root);
  assert.match(t, /Anna/);
  assert.doesNotMatch(t, /You:/);
  assert.equal(summary(c).attrs['aria-label'], 'You: Anna. Switch person');
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

for (const [st, word] of [['signed-in', /Signed in/], ['view-only', /View only/], ['helper', /A helper opened this page, so you can only look\. To make changes, open orch yourself/]]) {
  test('badge for ' + st, async () => {
    const c = load(st);
    c.state({me:'Anna', people:['Anna']});
    await new Promise(r => setTimeout(r, 10));
    assert.match(c.texts(c.root), word);
  });
}
for (const [st, cls, said] of [['signed-in', 'dot ok', 'You: Anna, signed in. Switch person'], ['view-only', 'dot', 'You: Anna, view only. Switch person']]) {
  test('one row: ' + st + ' is a dot on the avatar, its words in the label and tooltip (ORCH-1880)', async () => {
    const c = load(st);
    c.state({me:'Anna', people:['Anna']});
    await new Promise(r => setTimeout(r, 10));
    const s = summary(c), avatar = s.children[0];
    assert.equal(avatar.children.find(k => typeof k !== 'string')?.className, cls);
    assert.equal(s.attrs['aria-label'], said);
    assert.match(s.attrs.title, st === 'signed-in' ? /^Anna · Signed in$/ : /^Anna · View only: /);
    assert.equal(find(c.root, n => n.attrs?.['data-testid'] === 'session-state')[0].className, 'sr-only session-state');
  });
}

// Workspace switcher rows (switcher.js), report r-1117-0829-ws: the name block used a class the kit does not style
// (ws-item-details), so a long name never ended with "…" and ran under the "✓ Current" / "1 needs you" labels.
// Every class a row uses must exist in the kit, and a row follows the gallery: one grey line under the name,
// one thing on the right.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const KIT = path.join(__dirname, '../../../workspace/src/orch_ui/static');
const css = ['components.css', 'widgets.css'].map(f => fs.readFileSync(path.join(KIT, f), 'utf8')).join('\n');

function mk(tag) {
  return {tag, children: [], attrs: {}, className: '', style: {}, offsetTop: 0, offsetHeight: 40,
    append(...n) { this.children.push(...n.flat()); }, replaceChildren(...n) { this.children = n.flat(); },
    setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; },
    addEventListener(k, f) { this.attrs['on' + k] = f; }, querySelector() { return null; }, querySelectorAll() { return []; },
    insertAdjacentElement(_, el) { this.next = el; }, remove() {}, focus() {}, contains() { return false; },
    classList: {add() {}}};
}
function load(workspaces, displayName = 'ORCH Development') {
  const box = mk('div');
  const doc = {querySelector: s => s === '.workspace' ? box : null, getElementById: () => null, createElement: mk,
    createElementNS: (_, t) => mk(t), addEventListener() {}};
  const win = {listeners: {}, addEventListener(n, f) { this.listeners[n] = f; },
    OrchLook: {badge: (_, label) => Object.assign(mk('span'), {className: 'wsb', label}), name: () => displayName}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/switcher.js'), 'utf8'), {document: doc, window: win});
  win.listeners['orch:state']({detail: {look: {workspaces}}});
  box.attrs.onclick();
  const rows = box.next.children.filter(c => c && c.attrs && c.attrs['data-testid'] === 'ws-item');
  return rows.map(r => r.children);
}
const text = n => typeof n === 'string' ? n : (n.children || []).map(text).join('');
const classes = n => typeof n === 'string' ? [] : [...n.className.split(/\s+/).filter(Boolean), ...(n.children || []).flatMap(classes)];

const LIST = [
  {name: 'workspace-orch', here: true, needs: 1, url: 'http://127.0.0.1:8788/'},
  {name: 'a-workspace-with-a-very-long-folder-name', needs: 0, url: 'http://127.0.0.1:8790/'},
  {name: 'Rigi', needs: 2},
];

test('every class a switcher row uses is styled by the kit', () => {
  for (const row of load(LIST)) for (const c of row.flatMap(classes)) {
    if (c === 'wsb') continue; // the badge comes from look.js
    assert.match(css, new RegExp('\\.' + c.replace(/-/g, '\\-') + '(?![\\w-])'), `no kit rule for .${c}`);
  }
});

test('the name sits in the shrinking details block, so a long name ends with "…"', () => {
  for (const [, details] of load(LIST)) {
    assert.ok(details.className.split(' ').includes('sw-item-details'));
    assert.ok(details.className.split(' ').includes('grow'));
    assert.equal(details.children[0].className, 'ws-item-name');
  }
  assert.match(css, /\.sw-item-details\{[^}]*min-width:0[^}]*display:grid/);
});

test('one grey line under the name, one thing on the right (as in the gallery)', () => {
  const [cur, other, stopped] = load(LIST);
  assert.equal(text(cur[1]), 'ORCH DevelopmentCurrent'); // same name as the box above it
  assert.equal(cur[2].children.length, 1);
  assert.equal(text(cur[2]), '1 needs you');
  assert.equal(text(other[1]), 'a-workspace-with-a-very-long-folder-name');
  assert.equal(other[2].children.length, 0); // nobody waits: no "0 need you"
  assert.equal(text(stopped[1]), 'RigiNot running');
  assert.equal(text(stopped[2]), '2 need you');
});

test('the current workspace without anyone waiting shows the tick on the right', () => {
  const [cur] = load([{name: 'workspace-orch', here: true, needs: 0}]);
  assert.equal(text(cur[2]), '✓');
  assert.equal(cur[2].children[0].className, 'sw-tick');
});

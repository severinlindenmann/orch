// Workspace switcher rows (switcher.js), report r-1117-0829-ws: the name block used a class the kit does not style
// (ws-item-details), so a long name never ended with "…" and ran under the "✓ Current" / "1 needs you" labels.
// Every class a row uses must exist in the kit, and a row follows the gallery: one grey line under the name,
// the name on the full row width.
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

const LONG = 'customer-support-team-emea-de1'; // 30 characters
const LIST = [
  {name: 'workspace-orch', here: true, needs: 1, url: 'http://127.0.0.1:8788/'},
  {name: LONG, needs: 0, url: 'http://127.0.0.1:8790/'},
  {name: 'Rigi', needs: 2},
];

test('every class a switcher row uses is styled by the kit', () => {
  for (const row of load(LIST)) for (const c of row.flatMap(classes)) {
    if (c === 'wsb') continue; // the badge comes from look.js
    assert.match(css, new RegExp('\\.' + c.replace(/-/g, '\\-') + '(?![\\w-])'), `no kit rule for .${c}`);
  }
});

test('the name gets the whole row width and wraps instead of being cut (manager review 17 Nov)', () => {
  assert.equal(LONG.length, 30);
  for (const row of load(LIST)) {
    const details = row[1];
    assert.ok(details.className.split(' ').includes('sw-item-details'));
    assert.equal(details.children[0].className, 'ws-item-name');
    // nothing else shares the row with the name except the small tick on the current one
    const right = row.slice(2).filter(Boolean);
    assert.ok(right.every(r => text(r) === '✓'), 'only the tick sits right of the name');
  }
  const [, long] = load(LIST);
  assert.equal(text(long[1].children[0]), LONG); // the full name is in the page, not shortened
  const rule = css.match(/\.ws-item-name\{([^}]*)\}/)[1];
  assert.doesNotMatch(rule, /nowrap|ellipsis/);
  assert.match(rule, /overflow-wrap:anywhere/);
  assert.match(rule, /line-clamp:2/);
});

test('state and who waits share the grey line under the name', () => {
  const [cur, other, stopped] = load(LIST);
  assert.equal(text(cur[1]), 'ORCH DevelopmentCurrent · 1 needs you'); // same name as the box above it
  assert.equal(text(other[1]), LONG); // running, nobody waits: no "0 need you"
  assert.equal(text(stopped[1]), 'RigiNot running · 2 need you');
});

test('the current workspace shows the tick on the right, others nothing', () => {
  const [cur, other] = load(LIST);
  assert.equal(text(cur[2]), '✓');
  assert.equal(cur[2].children[0].className, 'sw-tick');
  assert.equal(other.length > 2 && other[2] ? text(other[2]) : '', '');
});

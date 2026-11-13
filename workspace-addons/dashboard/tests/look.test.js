const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const VEC = JSON.parse(fs.readFileSync(path.join(__dirname, '../../../contracts/vectors/look-v1.json'), 'utf8'));

function load() {
  const listeners = [];
  const ctx = {
    TextEncoder, Array, Math, JSON, Object, String, encodeURIComponent, console,
    localStorage: {getItem: () => null, setItem() {}},
    document: {querySelector: () => null, addEventListener() {}, createElement: () => ({}), title: ''},
    window: {addEventListener: (n, f) => listeners.push([n, f]), dispatchEvent() {}},
  };
  ctx.window.window = ctx.window;
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(WEB, 'look-icons.js'), 'utf8'), ctx);
  vm.runInContext(fs.readFileSync(path.join(WEB, 'look.js'), 'utf8'), ctx);
  return ctx.window;
}

test('generated data has the 100 icons and 12 colours', () => {
  const w = load();
  assert.equal(Object.keys(w.OrchLookData.icons).length, 100);
  assert.equal(w.OrchLookData.colors.length, 12);
  assert.ok(w.OrchLookData.icons.wallet.b.includes('<path'));
});

test('the default colour and letter follow vectors/look-v1.json', () => {
  const L = load().OrchLook;
  for (const v of VEC.default) {
    assert.equal(L.defaultColor(v.name), v.color, v.name);
    assert.equal(L.letter(v.name), v.letter, v.name);
  }
});

test('unknown icon or colour falls back to the defaults (render vectors)', () => {
  const L = load().OrchLook;
  for (const v of VEC.render) {
    const r = L.resolve({icon: v.icon, color: v.color}, v.name);
    assert.equal(r.icon, v.shown.icon, v.why);
    assert.equal(r.color, v.shown.color, v.why);
  }
});

test('the favicon is a data SVG with the icon, and the letter is escaped', () => {
  const L = load().OrchLook;
  const icon = decodeURIComponent(L.faviconHref({icon: 'wallet', color: 'amber'}, 'Finance'));
  assert.ok(icon.startsWith('data:image/svg+xml,<svg') && icon.includes('#fbbf24') && !icon.includes('<text'));
  const letter = decodeURIComponent(L.faviconHref({icon: null, color: null}, '<b>x'));
  assert.ok(letter.includes('<text') && !letter.includes('<b>'));
  assert.ok(letter.includes('>?</text>') || letter.includes('>B</text>'));
});

test('the icon picker names places in plain words, not relay or publish', () => {
  const s = fs.readFileSync(path.join(WEB, 'look.js'), 'utf8');
  assert.ok(s.includes("prev(32, 'In the dashboard, on your phone and on shared pages')"));
  assert.ok(s.includes("'Shown in the dashboard, on your phone and on shared pages.'"));
  assert.ok(s.includes("'Saved. Your phone and shared pages show it at their next refresh.'"));
  for (const m of s.match(/'[^'\n]*'/g)) assert.equal(/\b(relay|publish)\b/i.test(m), false, m);
});

test('look.js and switcher.js never use innerHTML or insertAdjacentHTML', () => {
  for (const f of ['look.js', 'switcher.js']) {
    const s = fs.readFileSync(path.join(WEB, f), 'utf8');
    assert.equal(/innerHTML|insertAdjacentHTML|outerHTML|document\.write/.test(s), false, f);
  }
});

function fakeDom(w) {
  const mk = tag => ({tag, attrs: {}, kids: [], className: '', setAttribute(k, v) { this.attrs[k] = v; }, append(...k) { this.kids.push(...k.map(x => typeof x === 'string' ? {text: x} : x)); }});
  w.document.createElement = mk;
  w.document.importNode = () => mk('svg');
  w.DOMParser = class { parseFromString() { return {documentElement: mk('svg')}; } };
}
function all(node, out = []) { if (node && node.kids) { out.push(node); node.kids.forEach(k => all(k, out)); } return out; }
const textOf = node => (node.text != null ? node.text : (node.kids || []).map(textOf).join(''));

test('the icon picker opens behind Change with 12 icons, More icons and one preview; the summary follows the choice', () => {
  let clicks = null, stateListener = null;
  const c = {TextEncoder, Array, Math, JSON, Object, String, encodeURIComponent, console, Set, CustomEvent: class { constructor(n) { this.type = n; } },
    localStorage: {getItem: () => null, setItem() {}},
    document: {querySelector: () => null, addEventListener: (n, f) => { if (n === 'click') clicks = f; }, title: ''},
    window: {addEventListener: (n, f) => { if (n === 'orch:state') stateListener = f; }, dispatchEvent() {}}};
  c.window.window = c.window;
  fakeDom(c);
  vm.createContext(c);
  vm.runInContext(fs.readFileSync(path.join(WEB, 'look-icons.js'), 'utf8'), c);
  vm.runInContext(fs.readFileSync(path.join(WEB, 'look.js'), 'utf8'), c);
  stateListener({detail: {look: {icon: 'wallet', color: 'amber', set_by: 'human'}, workspace: 'Finance'}});
  const L = c.window.OrchLook;
  let tree = all(L.settingsSection());
  assert.equal(tree.some(x => x.className === 'lk-picker'), false, 'closed at first');
  const change = tree.find(x => x.attrs['data-lk'] === 'open');
  assert.equal(textOf(change), 'Change');
  const click = lk => clicks({target: {closest: () => ({dataset: {lk: lk.lk, v: lk.v}, disabled: false})}});
  click({lk: 'open'});
  tree = all(L.settingsSection());
  assert.equal(tree.filter(x => x.className === 'lk-tile').length, 13, 'first letter + 12 icons');
  assert.equal(tree.some(x => x.attrs.role === 'tablist'), false, 'groups stay folded');
  assert.equal(textOf(tree.find(x => x.attrs['data-lk'] === 'more')), 'More icons');
  assert.equal(tree.filter(x => x.className === 'lk-pv-row').length, 1, 'a single preview');
  assert.equal(tree.some(x => x.attrs['data-lk'] === 'open'), false);
  const order = () => all(L.settingsSection()).filter(x => x.className === 'lk-tile').map(x => x.attrs['data-v']);
  const before = order();
  click({lk: 'icon', v: before[6]});
  assert.deepEqual(order(), before, 'picking an icon keeps the tiles in place');
  click({lk: 'icon', v: ''});
  tree = all(L.settingsSection());
  assert.match(textOf(tree.find(x => x.attrs['data-testid'] === 'look-summary')), /^First letter · /);
  click({lk: 'more'});
  tree = all(L.settingsSection());
  assert.ok(tree.some(x => x.attrs.role === 'tablist'));
  assert.equal(textOf(tree.find(x => x.attrs['data-lk'] === 'more')), 'Fewer icons');
});

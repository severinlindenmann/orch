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

test('look.js and switcher.js never use innerHTML or insertAdjacentHTML', () => {
  for (const f of ['look.js', 'switcher.js']) {
    const s = fs.readFileSync(path.join(WEB, f), 'utf8');
    assert.equal(/innerHTML|insertAdjacentHTML|outerHTML|document\.write/.test(s), false, f);
  }
});

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/handoff.js'), 'utf8');

function fn(name, ctx) {
  const i = src.indexOf('  function ' + name + '(');
  assert.ok(i >= 0, name);
  const j = src.indexOf('\n  }\n', i) + 4;
  vm.runInContext(src.slice(i, j) + '\nthis.' + name + ' = ' + name + ';', ctx);
  return ctx[name];
}

test('a request shows its age in plain words', () => {
  const ago = fn('ago', vm.createContext({Date, Number, Math}));
  const now = 1_000_000 * 1000;
  assert.equal(ago(1_000_000 - 10, now), 'just now');
  assert.equal(ago(1_000_000 - 5 * 60, now), '5 min ago');
  assert.equal(ago(1_000_000 - 60 * 60, now), '1 hour ago');
  assert.equal(ago(1_000_000 - 3 * 3600, now), '3 hours ago');
  assert.equal(ago(undefined, now), 'just now');
});

test('the update banners replace each other, one at a time', () => {
  const live = [];
  const doc = {
    querySelectorAll: () => live.filter(b => !b.gone),
    createElement: () => { const e = {children: [], gone: false, style: {}, setAttribute() {}, appendChild(c) { this.children.push(c); }, remove() { this.gone = true; }}; return e; },
    getElementById: () => null,
    body: {insertBefore: (b) => live.push(b), firstChild: null},
  };
  const ctx = vm.createContext({document: doc, Date, Number, Math});
  vm.runInContext(src.slice(src.indexOf('  function el('), src.indexOf('\n', src.indexOf('  function el(')) + 1), ctx);
  const i = src.indexOf('  function place('), j = src.indexOf('  var noticed');
  vm.runInContext(src.slice(i, j), ctx);
  const k = src.indexOf('  var shown = "";'), l = src.indexOf('  // the detached update');
  vm.runInContext(src.slice(k, l) + '\nthis.banner = banner;', ctx);
  const a = ctx.banner('Update started.');
  const b = ctx.banner('Update finished.');
  assert.equal(a.gone, true, 'the earlier update banner is replaced');
  assert.equal(b.gone, false);
  assert.equal(doc.querySelectorAll().length, 1);
});

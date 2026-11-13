import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const css = readFileSync(new URL('../static/motion.css', import.meta.url), 'utf8');
const comps = readFileSync(new URL('../static/components.css', import.meta.url), 'utf8');

test('needs-you is calm: one soft fade-in, no ring, no repeat', () => {
  assert.ok(!css.includes('orch-ring'), 'no pulsing ring');
  const needs = css.match(/\.needs-in\{[^}]*\}/)[0];
  assert.ok(needs.includes('orch-fade') && !needs.includes('infinite') && !/\s\d+\s*(;|\})/.test(needs.replace(/\d+ms/g, '')));
  assert.match(css, /\.needs-pulse\{animation:none/);
});

test('a plain refresh adds no motion and reduced motion switches everything off', () => {
  assert.match(css, /html\[data-refresh\] \*/);
  assert.match(css, /prefers-reduced-motion:reduce\)\{\*,\*:before,\*:after\{animation:none!important/);
});

test('system font only and no thick warning bars in the kit', () => {
  const tokens = readFileSync(new URL('../static/tokens.css', import.meta.url), 'utf8');
  assert.ok(!/Geist/.test(tokens + comps));
  assert.match(tokens, /--fs-body: 14px;/);
  assert.ok(!/border-left:[3-9]px solid var\(--warning\)[^}]*\}/.test(comps.replace(/\.qcard\{[^}]*\}/, '')));
});

import vm from 'node:vm';

function load() {
  const listeners = {};
  const classes = new Set();
  const row = {classList: {add: c => classes.add(c), remove: c => classes.delete(c)}, addEventListener() {}};
  const ctx = {
    performance: {getEntriesByType: () => [{type: 'navigate'}]},
    matchMedia: () => ({matches: false}),
    setTimeout, clearTimeout, document: {
      documentElement: {dataset: {}}, addEventListener() {}, querySelector: () => null, querySelectorAll: () => [],
    },
    window: {addEventListener: (n, f) => { listeners[n] = f; }}, console,
  };
  ctx.window.window = ctx.window;
  vm.runInNewContext(readFileSync(new URL('../static/motion.js', import.meta.url), 'utf8'), ctx);
  return {orch: ctx.window.orch, row, classes, listeners};
}

test('needs-in is never applied on load, only to a row that arrives live', async () => {
  const {orch, row, classes, listeners} = load();
  assert.equal(orch.needsIn(row), false);
  assert.ok(!classes.has('needs-in'), 'not before the page is live');
  listeners.load();
  await new Promise(r => setTimeout(r, 5));
  assert.equal(orch.needsIn(row), true);
  assert.ok(classes.has('needs-in'));
});

test('page-enter stagger skips rows that fade in as needs-you', () => {
  assert.match(readFileSync(new URL('../static/motion.js', import.meta.url), 'utf8'), /\[data-row\]:not\(\.needs-in\)/);
});

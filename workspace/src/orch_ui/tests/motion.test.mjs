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

// ORCH-1329: flip (grow or move from where it was) and leave (fade out where it was) for the new Focus.
function loadMotion(reduce) {
  const ctx = {
    performance: {getEntriesByType: () => [{type: 'navigate'}]},
    matchMedia: () => ({matches: reduce}),
    getComputedStyle: () => ({getPropertyValue: n => ({'--dur-slow': '240ms', '--dur-exit': '120ms', '--ease-move': ' cubic-bezier(0.4, 0, 0, 1)', '--ease-exit': 'cubic-bezier(0.6, 0, 0.8, 0.6)'})[n] || ''}),
    setTimeout, clearTimeout, document: {
      documentElement: {dataset: {}}, body: {append() {}}, addEventListener() {}, querySelector: () => null, querySelectorAll: () => [],
    },
    window: {addEventListener() {}}, console,
  };
  ctx.window.window = ctx.window;
  vm.runInNewContext(readFileSync(new URL('../static/motion.js', import.meta.url), 'utf8'), ctx);
  return ctx.window.orch;
}
function fakeEl(rect) {
  const calls = [];
  return {calls, style: {}, dataset: {}, setAttribute() {}, removeAttribute() {}, querySelectorAll: () => [], getBoundingClientRect: () => rect,
    animate(frames, timing) { calls.push({frames, timing}); return {}; }};
}
const R = (left, top, width, height) => ({left, top, width, height});

test('flip moves from the old place with transform and opacity only, on the slow token', () => {
  const orch = loadMotion(false), el = fakeEl(R(0, 0, 200, 100));
  orch.flip(el, R(50, 20, 100, 50));
  assert.equal(el.calls.length, 1);
  const {frames, timing} = el.calls[0];
  assert.equal(frames[0].transform, 'translate(50px,20px) scale(0.5,0.5)');
  assert.equal(frames[1].transform, 'none');
  for (const f of frames) for (const k of Object.keys(f)) assert.ok(['transform', 'opacity', 'transformOrigin'].includes(k), k);
  assert.equal(timing.duration, 240);
  assert.equal(timing.easing, 'cubic-bezier(0.4, 0, 0, 1)');
  orch.flip(el, R(0, 0, 200, 100));
  assert.equal(el.calls.length, 1, 'nothing moved: no animation');
  const slide = fakeEl(R(0, 0, 200, 100));
  orch.flip(slide, R(0, 40, 300, 100), {scale: false});
  assert.equal(slide.calls[0].frames[0].transform, 'translate(0px,40px)');
});

test('leave fades out where it was on the exit token and is inert meanwhile', () => {
  const orch = loadMotion(false), el = fakeEl(R(0, 0, 10, 10));
  let host = null;
  orch.leave(el, R(5, 6, 300, 200), {append: x => { host = x; }});
  assert.equal(host, el);
  assert.equal(el.inert, true);
  assert.equal(el.style.position, 'fixed');
  assert.equal(el.style.top, '6px');
  assert.equal(el.calls[0].timing.duration, 120);
  assert.deepEqual(Object.keys(el.calls[0].frames[1]).sort(), ['opacity', 'transform']);
});

test('with reduced motion flip and leave move nothing', () => {
  const orch = loadMotion(true), el = fakeEl(R(0, 0, 200, 100));
  assert.equal(orch.flip(el, R(50, 20, 100, 50)), null);
  assert.equal(orch.leave(el, R(0, 0, 10, 10), {append() { throw new Error('kept on screen'); }}), null);
  assert.equal(el.calls.length, 0);
});

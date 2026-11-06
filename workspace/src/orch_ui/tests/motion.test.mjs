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
  assert.match(tokens, /--fs-body: 13px;/);
  assert.ok(!/border-left:[3-9]px solid var\(--warning\)[^}]*\}/.test(comps.replace(/\.qcard\{[^}]*\}/, '')));
});

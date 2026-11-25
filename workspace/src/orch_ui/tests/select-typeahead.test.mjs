// ORCH-2051: buffered prefix navigation of the master select (static/select.js).
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const timers = [];
globalThis.window = {addEventListener() {}};
globalThis.document = {addEventListener() {}};
globalThis.setTimeout = f => timers.push(f) && timers.length;
globalThis.clearTimeout = () => {};
new Function(readFileSync(new URL('../static/select.js', import.meta.url), 'utf8'))();
const type = window.UI.select_typeAhead;
const names = ['SALES-001 Offer', 'SALES-097 Contract', 'SALES-098 Call', 'SALES-110 Invoice', 'Alpha', 'Alpine'];
const items = names.map(textContent => ({textContent}));
const key = (k, o = {}) => ({key: k, preventDefault() { this.prevented = true; }, ...o});
const expire = () => { timers.splice(0).pop()?.(); };
const run = (s, from = 0) => { let r; for (const c of s) r = type(items, from, key(c)); return r?.textContent; };

test('typing a whole key lands on it', () => { expire(); assert.equal(run('SALES-097'), names[1]); });
test('buffer ends after the timeout', () => { expire(); run('SALES-09'); expire(); assert.equal(run('a'), 'Alpha'); expire(); });
test('repeating one letter cycles', () => { expire(); assert.equal(run('a', 3), 'Alpha'); assert.equal(type(items, 4, key('a'))?.textContent, 'Alpine'); expire(); });
test('modified keys and non-characters are ignored', () => {
  expire();
  for (const e of [key('a', {ctrlKey: true}), key('a', {metaKey: true}), key('a', {altKey: true}), key('Enter'), key(' ')]) assert.equal(type(items, 0, e), null);
  assert.equal(run('S', 3), names[0]);
  expire();
});
test('no match returns nothing', () => { expire(); assert.equal(run('zz'), undefined); expire(); });

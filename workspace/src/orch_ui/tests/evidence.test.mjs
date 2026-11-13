import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const E = require('../static/evidence.js');

const file = ref => ({type: 'file', ref});

test('kind comes from the extension: png image, csv table, html page, other text', () => {
  assert.equal(E.kindOf(file('out/shot.png')), 'image');
  assert.equal(E.kindOf(file('a/b.JPG')), 'image');
  assert.equal(E.kindOf(file('chart.svg')), 'image');
  assert.equal(E.kindOf(file('out/export.csv')), 'table');
  assert.equal(E.kindOf(file('report.html')), 'page');
  assert.equal(E.kindOf(file('notes.md')), 'text');
  assert.equal(E.kindOf(file('Makefile')), 'text');
  assert.equal(E.kindOf(file('out/shot.png?v=2')), 'image');
});

test('only files are inferred; other types are text', () => {
  assert.equal(E.kindOf({type: 'command', ref: 'pytest -q'}), 'text');
  assert.equal(E.kindOf({type: 'url', ref: 'https://x.test/a.png'}), 'text');
  assert.equal(E.kindOf({type: 'note', ref: 'ok'}), 'text');
});

test('a missing file says on another computer, in the chip and the full view', () => {
  const ev = {...file('out/shot.png'), summary: 'Export screen'};
  assert.match(E.chip(ev, {missing: true}), /on another computer/);
  assert.match(E.full(ev, {missing: true}), /on another computer/);
  assert.doesNotMatch(E.chip(ev, {missing: true}), /<img/);
  assert.doesNotMatch(E.chip(ev, {url: 'evidence/a-shot.png'}), /on another computer/);
});

test('everything dynamic is escaped', () => {
  const ev = {type: 'note', ref: '<script>alert(1)</script>', text: '"><img src=x onerror=1>'};
  for (const html of [E.chip(ev, {}), E.full(ev, {})]) {
    assert.doesNotMatch(html, /<script>/);
    assert.doesNotMatch(html, /<img src=x/);
  }
});

test('image url must be a plain relative path, never javascript: or data:', () => {
  assert.doesNotMatch(E.chip(file('a.png'), {url: 'javascript:alert(1)'}), /javascript:/);
  assert.doesNotMatch(E.full(file('a.png'), {url: 'data:text/html,x'}), /data:/);
  assert.match(E.chip(file('a.png'), {url: 'evidence/ab12-a.png'}), /<img[^>]+src="evidence\/ab12-a\.png"/);
});

test('csv parses quotes, commas, CRLF; table view cuts at 50 rows', () => {
  const t = E.parseCsv('name,total\r\n"Acme, Inc",1500.50\r\n"say ""hi""",2\r\n');
  assert.deepEqual(t.columns, ['name', 'total']);
  assert.deepEqual(t.rows, [['Acme, Inc', '1500.50'], ['say "hi"', '2']]);
  assert.deepEqual(E.parseCsv(''), {columns: [], rows: []});
  const big = 'n\n' + Array.from({length: 120}, (_, i) => i).join('\n');
  const html = E.full(file('big.csv'), {csv: big, url: 'evidence/big.csv'});
  assert.equal((html.match(/<tr>/g) || []).length, 51);
  assert.match(html, /Showing 50 of 120 rows/);
});

test('a page is shown in a sandboxed frame', () => {
  const html = E.full(file('report.html'), {url: 'evidence/ab-report.html'});
  assert.match(html, /<iframe[^>]*sandbox=""/);
  assert.match(html, /Helper preview/);
  assert.doesNotMatch(html, /Agent preview/);
});

test('a command shows its command line plainly, never behind a Details toggle (owner rule)', () => {
  const html = E.full({type: 'command', ref: 'pytest -q'}, {});
  assert.match(html, /pytest -q/);
  assert.doesNotMatch(html, /<details|Technical details/);
});

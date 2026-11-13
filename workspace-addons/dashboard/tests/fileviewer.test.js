'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/kit/fileviewer.js'), 'utf8');
const win = {};
vm.runInNewContext(source, {window: win});
const V = win.FileViewer;

test('every kind of ticket file maps to one viewer kind, unknown ones to other', () => {
  const kinds = {'a.PNG': 'image', 'b.svg': 'image', 'c.pdf': 'pdf', 'site/index.html': 'page', 'd.csv': 'table', 'e.xlsx': 'xlsx',
    'f.md': 'md', 'g.json': 'code', 'h.py': 'code', 'i.txt': 'text', 'j.log': 'text', 'k.wav': 'audio', 'l.webm': 'video', 'm.zip': 'zip',
    'n.bin': 'other', 'noext': 'other'};
  for (const [name, kind] of Object.entries(kinds)) assert.equal(V.kindOf(name), kind, name);
});

test('the file URL always carries ticket, folder and name encoded, and download adds dl=1', () => {
  const f = {tid: 't_abc123', kind: 'evidence', name: 'a b/c&d.csv'};
  assert.equal(V.urlOf(f), '/api/file?t=t_abc123&k=evidence&n=a%20b%2Fc%26d.csv');
  assert.ok(V.urlOf(f, true).endsWith('&dl=1'));
});

test('csv parsing keeps quoted commas, quotes and line breaks in one cell', () => {
  const {columns, rows} = V.parseDelimited('name,note\r\n"Smith, A","said ""hi"""\n"two\nlines",x\n', ',');
  assert.equal(JSON.stringify(columns), JSON.stringify(['name', 'note']));
  assert.equal(JSON.stringify(rows), JSON.stringify([['Smith, A', 'said "hi"'], ['two\nlines', 'x']]));
});

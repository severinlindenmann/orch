'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/fileviewer.js'), 'utf8');
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

test('only web pages and PDFs get a thumbnail; the box has a stable key so a redraw keeps its frame', () => {
  const el = () => { const n = {className: '', dataset: {}, classList: {add() {}}, setAttribute() {}, append() {}, set textContent(v) {}, isConnected: false}; return n; };
  const w2 = {};
  vm.runInNewContext(source, {window: w2, document: {createElement: el}, navigator: {pdfViewerEnabled: true}, requestAnimationFrame() {}});
  const f = name => ({tid: 't_x', kind: 'artifacts', name, size: 1, mtime: ''});
  assert.equal(w2.FileViewer.thumb(f('a.png')), null);
  assert.equal(w2.FileViewer.thumb(f('a.csv')), null);
  assert.equal(w2.FileViewer.thumb(f('a.html')).dataset.key, 'pthumb-artifacts-a.html');
  assert.equal(w2.FileViewer.thumb(f('a.pdf')).dataset.key, 'pthumb-artifacts-a.pdf');
  const w3 = {};
  vm.runInNewContext(source, {window: w3, document: {createElement: el}, navigator: {pdfViewerEnabled: false}, requestAnimationFrame() {}});
  assert.equal(w3.FileViewer.thumb(f('a.pdf')), null);  // no built-in PDF viewer: the icon stays
});

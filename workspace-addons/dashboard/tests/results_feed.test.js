'use strict';
// ORCH-697: a ticket's results as the 16 result widgets, from one place (pages/results-feed.js) for wall tiles, the
// session chat and the ticket page. The demo ticket of the click-through (e2e/focus_d/widgets_ticket.json) has every kind.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.join(__dirname, '..', '..', '..');
const WEB = path.join(__dirname, '..', 'src', 'orch_dashboard', 'web');
const KIT = path.join(ROOT, 'workspace', 'src', 'orch_ui', 'static');
// the style guide's kind picker (kit/results.js), loaded the way the page loads it
const win = {};
vm.runInNewContext(fs.readFileSync(path.join(KIT, 'results.js'), 'utf8'), {window: win, document: {}, location: {href: 'http://127.0.0.1/'}, URL});
global.window = win;
const F = require(path.join(WEB, 'pages', 'results-feed.js'));
const DEMO = JSON.parse(fs.readFileSync(path.join(ROOT, 'e2e', 'focus_d', 'widgets_ticket.json'), 'utf8'));
const listing = {available: true, files: Object.keys(DEMO.files).map((name, i) => ({name, size: 1000 + i, mtime: '2026-11-19T14:0' + (i % 10) + ':00Z'}))};
// what /api/file would answer for a text file of the demo ticket
const textOf = name => {
  const f = DEMO.files[name];
  return f.text !== undefined ? f.text : fs.readFileSync(path.join(KIT, 'samples', f.sample), 'utf8');
};
const read = it => it.state !== 'loading' ? it
  : it.type === 'archive' ? F.resultsWith(it, {info: {entries: [{name: 'sample-notes.md', size: 130}], count: 2}})
    : it.type === 'pdf' ? F.resultsWith(it, {info: {pages: 1}})
      : F.resultsWith(it, {text: textOf(it.src0.name)});

test('the demo ticket gives every one of the 16 widget kinds from its files, evidence and links', () => {
  const items = F.resultsItems(DEMO.ticket, listing).map(read);
  const kinds = new Set(items.map(it => it.type));
  const all = Array.from(win.UI.result.TYPES, t => t.id);
  assert.equal(all.length, 16);
  assert.deepEqual(all.filter(k => !kinds.has(k)), [], 'every kind is there');
  const by = k => items.find(it => it.type === k);
  assert.equal(by('chart').name, 'Uploads by day');
  assert.deepEqual(by('chart').values, [41, 56, 38, 72, 88, 12, 9]);
  assert.equal(by('chart').meta, 'Chart · 7 values');
  assert.deepEqual(by('change').files, [['attach.py', 3, 1]]);
  assert.equal(by('change').meta, 'Change · 1 file');
  assert.equal(by('archive').meta, 'Archive · 2 files');
  assert.equal(by('pdf').meta, 'PDF · 1 page');
  assert.equal(by('table').meta, 'Table · 3 rows');
  const pr = by('pr');
  assert.equal(pr.name, 'Pull request 1309');
  assert.equal(pr.status, 'draft');
  assert.equal(pr.title, 'Files can be dropped on a ticket');
  assert.equal(by('link').name, 'Notes on phone widths');
  assert.equal(by('picture').src, '/api/file?t=t_widget16&k=artifacts&n=home-390.svg');
  assert.equal(by('picture').alt, 'Home at phone width');
  assert.equal(by('page').src, '/view/t_widget16/artifacts/phone-widths.html');
  assert.ok(by('file').download.endsWith('&dl=1'));
});

test('a check run is a text result: what ran, its last lines and passed or failed', () => {
  const items = F.resultsItems(DEMO.ticket, listing);
  const run = items.find(it => it.key.startsWith('run:'));
  assert.equal(run.type, 'text');
  assert.match(run.meta, /^Check passed/);
  assert.match(run.text, /^\$ node --test tests\/attach\.test\.js\n/);
  assert.match(run.text, /Check passed$/);
  assert.equal(run.step, 'c1');
  const failed = F.resultsItems({id: 't_abcdef', checklist: [{id: 'c1', evidence: [{type: 'command', ref: 'pytest -q', exit: 2, at: '2026-11-19T10:00:00Z'}]}]}, null);
  assert.equal(failed[0].meta.split(' · ')[0], 'Check failed (exit 2)');
});

test('each result knows the step that made it, so the chat shows it inside that step\'s message', () => {
  const items = F.resultsItems(DEMO.ticket, listing);
  const c1 = items.filter(it => it.step === 'c1').map(it => it.type).sort();
  assert.deepEqual(c1, ['md', 'pr', 'text']);
  const c2 = items.filter(it => it.step === 'c2').map(it => it.type).sort();
  assert.deepEqual(c2, ['link', 'page', 'picture', 'video']);
  assert.ok(items.filter(it => !it.step).every(it => it.key.startsWith('artifacts:')), 'only files no step proved have no step');
});

test('files, pull requests and links show once each, pull requests and links after the files', () => {
  const items = F.resultsItems(DEMO.ticket, listing);
  const keys = items.map(it => it.key);
  assert.equal(new Set(keys).size, keys.length);
  assert.equal(items.filter(it => it.type === 'pr').length, 1);
  const firstPr = items.findIndex(it => it.type === 'pr'), firstLink = items.findIndex(it => it.type === 'link');
  assert.ok(items.slice(0, firstPr).every(it => !['pr', 'link'].includes(it.type)));
  assert.ok(firstLink > firstPr);
});

test('files the person attached themselves are not results; files of other tickets or outside the folders never show', () => {
  const t = {id: 't_abcdef', history: [{by: 'human:demo', text: 'Attached sketch.png'}, {by: 'agent:claude', text: 'Attached plan.md'}],
    checklist: [{id: 'c1', evidence: [{type: 'file', ref: '.orch/tickets/t_other1/artifacts/x.png'}, {type: 'file', ref: '.orch/tickets/t_abcdef/../secrets/k.txt'},
      {type: 'file', ref: 'src/app.py'}, {type: 'file', ref: '.orch/tickets/t_abcdef/evidence/shot.png'}]}]};
  const items = F.resultsItems(t, {files: [{name: 'sketch.png', size: 3}, {name: 'plan.md', size: 4}]});
  assert.deepEqual(items.map(it => it.name), ['plan.md', 'shot.png']);
  assert.equal(items[1].src, '/api/file?t=t_abcdef&k=evidence&n=shot.png');
});

test('an issue link is an issue, a plain address a link, never a script address', () => {
  assert.equal(F.resultsLinkItem('https://github.com/o/r/issues/7').name, 'Issue 7');
  assert.equal(F.resultsLinkItem('https://example.com/a').type, 'link');
  const t = {id: 't_abcdef', refs: [{kind: 'url', url: 'javascript:alert(1)'}, {kind: 'url', url: 'http://plain.example.com'}], checklist: []};
  assert.deepEqual(F.resultsItems(t, null), [], 'only https addresses');
});

test('a JSON file is a chart only when it has labels and numbers of the same length; else it stays data', () => {
  assert.equal(F.resultsChart('{"labels":["a","b"],"values":[1,2]}').values.length, 2);
  assert.equal(F.resultsChart('{"labels":["a"],"values":[1,2]}'), null);
  assert.equal(F.resultsChart('{"labels":["a"],"values":["1"]}'), null);
  assert.equal(F.resultsChart('[1,2]'), null);
  assert.equal(F.resultsChart('not json'), null);
  const it = F.resultsWith({type: 'data', name: 'x.json', state: 'loading'}, {text: '{"a": 1}\n'});
  assert.equal(it.type, 'data');
  assert.equal(it.meta, 'Data · 1 line');
  assert.equal(it.state, undefined);
});

test('too big or unreadable shows the widget\'s own state; a long text keeps its first part', () => {
  assert.equal(F.resultsWith({type: 'text', state: 'loading'}, {error: 'large'}).state, 'large');
  assert.equal(F.resultsWith({type: 'text', state: 'loading'}, {error: 'error'}).state, 'error');
  const long = F.resultsWith({type: 'text', state: 'loading'}, {text: 'x\n'.repeat(200000)});
  assert.equal(long.state, 'large');
  assert.ok(long.text.length <= 256 * 1024);
});

test('plurals read right: 1 line, 2 lines, 1 file, 2 files', () => {
  assert.equal(F.resultsWith({type: 'md', state: 'loading'}, {text: 'one'}).meta, 'Document · 1 line');
  assert.equal(F.resultsWith({type: 'code', state: 'loading'}, {text: 'a\nb\n'}).meta, 'Code · 2 lines');
  assert.equal(F.resultsWith({type: 'archive', state: 'loading'}, {info: {entries: [{name: 'a', size: 1}], count: 1}}).meta, 'Archive · 1 file');
});

test('loaded after the kit renderer and before the pages that use it; the page redraw keeps a filled host', () => {
  const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
  const at = s => html.indexOf(s);
  assert.ok(at('kit/results.css') > 0 && at('kit/results.js') > 0);
  assert.ok(at('kit/results.js') < at('pages/results-feed.js'));
  for (const page of ['pages/ticket.js', 'pages/livechat.js', 'pages/livewall.js']) assert.ok(at('pages/results-feed.js') < at(page), page);
  const app = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
  assert.match(app, /dataset\.resultsHost !== undefined/);
  assert.match(app, /resultsFillAll\(document\)/);
  for (const page of ['ticket.js', 'livechat.js', 'livewall.js']) assert.match(fs.readFileSync(path.join(WEB, 'pages', page), 'utf8'), /resultsHost\(/, page + ' uses the one shared host');
});

test('no page-local widget: the pages draw results only through UI.result (R4.3)', () => {
  const feed = fs.readFileSync(path.join(WEB, 'pages', 'results-feed.js'), 'utf8');
  assert.match(feed, /UI\.result\(/);
  assert.match(feed, /UI\.resultOverlay\(/);
  assert.doesNotMatch(feed, /innerHTML/);
});

test('a workbook shows its header and rows; only a zip lists its files, other archives are plain files', () => {
  const t = F.resultsWith({type: 'table', state: 'loading'}, {info: {columns: ['Kind', 'Size'], rows: [['Picture', '2 MB']], rowCount: 1}});
  assert.deepEqual(t.rows, [['Kind', 'Size'], ['Picture', '2 MB']]);
  assert.equal(t.meta, 'Table · 1 row');
  const items = F.resultsItems({id: 't_abcdef', checklist: []}, {files: [{name: 'a.tar.gz', size: 9}, {name: 'b.zip', size: 9}]});
  assert.deepEqual(items.map(it => it.type), ['file', 'archive']);
});

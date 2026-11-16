'use strict';
// Owner feedback 14 Nov (sweep d-files): cards with a thumbnail, CSV as a table, Markdown rendered, a toolbar only above 6 files.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const helpers = require('../src/orch_dashboard/web/helpers.js');
const kit = {}; vm.runInContext(fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/date.js'), 'utf8'), vm.createContext({window:kit}));
const h = (tag, attrs = {}, ...children) => { const n = {tag, attrs, children:children.flat(Infinity).filter(x => x != null && x !== false)}; n.append = (...c) => n.children.push(...c); n.dataset = {}; n.classList = {add(){}}; return n; };
const nodes = n => n && typeof n === 'object' ? [n, ...(n.children || []).flatMap(nodes)] : [];
const text = n => !n ? '' : typeof n === 'string' ? n : (n.children || []).map(text).join('');
const EXT = {csv:'table', md:'md', png:'image', html:'page', txt:'text'};
const FileViewer = {kindOf:name => EXT[String(name).split('.').pop()] || 'other', word:k => ({table:'Table', md:'Note'})[k] || 'File', thumb:() => null,
  parseDelimited:(t, sep) => { const rows = t.split('\n').filter(Boolean).map(r => r.split(sep)); return {columns:rows.shift(), rows}; },
  renderMd:src => h('article', {className:'fv-md'}, h('h2', {}, src.split('\n')[0].replace(/^#+\s*/, '')))};
function ctx() {
  const c = {addEventListener(){}, document:{addEventListener(){}}, h, array:v => Array.isArray(v) ? v : [], iconEl:n => n, clean:String, window:{DashHelpers:helpers, UI:kit.UI, FileViewer, orch:{}}, snapshot:false,
    route:() => ({kind:'ticket'}), render(){}, ticketTabs:new Map(), fetch:() => new Promise(() => {}), URL, TextDecoder, locks:new Set(),
    ticketButton:(label, cls, click) => { const b = h('button', {className:'btn ' + cls}, label); b.onclick = click; return b; }, previewFile(){}};
  vm.createContext(c); vm.runInContext(source, c); return c;
}
const files = n => Array.from({length:n}, (_, i) => ({name:'file-' + (i + 1) + '.md', size:2048, mtime:'2026-11-14T09:0' + (i % 10) + ':00Z'}));
function panel(n) {
  const c = ctx(), t = {id:'t_one', status:'review'};
  vm.runInContext("artifactData.set('t_one', {at:Date.now(), data:{files:" + JSON.stringify(files(n)) + "}})", c);
  return nodes(h('div', {}, c.artifactsPanel(t)));
}
test('up to 6 files: cards only, no toolbar, no group headers', () => {
  for (const n of [1, 2, 6]) {
    const all = panel(n), json = JSON.stringify(all);
    assert.equal(all.filter(x => x.attrs['data-key'] === 'files-toolbar').length, 0, n + ' files: no toolbar');
    assert.equal(all.filter(x => x.tag === 'input' && x.attrs.type === 'search').length, 0);
    assert.equal(all.filter(x => x.tag === 'details').length, 0, 'no collapsible groups');
    assert.equal(all.filter(x => /(^| )file-tile( |$)/.test(x.attrs.className || '')).length, n);
    assert.doesNotMatch(json, /role-chip|Task:|Show all files/);
  }
});
test('above 6 files: search, sort and Cards/List only', () => {
  const all = panel(7), labels = all.filter(x => x.tag === 'select').map(x => x.attrs['aria-label']);
  assert.ok(all.some(x => x.attrs['data-key'] === 'files-toolbar'));
  assert.ok(all.some(x => x.tag === 'input' && x.attrs.type === 'search'));
  assert.deepEqual(labels, ['Sort']);
  const views = all.filter(x => x.tag === 'button' && /^(Cards|List)$/.test(text(x))).map(text);
  assert.deepEqual(views, ['Cards', 'List']);
});
test('a card shows name, size and one date; CSV is a table; Markdown is rendered', async () => {
  const c = ctx(), t = {id:'t_one'};
  const card = nodes(c.fileTile(t, c.ticketFileEntries ? {tid:'t_one', kind:'artifacts', name:'cups.csv', size:1024, mtime:'2026-11-14T10:20:00Z', fileKind:'table', role:'Result', task:'', created:'', title:'cups', meta:''} : null));
  assert.match(text(card[0]), /cups/);
  assert.match(text(card[0]), /1 KB/);
  const csv = c.previewText(t, 'artifacts', {name:'cups.csv'}, 'name,qty\ncups,500\nlids,500\n');
  assert.ok(nodes(csv).some(x => x.tag === 'table') && nodes(csv).filter(x => x.tag === 'tr').length === 3, 'CSV as a table');
  const md = c.previewText(t, 'artifacts', {name:'news.md'}, '# Dear friends\n\nThank you.');
  assert.ok(nodes(md).some(x => x.tag === 'h2' && text(x) === 'Dear friends'), 'Markdown is rendered, not shown as # text');
  assert.ok(nodes(c.previewText(t, 'artifacts', {name:'a.txt'}, 'plain\nlines')).some(x => x.tag === 'pre'));
});
test('b4: a file attached with a title shows that title, the file name small underneath', () => {
  const c = ctx(), t = {id:'t_one'};
  const file = vm.runInContext('evidenceFile', c)(t, {type:'file', ref:'.orch/tickets/t_one/evidence/logo.svg', at:'2026-11-14T09:00:00Z', title:'Poster draft'});
  assert.equal(file.title, 'Poster draft');
  const entry = vm.runInContext('fileEntry', c)(t, {kind:'evidence'}, file);
  assert.equal(entry.title, 'Poster draft');
  const tile = nodes(vm.runInContext('fileTile', c)(t, entry));
  assert.match(text(tile[0]), /Poster draft/);
  assert.ok(tile.some(x => /file-real-name/.test(x.attrs.className || '') && text(x) === 'logo.svg'), 'file name underneath');
  const row = nodes(vm.runInContext('ticketFileRow', c)(t, 'evidence', file));
  assert.ok(row.some(x => x.attrs.className === 'file-name' && text(x) === 'Poster draft'));
  const plain = vm.runInContext('fileEntry', c)(t, {kind:'artifacts'}, {name:'quote-Q-2026-114.pdf'});
  assert.equal(plain.title, 'Quote Q 2026 114', 'without a title the readable file name stays');
});
test('b4: a PDF result shows a small inline preview from the same-origin file endpoint', () => {
  const c = ctx(), t = {id:'t_one'};
  const tile = nodes(c.ticketPreviewTile(t, {name:'quote.pdf', mtime:''}, 'evidence'));
  const obj = tile.find(x => x.tag === 'object');
  assert.ok(obj && obj.attrs.type === 'application/pdf' && obj.attrs.data.startsWith('/api/file?t=t_one&k=evidence'));
});
test('b4: a long ticket title wraps to two lines then an ellipsis; shared-link row actions are always visible', () => {
  const css = n => fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web', n), 'utf8');
  assert.match(css('pages/ticket.css'), /ticket-strip h1 \.ed-title[^{]*\{[^}]*-webkit-line-clamp:2[^}]*overflow:hidden/);
  const style = css('style.css');
  assert.doesNotMatch(style, /\.compact-actions\{[^}]*opacity:0/, 'row actions are not hidden until hover');
  assert.doesNotMatch(style, /\.compact-row:hover \.compact-actions/);
});

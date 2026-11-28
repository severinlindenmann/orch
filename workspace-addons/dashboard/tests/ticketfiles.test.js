'use strict';
// The ticket's Files tab and its file rows. O-10 (owner, 28 Nov): a compact list with tags; a click opens the file viewer.
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
    route:() => ({kind:'ticket'}), state:{}, render(){}, ticketTabs:new Map(), fetch:() => new Promise(() => {}), URL, TextDecoder, locks:new Set(),
    ticketButton:(label, cls, click) => { const b = h('button', {className:'btn ' + cls}, label); b.onclick = click; return b; }, previewFile(){}};
  vm.createContext(c); vm.runInContext(source, c); return c;
}
const files = n => Array.from({length:n}, (_, i) => ({name:'file-' + (i + 1) + '.md', size:2048, mtime:'2026-11-14T09:0' + (i % 10) + ':00Z'}));
function panel(n) {
  const c = ctx(), t = {id:'t_one', status:'review'};
  vm.runInContext("artifactData.set('t_one', {at:Date.now(), data:{files:" + JSON.stringify(files(n)) + "}})", c);
  return nodes(h('div', {}, c.artifactsPanel(t)));
}
// O-10 (owner chose B, 28 Nov): the Files tab is a list like a file explorer, built from the master's file list.
test('O-10: one compact row per file, no tiles and no preview pane; search only above 6 files', () => {
  for (const n of [1, 2, 6]) {
    const all = panel(n), json = JSON.stringify(all);
    assert.equal(all.filter(x => x.tag === 'input' && x.attrs.type === 'search').length, 0, n + ' files: no search');
    assert.equal(all.filter(x => x.tag === 'details').length, 0, 'no collapsible groups');
    assert.equal(all.filter(x => x.attrs.className === 'files-row').length, n);
    assert.equal(all.filter(x => x.attrs.className === 'files-head').length, 1, 'one line of column heads');
    assert.doesNotMatch(json, /file-tile|file-grid|file-thumb|ticket-preview|files-preview|Cards/, 'no tiles, no previews, no pane');
  }
  const many = panel(7);
  assert.ok(many.some(x => x.tag === 'input' && x.attrs.type === 'search' && x.attrs['aria-label'] === 'Search files'));
  assert.equal(many.filter(x => x.tag === 'select').length, 0, 'the column heads sort; no Sort box');
});
test('O-10: a row says name, tags, kind, size and date; a click, Enter or Space opens the existing file viewer', () => {
  const c = ctx(), opened = [];
  const t = {id:'t_one', status:'active', history:[{by:'human:lume', text:'Attached brief.png'}],
    checklist:[{id:'c1', text:'Collect'}, {id:'c2', text:'Write the note', done:true, evidence:[{type:'file', ref:'.orch/tickets/t_one/evidence/proof.md', at:'2026-11-14T09:00:00Z', size:300}]}]};
  vm.runInContext("previewFile = (...a) => opened.push(a)", Object.assign(c, {opened}));
  vm.runInContext("artifactData.set('t_one', {at:Date.now(), data:{files:[{name:'cups.csv', size:1024, mtime:'2026-11-14T10:20:00Z'}, {name:'brief.png', size:10, mtime:'2026-11-14T08:00:00Z'}]}})", c);
  const all = nodes(h('div', {}, c.artifactsPanel(t))), rows = all.filter(x => x.attrs.className === 'files-row');
  const tags = r => nodes(r).filter(x => x.attrs.className === 'tag').map(text);
  const by = name => rows.find(r => r.attrs['data-key'].endsWith('-' + name));
  assert.deepEqual(tags(by('cups.csv')), ['Result']);
  assert.deepEqual(tags(by('proof.md')), ['Evidence for task 2']);
  assert.equal(nodes(by('proof.md')).find(x => x.attrs.className === 'tag').attrs.title, 'Task: Write the note');
  assert.deepEqual(tags(by('brief.png')), ['Added by you']);
  const row = by('cups.csv');
  assert.deepEqual(row.children.slice(1, 4).map(text), ['Table', '1 KB', kit.UI.stamp('2026-11-14T10:20:00Z')], 'kind, size, date in their columns');
  assert.equal(row.attrs.role, 'button'); assert.equal(row.attrs.tabindex, '0');
  assert.equal(row.attrs['aria-label'], 'Open cups.csv, Table, Result');
  row.onclick();
  let stopped = 0;
  row.onkeydown({key:'Enter', preventDefault(){ stopped++; }}); row.onkeydown({key:' ', preventDefault(){ stopped++; }}); row.onkeydown({key:'a', preventDefault(){ stopped++; }});
  assert.deepEqual(JSON.parse(JSON.stringify(opened)), [['t_one', 'artifacts', 'cups.csv'], ['t_one', 'artifacts', 'cups.csv'], ['t_one', 'artifacts', 'cups.csv']]);
  assert.equal(stopped, 2);
});
test('O-10: the column heads sort; newest first to begin with, a second click turns the order', () => {
  const c = ctx(), t = {id:'t_one', status:'active'};
  vm.runInContext("artifactData.set('t_one', {at:Date.now(), data:{files:[{name:'b.md', size:30, mtime:'2026-11-14T09:00:00Z'}, {name:'a.md', size:10, mtime:'2026-11-14T11:00:00Z'}, {name:'c.csv', size:20, mtime:'2026-11-14T10:00:00Z'}]}})", c);
  const names = () => nodes(h('div', {}, c.artifactsPanel(t))).filter(x => x.attrs.className === 'files-row').map(r => r.attrs['data-key'].replace('file-item-artifacts-', ''));
  const head = key => nodes(h('div', {}, c.artifactsPanel(t))).find(x => x.attrs['data-key'] === 'files-sort-' + key);
  assert.deepEqual(names(), ['a.md', 'c.csv', 'b.md']);
  assert.equal(head('changed').attrs['aria-sort'], 'descending'); assert.equal(head('name').attrs['aria-sort'], 'none');
  head('name').onclick();
  assert.deepEqual(names(), ['a.md', 'b.md', 'c.csv']);
  assert.equal(head('name').attrs['aria-sort'], 'ascending');
  head('name').onclick();
  assert.deepEqual(names(), ['c.csv', 'b.md', 'a.md']);
  head('size').onclick();
  assert.deepEqual(names(), ['b.md', 'c.csv', 'a.md'], 'biggest first');
  head('kind').onclick();
  assert.deepEqual(names(), ['a.md', 'b.md', 'c.csv'], 'Note, Note, Table');
  // the viewer steps through the files in the order the list shows
  assert.deepEqual([...c.visibleFileEntries(t, c.ticketFileEntries(t)).map(f => f.name)], ['a.md', 'b.md', 'c.csv']);
});
test('O-09: a presentation a helper attached is listed on Files and in the Result, by its own name, with a download that is the file itself', () => {
  const c = ctx(), t = {id:'t_one', status:'review', history:[{by:'agent:claude', text:'Attached deck.pptx'}]};
  vm.runInContext("artifactData.set('t_one', {at:Date.now(), data:{files:[{name:'deck.pptx', size:48211, mtime:'2026-11-14T10:20:00Z'}, {name:'slide-1.png', size:900, mtime:'2026-11-14T10:21:00Z'}]}})", c);
  const rows = nodes(h('div', {}, c.artifactsPanel(t))).filter(x => x.attrs.className === 'files-row');
  const deck = rows.find(r => r.attrs['data-key'] === 'file-item-artifacts-deck.pptx');
  assert.ok(deck, 'the original is on the Files tab');
  assert.equal(text(deck.children[1]), 'Presentation');
  assert.deepEqual(nodes(deck).filter(x => x.attrs.className === 'tag').map(text), ['Result']);
  const card = nodes(c.ticketReviewCard(t));
  const inCard = card.find(x => x.attrs['data-key'] === 'file-artifacts-deck.pptx');
  assert.ok(inCard, 'and in the Result card, as a row');
  assert.match(text(inCard), /deck\.pptx.*Presentation · 47 KB/);
  const dl = nodes(inCard).find(x => x.tag === 'a' && text(x) === 'Download');
  assert.equal(dl.attrs.href, '/api/file?t=t_one&k=artifacts&n=deck.pptx&dl=1', 'the download asks for the stored bytes (dl=1), not a preview');
  assert.equal(dl.attrs.download, 'deck.pptx');
});
test('a text preview looks like its file: CSV is a table; Markdown is rendered', async () => {
  const c = ctx(), t = {id:'t_one'};
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
  const tile = nodes(vm.runInContext('fileListRow', c)(t, entry));
  assert.match(text(tile[0]), /Poster draft/);
  assert.ok(tile.some(x => x.attrs.className === 'sub' && text(x) === 'logo.svg'), 'file name underneath');
  const row = nodes(vm.runInContext('ticketFileRow', c)(t, 'evidence', file));
  assert.ok(row.some(x => x.attrs.className === 'file-name' && text(x) === 'Poster draft'));
  const plain = vm.runInContext('fileEntry', c)(t, {kind:'artifacts'}, {name:'quote-Q-2026-114.pdf'});
  assert.equal(plain.title, 'quote-Q-2026-114.pdf', 'ORCH-240: without a title the real file name, extension included');
});
test('b4: a PDF result shows a small inline preview from the same-origin file endpoint', () => {
  const c = ctx(), t = {id:'t_one'};
  const tile = nodes(c.ticketPreviewTile(t, {name:'quote.pdf', mtime:''}, 'evidence'));
  const obj = tile.find(x => x.tag === 'object');
  assert.ok(obj && obj.attrs.type === 'application/pdf' && obj.attrs.data.startsWith('/api/file?t=t_one&k=evidence'));
});
test('b4: a long ticket title wraps to three lines then an ellipsis; shared-link row actions are always visible', () => {
  const css = n => fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web', n), 'utf8');
  // on a phone the header clamps to three lines; wider, and while a helper works, it shows the whole title (ORCH-70)
  assert.match(css('pages/ticket.css'), /ticket-strip h1\.title-clamp \.ed-title[^{]*\{[^}]*-webkit-line-clamp:3[^}]*overflow:hidden/);
  const style = css('style.css');
  assert.doesNotMatch(style, /\.compact-actions\{[^}]*opacity:0/, 'row actions are not hidden until hover');
  assert.doesNotMatch(style, /\.compact-row:hover \.compact-actions/);
});
test('ORCH-185: a picture a person attached is an input (What you asked), not a Result; a helper file stays a result', () => {
  const c = ctx(), t = {id:'t_one', status:'active', history:[
    {by:'human:lume', text:'Attached hero.png'}, {by:'agent:claude', text:'Attached report.md'}, {by:'human:lume', text:'Changed the note'}]};
  vm.runInContext("artifactData.set('t_one', {at:Date.now(), data:{files:[{name:'hero.png', size:99}, {name:'report.md', size:5}]}})", c);
  c.t = t;
  assert.deepEqual(vm.runInContext('JSON.stringify(inputFiles(t).map(f => f.name))', c), '["hero.png"]');
  assert.deepEqual(vm.runInContext('JSON.stringify(artifactFiles(t).map(f => f.name))', c), '["report.md"]');
});
test('ORCH-184: the Result card and the Files tab agree: a file a step proved is a result file too', () => {
  const c = ctx(), t = {id:'t_one', status:'review', checklist:[{id:'c1', text:'Write the note', done:true, evidence:[{type:'file', ref:'.orch/tickets/t_one/evidence/one.md'}, {type:'file', ref:'.orch/tickets/t_one/evidence/two.md'}]}, {id:'c2', text:'Draw it', done:true, evidence:[{type:'file', ref:'.orch/tickets/t_one/evidence/three.png'}]}]};
  vm.runInContext("artifactData.set('t_one', {at:Date.now(), data:{files:[]}})", c);
  const files = nodes(h('div', {}, c.artifactsPanel(t))).filter(x => x.attrs.className === 'files-row').length;
  c.t = t; assert.equal(vm.runInContext('ticketFileCount(t)', c), 3);
  assert.equal(files, 3, 'the Files tab lists three');
  const card = JSON.stringify(c.ticketReviewCard(t));
  assert.doesNotMatch(card, /No result file/);
  assert.match(card, /3 files/);
});
test('ORCH-185: a picture shows itself in its row; its viewer says it was attached by you', () => {
  const c = ctx(), t = {id:'t_one', status:'active', history:[{by:'human:lume', text:'Attached hero.png'}]};
  c.t = t;
  const row = nodes(vm.runInContext("ticketFileRow(t, 'artifacts', {name:'hero.png', size:99})", c));
  const img = row.find(n => n.tag === 'img');
  assert.ok(img && /name=hero\.png|n=hero\.png/.test(img.attrs.src));
  assert.ok(row.some(n => /has-thumb/.test(n.attrs?.className || '')));
  assert.equal(vm.runInContext("fileEntry(t, {kind:'artifacts'}, {name:'hero.png', size:99}).role", c), 'Attached by you');
  assert.equal(vm.runInContext("fileEntry(t, {kind:'artifacts'}, {name:'report.md', size:9}).role", c), 'Result');
});
test('files the person attached count in the Files tab and are listed there (ORCH-901)', () => {
  const c = ctx(), t = {id:'t_two', status:'todo', history:[{by:'human:you', text:'Attached a.png'}, {by:'human:you', text:'Attached b.txt'}]};
  vm.runInContext("artifactData.set('t_two', {at:Date.now(), data:{files:[{name:'a.png', size:10, mtime:'2026-11-19T09:00:00Z'}, {name:'b.txt', size:5, mtime:'2026-11-19T09:00:00Z'}]}})", c);
  assert.equal(vm.runInContext('ticketFileCount', c)(t), 2);
  assert.equal(JSON.stringify(c.ticketFileEntries(t).map(f => f.name).sort()), '["a.png","b.txt"]');
  assert.equal(c.ticketFileEntries(t)[0].role, 'Attached by you');
  assert.equal(vm.runInContext('reviewFile', c)({...t, status:'review'}), null, 'the person\'s own file is never shown as the result');
  assert.doesNotMatch(text(h('div', {}, c.artifactsPanel(t))), /No files attached yet/);
});
test('the file list did not load: an error with one Try again, never skeleton tiles for ever (R7.2)', () => {
  const c = ctx(), t = {id:'t_one', status:'review'}, notes = [];
  c.stateNote = (title, text, kind, action) => { notes.push({title, kind, action}); return h('div', {className:'empty-state err', role:'alert'}, title, ' ', text, action ? h('button', {className:'btn primary sm'}, action.label) : null); };
  vm.runInContext("artifactData.set('t_one', {at:Date.now(), data:null})", c);
  const all = nodes(h('div', {}, c.artifactsPanel(t)));
  assert.match(text(h('div', {}, ...all.slice(0, 1))), /The files did not load/);
  assert.equal(all.filter(x => /skeleton/.test(x.attrs?.className || '')).length, 0, 'no skeleton tiles');
  assert.equal(notes.length, 1);
  assert.equal(notes[0].kind, 'error');
  assert.equal(notes[0].action.label, 'Try again');
  let drawn = 0; c.render = () => { drawn++; };
  notes[0].action.onClick();
  assert.equal(vm.runInContext("artifactData.has('t_one')", c), false, 'Try again asks again');
  assert.equal(drawn, 1);
});

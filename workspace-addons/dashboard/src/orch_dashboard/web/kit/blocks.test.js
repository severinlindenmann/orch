'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {validate, render, isSafeHttps, LIMITS} = require('./blocks.js');
class Element {
  constructor(tag) { this.tagName = tag; this.className = ''; this.attributes = {}; this.children = []; this.text = ''; }
  get childNodes() { return this.children; }
  get textContent() { return this.text + this.children.map(c => c.textContent).join(''); }
  set textContent(v) { this.text = String(v); this.children = []; }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k] ?? null; }
}
const document = {createElement: t => new Element(t), createElementNS: (_, t) => new Element(t)};
const textOf = el => el.textContent;
const findAll = (el, pred) => [...(pred(el) ? [el] : []), ...el.children.flatMap(c => findAll(c, pred))];
const find = (el, pred) => findAll(el, pred)[0];
const tag = name => e => e.tagName === name;
const cls = name => e => (e.className || e.attributes.class || '').split(' ').includes(name);
const draw = (doc, opts = {}) => render(doc, {document, ...opts});
const docOf = (...blocks) => ({schema: 'orch.blocks/1', from: 'job', blocks});
const folder = path.resolve(__dirname, '../../../../../../contracts/vectors/blocks');
assert.ok(fs.existsSync(folder));
const files = fs.readdirSync(folder).filter(n => n.endsWith('.json')).sort();
assert.ok(files.length >= 21);
const fixtures = Object.fromEntries(files.map(n => [n, JSON.parse(fs.readFileSync(path.join(folder, n), 'utf8'))]));
const fixture = name => fixtures['valid-' + name + '.json'].doc;
function assertNoJunk(el) {
  for (const e of findAll(el, () => true)) {
    assert.doesNotMatch(textOf(e), /NaN|null|undefined|Infinity/);
    for (const v of Object.values(e.attributes)) assert.doesNotMatch(v, /NaN|null|undefined|Infinity/);
  }
}
function check(block, ok = true) {
  const doc = docOf(block);
  assert.equal(validate(doc).ok, ok, JSON.stringify(block).slice(0, 200));
  assert.equal(draw(doc).valid, ok);
}
for (const [name, c] of Object.entries(fixtures)) test(name, () => {
  const before = JSON.parse(JSON.stringify(c.doc));
  const r = draw(c.doc);
  assert.equal(validate(c.doc).ok, c.valid);
  assert.equal(r.valid, c.valid);
  assert.deepEqual(c.doc, before);
  if (c.valid) {
    for (const s of c.shows) assert.ok(textOf(r.el).includes(s), s);
    assert.equal(r.fallbacks, c.fallback);
    assert.equal(findAll(r.el, cls('b-fallback')).length, c.fallback);
    for (const el of findAll(r.el, cls('b-fallback'))) assert.match(textOf(el), /can't show this here/i);
    assertNoJunk(r.el);
  } else {
    assert.ok(textOf(r.el).includes("These results can't be shown"));
    assert.equal(findAll(r.el, e => cls('b-sum')(e) || tag('a')(e) || tag('table')(e)).length, 0);
    assert.equal(r.el.children[0].tagName, 'p');
    assert.equal(r.el.children[1].tagName, 'details');
    assert.equal(textOf(find(r.el, tag('summary'))), 'Details');
  }
});
test('all ten structures and accessibility', () => {
  const r = draw(fixture('all-ten')).el;
  for (const c of ['b-sum', 'b-steps', 'b-prog', 'b-stat', 'b-kv', 'b-table', 'b-file', 'b-link', 'b-log', 'b-chart']) assert.equal(findAll(r, cls(c)).length, 1, c);
  assert.equal(find(r, cls('b-steps')).tagName, 'ol');
  assert.equal(find(r, cls('b-kv')).tagName, 'dl');
  const progress = find(r, e => e.getAttribute('role') === 'progressbar');
  assert.equal(progress.getAttribute('aria-valuenow'), '12');
  assert.equal(progress.getAttribute('aria-valuemax'), '40');
  assert.equal(progress.getAttribute('aria-valuemin'), '0');
  assert.equal(progress.getAttribute('aria-label'), 'Files');
  const table = find(r, cls('b-table'));
  assert.equal(findAll(table, e => e.tagName === 'th' && e.getAttribute('scope') === 'col').length, 3);
  assert.equal(find(table, tag('tbody')).children.length, 2);
  assert.ok(textOf(table).includes('–'));
  assert.equal(textOf(find(table, tag('caption'))), 'Skipped invoices');
  assert.ok(textOf(find(r, cls('b-file'))).includes('invoices.csv'));
  assert.ok(textOf(find(r, cls('b-file'))).includes('47 KB'));
  const a = find(r, tag('a'));
  assert.equal(a.getAttribute('href'), 'https://example.com/reports/11');
  assert.match(a.getAttribute('rel'), /noopener/);
  assert.equal(a.getAttribute('target'), '_blank');
  const log = find(r, cls('b-log'));
  assert.equal(textOf(find(log, tag('pre'))), 'writing row 1204\ndone in 3.1 s');
  assert.match(textOf(find(log, cls('b-cut'))), /1202 earlier lines/);
  const sr = find(r, cls('b-sr'));
  assert.equal(sr.tagName, 'table'); assert.ok(cls('sr-only')(sr));
  for (const s of ['Mon', '210', 'Wed', 'no value']) assert.ok(textOf(sr).includes(s));
  for (const c of Object.values(fixtures).filter(c => c.valid)) {
    const el = draw(c.doc).el;
    for (const svg of findAll(el, tag('svg'))) assert.ok(svg.getAttribute('aria-hidden') === 'true' || (svg.getAttribute('role') === 'img' && svg.getAttribute('aria-label')));
    for (const th of findAll(el, tag('th'))) assert.equal(th.getAttribute('scope'), 'col');
  }
});
test('unknown total and clamped progress', () => {
  const el = draw(fixture('progress-unknown-total')).el;
  const p = find(el, e => e.getAttribute('role') === 'progressbar');
  assert.equal(p.getAttribute('aria-valuenow'), null);
  assert.equal(p.getAttribute('aria-valuemax'), null);
  assert.match(textOf(el), /7 so far/); assertNoJunk(el);
  const over = draw(docOf({type:'progress', label:'Files', done:80, total:40})).el;
  assert.equal(find(over, tag('i')).getAttribute('style'), 'width:100%');
});
test('pictures only use host supplied local urls', () => {
  const doc = fixture('picture-preview');
  assert.equal(find(draw(doc).el, tag('img')), undefined);
  const el = draw(doc, {fileUrl:p => '/files/' + p}).el;
  assert.equal(find(el, tag('img')).getAttribute('alt'), 'Chart');
  assert.equal(find(el, tag('img')).getAttribute('loading'), 'lazy');
  assert.equal(find(el, tag('img')).getAttribute('src'), '/files/reports/chart.png');
  for (const url of [null, false, 'javascript:alert(1)', '//evil.example/x.png', 'http://x/y.png', '/\\evil.example/x', '/\nevil']) {
    const tree = draw(doc, {fileUrl:() => url}).el;
    assert.equal(find(tree, tag('img')), undefined);
    assert.match(textOf(tree), /File not available/);
    assert.ok(!textOf(tree).includes('reports/chart.png'));
  }
  assert.ok(!textOf(el).includes('reports/chart.png'));
  const svg = docOf({type:'file', path:'reports/chart.svg', preview:'image'});
  assert.equal(find(draw(svg, {fileUrl:() => '/chart.svg'}).el, tag('img')), undefined);
});
test('markup stays text across every field', () => {
  const tree = draw(fixture('markup-stays-text')).el;
  assert.ok(textOf(tree).includes('<b>bold</b> <script>alert(1)</script>'));
  assert.equal(findAll(tree, e => ['script', 'b', 'i'].includes(e.tagName)).length, 0);
  for (const e of findAll(tree, () => true)) for (const v of Object.values(e.attributes)) assert.ok(!v.includes('<'));
  const x = '<img src=x onerror=alert(1)>';
  const blocks = [
    {type:'table', columns:[{key:'a',label:'A'}], rows:[{a:x}]},
    {type:'steps', items:[{label:x,state:'waiting'}]}, {type:'kv',items:[{key:x,value:x}]},
    {type:'chart',kind:'bar',series:[{name:x,points:[['x',1]]}]},
    {type:'stat',label:x,value:1}, {type:'log',lines:[x]}, {type:'file',path:'a.txt',label:x},
    {type:'link',url:'https://example.com',label:x}
  ];
  for (const b of blocks) {
    const r = draw(docOf(b)); assert.equal(r.valid, true); assert.ok(textOf(r.el).includes(x));
    assert.equal(findAll(r.el, e => ['img','script'].includes(e.tagName)).length, 0);
    for (const e of findAll(r.el, () => true)) assert.ok(!Object.keys(e.attributes).some(k => k.startsWith('on')));
  }
});
test('https checks and rendering defence', () => {
  const bad = ['javascript:alert(1)','file:///etc/passwd','http://example.com','https://user:pw@example.com/',
    'https://user@example.com/', 'HTTPS://example.com', '//example.com', 'data:text/html,x',
    'https://example.com/a b', 'https://example.com/<x>', 'https://example.com/"x', "https://example.com/'x",
    'https://example.com/' + 'a'.repeat(2000), 'https://exa@mple.com', 'https://example.com\\@evil.com'];
  for (const url of bad) {
    assert.equal(isSafeHttps(url), false, url);
    const d = docOf({type:'link',url,label:'Open'});
    assert.equal(validate(d).ok, false); assert.equal(draw(d).valid, false);
    assert.equal(find(draw(d).el, tag('a')), undefined);
  }
  for (const url of ['https://example.com/a?b=1#c','https://example.com/?a@b']) assert.equal(isSafeHttps(url), true);
  assert.match(fs.readFileSync(path.join(__dirname,'blocks.js'),'utf8'), /case 'link':[\s\S]*?if \(!isSafeHttps\(b.url\)\)/);
});
test('limits at and beyond boundaries', () => {
  const repeated = (n, v) => Array.from({length:n}, () => v);
  assert.equal(LIMITS.bytes, 65536);
  for (const n of [50,51]) assert.equal(validate(docOf(...repeated(n, {type:'summary',text:'x'}))).ok, n === 50);
  for (const n of [12,13]) check({type:'table',columns:Array.from({length:n}, (_,i) => ({key:'c'+i,label:'C'})),rows:[]}, n === 12);
  for (const n of [200,201]) {
    check({type:'table',columns:[{key:'a',label:'A'}],rows:repeated(n,{a:1})}, n === 200);
    check({type:'kv',items:[{key:'A',value:'x'.repeat(n)}]}, n === 200);
    check({type:'chart',kind:'line',series:[{name:'A',points:repeated(n,[1,1])}]}, n === 200);
    check({type:'log',lines:repeated(n,'x')}, n === 200);
  }
  for (const n of [100,101]) check({type:'steps',items:repeated(n,{label:'A',state:'done'})},n === 100);
  for (const n of [50,51]) check({type:'kv',items:repeated(n,{key:'A',value:null})},n === 50);
  for (const n of [4,5]) check({type:'chart',kind:'bar',series:repeated(n,{name:'A',points:[]})},n === 4);
  for (const n of [500,501]) check({type:'log',lines:['x'.repeat(n)]},n === 500);
  for (const n of [2000,2001]) check({type:'summary',text:'x'.repeat(n)},n === 2000);
  assert.equal(validate(docOf(...repeated(40,{type:'summary',text:'x'.repeat(2000)}))).ok,false);
  // UTF-8 bytes, rather than the JS string length, enforce the document budget.
  assert.equal(validate(docOf(...repeated(12,{type:'summary',text:'界'.repeat(2000)}))).ok,false);
  check({type:'log',lines:['a\tb']}); check({type:'log',lines:['a\nb']},false); check({type:'log',lines:['a\n']},false);
  check({type:'summary',text:'a\nb'}); check({type:'summary',text:'a\u0007'},false);
  check({type:'summary',text:'😀'.repeat(2000)});
  check({type:'progress',label:'A',done:0,total:0},false);
  check({type:'progress',label:'A',done:-1,total:1},false);
  check({type:'summary',text:'A',tone:'needs-you'},false);
  check({text:'A'},false); check({type:'summary',text:'A',extra:1},false);
  check({type:'future-type',extra:{anything:true}});
  for (const type of ['', 'A', 'a_b', 'a'.repeat(33)]) check({type},false);
  assert.equal(validate({...docOf(),from:'check'}).ok,false);
  assert.equal(validate({...docOf(),schema:'orch.blocks/2'}).ok,false);
  assert.equal(validate({...docOf(),extra:1}).ok,false);
});
test('nested schema rules and cell types', () => {
  for (const b of [
    {type:'steps',items:[{label:'A',state:'done',extra:1}]}, {type:'steps',items:[]},
    {type:'kv',items:[{key:'A',value:true}]}, {type:'kv',items:[]},
    {type:'table',columns:[{key:'bad-key',label:'A'}],rows:[]},
    {type:'table',columns:[{key:'a',label:'A',extra:1}],rows:[]},
    {type:'table',columns:[{key:'a',label:'A'}],rows:[{'bad-key':1}]},
    {type:'table',columns:[{key:'a',label:'A'}],rows:[Object.fromEntries(Array.from({length:13},(_,i)=>['c'+i,1]))]},
    {type:'chart',kind:'line',series:[{name:'A',points:[[1]]}]},
    {type:'chart',kind:'line',series:[{name:'A',points:[[1,2,3]]}]},
    {type:'chart',kind:'line',series:[{name:'A',points:[[1,true]]}]},
    {type:'chart',kind:'line',series:[{name:'A',points:[],extra:1}]},
    {type:'stat',label:'A',value:Infinity}, {type:'file',path:'a',size:1.5}
  ]) check(b,false);
});
test('workspace path rules', () => {
  for (const p of ['/etc/passwd','C:\\x','C:/x','a\\b','../x','a/../x','.env','app/.env','.git/config','.orch/secrets',
    '.orch/tickets/t_inv7c2/artifacts/../../x','a/./b']) check({type:'file',path:p},false);
  for (const p of ['.orch/tickets/t_inv7c2/artifacts/invoices.csv','reports/chart.png','a/b c.txt']) check({type:'file',path:p});
});
test('line charts split gaps and handle single, equal and extreme values', () => {
  for (const points of [[], [[1,1]], [[1,1],[1,1]], [[-1e308,-1e308],[1e308,1e308]], [['a',1],['b',null],['c',3]]]) {
    const el = draw(docOf({type:'chart',kind:'line',series:[{name:'A',points}]})).el;
    assertNoJunk(el);
    if (points.length === 3) assert.equal(findAll(el, tag('polyline')).length,2);
  }
  const el = draw(docOf({type:'chart',kind:'line',series:[{name:'A',points:[[0,0],[1,1],[10,2]]}]})).el;
  assert.match(find(el, tag('polyline')).getAttribute('points'), /34\.80,/);
});
test('empty tables, missing cells, durations and totals', () => {
  const empty = draw(fixture('empty-table')).el;
  assert.equal(textOf(find(empty, cls('b-empty'))),'Nothing to show');
  const el = draw(docOf({type:'table',title:'Times',columns:[{key:'a',label:'A',kind:'duration'}],rows:[{a:125},{a:3},{}],total_rows:10})).el;
  for (const s of ['2 min 5 s','3 s','–','First 3 of 10']) assert.ok(textOf(el).includes(s));
});
test('invalid raw JSON is bounded and input is never mutated', () => {
  const doc = {schema:'wrong',text:'x'.repeat(5000)};
  const el = draw(doc).el;
  assert.ok(textOf(find(el,tag('pre'))).length <= 4000);
  for (const c of Object.values(fixtures)) {
    const before = JSON.parse(JSON.stringify(c.doc)); draw(c.doc,{fileUrl:()=>null}); assert.deepEqual(c.doc,before);
  }
});
test('source guard and byte-identical kit copies', () => {
  const source = fs.readFileSync(path.join(__dirname,'blocks.js'),'utf8');
  assert.doesNotMatch(source,/innerHTML|insertAdjacentHTML|outerHTML|document\.write|eval\s*\(|new Function/);
  const root = path.resolve(__dirname,'../../../../../..');
  for (const name of ['blocks.js','blocks.css']) assert.deepEqual(fs.readFileSync(path.join(__dirname,name)), fs.readFileSync(path.join(root,'workspace/src/orch_ui/static',name)));
});
test('demo data contains every valid fixture', () => {
  const vm = require('node:vm'), context = {window:{}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'blocks-demo-data.js'),'utf8'),context);
  const expected = Object.keys(fixtures).filter(n => n.startsWith('valid-')).sort();
  assert.deepEqual(Array.from(context.window.BLOCK_FIXTURES, f => f.name), expected);
});

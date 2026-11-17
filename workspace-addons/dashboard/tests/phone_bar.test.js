'use strict';
// ORCH-73 (owner 16 Nov): on a phone a bottom bar (Home, Tickets, Review with the one needs-you number, More) and the
// ticket list as grouped short rows. Both widgets live in the master kit (widgets.js / widgets.css), not in page CSS.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const STATIC = path.join(__dirname, '../../../workspace/src/orch_ui/static');
const helpers = require(path.join(WEB, 'helpers.js'));
const listSrc = fs.readFileSync(path.join(WEB, 'pages/tickets.js'), 'utf8');
const appSrc = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
const widgetsCss = fs.readFileSync(path.join(STATIC, 'widgets.css'), 'utf8');

// a small DOM: enough for UI.tabbar and UI.shortGroup
function fakeDom() {
  const node = tag => {
    const n = {tagName:tag.toUpperCase(), children:[], dataset:{}, className:'', attrs:{}, listeners:{}, _text:'',
      get textContent() { return this._text + this.children.map(c => c.textContent ?? c.text ?? '').join(''); },
      set textContent(v) { this._text = String(v); this.children = []; },
      append(...c) { this.children.push(...c); }, replaceChildren(...c) { this._text = ''; this.children = [...c]; },
      setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return this.attrs[k] ?? null; }, removeAttribute(k) { delete this.attrs[k]; },
      addEventListener(type, fn) { this.listeners[type] = fn; }, querySelectorAll() { return []; }, set innerHTML(v) { this._html = v; }};
    return n;
  };
  return {createElement:node, createElementNS:(ns, tag) => node(tag), createTextNode:text => ({text, textContent:text})};
}
function kit() {
  const c = vm.createContext({window:{}, document:fakeDom()});
  vm.runInContext(fs.readFileSync(path.join(STATIC, 'widgets.js'), 'utf8'), c);
  return c.window.UI;
}
const all = n => n && typeof n === 'object' ? [n, ...(n.children || []).flatMap(all)] : [];
const items = (review = 0) => [{key:'home', label:'Home', href:'#home', current:true}, {key:'tickets', label:'Tickets', href:'#tickets'},
  {key:'review', label:'Review', href:'#review', count:review, countLabel:review + ' need you'}, {key:'more', label:'More', expanded:false, controls:'side-menu'}];

test('UI.tabbar: four places, the current one marked, More is a menu button', () => {
  const UI = kit(), bar = UI.tabbar(items(), {id:'tabbar'});
  assert.equal(bar.className, 'tabbar');
  assert.equal(bar.attrs['aria-label'], 'Main');
  assert.deepEqual(bar.children.map(c => c.textContent), ['Home', 'Tickets', 'Review', 'More']);
  assert.equal(bar.children[0].attrs['aria-current'], 'page');
  assert.equal(bar.children[1].attrs['aria-current'], undefined);
  assert.equal(bar.children[3].tagName, 'BUTTON');
  assert.equal(bar.children[3].attrs['aria-expanded'], 'false');
  assert.equal(bar.children[3].attrs['aria-controls'], 'side-menu');
});

test('UI.tabbar: the needs-you number only on Review and only above 0; update() changes it in place', () => {
  const UI = kit(), bar = UI.tabbar(items(0));
  assert.ok(!all(bar).some(n => n.className === 'count'), 'no number when nothing waits');
  assert.equal(bar.children[2].attrs['aria-label'], 'Review');
  UI.tabbar.update(bar, items(3));
  const count = all(bar).filter(n => n.className === 'count');
  assert.equal(count.length, 1);
  assert.equal(count[0].textContent, '3');
  assert.equal(bar.children[2].attrs['aria-label'], 'Review, 3 need you');
  UI.tabbar.update(bar, [{key:'more', label:'More', expanded:true}]);
  assert.equal(bar.children[3].attrs['aria-expanded'], 'true');
});

test('UI.shortGroup: header with count, rows with number, title, fact and one side thing; folded shows no rows; more', () => {
  const UI = kit(), side = {tagName:'BUTTON', textContent:'Answer'};
  const open = UI.shortGroup({title:'Needs you', icon:'needs', count:1, rows:[{key:'WS-1', title:'Services', href:'#t/1', fact:'Question · 3 h ago', side}], more:{label:'2 more'}});
  assert.match(open.className, /short-group/);
  const rows = all(open).filter(n => /short-row/.test(n.className));
  assert.equal(rows.length, 1);
  assert.equal(all(rows[0]).find(n => n.className === 'short-title').textContent, 'WS-1 Services');
  assert.equal(all(rows[0]).find(n => n.className === 'short-fact').textContent, 'Question · 3 h ago');
  assert.ok(all(rows[0]).includes(side));
  assert.ok(all(open).some(n => n.textContent === '2 more'));
  const folded = UI.shortGroup({title:'Done', icon:'done', count:9, folded:true, rows:[{key:'WS-2', title:'x'}]});
  assert.equal(all(folded).filter(n => /short-row/.test(n.className)).length, 0);
  assert.equal(all(folded).find(n => n.tagName === 'BUTTON').attrs['aria-expanded'], 'false');
});

// the Tickets page: a phone-only list beside the wide-only table
const h = (tag, attrs = {}, ...kids) => ({tag, attrs, children:kids.flat(Infinity).filter(x => x != null && x !== false), setAttribute(k, v) { this.attrs[k] = v; }, addEventListener() {}, dataset:{}, append(...k) { this.children.push(...k); }});
function listCtx(list, extra = {}) {
  const groups = [];
  const UI = {shortGroup:o => { groups.push(o); return {o, querySelectorAll:() => [], querySelector:() => null}; }, statusIcon:n => h('svg', {className:'st ' + n})};
  const c = {h, window:{DashHelpers:helpers, UI}, array:v => Array.isArray(v) ? v : [], clean:String, questions:t => (t.questions || []).filter(q => q.answer == null),
    shown:t => t, chip:(t, cls) => h('span', {className:'chip ' + cls}, t), state:{runs:{}}, starting:new Set(), now:() => Date.now(),
    needsList:() => [], tickets:() => list, name:v => String(v || ''), location:{hash:'#tickets'}, snapshot:false, href:id => '#t/' + id, render(){},
    localStorage:{getItem:() => null}, changesPending:() => false,
    button:(label, cls, fn) => { const b = h('button', {className:'btn ' + cls}, label); b.onclick = fn; return b; }, ...extra};
  vm.createContext(c); vm.runInContext(listSrc, c);
  return {c, groups};
}
const text = n => !n ? '' : typeof n === 'string' || typeof n === 'number' ? String(n) : (n.children || []).map(text).join('');

test('phone list: groups as short rows, Answer where the person is needed, steps as n/m, the rest a fact', () => {
  const list = [
    {id:'q', key:'WS-1', title:'Services', status:'waiting', questions:[{id:'q1', text:'Start?'}], updated_at:new Date().toISOString()},
    {id:'a', key:'WS-2', title:'Count', status:'active', checklist:[{done:true}, {}, {}], updated_at:new Date().toISOString()},
    {id:'o', key:'WS-3', title:'Later', status:'open'},
  ];
  const {c, groups} = listCtx(list);
  const out = c.phoneList(list);
  assert.match(out.attrs.className, /phone-only/);
  assert.deepEqual(groups.map(g => g.title), ['Needs you', 'Working', 'To do']);
  const need = groups[0].rows[0];
  assert.equal(need.key, 'WS-1');
  assert.match(need.fact, /^Question/);
  assert.equal(text(need.side), 'Answer');
  assert.equal(groups[1].icon, 'working');
  assert.equal(text(groups[1].rows[0].side), '1/3');
  assert.equal(groups[2].rows[0].side, null, 'no steps: nothing on the right');
});

test('phone list: a long group shows 5 rows and "n more"; a folded group no rows', () => {
  const list = Array.from({length:8}, (_, i) => ({id:'o' + i, key:'WS-' + i, title:'T' + i, status:'open'}));
  const {c, groups} = listCtx(list);
  c.phoneList(list);
  assert.equal(groups[0].rows.length, 5);
  assert.equal(groups[0].more.label, '3 more');
  vm.runInContext("foldedGroups.add('open')", c);
  groups.length = 0;
  c.phoneList(list);
  assert.equal(groups[0].folded, true);
});

test('the table and the List/Board switch are wide-only; the phone list rides along in list and board view', () => {
  assert.match(listSrc, /className:'table-wrap wide-only'/);
  assert.match(listSrc, /className:'view-toggle wide-only'/);
  assert.match(listSrc, /fragment\(ticketTable\(visible\), window\.UI\?\.shortGroup \? phoneList\(visible\) : null\)/);
  assert.match(listSrc, /className:'wide-only', 'data-key':'board-wide'/);
});

test('the shell paints the bottom bar with the needs-you number on Review and More opening the side menu', () => {
  assert.match(appSrc, /paintTabbar\(here, needCount, needsWords\)/);
  assert.match(appSrc, /key:'review', label:'Review', href:'#review', current:here === '#review', count:needCount/);
  assert.match(appSrc, /key:'more', label:'More'.*onClick:\(\) => setMenu\(/);
  assert.match(appSrc, /document\.body\.append\(bar\)/, 'the bar is a direct child of body (the master CSS keys on body:has(>.tabbar))');
});

test('the look is in the master, not in a page stylesheet', () => {
  assert.match(widgetsCss, /\.tabbar\{display:none\}/);
  assert.match(widgetsCss, /@media\(max-width:720px\)\{\s*\.tabbar\{display:grid/);
  assert.match(widgetsCss, /\.short-row\{/);
  assert.match(widgetsCss, /@media\(min-width:721px\)\{\.phone-only\{display:none!important\}\}/);
  for (const f of fs.readdirSync(path.join(WEB, 'pages')).filter(f => f.endsWith('.css')).concat(['../style.css'])) {
    assert.doesNotMatch(fs.readFileSync(path.join(WEB, 'pages', f), 'utf8'), /\.tabbar|\.short-row|\.short-group/, f);
  }
  const gallery = fs.readFileSync(path.join(STATIC, 'gallery.html'), 'utf8');
  assert.match(gallery, /id="w-tabbar"/);
  assert.match(gallery, /id="w-short"/);
});

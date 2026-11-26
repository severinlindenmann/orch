'use strict';
// ORCH-338: the layer of the new live page (pages/live-layer.js). The model is plain data: where the layer sits, where
// it opens again, what Esc does, the size limits and what is kept per browser. ORCH-339: the split into 1, 2 or 3 panes.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/live-layer.js'), 'utf8');
const model = source.slice(0, source.indexOf('// --- the page ---'));
function load() {
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(model + '\nthis.api = {liveBesideNote, liveBesideHidden, liveLayerFresh, liveLayerRead, liveLayerWrite, liveLayerWhere, liveLayerStep, liveLayerNarrow, liveLayerTight, liveLayerCompact, liveLayerCrowded, liveLayerSort, liveAskModel, liveLayerHelper, liveFoldRead, LIVE_FOLD_KEY, LIVE_LAYER_KEY, LIVE_MAX, liveLayerFit, liveLayerRightMax, liveLayerFirstPlace, liveAskWhy, liveLayerBottomCap, liveTreeLeaves, liveTreeSplit, liveTreeDrop, liveTreeSize, liveTreeEqual, liveTreeOk, liveTreeAt, liveLayerRailWanted};', ctx);
  return ctx.api;
}
const L = load();
const store = (init = {}) => { const m = new Map(Object.entries(init)); return {getItem: k => m.has(k) ? m.get(k) : null, setItem: (k, v) => m.set(k, v), m}; };
const run = (s, acts, phone = false) => acts.reduce((x, a) => L.liveLayerStep(x, a, phone), s);

test('a new browser starts with only the bar; opening a session puts it at the bottom', () => {
  const s = L.liveLayerFresh();
  assert.equal(s.mode, 'bar');
  const o = L.liveLayerStep(s, {type:'open', key:'t_1'});
  assert.equal(o.mode, 'bottom');
  assert.deepEqual([...o.panes], ['t_1']);
  assert.equal(s.mode, 'bar', 'the step never changes the model it got');
});

test('bottom, right and full screen; leaving full screen goes back to where it was', () => {
  let s = run(L.liveLayerFresh(), [{type:'open', key:'t_1'}, {type:'place', mode:'right'}]);
  assert.equal(s.mode, 'right');
  assert.equal(s.last, 'right');
  s = L.liveLayerStep(s, {type:'place', mode:'full'});
  assert.equal(s.mode, 'full');
  s = L.liveLayerStep(s, {type:'leave-full'});
  assert.equal(s.mode, 'right');
  s = run(s, [{type:'place', mode:'bottom'}, {type:'place', mode:'full'}, {type:'leave-full'}]);
  assert.equal(s.mode, 'bottom');
});

test('minimise leaves the bar, closed to the side leaves the edge; both open again where it was last', () => {
  let s = run(L.liveLayerFresh(), [{type:'open', key:'t_1'}, {type:'place', mode:'right'}, {type:'min'}]);
  assert.equal(s.mode, 'bar');
  assert.equal(L.liveLayerStep(s, {type:'reopen'}).mode, 'right');
  s = run(s, [{type:'reopen'}, {type:'place', mode:'side'}]);
  assert.equal(s.mode, 'side');
  assert.equal(L.liveLayerStep(s, {type:'reopen'}).mode, 'right');
  s = run(s, [{type:'reopen'}, {type:'place', mode:'full'}, {type:'min'}, {type:'reopen'}]);
  assert.equal(s.mode, 'right', 'minimised from full screen it opens docked, not full');
  assert.equal(L.liveLayerStep(s, {type:'open', key:'t_2'}).mode, 'right', 'opening another session keeps the place');
});

test('Open ticket steps a bottom or full screen layer down to the bar and leaves a docked one (ORCH-676)', () => {
  const open = L.liveLayerStep(L.liveLayerFresh(), {type:'open', key:'t_1'});
  assert.equal(open.mode, 'bottom');
  assert.equal(L.liveLayerStep(open, {type:'to-ticket'}).mode, 'bar', 'the bottom panel gets out of the way');
  const full = L.liveLayerStep(open, {type:'place', mode:'full'});
  assert.equal(L.liveLayerStep(full, {type:'to-ticket'}).mode, 'bar');
  assert.equal(L.liveLayerStep(L.liveLayerStep(full, {type:'to-ticket'}), {type:'reopen'}).mode, 'bottom', 'it opens again where it was');
  const right = L.liveLayerStep(open, {type:'place', mode:'right'});
  assert.equal(L.liveLayerStep(right, {type:'to-ticket'}), right, 'docked beside the page it covers nothing');
  const bar = L.liveLayerFresh();
  assert.equal(L.liveLayerStep(bar, {type:'to-ticket'}), bar);
});

test('closing the last session keeps the bar (or the edge) and forgets the session', () => {
  let s = run(L.liveLayerFresh(), [{type:'open', key:'t_1'}, {type:'close', key:'t_1'}]);
  assert.equal(s.mode, 'bar');
  assert.deepEqual([...s.panes], []);
  assert.equal(L.liveLayerStep(s, {type:'reopen'}), s, 'nothing to open again');
  assert.equal(L.liveLayerStep(s, {type:'place', mode:'full'}), s, 'no full screen without a session');
});

test('Esc goes one step back: the menu, then full screen, then the panel to the bar (only from inside it)', () => {
  let s = run(L.liveLayerFresh(), [{type:'open', key:'t_1'}, {type:'place', mode:'right'}, {type:'place', mode:'full'}, {type:'menu', menu:'bar'}]);
  assert.equal(s.menu, 'bar');
  s = L.liveLayerStep(s, {type:'escape'});
  assert.equal(s.menu, '');
  assert.equal(s.mode, 'full');
  s = L.liveLayerStep(s, {type:'escape'});
  assert.equal(s.mode, 'right');
  assert.equal(L.liveLayerStep(s, {type:'escape', inside:false}), s, 'Esc on the page behind leaves the panel open');
  s = L.liveLayerStep(s, {type:'escape', inside:true});
  assert.equal(s.mode, 'bar');
  assert.equal(L.liveLayerStep(s, {type:'escape', inside:true}), s, 'the bar is the last step');
});

test('on a phone the right edge falls back to the bottom and right is never kept as the last place', () => {
  let s = run(L.liveLayerFresh(), [{type:'open', key:'t_1'}, {type:'place', mode:'right'}]);
  assert.equal(L.liveLayerWhere(s, true), 'bottom');
  assert.equal(L.liveLayerWhere(s, false), 'right');
  const p = run(L.liveLayerFresh(), [{type:'open', key:'t_1'}, {type:'place', mode:'right'}], true);
  assert.equal(p.mode, 'bottom');
  assert.equal(p.last, 'bottom');
  s = run(s, [{type:'min'}, {type:'reopen'}], true);
  assert.equal(s.mode, 'bottom');
});

test('the size stays between the smallest panel and a share of the window', () => {
  const s = run(L.liveLayerFresh(), [{type:'open', key:'t_1'}]);
  assert.equal(L.liveLayerStep(s, {type:'size', dim:'height', px:50, room:800}).height, 200);
  assert.equal(L.liveLayerStep(s, {type:'size', dim:'height', px:5000, room:800}).height, 680);
  assert.equal(L.liveLayerStep(s, {type:'size', dim:'height', px:420.4, room:800}).height, 420);
  assert.equal(L.liveLayerStep(s, {type:'size', dim:'width', px:100, room:1280}).width, 320);
  assert.equal(L.liveLayerStep(s, {type:'size', dim:'width', px:2000, room:1280}).width, 896);
});

test('place and size are kept per browser; full screen too (ORCH-1661), and Esc still goes back to where it was; bad data is ignored', () => {
  const st = store();
  let s = run(L.liveLayerFresh(), [{type:'open', key:'t_1'}, {type:'place', mode:'right'}, {type:'size', dim:'width', px:600, room:1920}, {type:'size', dim:'height', px:400, room:1080}, {type:'place', mode:'full'}]);
  L.liveLayerWrite(st, s);
  const full = L.liveLayerRead(st);
  assert.equal(full.mode, 'full', 'full screen is kept after a reload');
  assert.equal(L.liveLayerStep(full, {type:'escape', inside:true}).mode, 'right', 'Esc goes back to the right, where it was');
  s = run(s, [{type:'leave-full'}]);
  L.liveLayerWrite(st, s);
  const back = L.liveLayerRead(st);
  assert.equal(back.mode, 'right');
  assert.equal(back.last, 'right');
  assert.equal(back.width, 600);
  assert.equal(back.height, 400);
  assert.deepEqual([...back.panes], ['t_1']);
  assert.equal(back.menu, '');
  for (const raw of ['{', 'null', '7', JSON.stringify({mode:'nowhere', last:'up', width:-3, panes:['../x', 5]})]) {
    const r = L.liveLayerRead(store({[L.LIVE_LAYER_KEY]:raw}));
    assert.equal(r.mode, 'bar', raw);
    assert.equal(r.last, 'bottom', raw);
    assert.equal(r.width, null, raw);
    assert.deepEqual([...r.panes], [], raw);
  }
  assert.equal(L.liveLayerRead(store({[L.LIVE_LAYER_KEY]:JSON.stringify({mode:'bottom', panes:[]})})).mode, 'bar', 'no session: only the bar');
  assert.equal(L.liveLayerRead(null).mode, 'bar', 'no storage (private window)');
  assert.doesNotThrow(() => L.liveLayerWrite({setItem() { throw new Error('full'); }}, s));
});

test('Add beside (a wall tile) splits right of the selected pane up to four; the new pane is selected', () => {
  let s = run(L.liveLayerFresh(), [{type:'open', key:'t_1'}, {type:'beside', key:'t_2'}]);
  assert.deepEqual([...s.panes], ['t_1', 't_2']);
  assert.equal(s.cur, 't_2');
  assert.equal(s.mode, 'bottom');
  s = run(s, [{type:'beside', key:'t_3'}, {type:'beside', key:'t_4'}]);
  assert.deepEqual([...s.panes], ['t_1', 't_2', 't_3', 't_4']);
  assert.equal(L.LIVE_MAX, 4);
  s = L.liveLayerStep(s, {type:'beside', key:'t_5'});
  assert.deepEqual([...s.panes], ['t_1', 't_2', 't_3', 't_5'], 'a fifth takes the last pane');
  assert.deepEqual([...L.liveLayerStep(s, {type:'beside', key:'t_1'}).panes], ['t_1', 't_2', 't_3', 't_5'], 'a shown session is only selected');
  assert.equal(L.liveLayerStep(s, {type:'beside', key:'t_1'}).cur, 't_1');
  assert.equal(L.liveLayerStep(s, {type:'beside'}), s, 'nothing to add');
  const min = run(s, [{type:'min'}, {type:'close', key:'t_5'}, {type:'beside', key:'t_9'}]);
  assert.equal(min.mode, 'bottom', 'Add beside from the bar opens the layer again');
  assert.deepEqual([...min.panes], ['t_1', 't_2', 't_3', 't_9'], 'the split stays when it opens again');
});

test('ORCH-2200: split any pane right or down; dividers share the room; closing gives it back; panes keep their place', () => {
  let s = run(L.liveLayerFresh(), [{type:'open', key:'chat'}, {type:'split', at:'chat', dir:'right', key:'term'}, {type:'split', at:'term', dir:'down', key:'mgr'}]);
  assert.deepEqual(JSON.parse(JSON.stringify(s.tree)), {d:'row', k:['chat', {d:'col', k:['term', 'mgr'], z:[0.5, 0.5]}], z:[0.5, 0.5]}, 'Z1680: helper left, terminal and Manager stacked right');
  assert.deepEqual([...s.panes], ['chat', 'term', 'mgr']);
  assert.equal(s.cur, 'mgr', 'the new pane is selected');
  assert.equal(L.liveLayerStep(s, {type:'split', at:'chat', dir:'down', key:'term'}), s, 'a shown session is not shown twice');
  assert.equal(L.liveLayerStep(s, {type:'split', at:'nope', dir:'down', key:'x'}), s, 'only from a shown pane');
  s = L.liveLayerStep(s, {type:'resize', path:'', i:0, share:0.62});
  assert.deepEqual([...s.tree.z], [0.62, 0.38]);
  assert.deepEqual([...L.liveLayerStep(s, {type:'resize', path:'', i:0, share:0.99}).tree.z], [0.85, 0.15], 'a pane keeps at least 15 %');
  s = L.liveLayerStep(s, {type:'resize', path:'1', i:0, share:0.3});
  assert.deepEqual([...s.tree.k[1].z], [0.3, 0.7]);
  assert.deepEqual([...L.liveLayerStep(s, {type:'equal', path:'1'}).tree.k[1].z], [0.5, 0.5], 'double click: equal');
  const swapped = L.liveLayerStep(s, {type:'swap', from:'term', key:'t_9'});
  assert.equal(swapped.tree.k[1].k[0], 't_9', 'another session in a pane takes the same place');
  const opened = run(s, [{type:'select', key:'term'}, {type:'open', key:'t_7'}]);
  assert.deepEqual([...opened.panes], ['chat', 't_7', 'mgr'], 'open from the bar takes the selected pane in place');
  const closed = L.liveLayerStep(s, {type:'close', key:'term'});
  assert.deepEqual(JSON.parse(JSON.stringify(closed.tree)), {d:'row', k:['chat', 'mgr'], z:[0.62, 0.38]}, 'its split folds into the neighbour');
  const st = store();
  L.liveLayerWrite(st, s);
  assert.deepEqual(JSON.parse(JSON.stringify(L.liveLayerRead(st).tree)), JSON.parse(JSON.stringify(s.tree)), 'the layout survives a reload');
  assert.equal(L.liveTreeOk({d:'row', k:['a', 'a', 'bad key'], z:[1, 1, 1]}), 'a', 'a stored tree is made safe');
  assert.equal(L.liveTreeOk({d:'diag', k:['a', 'b']}), null);
});

test('ORCH-2200: splitting right again in a row gives the new pane an equal slice (four panes stay readable)', () => {
  const s = run(L.liveLayerFresh(), [{type:'open', key:'a'}, ...['b', 'c', 'd'].map((k, i) => ({type:'split', at:['a', 'b', 'c'][i], dir:'right', key:k}))]);
  assert.deepEqual([...s.panes], ['a', 'b', 'c', 'd']);
  assert.deepEqual([...s.tree.z], [0.25, 0.25, 0.25, 0.25]);
  const t = L.liveLayerStep(s, {type:'close', key:'b'});
  assert.deepEqual([...L.liveLayerStep(t, {type:'split', at:'a', dir:'right', key:'b'}).tree.z], [0.25, 0.25, 0.25, 0.25]);
});

test('ORCH-2200: panes stay where the person put them when a status or a pin changes (no sorting by the bar)', () => {
  assert.doesNotMatch(source.slice(source.indexOf('function liveLayerDo('), source.indexOf('// After Add beside')), /liveLayerSort\(/);
  assert.doesNotMatch(source.slice(source.indexOf("window.addEventListener('orch:live-pins'"), source.indexOf('// Renaming a session')), /liveLayerSort\(/);
});

test('opening a session from the bar selects it when shown, else it takes the selected pane', () => {
  let s = run(L.liveLayerFresh(), [{type:'open', key:'t_1'}, {type:'beside', key:'t_2'}, {type:'beside', key:'t_3'}, {type:'select', key:'t_2'}]);
  assert.equal(s.cur, 't_2');
  assert.equal(L.liveLayerStep(s, {type:'select', key:'t_2'}), s);
  assert.equal(L.liveLayerStep(s, {type:'select', key:'t_8'}), s, 'only a shown pane can be selected');
  const shown = L.liveLayerStep(s, {type:'open', key:'t_3'});
  assert.deepEqual([...shown.panes], ['t_1', 't_2', 't_3']);
  assert.equal(shown.cur, 't_3');
  const other = L.liveLayerStep(s, {type:'open', key:'t_7'});
  assert.deepEqual([...other.panes], ['t_1', 't_7', 't_3']);
  assert.equal(other.cur, 't_7');
});

test('closing a pane gives its room to the others and selects its neighbour; the last one leaves the bar', () => {
  let s = run(L.liveLayerFresh(), [{type:'open', key:'t_1'}, {type:'beside', key:'t_2'}, {type:'beside', key:'t_3'}, {type:'select', key:'t_2'}]);
  s = L.liveLayerStep(s, {type:'close', key:'t_2'});
  assert.deepEqual([...s.panes], ['t_1', 't_3']);
  assert.equal(s.cur, 't_3');
  assert.equal(s.mode, 'bottom');
  s = L.liveLayerStep(s, {type:'close', key:'t_1'});
  assert.deepEqual([...s.panes], ['t_3']);
  assert.equal(s.cur, 't_3');
  assert.equal(L.liveLayerStep(s, {type:'close', key:'t_x'}), s, 'an unknown pane changes nothing');
  s = L.liveLayerStep(s, {type:'close', key:'t_3'});
  assert.equal(s.mode, 'bar');
  assert.equal(s.cur, '');
});

test('the split and the selected pane are kept per browser, at most four', () => {
  const st = store();
  const s = run(L.liveLayerFresh(), [{type:'open', key:'t_1'}, {type:'beside', key:'t_2'}, {type:'select', key:'t_1'}]);
  L.liveLayerWrite(st, s);
  const back = L.liveLayerRead(st);
  assert.deepEqual([...back.panes], ['t_1', 't_2']);
  assert.equal(back.cur, 't_1');
  const many = L.liveLayerRead(store({[L.LIVE_LAYER_KEY]:JSON.stringify({mode:'bottom', panes:['a', 'a', 'b', 'c', 'd', 'e'], cur:'zz'})}));
  assert.deepEqual([...many.panes], ['a', 'b', 'c', 'd'], 'twice is once, five is four');
  assert.equal(many.cur, 'a', 'an unknown selection falls back to the first pane');
});

test('panes fold pin and place into More when narrow, on the right with more than one, and on a phone', () => {
  assert.equal(L.liveLayerNarrow('bottom', 1, 1040, false), false);
  assert.equal(L.liveLayerNarrow('bottom', 2, 1040, false), true);   // two at 1280 wide: the header with Chat | Terminal does not fit
  assert.equal(L.liveLayerNarrow('bottom', 2, 1680, false), false);
  assert.equal(L.liveLayerNarrow('bottom', 3, 1040, false), true);
  assert.equal(L.liveLayerNarrow('bottom', 3, 1680, false), true);   // three at 1920 wide: 560 px each
  assert.equal(L.liveLayerNarrow('bottom', 3, 2400, false), false);
  assert.equal(L.liveLayerNarrow('right', 2, 760, false), true);
  assert.equal(L.liveLayerNarrow('right', 1, 760, false), false);
  assert.equal(L.liveLayerNarrow('right', 1, 537, false), true);    // on the right at 1280 wide
  assert.equal(L.liveLayerNarrow('bottom', 1, 390, true), true);
});

test('pin and place stay in the header down to about 400 px a pane, as in draft D (ORCH-1568)', () => {
  assert.equal(L.liveLayerTight('bottom', 2, 1040, false), false);  // two at 1280 wide: 520 px each
  assert.equal(L.liveLayerTight('right', 1, 537, false), false);    // one on the right at 1280 wide
  assert.equal(L.liveLayerTight('bottom', 3, 1040, false), true);   // three at 1280 wide: under 400 px each
  assert.equal(L.liveLayerTight('bottom', 3, 1680, false), false);  // three at 1920 wide
  assert.equal(L.liveLayerTight('right', 2, 760, false), true);     // stacked on the right
  assert.equal(L.liveLayerTight('bottom', 1, 390, true), true);     // a phone
});

test('panes sit in the order of the bar; a session not in the bar stays last', () => {
  const s = run(L.liveLayerFresh(), [{type:'open', key:'t_3'}, {type:'beside', key:'t_x'}, {type:'beside', key:'t_1'}]);
  const sorted = L.liveLayerSort(s, ['t_1', 't_2', 't_3']);
  assert.deepEqual([...sorted.panes], ['t_1', 't_3', 't_x']);
  assert.equal(sorted.cur, 't_1', 'the selection stays on its session');
  assert.equal(L.liveLayerSort(sorted, ['t_1', 't_2', 't_3']), sorted, 'already in order: the same model');
});

test('the layer names no add-on and builds no inline style', () => {
  const plain = source.replace(/\.focus\(/g, '.(');
  assert.doesNotMatch(plain, /\b(focus|automation|scheduler|publish|wiki)\b/i);
  assert.doesNotMatch(source, /setAttribute\(\s*['"]style/);
});

test('the dock goes inside the mount that survives a page change (#keep), else right after main', () => {
  const body = source.slice(source.indexOf('function liveDockHost() {'), source.indexOf('function liveLayerDo('));
  const node = (id, parent = null) => ({id, parentNode:parent, get isConnected() { return !!this.parentNode; }, className:'',
    append(c) { c.parentNode = this; }, after(c) { c.parentNode = this.parentNode; }});
  const run = withKeep => {
    const shellBody = node('shell-body'), main = node('content', shellBody), keep = withKeep ? node('keep', shellBody) : null, made = [];
    const document = {getElementById: id => id === 'content' ? main : id === 'keep' ? keep : made.find(n => n.id === id) || null,
      createElement: () => { const n = node(''); made.push(n); return n; }};
    const ctx = {document, window:{}};
    vm.createContext(ctx); vm.runInContext(body, ctx);
    const host = ctx.liveDockHost();
    assert.equal(ctx.liveDockHost(), host, 'one dock, never a second element');
    return {host, keep, shellBody};
  };
  const a = run(true);
  assert.equal(a.host.parentNode, a.keep);
  assert.equal(a.host.className, 'live-dock');
  const b = run(false);
  assert.equal(b.host.parentNode, b.shellBody);
});

// ORCH-340 review: the page side of the layer.
const page = source.slice(source.indexOf('// --- the page ---'));
test('full screen makes the page behind inert and undoes only what it set', () => {
  const el = (id, opts = {}) => ({id, inert: !!opts.inert, dataset:{}, attrs:new Set(), sel:opts.sel || '',
    contains: n => n === el.dock && !!opts.holdsDock, matches: q => !!opts.sel && q.split(', ').includes(opts.sel),
    hasAttribute(a) { return a === 'data-live-inert' && 'liveInert' in this.dataset; }});
  el.dock = {id:'live-dock'};
  const kids = [el('shell', {holdsDock:true}), el('side'), el('main'), el('d', {sel:'dialog'}), el('toast', {sel:'[aria-live]'}), el('was', {inert:true})];
  const ctx = {document:{getElementById: id => (id === 'live-dock' ? el.dock : null), querySelectorAll: () => kids}};
  vm.createContext(ctx);
  vm.runInContext(page.slice(page.indexOf('function liveLayerInert'), page.indexOf('function liveLayerPad')) + '\nthis.f = liveLayerInert;', ctx);
  ctx.f(true);
  assert.deepEqual(kids.filter(k => k.inert).map(k => k.id), ['side', 'main', 'was']);
  ctx.f(false);
  assert.deepEqual(kids.filter(k => k.inert).map(k => k.id), ['was'], 'what was inert before stays so');
  assert.match(page, /liveLayerInert\(where === 'full'\)/);
  assert.match(page, /function liveLayerOff\(\) \{\n {2}liveLayerInert\(false\);/);
});

test('a drag ends when the grip loses the pointer (a repaint mid-drag), and keeps the size once', () => {
  assert.match(page, /\['pointerup', 'pointercancel', 'lostpointercapture'\]/);
  assert.match(page, /if \(done\) return;/);
});

test('a window resize draws the layer again only across the phone width or the crowded width (ORCH-1600)', () => {
  assert.doesNotMatch(page, /addEventListener\('resize', \(\) => \{ if \(document\.getElementById\('live-dock'\)\) \{ liveLayerPainted = ''/);
  assert.match(page, /if \(now !== phone \|\| wide !== crowd\)/);
});

// ORCH-463: words on the pane buttons, full titles in the split, Add beside asks which session.
test('a split, narrow or small pane is compact: its title gets a row of its own', () => {
  assert.equal(L.liveLayerCompact('bottom', 1, 1680, false), false, 'one roomy pane: one row');
  assert.equal(L.liveLayerCompact('bottom', 1, 1040, false), true, 'one pane at 1280 wide: the title gets its row');
  assert.equal(L.liveLayerCompact('bottom', 2, 1280, false), true, 'every split');
  assert.equal(L.liveLayerCompact('bottom', 1, 800, false), true, 'a small single pane');
  assert.equal(L.liveLayerCompact('bottom', 1, 390, true), true, 'a phone');
});

test('ORCH-2199 (owner pick G a): full screen, split, pin and close are visible; More keeps Stop, End, History and the place', () => {
  const pane = source.slice(source.indexOf('function livePane('), source.indexOf('// The live part of a pane'));
  for (const w of ['Full screen', 'Split right', 'Split down', 'Pin', 'Leave full screen', 'Close', 'More']) assert.match(pane, new RegExp(`'${w}'`), w);
  const more = source.slice(source.indexOf('function liveMoreMenu('), source.indexOf('// The status pill of a pane'));
  for (const w of ['At the bottom', 'On the right', 'Bar only', 'Closed to the side']) assert.match(more, new RegExp(`'${w}'`), w);
  assert.match(more, /liveMoreEnd\(key\)/, 'Stop and End session');
  assert.match(more, /liveHistMenuItem\(key\)/, 'History');
  assert.doesNotMatch(more, /'Open ticket'/, 'Open ticket moved to the status popover');
  assert.match(more, /'data-fold-item':''/, 'pin and split come into More only in a narrow pane');
  assert.match(pane, /'data-key':'live-pin', 'data-fold':''/);
  assert.doesNotMatch(pane, /liveHistButton|liveModelRow|livePermPaneRow/, 'no row above the screen, no History word');
  assert.doesNotMatch(pane, /liveBtn\('btn icon/, 'no icon-only button left in a pane');
  assert.match(pane, /'data-key':'live-split-' \+ dir, 'data-fold':''/, 'ORCH-2200: split right and split down, folded into More when narrow');
  assert.match(source, /act === 'beside-pick'\) liveLayerDo\(\{type:'beside', key:b\.dataset\.session\}/);
  assert.doesNotMatch(source, /act === 'beside'\)/, 'no click adds a session unasked');
  const menu = source.slice(source.indexOf('function liveBesideMenu('), source.indexOf('// The More menu'));
  assert.match(menu, /'data-live':'beside-pick'/);
  assert.match(menu, /others\.map\(/);
});

test('a button with a word is named by the word unless its label starts with it', () => {
  const body = source.slice(source.indexOf('function liveBtn('), source.indexOf('// A pane\'s button'));
  const ctx = {h:(tag, attrs) => attrs, liveIc:() => null};
  vm.createContext(ctx); vm.runInContext(body + '\nthis.f = liveBtn;', ctx);
  assert.equal(ctx.f('b', 'pin', 'Pin ORCH-1', 'g', {}, 'Pin')['aria-label'], 'Pin ORCH-1');
  assert.equal(ctx.f('b', 'x', 'Where it sits', 'g', {}, 'Bottom')['aria-label'], null);
  assert.equal(ctx.f('b', 'x', 'Where it sits', 'g')['aria-label'], 'Where it sits');
});

test('ORCH-817, ORCH-1616: every pane has Stop and End session in its More menu; the old body Stop is gone', () => {
  assert.doesNotMatch(source, /data-live-stop/);
  assert.match(source, /\.\.\.\(sess \? liveEndHere\(key, label\) : \[\]\)/);
  assert.match(source, /\[window\.liveEndOpenAt\?\.\('pane'\) === key \? window\.liveEndMenu\(key, 'pane:' \+ key\) : null\]/);
  assert.match(source, /sess && typeof window\.liveEndMenu === 'function' \? liveMoreEnd\(key\) : null/);
  assert.match(source, /typeof window\.liveEndKey === 'function' \? window\.liveEndKey\(\) : null\]\);/, 'the dock repaints when a Stop or End menu opens');
});

test('ORCH-817: an ended helper without a ticket keeps its pane with Start again and History; an ended terminal does not', () => {
  assert.match(source, /o\.open === true \|\| o\.kind !== 'terminal'/);
  assert.match(source, /ended:!running && x\.kind !== 'terminal' && \(x\.open !== true \|\| \(!!window\.LiveSessions\?\.ready && !live\)\)/);
  assert.match(source, /sess\?\.ended \? h\('div', \{className:'live-pb live-pb-start'\}, liveEndedBody\(sess, label\)\)/);
  assert.match(source, /liveStartAgain\(b\.dataset\.liveAgain, b\)/);
  assert.match(source, /act\('session\.new', \{kind\}, \{quiet:true\}\)/);
  assert.match(source, /liveHistBody\(sess\)/);
});

test('ORCH-817: a quiet helper pane has no notice and no status line; a stuck one gets the slim line (ORCH-2201)', () => {
  assert.match(source, /sess\.kind === 'terminal' \? null : h\('div', \{className:'live-end-idle', 'data-live-idle':''/);
  assert.match(source, /window\.liveEndIdleFill\(idle, body\.dataset\.liveBody\)/);
});

test('the pane shows the waiting question with its options and answers it there (ORCH-675)', () => {
  const {liveAskModel} = load();
  const t = {questions:[{id:'q1', answer:'x', text:'old'}, {id:'q2', digest:'d', text:'Which banner colour should I use?', options:['Blue', 'Green', '']}]};
  assert.deepEqual(JSON.parse(JSON.stringify(liveAskModel(t))), {id:'q2', digest:'d', text:'Which banner colour should I use?', options:['Blue', 'Green'], plain:true, suggest:'', because:''});
  assert.equal(liveAskModel({questions:[{id:'q1', answer:'x'}]}), null);
  assert.equal(liveAskModel({}), null);
  assert.equal(liveAskModel({questions:[{id:'q3', kind:'plan', text:'Plan?'}]}).plain, false);
  assert.match(source, /liveAskFill[^]*?act\('answer', \{ticket:id, question:q\.id, digest:q\.digest/, 'the answer is the same op a question card sends');
});

test('the waiting question shows once: the now line steps back while the question box shows it (ORCH-708)', () => {
  // ORCH-817 adds the idle note between the fill and the hide; the now line still steps back for the question box
  assert.match(source, /liveAskFill\(askBox, body\.dataset\.liveBody\);[^]{0,300}?now\.hidden = live\?\.status !== 'needs-you' \|\| \(!!askBox && !askBox\.hidden\)/,
    'the fill hides the now line after the question box is written');
});

test('after an answer in the pane the keyboard stays in the pane, so Esc still steps the layer back (ORCH-709)', () => {
  const fill = source.slice(source.indexOf('function liveAskFill'), source.indexOf('// The live part of a pane'));
  assert.match(fill, /const had = box\.contains\(document\.activeElement\) && !!box\.closest\('#live-dock'\);[^]*?liveLayerFill\(\);[^]*?if \(had\) \{ liveLayerWant = \{id, until:[^}]*ask:true\}; liveLayerTake\(\)/,
    'the question leaves and the keyboard goes back into the pane');
  const take = source.slice(source.indexOf('function liveLayerTake'), source.indexOf('// Full screen covers the page'));
  assert.match(take, /\[data-live-ask\]:not\(\[hidden\]\) :is\(button, input\):not\(:disabled\)/, 'the next question\'s first choice first');
});

// ORCH-706: a helper that waits for an OK on its screen shows its choice in the last lines; in a short pane (the panel
// at the bottom, a phone) the box was squeezed to two lines. It never shrinks below its lines (the API sends at most
// a few), the pane body scrolls instead.
test('the last-lines box never shrinks below its lines in a short pane', () => {
  const css = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/widgets.css'), 'utf8');
  const rule = (css.match(/(?:^|\n)\.live-lines\{([^}]*)\}/) || [])[1];
  assert.ok(rule, 'the .live-lines rule is in widgets.css');
  const flex = (rule.match(/(?:^|;)flex:([^;]*)/) || [])[1] || '';
  const shrink = (rule.match(/(?:^|;)flex-shrink:([^;]*)/) || [])[1] || flex.trim().split(/\s+/)[1];
  assert.equal(String(shrink).trim(), '0', 'flex shrink of .live-lines is 0: ' + rule);
});

// ORCH-1360: a focusable separator says its size; Tab scrolls the page clear of the layer.
test('the grip always says its smallest, largest and current size', () => {
  const ctx = {window:{innerWidth:1280, innerHeight:800}, LIVE_SIZE:{height:[200, 0.85], width:[320, 0.7]}};
  vm.createContext(ctx);
  vm.runInContext(page.slice(page.indexOf('function liveGripValues'), page.indexOf('// What the panel shows')) + '\nthis.f = liveGripValues;', ctx);
  assert.deepEqual({...ctx.f('height', null)}, {'aria-valuemin':'200', 'aria-valuemax':'680', 'aria-valuenow':'360'}, 'no kept size: the CSS default');
  assert.deepEqual({...ctx.f('height', 999)}, {'aria-valuemin':'200', 'aria-valuemax':'680', 'aria-valuenow':'680'}, 'never above the largest');
  assert.equal(ctx.f('width', null)['aria-valuenow'], '538');
  assert.equal(ctx.f('width', 100)['aria-valuenow'], '320', 'never below the smallest');
  assert.match(page, /\.\.\.liveGripValues\(dim, px\)/);
});

test('the page keeps room for the layer when Tab scrolls to the next link', () => {
  const pad = page.slice(page.indexOf('function liveLayerPad'), page.indexOf('function liveLayerOff'));
  assert.match(pad, /setProperty\('scroll-padding-bottom', \(pad \+ tb \+ \(pad \? 12 : 0\)\) \+ 'px'\)/);
  assert.match(pad, /setProperty\('scroll-padding-right'/);
  const off = page.slice(page.indexOf('function liveLayerOff'), page.indexOf('// Called after every page render'));
  assert.match(off, /removeProperty\('scroll-padding-bottom'\)/);
});

test('an answer in the layer waits with Undo on its toast before it is sent (ORCH-1359)', () => {
  const fill = source.slice(source.indexOf('function liveAskFill'), source.indexOf('// The live part of a pane'));
  assert.match(source, /const LIVE_ASK_UNDO_MS = 5200/, 'the same window as on Home');
  assert.match(fill, /liveAskPending\.has\(id \+ '\/' \+ found\.id\) \? null : found|!liveAskPending\.has\(id \+ '\/' \+ found\.id\) \? found : null/, 'a waiting answer hides the question');
  assert.match(fill, /toast\?\.\('Answered: ' \+ text, 'ok', \(\) => \{ finish\(true\)/, 'the toast offers Undo');
  const wait = fill.indexOf('if (undone) return;'), send = fill.indexOf("act('answer'");
  assert.ok(wait > 0 && send > wait, 'the answer is sent only after the Undo window');
  assert.match(fill, /if \(over\) return; over = true;/, 'an Undo after the window has ended does nothing');
  assert.match(fill, /if \(b\.textContent === 'Undo'\) b\.remove\(\)/, 'and the toast loses its Undo once the answer goes out');
  assert.match(source, /addEventListener\('pagehide', \(\) => \{ for \(const now of \[\.\.\.liveAskPending\.values\(\)\]\) now\(\); \}\)/, 'leaving the page sends it at once');
});

test('a saved name offers Undo that puts the old own name back (ORCH-1359)', () => {
  assert.match(source, /toast\?\.\('Name saved\.', 'ok', \(\) => window\.LiveSessions\?\.rename\(key, before \|\| ''\)\)/);
  assert.match(source, /if \(own === \(before \|\| ''\)\) \{ liveRenEnd\(key, false\); return; \}/, 'an unchanged name shows no toast');
});

test('the bar, the panel, the side tab and the message box keep toasts clear (ORCH-1359)', () => {
  assert.match(source, /className:'live-bar'[^\n]*'data-toast-clear':''/);
  assert.match(source, /className:'live-edge'[^\n]*'data-toast-clear':''/);
  assert.match(source, /className:'live-panel'[^\n]*'data-toast-clear':''/);
  assert.match(source, /function liveLayerPad[^]*?window\.UI\?\.toastPlace\?\.\(\)/, 'a shown toast moves when the layer changes');
});

// ORCH-1362 (UX checklist D5): Add beside is never greyed; with nothing to add its menu says why and what to do.
test('Add beside stays a button; its menu says why nothing can go beside and what to do instead', () => {
  assert.equal(L.liveBesideNote(1, 2), '', 'sessions to pick: no note');
  assert.match(L.liveBesideNote(1, 0), /^No other session is live\. Start one/);
  assert.match(L.liveBesideNote(4, 2), /^Up to four sessions show at once\. Close one/);
  const pane = source.slice(source.indexOf('function livePane('), source.indexOf('// The body of a pane'));
  const split = pane.slice(pane.indexOf("['right', 'down'].map"), pane.indexOf("livePaneBtn('pin'"));
  assert.doesNotMatch(split, /disabled/, 'Split is never greyed');
  assert.match(pane, /liveSplitMenu\(s\.menu, key, label, o\.others, besideNone\)/);
  const sm = source.slice(source.indexOf('function liveSplitMenu('), source.indexOf('let liveSplitWant'));
  assert.match(sm, /'data-key':'live-split-none'\}, note\)/, 'its menu says why nothing can go there');
  for (const w of ['Chat with\\u2026', "'Terminal'", "'Plain terminal'"]) assert.ok(sm.includes(w), w);
  const menu = source.slice(source.indexOf('function liveBesideMenu('), source.indexOf('// The More menu'));
  assert.match(menu, /note \? h\('p', \{className:'meta', role:'status', 'data-key':'live-beside-none'\}, note\)/);
  const more = source.slice(source.indexOf('function liveMoreEnd('), source.indexOf('// ORCH-817: Stop (the current step)'));
  assert.doesNotMatch(more, /disabled/, 'Stop in More is never greyed');
  assert.match(more, /'Nothing is running right now\.'/, 'and says next to it when nothing runs');
});

test('the Results shelf keep step skips the leaving picture of a pane, which has no data-key (motion.js, ORCH-1356)', () => {
  const start = source.indexOf('function liveShelfKeep(');
  const fn = source.slice(start, source.indexOf('\n}\n', start) + 3);
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(fn + '\nthis.keep = liveShelfKeep;', ctx);
  const swapped = [];
  const fresh = {replaceWith: el => swapped.push(el)};
  const host = {querySelector: sel => sel.includes('shelf-results-t_1') ? fresh : null};
  const real = {dataset: {key: 'shelf-results-t_1'}}, ghost = {dataset: {}};
  assert.doesNotThrow(() => ctx.keep([ghost, real], host));
  assert.deepEqual(swapped, [real], 'only the real shelf is put back');
  assert.match(source, /querySelectorAll\('\.live-shelf \[data-results-host\]\[data-key\]'\)/, 'and the paint collects only shelves with a key');
});

// ORCH-1358: the pane header follows the live sessions API, as the bar and the wall do.
test('the pane header follows the live session: ended is no helper, needs you says Needs you', () => {
  const own = {state:'working', word:'Working', detail:''};
  assert.equal(L.liveLayerHelper({status:'closed'}, own), null, 'an ended session never says Working');
  assert.equal(L.liveLayerHelper({status:'in-line'}, own), null);
  const you = L.liveLayerHelper({status:'needs-you', detail:'Your answer'}, {state:'idle', word:'Idle', detail:''});
  assert.equal(you.state, 'you'); assert.equal(you.word, 'Needs you'); assert.equal(you.detail, 'Your answer');
  assert.equal(L.liveLayerHelper({status:'idle'}, own).state, 'idle');
  const hold = {state:'waiting', word:'On hold', detail:'Waits on a script'};
  assert.equal(L.liveLayerHelper({status:'working'}, hold), hold, 'the page keeps its finer word for a working session');
  assert.equal(L.liveLayerHelper(null, own), own, 'before the first answer the page state stays');
});

test('before the page state arrives a working session keeps the API word (Stuck, On hold)', () => {
  const x = L.liveLayerHelper({status:'working', word:'Stuck', detail:'No update for a while'}, null);
  assert.equal(x.state, 'stuck'); assert.equal(x.word, 'Stuck');
  assert.equal(L.liveLayerHelper({status:'working', word:'Working'}, null).word, 'Working');
});

test('ORCH-1600: the folded sides are read from this computer; anything unreadable leaves both open', () => {
  const store = v => ({getItem: k => (k === L.LIVE_FOLD_KEY ? v : null)});
  assert.deepEqual({...L.liveFoldRead(store('{"left":true}'))}, {left: true, right: false});
  assert.deepEqual({...L.liveFoldRead(store('{"left":false,"right":true}'))}, {left: false, right: true});
  assert.deepEqual({...L.liveFoldRead(store('{"left":"yes"}'))}, {left: false, right: false});
  assert.deepEqual({...L.liveFoldRead(store('not json'))}, {left: false, right: false});
  assert.deepEqual({...L.liveFoldRead(null)}, {left: false, right: false});
});

test('ORCH-1600: one wide pane under 1500 px is crowded (Pin, Add beside, Minimise go into More); compact panes are not', () => {
  assert.equal(L.liveLayerCrowded('full', 1, 1280, false), true, 'full screen at 1280');
  assert.equal(L.liveLayerCrowded('full', 1, 1920, false), false, 'full screen at 1920: the whole header fits');
  assert.equal(L.liveLayerCrowded('bottom', 1, 1040, false), false, 'compact already');
  assert.equal(L.liveLayerCrowded('full', 2, 1280, false), false, 'a split is compact');
  assert.equal(L.liveLayerCrowded('full', 1, 390, true), false, 'a phone');
});

test('ORCH-1616: a split shows as many panes as fit (2 at 1280, 3 at 1920), the selected one always; the page beside keeps 600 px', () => {
  const fit = (...a) => [...L.liveLayerFit(...a)];
  const three = ['a', 'b', 'c'];
  assert.deepEqual(fit(three, 'a', 'bottom', 1060, false), ['a', 'b']);   // 1280 wide minus the side menu
  assert.deepEqual(fit(three, 'c', 'bottom', 1060, false), ['a', 'c']);   // the selected one is never left out
  assert.deepEqual(fit(three, 'b', 'bottom', 1700, false), three);        // 1920 wide
  assert.deepEqual(fit(three, 'c', 'full', 1280, false), ['a', 'c']);
  assert.deepEqual(fit(three, 'c', 'right', 460, false), ['a', 'c']);     // stacked on the right: two at most
  assert.deepEqual(fit(three, 'b', 'bottom', 1700, true), ['b']);         // a phone: only the selected one
  assert.deepEqual(fit(['a'], 'a', 'bottom', 300, false), ['a']);
  assert.equal(L.liveLayerRightMax(1280, 220), 460);
  assert.equal(L.liveLayerRightMax(900, 220), 320, 'never under the smallest panel');
  const css = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/widgets.css'), 'utf8');
  assert.match(css, /--live-w:clamp\(320px,min\(42vw,760px\),calc\(100vw - var\(--sidebar-width\) - 600px\)\)/);
});

test('ORCH-1643: a suggested answer is highlighted only with the helper\'s reason, and the reason reads under the question', () => {
  const {liveAskModel, liveAskWhy} = load();
  const q = o => liveAskModel({questions:[{id:'q1', digest:'d', text:'Keep the old name?', options:['Keep the old name', 'Use the new name'], ...o}]});
  const with_ = q({recommended:'Keep the old name', because:'links people already shared keep working.'});
  assert.equal(with_.suggest, 'Keep the old name');
  assert.equal(liveAskWhy(with_), 'The helper suggests \u201cKeep the old name\u201d: links people already shared keep working.');
  assert.equal(q({recommended:'Keep the old name'}).suggest, '', 'no reason: nothing highlighted');
  assert.equal(liveAskWhy(q({recommended:'Keep the old name'})), '');
  assert.equal(q({recommended:'Something else', because:'why'}).suggest, '', 'a suggestion that is not a choice is not highlighted');
});
test('ORCH-1643: a layer never placed opens on the right on a desktop under 1600 px (the page keeps its height), at the bottom at 1920 and on a phone; a saved place wins', () => {
  const {liveLayerFirstPlace, liveLayerRead, LIVE_LAYER_KEY} = load();
  assert.equal(liveLayerFirstPlace(1280, false), 'right');
  assert.equal(liveLayerFirstPlace(1920, false), 'bottom');
  assert.equal(liveLayerFirstPlace(390, true), 'bottom');
  assert.equal(liveLayerRead(null, '', 'right').last, 'right');
  const st = {getItem:() => JSON.stringify({mode:'bar', last:'bottom', panes:[]})};
  assert.equal(liveLayerRead(st, '', 'right').last, 'bottom', 'the place the person used is kept');
  assert.equal(LIVE_LAYER_KEY, 'orch.live.layer');
});

test('ORCH-1659: a third pane at 1280 says which session waits on the bar instead of hiding it quietly', () => {
  const s = run(L.liveLayerFresh(), [{type:'open', key:'t_1'}, {type:'beside', key:'t_2'}, {type:'beside', key:'t_3'}]);
  assert.deepEqual([...s.panes], ['t_1', 't_2', 't_3']);
  const shown = L.liveLayerFit(s.panes, s.cur, 'bottom', 1280 - 220, false);
  assert.equal(shown.length, 2);
  assert.ok(shown.includes('t_3'), 'the one just added shows');
  const wait = s.panes.filter(k => !shown.includes(k));
  assert.equal(L.liveBesideHidden(shown.length, ['DEM-1 Fix the price list']), 'Room for 2 sessions here, so DEM-1 Fix the price list waits on the bar. Open it there, or close a pane.');
  assert.equal(wait.length, 1);
  assert.equal(L.liveBesideHidden(3, []), '', 'every pane shows: nothing to say');
  assert.match(L.liveBesideHidden(1, ['A', 'B']), /^Room for 1 session here, so A, B wait on the bar\./);
});

// ORCH-261 ship stop: the bottom split over Review cut the only card and spent half its room on an empty pane.
test('while the page has cards to answer, quiet panes fold to the bar; the selected one and an all-quiet split stay', () => {
  const fit = (...a) => [...L.liveLayerFit(...a)];
  assert.deepEqual(fit(['t_1', 't_2'], 't_1', 'bottom', 1060, false, ['t_2']), ['t_1'], 'the empty pane leaves the split');
  assert.deepEqual(fit(['t_1', 't_2'], 't_2', 'bottom', 1060, false, ['t_2']), ['t_1', 't_2'], 'the pane the person picked stays');
  assert.deepEqual(fit(['t_1', 't_2'], 't_1', 'bottom', 1060, false, ['t_1', 't_2']), ['t_1', 't_2'], 'only quiet panes: nothing folds');
  assert.deepEqual(fit(['t_1', 't_2'], 't_1', 'bottom', 1060, false), ['t_1', 't_2'], 'no cards behind: as before');
  assert.deepEqual(fit(['t_1', 't_2', 't_3'], 't_3', 'bottom', 1700, false, ['t_2']), ['t_1', 't_3']);
});
test('the bottom panel keeps a card and its answers in reach while the page has cards to answer', () => {
  const cap = L.liveLayerBottomCap;
  assert.equal(cap(800, false), null, 'no cards behind: the style sheet height');
  assert.equal(cap(800, true), 340, '800 high: 412 px of page stay above the bar and panel');
  assert.equal(cap(900, true), 405);
  assert.equal(cap(1080, true), 486, 'tall windows keep the usual 45 %');
  assert.equal(cap(600, true), 340, 'never so small that a question card and the message box do not fit');
});

test('ORCH-2202 (owner pick I a): beside Focus on the right the side menu folds to its rail when the page would get under 560 px', () => {
  assert.equal(L.liveLayerRailWanted(1280, 232, 620, true), true, '1280 x 772: the menu folds, Focus gets its room');
  assert.equal(L.liveLayerRailWanted(1680, 232, 620, true), false, '1680 x 920: the page keeps more than 560 px, nothing folds');
  assert.equal(L.liveLayerRailWanted(1280, 232, 620, false), false, 'only with Focus on the right');
  assert.equal(L.liveLayerRailWanted(1100, 232, 620, true), false, 'under 1280 the menu is a rail already');
  assert.equal(L.liveLayerRailWanted(1440, 232, 400, true), false, 'a narrower Focus the person dragged leaves the menu open');
  const css = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/widgets.css'), 'utf8');
  assert.match(css, /body\[data-live-narrow\] \.ticket-layout\{grid-template-columns:minmax\(0,1fr\)\}/, 'the ticket goes to one column');
  const comp = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/components.css'), 'utf8');
  assert.match(comp, /\.shell:is\(\[data-side=rail\],\[data-live-rail\]\)\{--sidebar-width:64px\}/, 'the same icon rail as Close menu');
});

// ORCH-2197 (owner pick C a): a helper that waits for an OK on its screen gets the OK card in its pane, Chat and
// Terminal view alike; the command shows by default (owner's comment); the answers only for a prompt the server read.
function okCard({prompt = null, view = 'chat', detail = 'Your OK on the screen: databricks jobs run-now 5884'} = {}) {
  const node = (tag, attrs = {}, ...kids) => {
    const n = {tag, attrs, kids:[], text:'', listeners:{}, hidden:!!attrs.hidden, disabled:!!attrs.disabled,
      dataset:{}, setAttribute(k, v) { this.attrs[k] = v; }, addEventListener(k, f) { this.listeners[k] = f; },
      append(...xs) { for (const x of xs) if (x != null) this.kids.push(typeof x === 'string' ? {text:x, kids:[]} : x); }};
    Object.defineProperty(n, 'textContent', {get() { return [n.text, ...n.kids.map(k => k.textContent ?? k.text)].join(''); }, set(v) { n.text = v; n.kids = []; }});
    n.append(...kids);
    return n;
  };
  const posts = [], toasts = [];
  const ctx = {h:node, window:{orch:{toast:(t, k) => toasts.push([t, k])}}, Date, encodeURIComponent, console,
    liveViewOf:() => view, liveLayerFill() {}, fetch:async () => ({ok:true, json:async () => ({prompt})}),
    liveTermPost:async (p, b) => { posts.push([p, b]); return {ok:true, status:200, text:''}; }};
  vm.createContext(ctx);
  const page = source.slice(source.indexOf('const liveOk = new Map()'), source.indexOf('function liveAskFill'));
  vm.runInContext(page + '\nthis.api = {liveOkFill, liveOkWaits, liveOk};', ctx);
  const box = node('div', {hidden:true});
  const live = {status:'needs-you', detail};
  return {ctx, box, live, posts, toasts, fill: () => ctx.api.liveOkFill(box, 't_1', live)};
}
const findKey = (n, key) => n.attrs?.['data-key'] === key ? n : (n.kids || []).map(k => findKey(k, key)).find(Boolean) || null;

test('a helper waiting for an OK on its screen gets the OK card with its command shown (ORCH-2197)', async () => {
  const c = okCard();
  assert.equal(c.ctx.api.liveOkWaits({status:'needs-you', detail:'Your OK on the screen'}), true);
  assert.equal(c.ctx.api.liveOkWaits({status:'needs-you', detail:'Your answer'}), false, 'a ticket question has its own card');
  assert.equal(c.ctx.api.liveOkWaits({status:'working', detail:''}), false);
  c.fill();
  assert.equal(c.box.hidden, false);
  assert.equal(findKey(c.box, 'live-ok-title').textContent, 'Helper asks to run a command');
  assert.equal(findKey(c.box, 'live-ok-command').textContent, 'databricks jobs run-now 5884', 'shown by default, no Show command');
  assert.equal(findKey(c.box, 'live-ok-allow'), null, 'no answer buttons before the server read the prompt');
  assert.ok(findKey(c.box, 'live-ok-term'), 'Open terminal');
});

test('Allow once and Don\'t allow answer the prompt the server read, by its digest; never by themselves', async () => {
  const prompt = {question:'Do you want to proceed?', options:['Yes', 'No'], yes:'1', no:'2', digest:'abc123',
    command:'databricks jobs run-now 588496183906654 --profile pilatus_hub_sbox', reason:'Guard: starts a job run. Confirm it is wanted'};
  const c = okCard({prompt});
  c.fill();
  await new Promise(r => setImmediate(r));  // the prompt arrives
  c.fill();
  assert.equal(findKey(c.box, 'live-ok-command').textContent, prompt.command);
  assert.equal(findKey(c.box, 'live-ok-why').textContent, prompt.reason);
  assert.equal(findKey(c.box, 'live-ok-allow').textContent, 'Allow once');
  assert.equal(findKey(c.box, 'live-ok-deny').textContent, 'Don’t allow');
  assert.equal(c.posts.length, 0, 'nothing is answered without a click');
  await findKey(c.box, 'live-ok-allow').listeners.click();
  assert.deepEqual(JSON.parse(JSON.stringify(c.posts)), [['/api/term/confirm', {ticket:'t_1', answer:'yes', digest:'abc123'}]]);
  assert.deepEqual(c.toasts.at(-1), ['Allowed once.', 'ok']);
});

test('in the Terminal view the card stays, without Open terminal (ORCH-2197)', async () => {
  const c = okCard({view:'term', detail:'Your OK on the screen'});
  c.fill();
  assert.equal(findKey(c.box, 'live-ok-title').textContent, 'Helper asks for your OK');
  assert.equal(findKey(c.box, 'live-ok-term'), null);
  assert.equal(findKey(c.box, 'live-ok-here').textContent, 'Answer it in the terminal.');
});

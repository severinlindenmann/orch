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
  vm.runInContext(model + '\nthis.api = {liveLayerFresh, liveLayerRead, liveLayerWrite, liveLayerWhere, liveLayerStep, liveLayerNarrow, liveLayerSort, liveAskModel, LIVE_LAYER_KEY, LIVE_MAX};', ctx);
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

test('place and size are kept per browser; full screen opens docked after a reload; bad data is ignored', () => {
  const st = store();
  let s = run(L.liveLayerFresh(), [{type:'open', key:'t_1'}, {type:'place', mode:'right'}, {type:'size', dim:'width', px:600, room:1920}, {type:'size', dim:'height', px:400, room:1080}, {type:'place', mode:'full'}]);
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

test('Add beside splits into two, then three panes; the third is the most and the new pane is selected', () => {
  let s = run(L.liveLayerFresh(), [{type:'open', key:'t_1'}, {type:'beside', key:'t_2'}]);
  assert.deepEqual([...s.panes], ['t_1', 't_2']);
  assert.equal(s.cur, 't_2');
  assert.equal(s.mode, 'bottom');
  s = L.liveLayerStep(s, {type:'beside', key:'t_3'});
  assert.deepEqual([...s.panes], ['t_1', 't_2', 't_3']);
  assert.equal(L.LIVE_MAX, 3);
  s = L.liveLayerStep(s, {type:'beside', key:'t_4'});
  assert.deepEqual([...s.panes], ['t_1', 't_2', 't_4'], 'a fourth takes the last pane');
  assert.deepEqual([...L.liveLayerStep(s, {type:'beside', key:'t_1'}).panes], ['t_1', 't_2', 't_4'], 'a shown session is only selected');
  assert.equal(L.liveLayerStep(s, {type:'beside', key:'t_1'}).cur, 't_1');
  assert.equal(L.liveLayerStep(s, {type:'beside'}), s, 'nothing to add');
  const min = run(s, [{type:'min'}, {type:'beside', key:'t_9'}]);
  assert.equal(min.mode, 'bottom', 'Add beside from the bar opens the layer again');
  assert.deepEqual([...min.panes], ['t_1', 't_2', 't_9'], 'the split stays when it opens again');
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

test('the split and the selected pane are kept per browser, at most three', () => {
  const st = store();
  const s = run(L.liveLayerFresh(), [{type:'open', key:'t_1'}, {type:'beside', key:'t_2'}, {type:'select', key:'t_1'}]);
  L.liveLayerWrite(st, s);
  const back = L.liveLayerRead(st);
  assert.deepEqual([...back.panes], ['t_1', 't_2']);
  assert.equal(back.cur, 't_1');
  const many = L.liveLayerRead(store({[L.LIVE_LAYER_KEY]:JSON.stringify({mode:'bottom', panes:['a', 'a', 'b', 'c', 'd'], cur:'zz'})}));
  assert.deepEqual([...many.panes], ['a', 'b', 'c'], 'twice is once, four is three');
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

test('a window resize draws the layer again only across the phone width', () => {
  assert.doesNotMatch(page, /addEventListener\('resize', \(\) => \{ if \(document\.getElementById\('live-dock'\)\) \{ liveLayerPainted = ''/);
  assert.match(page, /if \(now !== phone\)/);
});

test('ORCH-817: every pane has Stop and End session in its header (More when narrow); the old body Stop is gone', () => {
  assert.doesNotMatch(source, /data-live-stop/);
  assert.match(source, /\.\.\.\(sess \? liveEndHere\(key, label, o\.narrow\) : \[\]\)/);
  assert.match(source, /narrow \? \[window\.liveEndOpenAt\?\.\('pane'\) === key \? window\.liveEndMenu\(key, 'pane:' \+ key\) : null\] : window\.liveEndButtons\(key, label\)/);
  assert.match(source, /sess && typeof window\.liveEndMenu === 'function' \? liveMoreEnd\(key\) : null/);
  assert.match(source, /typeof window\.liveEndKey === 'function' \? window\.liveEndKey\(\) : null\]\);/, 'the dock repaints when a Stop or End menu opens');
});

test('ORCH-817: an ended helper without a ticket keeps its pane with Start again and History; an ended terminal does not', () => {
  assert.match(source, /o\.open === true \|\| o\.kind !== 'terminal'/);
  assert.match(source, /ended:!running && x\.kind !== 'terminal' && \(x\.open !== true \|\| \(!!window\.LiveSessions\?\.ready && !live\)\)/);
  assert.match(source, /sess\?\.ended \? h\('div', \{className:'live-pb live-pb-start'\}, liveEndedBody\(sess, label\)\)/);
  assert.match(source, /act\('session\.new', \{kind:b\.dataset\.liveAgain\}/);
  assert.match(source, /liveHistBody\(sess\)/);
});

test('ORCH-817: an idle helper pane gets the idle note instead of one status line', () => {
  assert.match(source, /sess\.kind === 'terminal' \? null : h\('div', \{className:'live-end-idle', 'data-live-idle':''/);
  assert.match(source, /window\.liveEndIdleFill\(idle, body\.dataset\.liveBody, text\)/);
});

test('the pane shows the waiting question with its options and answers it there (ORCH-675)', () => {
  const {liveAskModel} = load();
  const t = {questions:[{id:'q1', answer:'x', text:'old'}, {id:'q2', digest:'d', text:'Which banner colour should I use?', options:['Blue', 'Green', '']}]};
  assert.deepEqual(JSON.parse(JSON.stringify(liveAskModel(t))), {id:'q2', digest:'d', text:'Which banner colour should I use?', options:['Blue', 'Green'], plain:true});
  assert.equal(liveAskModel({questions:[{id:'q1', answer:'x'}]}), null);
  assert.equal(liveAskModel({}), null);
  assert.equal(liveAskModel({questions:[{id:'q3', kind:'plan', text:'Plan?'}]}).plain, false);
  assert.match(source, /liveAskFill[^]*?act\('answer', \{ticket:id, question:q\.id, digest:q\.digest/, 'the answer is the same op a question card sends');
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

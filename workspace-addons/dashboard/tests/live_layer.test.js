'use strict';
// ORCH-338: the layer of the new live page (pages/live-layer.js). The model is plain data: where the layer sits, where
// it opens again, what Esc does, the size limits and what is kept per browser.
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
  vm.runInContext(model + '\nthis.api = {liveLayerFresh, liveLayerRead, liveLayerWrite, liveLayerWhere, liveLayerStep, LIVE_LAYER_KEY};', ctx);
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

test('the layer names no add-on and builds no inline style', () => {
  const plain = source.replace(/\.focus\(/g, '.(');
  assert.doesNotMatch(plain, /\b(focus|automation|scheduler|publish|wiki)\b/i);
  assert.doesNotMatch(source, /setAttribute\(\s*['"]style/);
});

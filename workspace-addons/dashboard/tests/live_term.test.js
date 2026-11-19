'use strict';
// ORCH-744: the terminal view in the layer (pages/liveterm.js). Which pane bodies get the real screen, and that the
// one terminal of a session moves into a pane the layer drew again (its typing state and screen stay).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/liveterm.js'), 'utf8');
class N {
  constructor(attrs = {}) { this.dataset = attrs.dataset || {}; this.children = []; this.parentNode = null; this.hidden = false; this.sel = attrs.sel || {}; }
  querySelector(s) { return this.sel[s] || null; }
  closest() { return null; }
  after(n) { this.parentNode.append(n); }
  append(n) { if (n.parentNode) n.remove(); n.parentNode = this; this.children.push(n); }
  remove() { const p = this.parentNode; if (p) p.children.splice(p.children.indexOf(this), 1); this.parentNode = null; }
}
function load() {
  const made = [], streams = [], posts = [];
  class ES {
    constructor(url) { this.url = url; this.on = {}; this.readyState = 1; this.closed = false; streams.push(this); }
    addEventListener(t, f) { this.on[t] = f; }
    emit(t, data) { this.on[t]({data}); }
    close() { this.closed = true; this.readyState = 2; }
  }
  const ctx = {
    module: {exports: {}}, Date, Map, setTimeout, clearTimeout, encodeURIComponent, JSON, EventSource: ES,
    window: {UI: {term: o => {
      const el = new N(); let typing = false;
      const ui = {el, o, got: [], hello: h => ui.got.push(['hello', h]), screen: x => ui.got.push(['screen', x]), write: b => ui.got.push(['out', b]),
        size: z => ui.got.push(['size', z]), end: w => ui.got.push(['end', w]), show: w => ui.got.push(['show', w]),
        setTyping: on => { typing = !!on; }, typing: () => typing, back() { ui.backs = (ui.backs || 0) + 1; }, dispose() { ui.disposed = true; }};
      made.push(ui); return ui;
    }}},
    document: {hidden: false, contains: n => { for (let x = n; x; x = x.parentNode) if (x.attached) return true; return false; }},
    fetch: async (url, init) => { posts.push([url, JSON.parse(init.body)]); return {ok: true}; },
  };
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  return {api: ctx.module.exports, made, streams, posts};
}
const body = (id, more = {}) => {
  const pre = new N();
  const b = new N({dataset: {liveBody: id, ...(more.dataset || {})}, sel: {'[data-live-lines]': pre, ...(more.sel || {})}});
  b.append(pre); b.attached = true;
  return {b, pre};
};

test('a ticket pane shows the terminal in Terminal view, or when it has no chat view; never for a session without a ticket', () => {
  const {api} = load();
  assert.equal(api.liveTermWanted(body('t_a').b), true, 'no chat view: the terminal');
  assert.equal(api.liveTermWanted(body('t_a', {dataset: {liveView: 'chat'}, sel: {'[data-live-chat]': new N()}}).b), false);
  assert.equal(api.liveTermWanted(body('t_a', {dataset: {liveView: 'term'}, sel: {'[data-live-chat]': new N()}}).b), true);
  assert.equal(api.liveTermWanted(body('s_1', {dataset: {liveKind: 'terminal'}}).b), false);
});

test('no live helper: no terminal; a live one: one terminal and one stream per session, the last lines hidden', () => {
  const {api, made, streams} = load();
  const {b, pre} = body('t_a');
  api.liveTermApply(b, null);
  assert.equal(made.length, 0);
  api.liveTermApply(b, {id: 't_a'});
  api.liveTermApply(b, {id: 't_a'});
  assert.equal(made.length, 1);
  assert.equal(made[0].el.parentNode, b);
  assert.equal(pre.hidden, true);
  assert.deepEqual(streams.map(x => x.url), ['/api/term/stream?ticket=t_a']);
});

test('the bridge\'s events go to the terminal; an end closes the stream and it opens again only later', () => {
  const {api, made, streams} = load();
  const {b} = body('t_a');
  api.liveTermApply(b, {id: 't_a'});
  const es = streams[0];
  es.emit('hello', '{"typing_allowed":true}');
  es.emit('screen', '{"cols":80,"rows":24,"data":"aGk="}');
  es.emit('out', 'eA==');
  es.emit('size', '{"cols":90,"rows":20}');
  es.emit('end', '{"state":"none"}');
  assert.deepEqual(JSON.parse(JSON.stringify(made[0].got)), [['hello', {typing_allowed: true}], ['screen', {cols: 80, rows: 24, data: 'aGk='}],
    ['out', 'eA=='], ['size', {cols: 90, rows: 20}], ['end', 'none']]);
  assert.equal(es.closed, true);
  api.liveTermApply(b, {id: 't_a'});
  assert.equal(streams.length, 1, 'not opened again at once');
});

test('typing and a new size go to the bridge\'s input and size addresses for this session', async () => {
  const {api, made, posts} = load();
  const {b} = body('t_a');
  api.liveTermApply(b, {id: 't_a'});
  const r = await made[0].o.onInput('ls\r');
  await made[0].o.onSize({cols: 120, rows: 30});
  assert.equal(r.ok, true);
  assert.deepEqual(JSON.parse(JSON.stringify(posts)), [['/api/term/input', {ticket: 't_a', data: 'ls\r'}], ['/api/term/size', {ticket: 't_a', cols: 120, rows: 30}]]);
});

test('the layer draws the pane again: the same terminal moves in and gets the keyboard back', () => {
  const {api, made} = load();
  const first = body('t_a');
  api.liveTermApply(first.b, {id: 't_a'});
  made[0].setTyping(true);
  const again = body('t_a');
  api.liveTermApply(again.b, {id: 't_a'});
  assert.equal(made.length, 1, 'no second terminal');
  assert.equal(made[0].el.parentNode, again.b);
  assert.equal(made[0].typing(), true);
  assert.equal(made[0].backs, 2);
});

test('switching the pane to Chat takes the terminal out, stops typing and closes the stream', () => {
  const {api, made, streams} = load();
  const {b} = body('t_a');
  api.liveTermApply(b, {id: 't_a'});
  made[0].setTyping(true);
  b.dataset.liveView = 'chat'; b.sel['[data-live-chat]'] = new N();
  api.liveTermApply(b, {id: 't_a'});
  assert.equal(made[0].el.parentNode, null);
  assert.equal(made[0].typing(), false);
  assert.equal(streams[0].closed, true);
});

test('the layer drew the pane again and it now shows Chat: the terminal in the old body stops at once', () => {
  const {api, made, streams} = load();
  const first = body('t_a');
  api.liveTermApply(first.b, {id: 't_a'});
  made[0].setTyping(true);
  first.b.attached = false;  // replaced by the repaint
  const again = body('t_a', {dataset: {liveView: 'chat'}, sel: {'[data-live-chat]': new N()}});
  api.liveTermApply(again.b, {id: 't_a'});
  assert.equal(made[0].typing(), false);
  assert.equal(streams[0].closed, true);
});

test('a stream error: reconnecting says so (no typing); refused says error and opens again only later', () => {
  const {api, made, streams} = load();
  const {b} = body('t_a');
  api.liveTermApply(b, {id: 't_a'});
  streams[0].readyState = 0; streams[0].onerror();
  assert.deepEqual(made[0].got.at(-1), ['show', 'loading']);
  streams[0].readyState = 2; streams[0].onerror();
  assert.deepEqual(made[0].got.at(-1), ['show', 'error'], 'the error is the last word, not the close');
  api.liveTermApply(b, {id: 't_a'});
  assert.equal(streams.length, 1);
});

test('a terminal no pane shows stops typing and closes its stream at the next tick; later it is freed', () => {
  const {api, made, streams} = load();
  const {b} = body('t_a');
  api.liveTermApply(b, {id: 't_a'});
  made[0].setTyping(true);
  b.attached = false;
  api.liveTermTick();
  assert.equal(made[0].typing(), false);
  assert.equal(streams[0].closed, true, 'the bridge serves few pages: the stream closes at once');
  assert.equal(api.liveTerms.size, 1, 'kept a while for a pane that opens again');
});

test('served as a page module and loaded after the layer and the kit terminal', () => {
  const server = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/server.py'), 'utf8');
  assert.match(server, /\|liveterm\)\\\.js/);
  const html = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/index.html'), 'utf8');
  const at = s => html.indexOf(s);
  assert.ok(at('kit/term.js') > 0 && at('kit/term.css') > 0);
  assert.ok(at('pages/live-layer.js') < at('pages/liveterm.js') && at('pages/liveterm.js') < at('app.js'));
});

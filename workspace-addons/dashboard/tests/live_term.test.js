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
  const made = [], fetched = [];
  const ctx = {
    module: {exports: {}}, Date, Map, setTimeout, clearTimeout, encodeURIComponent, JSON,
    window: {UI: {term: o => { const el = new N(); let typing = false; const ui = {el, o, update() {}, show() {}, setTyping: on => { typing = !!on; }, typing: () => typing, back() { ui.backs = (ui.backs || 0) + 1; }}; made.push(ui); return ui; }}},
    document: {hidden: false, contains: n => { for (let x = n; x; x = x.parentNode) if (x.attached) return true; return false; }},
    fetch: async url => { fetched.push(url); return {ok: true, json: async () => ({state: 'none'})}; },
  };
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  return {api: ctx.module.exports, made, fetched};
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

test('no live helper: no terminal; a live one: one terminal per session, the last lines hidden, its screen read', async () => {
  const {api, made, fetched} = load();
  const {b, pre} = body('t_a');
  api.liveTermApply(b, null);
  assert.equal(made.length, 0);
  api.liveTermApply(b, {id: 't_a'});
  assert.equal(made.length, 1);
  assert.equal(made[0].el.parentNode, b);
  assert.equal(pre.hidden, true);
  await new Promise(r => setTimeout(r, 5));
  assert.deepEqual(fetched, ['/api/term?ticket=t_a']);
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

test('switching the pane to Chat takes the terminal out and stops typing', () => {
  const {api, made} = load();
  const {b} = body('t_a');
  api.liveTermApply(b, {id: 't_a'});
  made[0].setTyping(true);
  b.dataset.liveView = 'chat'; b.sel['[data-live-chat]'] = new N();
  api.liveTermApply(b, {id: 't_a'});
  assert.equal(made[0].el.parentNode, null);
  assert.equal(made[0].typing(), false);
});

test('a terminal no pane shows stops typing at the next tick', () => {
  const {api, made} = load();
  const {b} = body('t_a');
  api.liveTermApply(b, {id: 't_a'});
  made[0].setTyping(true);
  b.attached = false;
  api.liveTermTick();
  assert.equal(made[0].typing(), false);
  assert.equal(api.liveTerms.size, 1, 'kept a while for a pane that opens again');
});

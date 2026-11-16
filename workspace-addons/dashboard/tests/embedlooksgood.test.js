const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const marker = source.slice(source.indexOf('// A shipped add-on page'));
const ORIGIN = 'http://127.0.0.1:8000';
// Factory "Looks good, all": every collaborator of the handler is faked.
function setup({shipped = true, kind = 'page', snapshot = false, statuses = {t_aaaaaa:'review', t_bbbbbb:'review', t_cccccc:'active'}, failFor = []} = {}) {
  const calls = {moves:[], posts:[], toasts:[], undo:null};
  const frameWindow = {postMessage:(m, o) => calls.posts.push([m, o])};
  const frame = {contentWindow:frameWindow};
  const tickets = Object.fromEntries(Object.entries(statuses).map(([id, status]) => [id, {id, status}]));
  const toast = {remove(){}, querySelector:() => ({before:b => { calls.undo = b; }})};
  const ctx = {snapshot, location:{origin:ORIGIN}, array:v => Array.isArray(v) ? v : [], clean:v => String(v ?? ''),
    route:() => ({kind, id:'factory'}), addons:() => [{name:'factory', shipped}], ticketOf:id => tickets[id] || null,
    document:{querySelector:() => frame}, addEventListener(){}, mutation:0, accept(){},
    fetch:async () => ({ok:true, json:async () => ({})}),
    h:(tag, attrs, ...kids) => { const el = {tag, attrs, listeners:{}, addEventListener(n, f) { el.listeners[n] = f; }}; return el; },
    moveTicket:async (id, status, undoing, extra) => { calls.moves.push([id, status, !!undoing, {...extra}]); if (!failFor.includes(id)) tickets[id].status = status; },
    window:{orch:{toast:(t, kind) => { calls.toasts.push([t, kind]); return toast; }}}};
  vm.createContext(ctx); vm.runInContext(marker, ctx);
  return {ctx, calls, frameWindow};
}
const msg = (frameWindow, extra = {}) => ({origin:ORIGIN, source:frameWindow, data:{type:'orch.looksgood', id:'abcdefgh1234', tickets:['t_aaaaaa', 't_bbbbbb'], ...extra}});
const plain = v => JSON.parse(JSON.stringify(v));

test('only the shown shipped add-on frame of this origin may ask, with 1..10 valid ticket ids', () => {
  const {ctx, frameWindow} = setup();
  assert.deepEqual(plain(ctx.embedLooksGoodRequest(msg(frameWindow, {tickets:['t_aaaaaa', 't_aaaaaa', 't_bbbbbb']})).tickets), ['t_aaaaaa', 't_bbbbbb']);
  assert.equal(ctx.embedLooksGoodRequest({...msg(frameWindow), origin:'https://evil.example'}), null);
  assert.equal(ctx.embedLooksGoodRequest({...msg(frameWindow), source:{}}), null);
  const many = Array.from({length:11}, (_, i) => 't_a' + String(100000 + i));
  for (const bad of [{type:'orch.idea'}, {id:'X'}, {id:5}, {tickets:[]}, {tickets:'t_aaaaaa'}, {tickets:['../x']}, {tickets:['t_aaaaaa', 5]}, {tickets:many}]) assert.equal(ctx.embedLooksGoodRequest(msg(frameWindow, bad)), null);
  let s = setup({shipped:false}); assert.equal(s.ctx.embedLooksGoodRequest(msg(s.frameWindow)), null);
  s = setup({kind:'ticket'}); assert.equal(s.ctx.embedLooksGoodRequest(msg(s.frameWindow)), null);
  s = setup({snapshot:true}); assert.equal(s.ctx.embedLooksGoodRequest(msg(s.frameWindow)), null);
});

test('only tickets in review move to done, quietly, with ONE toast and the page told how many', async () => {
  const {ctx, calls, frameWindow} = setup();
  await ctx.looksGoodAll(ctx.embedLooksGoodRequest(msg(frameWindow, {tickets:['t_aaaaaa', 't_bbbbbb', 't_cccccc', 't_zzzzzz']})));
  assert.deepEqual(plain(calls.moves.map(m => [m[0], m[1], m[3].quiet])), [['t_aaaaaa', 'done', true], ['t_bbbbbb', 'done', true]]);
  assert.deepEqual(plain(calls.toasts), [['Looks good on 2 results', 'ok']]);
  assert.deepEqual(plain(calls.posts), [[{type:'orch.looksgood.done', moved:2, id:'abcdefgh1234'}, ORIGIN]]);
});

test('Undo moves the same tickets back to review', async () => {
  const {ctx, calls, frameWindow} = setup();
  await ctx.looksGoodAll(ctx.embedLooksGoodRequest(msg(frameWindow)));
  calls.undo.listeners.click();
  assert.deepEqual(plain(calls.moves.slice(2).map(m => [m[0], m[1], m[2]])), [['t_aaaaaa', 'review', true], ['t_bbbbbb', 'review', true]]);
});

test('nothing in review, or every move refused, tells the page it failed; a partial move is done plus an error toast', async () => {
  let s = setup({statuses:{t_aaaaaa:'done', t_bbbbbb:'active'}});
  await s.ctx.looksGoodAll(s.ctx.embedLooksGoodRequest(msg(s.frameWindow)));
  assert.equal(s.calls.posts[0][0].type, 'orch.looksgood.failed'); assert.equal(s.calls.moves.length, 0);
  s = setup({failFor:['t_aaaaaa', 't_bbbbbb']});
  await s.ctx.looksGoodAll(s.ctx.embedLooksGoodRequest(msg(s.frameWindow)));
  assert.equal(s.calls.posts[0][0].type, 'orch.looksgood.failed');
  s = setup({failFor:['t_bbbbbb']});
  await s.ctx.looksGoodAll(s.ctx.embedLooksGoodRequest(msg(s.frameWindow)));
  assert.equal(s.calls.posts[0][0].moved, 1); assert.equal(s.calls.toasts[1][1], 'error');
});

test('a second batch while one runs does nothing', async () => {
  const {ctx, calls, frameWindow} = setup();
  const req = ctx.embedLooksGoodRequest(msg(frameWindow));
  await Promise.all([ctx.looksGoodAll(req), ctx.looksGoodAll(req)]);
  assert.equal(calls.posts.length, 1);
});

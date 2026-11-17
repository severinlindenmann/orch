const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const marker = source.slice(source.indexOf('// A shipped add-on page'));
const ORIGIN = 'http://127.0.0.1:8000';
const TARGET = 't_abc123:s2:ws_design0001:0,1';
// Ask another workspace at a Factory stop: one click runs the add-on's `ask` act. Everything the handler touches is faked.
function setup({shipped = true, kind = 'page', snapshot = false, result} = {}) {
  const calls = {acts:[], posts:[]};
  const frameWindow = {postMessage:(m, o) => calls.posts.push([m, o])};
  const frame = {contentWindow:frameWindow};
  const answer = result || {ok:true, status:200, state:{act_answer:{addon:'factory', answer:{state:'delivered', order:'t_abc123'}}}};
  const ctx = {snapshot, location:{origin:ORIGIN}, array:v => Array.isArray(v) ? v : [], clean:v => String(v ?? ''),
    route:() => ({kind, id:'factory'}), addons:() => [{name:'factory', shipped}], ticketOf:() => null,
    document:{querySelector:() => frame}, act:async (...a) => { calls.acts.push(a); return answer; },
    addEventListener(){}, window:{orch:{toast(){}}}};
  vm.createContext(ctx); vm.runInContext(marker, ctx);
  return {ctx, calls, frameWindow};
}
const msg = (frameWindow, extra = {}) => ({origin:ORIGIN, source:frameWindow, data:{type:'orch.ask', id:'abcdefgh1234', target:TARGET, ...extra}});
const plain = v => JSON.parse(JSON.stringify(v));

test('only the shown shipped add-on frame of this origin may ask, with a well-formed target', () => {
  const {ctx, frameWindow} = setup();
  assert.equal(ctx.embedAskRequest(msg(frameWindow)).target, TARGET);
  assert.equal(ctx.embedAskRequest(msg(frameWindow, {target:'t_abc123:s2:ws_design0001:-'})).addon, 'factory');
  assert.equal(ctx.embedAskRequest({...msg(frameWindow), origin:'https://evil.example'}), null);
  assert.equal(ctx.embedAskRequest({...msg(frameWindow), source:{}}), null);
  for (const bad of [{type:'orch.idea'}, {id:'x'}, {id:5}, {target:5}, {target:'x'}, {target:'t_abc123:s0:ws_design0001:0'}, {target:TARGET + ';rm'}, {target:'--t_abc123:s2:ws_design0001:0'}, {target:'t_abc123:s2:ws_design0001:'}]) assert.equal(ctx.embedAskRequest(msg(frameWindow, bad)), null);
  let s = setup({shipped:false}); assert.equal(s.ctx.embedAskRequest(msg(s.frameWindow)), null);
  s = setup({kind:'ticket'}); assert.equal(s.ctx.embedAskRequest(msg(s.frameWindow)), null);
  s = setup({snapshot:true}); assert.equal(s.ctx.embedAskRequest(msg(s.frameWindow)), null);
});

test("the person's click runs the add-on's ask act and tells the page it went out", async () => {
  const {ctx, calls, frameWindow} = setup();
  await ctx.fileEmbedAsk(ctx.embedAskRequest(msg(frameWindow)));
  assert.deepEqual(plain(calls.acts), [['addon.act', {addon:'factory', verb:'ask', target:TARGET}]]);
  assert.deepEqual(plain(calls.posts), [[{type:'orch.ask.done', state:'delivered', id:'abcdefgh1234'}, '*']]);  // the frame is sandboxed (opaque origin): sent to that frame only
});

test('a refused act tells the page why; an answer that does not confirm is a failure', async () => {
  let s = setup({result:{ok:false, status:403, text:'You already asked Design about this stop.'}});
  await s.ctx.fileEmbedAsk(s.ctx.embedAskRequest(msg(s.frameWindow)));
  assert.deepEqual(plain(s.calls.posts), [[{type:'orch.ask.failed', error:'You already asked Design about this stop.', id:'abcdefgh1234'}, '*']]);  // the frame is sandboxed (opaque origin): sent to that frame only
  for (const state of [{}, {act_answer:{addon:'sync', answer:{state:'delivered'}}}, {act_answer:{addon:'factory', answer:{state:'sent'}}}]) {
    s = setup({result:{ok:true, status:200, state}});
    await s.ctx.fileEmbedAsk(s.ctx.embedAskRequest(msg(s.frameWindow)));
    assert.equal(s.calls.posts[0][0].type, 'orch.ask.failed');
  }
});

test('a queued ask (the other workspace is offline) is reported as queued', async () => {
  const {ctx, calls, frameWindow} = setup({result:{ok:true, status:200, state:{act_answer:{addon:'factory', answer:{state:'queued'}}}}});
  await ctx.fileEmbedAsk(ctx.embedAskRequest(msg(frameWindow)));
  assert.equal(calls.posts[0][0].state, 'queued');
});

test('a second click while sending asks nothing twice', async () => {
  const {ctx, calls, frameWindow} = setup();
  const req = ctx.embedAskRequest(msg(frameWindow));
  await Promise.all([ctx.fileEmbedAsk(req), ctx.fileEmbedAsk(req)]);
  assert.equal(calls.acts.length, 1);
});

test('a partly sent ask is reported with what went out, never as "nothing was sent"', async () => {
  const {ctx, calls, frameWindow} = setup({result:{ok:true, status:200, state:{act_answer:{addon:'factory', answer:{state:'partial', said:'Only part of it went out: the card.'}}}}});
  await ctx.fileEmbedAsk(ctx.embedAskRequest(msg(frameWindow)));
  assert.deepEqual(plain(calls.posts), [[{type:'orch.ask.done', state:'partial', said:'Only part of it went out: the card.', id:'abcdefgh1234'}, '*']]);  // the frame is sandboxed (opaque origin): sent to that frame only
});

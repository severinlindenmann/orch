const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const marker = source.slice(source.indexOf('// A shipped add-on page'));
const ORIGIN = 'http://127.0.0.1:8000';
// The Factory idea box: one click files the idea as the person's act. Everything the handler touches is faked.
function setup({shipped = true, kind = 'page', snapshot = false, result} = {}) {
  const calls = {acts:[], posts:[], toasts:[]};
  const frameWindow = {postMessage:(m, o) => calls.posts.push([m, o])};
  const frame = {contentWindow:frameWindow};
  const answer = result || {ok:true, status:200, state:{act_answer:{addon:'factory', answer:{order:'t_new123', started:true, text:'Idea saved. Your agent is writing the first draft.'}}}};
  const ctx = {snapshot, location:{origin:ORIGIN}, array:v => Array.isArray(v) ? v : [], clean:v => String(v ?? ''),
    route:() => ({kind, id:'factory'}), addons:() => [{name:'factory', shipped}], ticketOf:() => null,
    document:{querySelector:() => frame}, act:async (...a) => { calls.acts.push(a); return answer; },
    addEventListener(){}, window:{orch:{toast:t => calls.toasts.push(t)}}};
  ctx.orchFrameChan = () => 'ab'.repeat(16);  // the shown frame's per-frame code (settings.js, ORCH-186)
  vm.createContext(ctx); vm.runInContext(marker, ctx);
  return {ctx, calls, frameWindow, frame};
}
const msg = (frameWindow, extra = {}) => ({origin:ORIGIN, source:frameWindow, data:{type:'orch.idea', id:'abcdefgh1234', text:'A page with our opening hours', ...extra}});
const plain = v => JSON.parse(JSON.stringify(v));

test('only the shown shipped add-on frame of this origin may ask; anything else is ignored', () => {
  const {ctx, frameWindow} = setup();
  assert.equal(ctx.embedIdeaRequest(msg(frameWindow)).text, 'A page with our opening hours');
  assert.equal(ctx.embedIdeaRequest(msg(frameWindow)).addon, 'factory');
  assert.equal(ctx.embedIdeaRequest({...msg(frameWindow), origin:'https://evil.example'}), null);
  // ORCH-186: the shown shipped frame is sandboxed (origin "null"): it must carry its per-frame code
  assert.equal(ctx.embedIdeaRequest({...msg(frameWindow), origin:'null'}), null);
  const coded = {...msg(frameWindow), origin:'null'}; coded.data = {...coded.data, chan:'ab'.repeat(16)};
  assert.notEqual(ctx.embedIdeaRequest(coded), null);
  assert.equal(ctx.embedIdeaRequest({...coded, data:{...coded.data, chan:'cd'.repeat(16)}}), null);
  assert.equal(ctx.embedIdeaRequest({...coded, source:{}}), null);  // ...and come from that frame
  assert.equal(ctx.embedIdeaRequest({...msg(frameWindow), source:{}}), null);
  assert.equal(ctx.embedIdeaRequest({...msg(frameWindow), source:null}), null);
  for (const bad of [{type:'orch.say'}, {type:'orch.idea.done'}, {id:'x'}, {id:5}, {id:'ABCDEFGH'}, {text:5}, {text:'   '}, {text:'---'}]) assert.equal(ctx.embedIdeaRequest(msg(frameWindow, bad)), null);
  let s = setup({shipped:false}); assert.equal(s.ctx.embedIdeaRequest(msg(s.frameWindow)), null);
  s = setup({kind:'ticket'}); assert.equal(s.ctx.embedIdeaRequest(msg(s.frameWindow)), null);
  s = setup({snapshot:true}); assert.equal(s.ctx.embedIdeaRequest(msg(s.frameWindow)), null);
});

test('text becomes one plain line: no controls, bidi or zero-width characters, no leading dash', () => {
  const {ctx, frameWindow} = setup();
  assert.equal(ctx.embedIdeaRequest(msg(frameWindow, {text:'-- Hours\npage‮​  with map\u0007'})).text, 'Hours page with map');
});

test("the person's click files the idea through the dashboard's own act and tells the page the order", async () => {
  const {ctx, calls, frameWindow} = setup();
  await ctx.fileEmbedIdea(ctx.embedIdeaRequest(msg(frameWindow)));
  assert.deepEqual(plain(calls.acts), [['addon.act', {addon:'factory', verb:'idea', target:'A page with our opening hours'}]]);
  assert.deepEqual(plain(calls.posts), [[{type:'orch.idea.done', order:'t_new123', id:'abcdefgh1234'}, '*']]);  // the frame is sandboxed (opaque origin): sent to that frame only
  assert.equal(calls.toasts.length, 1);
});

test('a refused act (no page session: watch-only) tells the page why, so it offers the Chat fallback', async () => {
  const {ctx, calls, frameWindow} = setup({result:{ok:false, status:403, text:'Sign in to do this: open the dashboard with a sign-in link from orch.'}});
  await ctx.fileEmbedIdea(ctx.embedIdeaRequest(msg(frameWindow)));
  assert.deepEqual(plain(calls.posts), [[{type:'orch.idea.failed', error:'Sign in to do this: open the dashboard with a sign-in link from orch.', id:'abcdefgh1234'}, '*']]);  // the frame is sandboxed (opaque origin): sent to that frame only
});

test("an answer without an order, or another add-on's answer, is a failure; too long is refused before any act", async () => {
  for (const state of [{}, {act_answer:{addon:'sync', answer:{order:'t_new123'}}}, {act_answer:{addon:'factory', answer:{order:'../x'}}}]) {
    const {ctx, calls, frameWindow} = setup({result:{ok:true, status:200, state}});
    await ctx.fileEmbedIdea(ctx.embedIdeaRequest(msg(frameWindow)));
    assert.equal(calls.posts[0][0].type, 'orch.idea.failed');
  }
  const {ctx, calls, frameWindow} = setup();
  await ctx.fileEmbedIdea(ctx.embedIdeaRequest(msg(frameWindow, {text:'x'.repeat(501)})));
  assert.equal(calls.acts.length, 0); assert.equal(calls.posts[0][0].type, 'orch.idea.failed');
});

test('a second click while saving files nothing twice', async () => {
  const {ctx, calls, frameWindow} = setup();
  const req = ctx.embedIdeaRequest(msg(frameWindow));
  await Promise.all([ctx.fileEmbedIdea(req), ctx.fileEmbedIdea(req)]);
  assert.equal(calls.acts.length, 1);
});

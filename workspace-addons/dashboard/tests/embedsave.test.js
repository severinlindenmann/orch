const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const marker = source.slice(source.indexOf('// A shipped add-on page'));
const ORIGIN = 'http://127.0.0.1:8000';
const TARGET = 'e_0123456789abcdef01234567', REV = 'a'.repeat(64), NEW = 'b'.repeat(64);
// Save in a shipped add-on page's editor (Skills, ORCH-840): only the shown shipped frame, only after a real click,
// an opaque id, a revision and the text; the dashboard runs that add-on's `save` act and tells the page.
function setup({shipped = true, kind = 'page', snapshot = false, clicked = true, result} = {}) {
  const calls = {acts:[], posts:[]};
  const frameWindow = {postMessage:(m, o) => calls.posts.push([m, o])};
  const frame = {contentWindow:frameWindow};
  const answer = result || {ok:true, status:200, state:{act_answer:{addon:'skills', answer:{revision:NEW, changed:true}}}};
  const ctx = {snapshot, location:{origin:ORIGIN}, array:v => Array.isArray(v) ? v : [], clean:v => String(v ?? ''),
    route:() => ({kind, id:'skills'}), addons:() => [{name:'skills', shipped}], ticketOf:() => null,
    document:{querySelector:() => frame}, act:async (...a) => { calls.acts.push(a); return answer; },
    navigator:{userActivation:{isActive:clicked}}, TextEncoder,
    addEventListener(){}, window:{orch:{toast(){}}}};
  vm.createContext(ctx); vm.runInContext(marker, ctx);
  return {ctx, calls, frameWindow};
}
const TEXT = JSON.stringify({text:'# Rules\n<img src=x onerror=alert(1)>\n'});
const msg = (frameWindow, extra = {}) => ({origin:ORIGIN, source:frameWindow, data:{type:'orch.save', id:'abcdefgh1234', target:TARGET, revision:REV, text:TEXT, ...extra}});
const plain = v => JSON.parse(JSON.stringify(v));

test('only the shown shipped add-on frame may ask, with an opaque id, a revision and a text', () => {
  const {ctx, frameWindow} = setup();
  const req = ctx.embedSaveRequest(msg(frameWindow));
  assert.deepEqual([req.addon, req.target, req.revision, req.text], ['skills', TARGET, REV, TEXT]);
  assert.equal(ctx.embedSaveRequest({...msg(frameWindow), origin:'https://evil.example'}), null);
  assert.equal(ctx.embedSaveRequest({...msg(frameWindow), source:{}}), null);
  for (const bad of [{type:'orch.act'}, {id:'x'}, {target:'skill:workspace:x'}, {target:'../AGENTS.md'}, {target:'e_' + '0'.repeat(23)},
    {target:TARGET + '\n'}, {revision:'x'}, {revision:REV.toUpperCase()}, {text:''}, {text:5}, {text:'a\u0000b'}, {addon:'other'}]) {
    const r = ctx.embedSaveRequest(msg(frameWindow, bad));
    if (bad.addon) assert.equal(r.addon, 'skills', 'the add-on comes from the shown page, never from the message');
    else assert.equal(r, null, JSON.stringify(bad));
  }
  let s = setup({shipped:false}); assert.equal(s.ctx.embedSaveRequest(msg(s.frameWindow)), null);
  s = setup({kind:'ticket'}); assert.equal(s.ctx.embedSaveRequest(msg(s.frameWindow)), null);
  s = setup({snapshot:true}); assert.equal(s.ctx.embedSaveRequest(msg(s.frameWindow)), null);
});

test("the person's Save runs the add-on's save with the text and tells the page the new revision", async () => {
  const {ctx, calls, frameWindow} = setup();
  await ctx.runEmbedSave(ctx.embedSaveRequest(msg(frameWindow)));
  assert.deepEqual(plain(calls.acts), [['addon.act', {addon:'skills', verb:'save', target:TARGET, value:REV, text:TEXT}]]);
  assert.deepEqual(plain(calls.posts), [[{type:'orch.save.done', revision:NEW, changed:true, id:'abcdefgh1234'}, '*']]);
});

test('without a click of the person nothing runs', async () => {
  const {ctx, calls, frameWindow} = setup({clicked:false});
  await ctx.runEmbedSave(ctx.embedSaveRequest(msg(frameWindow)));
  assert.equal(calls.acts.length, 0);
  assert.equal(calls.posts[0][0].type, 'orch.save.failed');
});

test('a stale save tells the page so', async () => {
  const {ctx, calls, frameWindow} = setup({result:{ok:false, status:409, text:'This file changed since you opened it.'}});
  await ctx.runEmbedSave(ctx.embedSaveRequest(msg(frameWindow)));
  assert.deepEqual(plain(calls.posts), [[{type:'orch.save.failed', error:'This file changed since you opened it.', stale:true, id:'abcdefgh1234'}, '*']]);
});

test('an answer without a new revision is not taken as saved', async () => {
  const {ctx, calls, frameWindow} = setup({result:{ok:true, status:200, state:{act_answer:{addon:'other', answer:{revision:NEW}}}}});
  await ctx.runEmbedSave(ctx.embedSaveRequest(msg(frameWindow)));
  assert.equal(calls.posts[0][0].type, 'orch.save.failed');
});

test('a too long text and a second click while saving run nothing', async () => {
  let s = setup();
  await s.ctx.runEmbedSave(s.ctx.embedSaveRequest(msg(s.frameWindow, {text:'é'.repeat(90 * 1024)})));
  assert.equal(s.calls.acts.length, 0);
  s = setup();
  const req = s.ctx.embedSaveRequest(msg(s.frameWindow));
  await Promise.all([s.ctx.runEmbedSave(req), s.ctx.runEmbedSave(req)]);
  assert.equal(s.calls.acts.length, 1);
});

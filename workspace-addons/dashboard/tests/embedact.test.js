const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const marker = source.slice(source.indexOf('// A shipped add-on page'));
const ORIGIN = 'http://127.0.0.1:8000';
// A shipped add-on page's own setting (Usage): the page names one verb and a target; the dashboard runs that add-on's act.
function setup({shipped = true, kind = 'page', snapshot = false, result} = {}) {
  const calls = {acts:[], posts:[]};
  const frameWindow = {postMessage:(m, o) => calls.posts.push([m, o])};
  const frame = {contentWindow:frameWindow};
  const answer = result || {ok:true, status:200, state:{act_answer:{addon:'usage', answer:{changed:true, next:'Saved.'}}}};
  const ctx = {snapshot, location:{origin:ORIGIN}, array:v => Array.isArray(v) ? v : [], clean:v => String(v ?? ''),
    route:() => ({kind, id:'usage'}), addons:() => [{name:'usage', shipped}], ticketOf:() => null,
    document:{querySelector:() => frame}, act:async (...a) => { calls.acts.push(a); return answer; },
    addEventListener(){}, window:{orch:{toast(){}}}};
  vm.createContext(ctx); vm.runInContext(marker, ctx);
  return {ctx, calls, frameWindow};
}
const msg = (frameWindow, extra = {}) => ({origin:ORIGIN, source:frameWindow, data:{type:'orch.act', id:'abcdefgh1234', verb:'limit', target:'a_abc123:week:90%', ...extra}});
const plain = v => JSON.parse(JSON.stringify(v));

test('only the shown shipped add-on frame of this origin may ask, with a plain verb and target', () => {
  const {ctx, frameWindow} = setup();
  const req = ctx.embedActRequest(msg(frameWindow));
  assert.deepEqual([req.addon, req.verb, req.target], ['usage', 'limit', 'a_abc123:week:90%']);
  assert.equal(ctx.embedActRequest({...msg(frameWindow), origin:'https://evil.example'}), null);
  assert.equal(ctx.embedActRequest({...msg(frameWindow), source:{}}), null);
  for (const bad of [{type:'orch.idea'}, {id:'x'}, {verb:'Limit'}, {verb:'refresh'}, {verb:'a b'}, {verb:5}, {target:''},
    {target:'-x'}, {target:' x'}, {target:'a\nb'}, {target:'a‮b'}, {target:'x'.repeat(201)}, {target:5}]) {
    assert.equal(ctx.embedActRequest(msg(frameWindow, bad)), null, JSON.stringify(bad));
  }
  let s = setup({shipped:false}); assert.equal(s.ctx.embedActRequest(msg(s.frameWindow)), null);
  s = setup({kind:'ticket'}); assert.equal(s.ctx.embedActRequest(msg(s.frameWindow)), null);
  s = setup({snapshot:true}); assert.equal(s.ctx.embedActRequest(msg(s.frameWindow)), null);
});

test("the person's click runs the shown add-on's act and tells the page", async () => {
  const {ctx, calls, frameWindow} = setup();
  await ctx.runEmbedAct(ctx.embedActRequest(msg(frameWindow)));
  assert.deepEqual(plain(calls.acts), [['addon.act', {addon:'usage', verb:'limit', target:'a_abc123:week:90%'}]]);
  assert.deepEqual(plain(calls.posts), [[{type:'orch.act.done', answer:{changed:true}, id:'abcdefgh1234'}, ORIGIN]]);
});

test('a refused act tells the page why, in the add-on’s words', async () => {
  const {ctx, calls, frameWindow} = setup({result:{ok:false, status:400, text:'A percent limit is at most 100%.'}});
  await ctx.runEmbedAct(ctx.embedActRequest(msg(frameWindow)));
  assert.deepEqual(plain(calls.posts), [[{type:'orch.act.failed', error:'A percent limit is at most 100%.', id:'abcdefgh1234'}, ORIGIN]]);
});

test('a second click while saving runs nothing twice and says so', async () => {
  const {ctx, calls, frameWindow} = setup();
  const req = ctx.embedActRequest(msg(frameWindow));
  await Promise.all([ctx.runEmbedAct(req), ctx.runEmbedAct(req)]);
  assert.equal(calls.acts.length, 1);
  assert.equal(calls.posts.filter(p => p[0].type === 'orch.act.failed').length, 1);
});

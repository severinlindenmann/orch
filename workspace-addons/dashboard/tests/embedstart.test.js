const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const marker = source.slice(source.indexOf('// A shipped add-on page'));
const ORIGIN = 'http://127.0.0.1:8000';
// Start on a parked Factory order (ORCH-277): every collaborator of the handler is faked.
function setup({shipped = true, kind = 'page', snapshot = false, clicked = true, foreign = false, answer = {question:'q7'}, ok = true} = {}) {
  const calls = {acts:[], posts:[], opened:[]};
  const frameWindow = {postMessage:(m, o) => calls.posts.push([m, o])};
  const frame = {contentWindow:frameWindow};
  const tickets = {t_aaaaaa:{id:'t_aaaaaa', status:'open', ext:foreign ? {other:{}} : {factory:{}}}};
  const ctx = {snapshot, location:{origin:ORIGIN}, array:v => Array.isArray(v) ? v : [], clean:v => String(v ?? ''),
    route:() => ({kind, id:'factory'}), addons:() => [{name:'factory', shipped}], ticketOf:id => tickets[id] || null,
    document:{querySelector:() => frame}, addEventListener(){}, mutation:0, accept(){},
    fetch:async () => ({ok:true, json:async () => ({})}),
    act:async (op, args) => { calls.acts.push([op, args]); return ok ? {ok:true, state:{act_answer:{addon:'factory', answer}}} : {ok:false, text:'This order is not saved for later any more.'}; },
    window:{orch:{toast(){}}}, navigator:{userActivation:{isActive:clicked}}};
  vm.createContext(ctx); vm.runInContext(marker, ctx);
  ctx.openEmbedQuestion = req => calls.opened.push([req.ticket, req.question, req.frame === frame]);
  return {ctx, calls, frameWindow};
}
const msg = (frameWindow, extra = {}) => ({origin:ORIGIN, source:frameWindow, data:{type:'orch.start', id:'abcdefgh1234', order:'t_aaaaaa', ...extra}});
const plain = v => JSON.parse(JSON.stringify(v));

test('only the shown shipped add-on frame of this origin may ask, with one valid order id', () => {
  const {ctx, frameWindow} = setup();
  assert.equal(ctx.embedStartRequest(msg(frameWindow)).order, 't_aaaaaa');
  assert.equal(ctx.embedStartRequest({...msg(frameWindow), origin:'https://evil.example'}), null);
  assert.equal(ctx.embedStartRequest({...msg(frameWindow), source:{}}), null);
  for (const bad of [{type:'orch.idea'}, {id:'X'}, {order:'../x'}, {order:5}, {order:undefined}]) assert.equal(ctx.embedStartRequest(msg(frameWindow, bad)), null);
  let s = setup({shipped:false}); assert.equal(s.ctx.embedStartRequest(msg(s.frameWindow)), null);
  s = setup({kind:'ticket'}); assert.equal(s.ctx.embedStartRequest(msg(s.frameWindow)), null);
  s = setup({snapshot:true}); assert.equal(s.ctx.embedStartRequest(msg(s.frameWindow)), null);
});

test('one click runs the add-on start act and opens the new question in the dashboard card', async () => {
  const {ctx, calls, frameWindow} = setup();
  await ctx.startEmbedOrder(ctx.embedStartRequest(msg(frameWindow)));
  assert.deepEqual(plain(calls.acts), [['addon.act', {addon:'factory', verb:'start', target:'t_aaaaaa'}]]);
  assert.deepEqual(plain(calls.posts), [[{type:'orch.start.done', question:'q7', id:'abcdefgh1234'}, '*']]);
  assert.deepEqual(calls.opened, [['t_aaaaaa', 'q7', true]]);  // the person presses Start there, not here
});

test('a refused act tells the page why and opens nothing', async () => {
  const {ctx, calls, frameWindow} = setup({ok:false});
  await ctx.startEmbedOrder(ctx.embedStartRequest(msg(frameWindow)));
  assert.equal(calls.posts[0][0].type, 'orch.start.failed');
  assert.match(calls.posts[0][0].error, /not saved for later/);
  assert.equal(calls.opened.length, 0);
  const s = setup({answer:{question:'<b>'}});
  await s.ctx.startEmbedOrder(s.ctx.embedStartRequest(msg(s.frameWindow)));
  assert.equal(s.calls.posts[0][0].type, 'orch.start.failed'); assert.equal(s.calls.opened.length, 0);
});

test('another add-on\'s ticket, or no click of the person, does nothing', async () => {
  let s = setup({foreign:true});
  await s.ctx.startEmbedOrder(s.ctx.embedStartRequest(msg(s.frameWindow)));
  assert.equal(s.calls.acts.length, 0); assert.equal(s.calls.posts[0][0].type, 'orch.start.failed');
  s = setup({clicked:false});
  await s.ctx.startEmbedOrder(s.ctx.embedStartRequest(msg(s.frameWindow)));
  assert.equal(s.calls.acts.length, 0);
  assert.deepEqual(plain(s.calls.posts), [[{type:'orch.start.failed', error:'Click the button again to do this.', id:'abcdefgh1234'}, '*']]);
});

test('a second click while one runs does nothing', async () => {
  const {ctx, calls, frameWindow} = setup();
  const req = ctx.embedStartRequest(msg(frameWindow));
  await Promise.all([ctx.startEmbedOrder(req), ctx.startEmbedOrder(req)]);
  assert.equal(calls.acts.length, 1);
});

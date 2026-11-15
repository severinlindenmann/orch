const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const marker = source.slice(source.indexOf('// A shipped add-on page'));
const ORIGIN = 'http://127.0.0.1:8000';
// Plan the run / Ask for changes on a Factory draft: the dashboard sends the words as the person's message (run.send,
// proven by the page) and starts the agent when none works. Everything the handler touches is faked.
function setup({shipped = true, kind = 'page', snapshot = false, status = 'ready', ext = {factory:{role:'order'}}, results = {}} = {}) {
  const calls = {acts:[], posts:[]};
  const frameWindow = {postMessage:(m, o) => calls.posts.push([m, o])};
  const frame = {contentWindow:frameWindow};
  const tickets = [{id:'t_order01', title:'Hours page', status, ext}, {id:'t_other01', title:'Other', status:'ready', ext:{sync:{}}}];
  const ctx = {snapshot, location:{origin:ORIGIN}, array:v => Array.isArray(v) ? v : [], clean:v => String(v ?? ''),
    route:() => ({kind, id:'factory'}), addons:() => [{name:'factory', shipped}], ticketOf:id => tickets.find(t => t.id === id),
    document:{querySelector:() => frame}, act:async (op, args) => { calls.acts.push([op, args]); return results[op] || {ok:true, status:200, state:{}}; },
    addEventListener(){}, window:{orch:{toast(){}}}};
  vm.createContext(ctx); vm.runInContext(marker, ctx);
  return {ctx, calls, frameWindow};
}
const msg = (frameWindow, extra = {}) => ({origin:ORIGIN, source:frameWindow, data:{type:'orch.send', id:'abcdefgh1234', ticket:'t_order01', text:'Now plan the run.', ...extra}});
const plain = v => JSON.parse(JSON.stringify(v));

test('only the shown shipped add-on frame of this origin, for a ticket of its own add-on, may ask', () => {
  const {ctx, frameWindow} = setup();
  assert.equal(ctx.embedSendRequest(msg(frameWindow)).ticket, 't_order01');
  assert.equal(ctx.embedSendRequest({...msg(frameWindow), origin:'https://evil.example'}), null);
  assert.equal(ctx.embedSendRequest({...msg(frameWindow), origin:'null'}), null);
  assert.equal(ctx.embedSendRequest({...msg(frameWindow), source:{}}), null);
  assert.equal(ctx.embedSendRequest({...msg(frameWindow), source:null}), null);
  for (const bad of [{type:'orch.idea'}, {type:'orch.send.done'}, {id:'x'}, {ticket:'t_other01'}, {ticket:'t_zzzzzz'}, {ticket:'../x'}, {text:5}, {text:'  \n '}]) assert.equal(ctx.embedSendRequest(msg(frameWindow, bad)), null);
  let s = setup({shipped:false}); assert.equal(s.ctx.embedSendRequest(msg(s.frameWindow)), null);
  s = setup({kind:'ticket'}); assert.equal(s.ctx.embedSendRequest(msg(s.frameWindow)), null);
  s = setup({snapshot:true}); assert.equal(s.ctx.embedSendRequest(msg(s.frameWindow)), null);
  s = setup({ext:null}); assert.equal(s.ctx.embedSendRequest(msg(s.frameWindow)), null);
});

test('hidden characters go, line breaks stay', () => {
  const {ctx, frameWindow} = setup();
  assert.equal(ctx.embedSendRequest(msg(frameWindow, {text:'Change: shorter\nadd a map‮​\u0007'})).text, 'Change: shorter\nadd a map');
});

test("the click sends the person's message with the dashboard's own run.send, then starts the agent", async () => {
  const {ctx, calls, frameWindow} = setup();
  await ctx.sendEmbedMessage(ctx.embedSendRequest(msg(frameWindow)));
  assert.deepEqual(plain(calls.acts), [['run.send', {ticket:'t_order01', text:'Now plan the run.'}], ['run.start', {ticket:'t_order01'}]]);
  assert.deepEqual(plain(calls.posts), [[{type:'orch.send.done', ticket:'t_order01', started:true, id:'abcdefgh1234'}, ORIGIN]]);
});

test('an agent already working gets the message without a second start', async () => {
  const {ctx, calls, frameWindow} = setup({status:'active'});
  await ctx.sendEmbedMessage(ctx.embedSendRequest(msg(frameWindow)));
  assert.deepEqual(calls.acts.map(a => a[0]), ['run.send']);
  assert.equal(calls.posts[0][0].type, 'orch.send.done');
});

test('a refused send (no page session: watch-only) starts nothing and tells the page why', async () => {
  const {ctx, calls, frameWindow} = setup({results:{'run.send':{ok:false, status:403, text:'Open the dashboard from this computer to do this.'}}});
  await ctx.sendEmbedMessage(ctx.embedSendRequest(msg(frameWindow)));
  assert.deepEqual(calls.acts.map(a => a[0]), ['run.send']);
  assert.deepEqual(plain(calls.posts), [[{type:'orch.send.failed', error:'Open the dashboard from this computer to do this.', id:'abcdefgh1234'}, ORIGIN]]);
});

test('too long is refused before any act; a second click while sending sends once', async () => {
  let s = setup();
  await s.ctx.sendEmbedMessage(s.ctx.embedSendRequest(msg(s.frameWindow, {text:'x'.repeat(2001)})));
  assert.equal(s.calls.acts.length, 0); assert.equal(s.calls.posts[0][0].type, 'orch.send.failed');
  s = setup();
  const req = s.ctx.embedSendRequest(msg(s.frameWindow));
  await Promise.all([s.ctx.sendEmbedMessage(req), s.ctx.sendEmbedMessage(req)]);
  assert.equal(s.calls.acts.filter(a => a[0] === 'run.send').length, 1);
});

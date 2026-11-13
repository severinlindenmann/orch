const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const marker = source.slice(source.indexOf('// A shipped add-on page'));
// Everything the handler touches is faked; `calls` records every act (answer request) and mounted card.
function setup({shipped = true, kind = 'page', tickets, snapshot = false, fresh} = {}) {
  const calls = {acts:[], mounts:[], opened:[], posts:[], dialogs:[]};
  const frameWindow = {postMessage:(m, o) => calls.posts.push([m, o])};
  const frame = {contentWindow:frameWindow};
  const t = tickets || [{id:'t_abcdef', key:'FAC-1', title:'Ship it', questions:[{id:'q1', text:'Start?', digest:'d', options:['Start', 'Not now'], recommended:'Start', answer:null}, {id:'q0', text:'Old', answer:'x'}]}];
  const ctx = {snapshot, location:{origin:'http://127.0.0.1:8000'}, array:v => Array.isArray(v) ? v : [], clean:v => String(v ?? ''),
    route:() => ({kind, id:'factory'}), addons:() => [{name:'factory', shipped}], ticketOf:id => t.find(x => x.id === id || x.key === id),
    document:{querySelector:() => frame}, el:(tag, cls, text) => ({tag, cls, text, children:[], append(...c) { this.children.push(...c); }}),
    dialog:title => { const d = {title, children:[], open:true, isConnected:true, listeners:{}, append(...c) { this.children.push(...c); }, addEventListener(n, f) { this.listeners[n] = f; }}; calls.dialogs.push(d); return {d, actions:{}}; },
    mountQuestion:(host, q, context) => { calls.mounts.push([q, context]); }, act:async (...a) => { calls.acts.push(a); return {ok:true}; },
    mutation:0, fetched:[], fetch:async url => { ctx.fetched.push(url); return {ok:true, json:async () => ({tickets:fresh || t})}; },
    accept:next => { t.splice(0, t.length, ...next.tickets); },
    addEventListener(){}, window:{orch:{open:d => calls.opened.push(d)}}};
  vm.createContext(ctx); vm.runInContext(marker, ctx);
  return {ctx, calls, frameWindow, frame};
}
const good = (frameWindow, extra = {}) => ({origin:'http://127.0.0.1:8000', source:frameWindow, data:{type:'orch.question', ticket:'t_abcdef', question:'q1', ...extra}});
test('a valid message from the embedded shipped add-on iframe is accepted', () => {
  const {ctx, frameWindow} = setup();
  const req = ctx.embedQuestionRequest(good(frameWindow));
  assert.equal(req.ticket, 't_abcdef'); assert.equal(req.question, 'q1');
});
test('foreign origin, other frame or window, null source, wrong type, bad ids are ignored', () => {
  const {ctx, frameWindow} = setup();
  assert.equal(ctx.embedQuestionRequest({...good(frameWindow), origin:'https://evil.example'}), null);
  assert.equal(ctx.embedQuestionRequest({...good(frameWindow), origin:'null'}), null);
  assert.equal(ctx.embedQuestionRequest({...good({}), source:{}}), null);
  assert.equal(ctx.embedQuestionRequest({...good(frameWindow), source:null}), null);
  assert.equal(ctx.embedQuestionRequest(good(frameWindow, {type:'orch.answer'})), null);
  assert.equal(ctx.embedQuestionRequest(good(frameWindow, {type:'orch.question.done'})), null);
  for (const bad of [{ticket:'t_a; rm'}, {ticket:'../x'}, {ticket:5}, {question:'q1 x'}, {question:''}, {question:{}}]) assert.equal(ctx.embedQuestionRequest(good(frameWindow, bad)), null);
  assert.equal(ctx.embedQuestionRequest({origin:'http://127.0.0.1:8000', source:frameWindow, data:'orch.question'}), null);
});
test('only a shipped add-on page that is on screen may ask', () => {
  let s = setup({shipped:false}); assert.equal(s.ctx.embedQuestionRequest(good(s.frameWindow)), null);
  s = setup({kind:'ticket'}); assert.equal(s.ctx.embedQuestionRequest(good(s.frameWindow)), null);
});
test('opening shows the dashboard-owned question, takes nothing from the message, and sends no answer', async () => {
  const {ctx, calls, frame} = setup();
  await ctx.openEmbedQuestion({ticket:'t_abcdef', question:'q1', frame, text:'INJECTED', options:['evil']});
  assert.equal(calls.mounts.length, 1);
  const [q, context] = calls.mounts[0];
  assert.equal(q.title, 'Start?'); assert.deepEqual(q.options.map(o => o.text), ['Start', 'Not now']);
  assert.equal(calls.acts.length, 0, 'nothing is answered until the person presses an option');
  assert.equal(calls.posts.length, 0);
  context.onAnswered();
  assert.deepEqual(JSON.parse(JSON.stringify(calls.posts)), [[{type:'orch.question.done', ticket:'t_abcdef', question:'q1'}, 'http://127.0.0.1:8000']]);
});
test('an unknown or already answered question says so plainly and mounts no card', async () => {
  const {ctx, calls, frame} = setup();
  for (const [ticket, question] of [['t_abcdef', 'q0'], ['t_abcdef', 'q9'], ['t_zzzzzz', 'q1']]) {
    await ctx.openEmbedQuestion({ticket, question, frame});
    const d = calls.dialogs[calls.dialogs.length - 1]; d.open = false; d.listeners.close();  // the person closes it
  }
  assert.equal(calls.mounts.length, 0); assert.equal(calls.acts.length, 0);
  assert.equal(calls.dialogs.length, 3);
  for (const d of calls.dialogs) assert.match(JSON.stringify(d), /no longer waiting for you/);
});
test('the message handler never calls act', () => {
  assert.doesNotMatch(marker, /\bact\(/);
});

test('a shared read-only snapshot opens nothing', () => {
  const {ctx, frameWindow} = setup({snapshot:true});
  assert.equal(ctx.embedQuestionRequest(good(frameWindow)), null);
});
test('repeated asks never stack dialogs; a closed dialog allows the next one', async () => {
  const {ctx, calls, frameWindow} = setup();
  const req = ctx.embedQuestionRequest(good(frameWindow));
  await Promise.all([ctx.openEmbedQuestion(req), ctx.openEmbedQuestion(req), ctx.openEmbedQuestion(req)]);
  assert.equal(calls.dialogs.length, 1);
  calls.dialogs[0].open = false; calls.dialogs[0].listeners.close();
  await ctx.openEmbedQuestion(req);
  assert.equal(calls.dialogs.length, 2);
  assert.equal(calls.acts.length, 0);
});

test('the question is read fresh from the server, so a question the cached state lacks still opens its card', async () => {
  const stale = [{id:'t_abcdef', key:'FAC-1', title:'Ship it', questions:[]}];
  const now = [{id:'t_abcdef', key:'FAC-1', title:'Ship it', questions:[{id:'q1', text:'Start?', digest:'d', options:['Start'], answer:null}]}];
  const {ctx, calls, frame} = setup({tickets:stale, fresh:now});
  await ctx.openEmbedQuestion({ticket:'t_abcdef', question:'q1', frame});
  assert.deepEqual(ctx.fetched, ['/api/state?fresh=1']);
  assert.equal(calls.mounts.length, 1);
  assert.doesNotMatch(JSON.stringify(calls.dialogs), /no longer waiting/);
});
test('a fresh read that says the question is answered still says it is no longer waiting', async () => {
  const stale = [{id:'t_abcdef', key:'FAC-1', title:'Ship it', questions:[{id:'q1', text:'Start?', answer:null}]}];
  const now = [{id:'t_abcdef', key:'FAC-1', title:'Ship it', questions:[{id:'q1', text:'Start?', answer:'Start'}]}];
  const {ctx, calls, frame} = setup({tickets:stale, fresh:now});
  await ctx.openEmbedQuestion({ticket:'t_abcdef', question:'q1', frame});
  assert.equal(calls.mounts.length, 0);
  assert.match(JSON.stringify(calls.dialogs), /no longer waiting/);
});

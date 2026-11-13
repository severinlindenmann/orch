const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const H = require(path.join(WEB, 'helpers.js'));

test('a conflict reads plainly: no id, actor name or UTC time', () => {
  const raw = 'Ticket t_d17r8g was changed by agent:claude at 12:08. Reload the page and try again.';
  assert.equal(H.scrubText(raw), 'Claude just changed this ticket \u2014 updated.');
  assert.equal(H.scrubText('Ticket t_d17r8g was changed by human:lume at 09:01.'), 'Someone just changed this ticket \u2014 updated.');
});
test('any other notice loses ids, actor names and times', () => {
  const out = H.scrubText('agent:claude moved t_abc123 at 12:08 UTC; stamp 2026-11-08T12:08:00Z, by human:lume');
  assert.doesNotMatch(out, /t_[a-z0-9]+|agent:|human:|\d{1,2}:\d{2}|T\d\d:/);
  assert.equal(H.scrubText('Saved.'), 'Saved.');
});
test('every toast/error path in the dashboard goes through the scrub', () => {
  const files = ['app.js', 'pages/home.js', 'pages/ticket.js', 'pages/tickets.js', 'pages/newticket.js', 'pages/settings.js'];
  for (const f of files) {
    const src = fs.readFileSync(path.join(WEB, f), 'utf8');
    assert.doesNotMatch(src, /Reload the (page|ticket)/, f + ' tells the person to reload');
  }
  const app = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
  assert.match(app, /window\.orch\.toast = .*scrubText/s, 'the one toast is wrapped with scrubText');
});
test('actRetry reloads and retries once, only while the intent still applies', async () => {
  const src = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
  const start = src.indexOf('async function actRetry'), end = src.indexOf('window.orchAct');
  const calls = [];
  let results = [{ok: false, status: 409, text: 'x'}, {ok: true, status: 200}];
  const ctx = {snapshot: false, accepted: 0, fetch: async () => ({ok: true, json: async () => ({})}), accept() { ctx.accepted++; },
    act: async (op, args) => { calls.push(args); return results.shift(); }};
  vm.createContext(ctx); vm.runInContext(src.slice(start, end), ctx);
  let rev = 1;
  let res = await ctx.actRetry('ticket.patch', () => ({rev: rev++}), () => true);
  assert.equal(res.ok, true); assert.equal(calls.length, 2); assert.equal(ctx.accepted, 1); assert.deepEqual(calls.map(c => c.rev), [1, 2]);
  calls.length = 0; results = [{ok: false, status: 409, text: 'x'}, {ok: true}];
  res = await ctx.actRetry('ticket.patch', () => ({}), () => false);
  assert.equal(res.status, 409); assert.equal(calls.length, 1);
  calls.length = 0; results = [{ok: false, status: 422, text: 'no'}, {ok: true}];
  res = await ctx.actRetry('ticket.patch', () => ({}), () => true);
  assert.equal(res.status, 422); assert.equal(calls.length, 1);
  calls.length = 0; results = [{ok: false, status: 409}, {ok: false, status: 409}, {ok: true}];
  res = await ctx.actRetry('ticket.patch', () => ({}), () => true);
  assert.equal(calls.length, 2); assert.equal(res.status, 409); // once, never a loop
});
const entry = (by, text, at) => ({by, text, at: at || '2026-11-08T12:10:00Z'});
test('"Ask for changes" reads "You asked for changes" with the note', () => {
  const checklist = [{id: 'c1', text: 'Change: make the header blue'}];
  const history = [entry('human:lume', 'Added check c1', '2026-11-08T12:09:58Z'), entry('human:lume', 'Patched status (status review -> active)')];
  const rows = H.historyView(history, checklist, 'human:lume');
  assert.equal(rows.length, 1);
  assert.equal(rows[0].sentence, 'You asked for changes: make the header blue');
  assert.equal(H.historyView(history, checklist, 'human:other')[0].sentence, 'Lume asked for changes: make the header blue');
});
test('other person lines are plain sentences', () => {
  const v = (text, me = 'human:lume') => H.historyView([entry('human:lume', text)], [], me)[0].sentence;
  assert.equal(v('Status review -> done'), 'You marked it Done');
  assert.equal(v('Patched status (status active -> ready)'), 'You moved it to To do');
  assert.equal(v('Patched title, owner'), 'You changed the title and the owner');
  assert.equal(H.historyView([entry('agent:claude', 'Status active -> review')], [], 'human:lume')[0].sentence, null);
});
test('parts group under their parent whether `parent` holds the id or the key', () => {
  const mk = (id, key, parent) => ({id, key, parent, title: id, created_at: '2026-11-08T10:00:0' + id.slice(-1) + 'Z', status: 'open'});
  for (const ref of ['t_p1', 'PIL-2']) {
    const rows = H.treeRows([mk('t_c1', 'PIL-10', ref), mk('t_p1', 'PIL-2', null), mk('t_c2', 'PIL-11', ref)]);
    assert.deepEqual(rows.map(r => [r.ticket.key, r.depth, r.children]), [['PIL-2', 0, 2], ['PIL-10', 1, 0], ['PIL-11', 1, 0]]);
    assert.equal(rows[1].parentMissing, false);
  }
});

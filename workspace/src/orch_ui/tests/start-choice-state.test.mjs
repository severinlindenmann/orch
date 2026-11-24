// ORCH-485: the Start choice's logic (static/start-choice-state.js): the main button, greyed reasons, one run per
// double click, Starting until the helper runs, quiet Busy and queued replies.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const S = require('../static/start-choice-state.js');

function fakeClock() {
  let next = 1; const timers = new Map();
  return {
    setTimeout: (f, ms) => { const id = next++; timers.set(id, {f, ms}); return id; },
    clearTimeout: id => timers.delete(id),
    fire() { const all = [...timers.values()]; timers.clear(); all.forEach(t => t.f()); },
    get size() { return timers.size; },
  };
}
const tick = () => new Promise(r => setImmediate(r));

test('the main button says Continue when an earlier session can be reopened, else Start; both send a plain start', () => {
  const none = S.sessions({sessions: []}, new Date());
  assert.deepEqual(S.main(none), {what: 'start', label: 'Start helper'});
  const away = S.sessions({sessions: [{id: 's1', title: 'x', reopenable: false, last_used: '2026-11-17T10:00:00Z'}]}, new Date());
  assert.equal(S.main(away).what, 'start', 'a session on another computer cannot be continued here');
  const here = S.sessions({sessions: [{id: 's2', title: 'y', reopenable: true, turns: 3, last_used: '2026-11-17T10:00:00Z'}]}, new Date());
  assert.deepEqual(S.main(here), {what: 'continue', label: 'Continue'});
  assert.deepEqual(S.main(none, {label: 'Send and start helper'}), {what: 'start', label: 'Send and start helper'});
  assert.equal(S.main(S.sessions(null)).what, 'start', 'while the list loads the button says Start');
});

test('ORCH-667: a stopped helper keeps its conversation as the one in use; Continue offers it', () => {
  // the real /api/sessions row after a stop: current true, reopenable false (the server continues it on a plain start)
  const kept = {id: 's1', title: 'Ship it', current: true, reopenable: false, readable: true, turns: 3, last_used: '2026-11-18T20:30:00Z'};
  const v = S.sessions({available: true, sessions: [kept]}, new Date());
  assert.deepEqual(S.main(v), {what: 'continue', label: 'Continue'});
  assert.equal(S.last(v.rows).id, 's1');
  const gone = S.sessions({sessions: [{...kept, readable: false}]}, new Date());
  assert.equal(S.main(gone).what, 'start', 'a kept conversation whose file is gone cannot be continued');
  const both = S.sessions({sessions: [kept, {id: 's0', title: 'Old', reopenable: true, readable: true, turns: 2, last_used: '2026-11-17T10:00:00Z'}]}, new Date());
  assert.equal(S.last(both.rows).id, 's1', 'the one in use is what a plain start continues');
});

test('a fresh start sends the tool only when it is not the usual one, the model only when it changed', () => {
  const cur = S.model({model: {name: 'opus', by: 'orch'}});
  assert.deepEqual(S.freshOps('t_1', {tool: 'claude', model: 'opus'}, 'claude', cur), [['run.start', {ticket: 't_1', fresh: true}]]);
  assert.deepEqual(S.freshOps('t_1', {tool: 'codex', model: 'sonnet'}, 'claude', cur),
    [['ticket.model', {ticket: 't_1', model: 'sonnet'}], ['run.start', {ticket: 't_1', fresh: true, agent: 'codex'}]]);
  assert.deepEqual(S.model(null), {name: 'sonnet', auto: true});
});

test('every greyed choice says why in one plain sentence', () => {
  const t = S.tools([{name: 'claude', label: 'Claude Code', models: true, chosen: true}, {name: 'codex', label: 'Codex', found: false}]);
  assert.deepEqual(t.tools.map(x => x.name), ['claude'], 'a tool not found on this computer is not offered');
  assert.equal(S.why('fresh', {tools: t}), '');
  assert.equal(S.why('main', {starting: true}), 'The helper is starting.');
  assert.equal(S.why('fresh', {running: true}), 'A helper is already working on this ticket.');
  assert.equal(S.why('reopen', {running: true}), 'Stop the helper to reopen an earlier session.');
  assert.match(S.why('main', {inLine: true}), /waits in line/);
  assert.equal(S.why('fresh', {tools: S.tools([])}), 'No helper tool is set up on this computer.');
  assert.equal(S.why('model', {tool: {models: false}}), 'This tool uses its own model.');
  const away = S.sessionRow({id: 's', reopenable: false}, new Date());
  assert.equal(S.why('reopen', {row: away}), 'On another computer, so it cannot be reopened here.');
  assert.equal(S.why('reopen', {row: S.sessionRow({id: 's', current: true}, new Date())}), 'This session is in use now.');
  assert.equal(S.why('reopen', {row: S.sessionRow({id: 's', reopenable: true}, new Date())}), '');
});

test('places: plain words with the right singular and plural, a full line says a start waits', () => {
  const p = S.places({a: {running: true}, b: {running: true, claim: {mode: 'headless'}}}, {live_max: 6}, {waiting: ['t_9']});
  assert.equal(S.placesText(p), 'A start uses 1 of 6 helper places. Now 1 of 6 is in use. 1 ticket waits in line.');
  assert.deepEqual(S.inLine(p, 't_9'), {at: 1, of: 1});
  const full = S.places({a: {running: true}}, {live_max: 1}, {});
  assert.match(S.placesText(full), /^The one helper place is in use\. A start waits in line/);
});

test('a double click starts one run, and the button stays Starting until the helper runs', async () => {
  const clock = fakeClock(), sent = [], events = [];
  const st = S.starter({clock, send: async (op, args) => { sent.push([op, args]); return {ok: true}; }});
  st.subscribe(e => events.push(e.state));
  const a = st.start('t_1', [['run.start', {ticket: 't_1'}]]);
  const b = st.start('t_1', [['run.start', {ticket: 't_1'}]]);
  assert.deepEqual(await b, {ok: true, again: true});
  await a;
  assert.equal(sent.length, 1, 'only one start went to the server');
  assert.equal(st.starting('t_1'), true, 'the reply came but no helper is seen yet: still Starting');
  assert.equal((await st.start('t_1', [['run.start', {ticket: 't_1'}]])).again, true, 'a click after the reply still does nothing');
  st.seen('t_1', false);
  assert.equal(st.starting('t_1'), true);
  st.seen('t_1', true);
  assert.equal(st.starting('t_1'), false);
  assert.equal(clock.size, 0, 'the slow timer is gone');
  assert.deepEqual(events, ['starting', 'started', 'running']);
});

test('a second start the server refuses as busy is quiet; a queued start is not a failure; a real refusal ends Starting', async () => {
  const replies = {t_b: {ok: false, text: 'An agent is already working on this ticket (started by lume today 11:02).'},
    t_q: {ok: false, text: 'All helper places are in use: ORCH-9 waits in line.'}, t_f: {ok: false, text: 'Unknown tool.'}};
  const events = [];
  const st = S.starter({clock: fakeClock(), send: async (op, args) => replies[args.ticket]});
  st.subscribe(e => events.push([e.ticket, e.state]));
  for (const t of Object.keys(replies)) await st.start(t, [['run.start', {ticket: t}]]);
  assert.deepEqual(events.filter(e => e[1] !== 'starting'), [['t_b', 'quiet'], ['t_q', 'queued'], ['t_f', 'failed']]);
  assert.equal(Object.keys(replies).some(t => st.starting(t)), false);
});

test('ops run in order and stop at the first refusal; a helper that never shows ends Starting with a plain line', async () => {
  const clock = fakeClock(), sent = [];
  const st = S.starter({clock, send: async op => { sent.push(op); return {ok: op !== 'ticket.model'}; }});
  await st.start('t_1', [['ticket.model', {}], ['run.start', {}]]);
  assert.deepEqual(sent, ['ticket.model'], 'the start is not sent when the model change was refused');
  const st2 = S.starter({clock, send: async () => ({ok: true})});
  const ev = [];
  st2.subscribe(e => ev.push(e));
  await st2.start('t_2', [['run.start', {}]]);
  clock.fire();
  assert.equal(st2.starting('t_2'), false);
  assert.equal(ev.at(-1).state, 'slow');
  assert.match(ev.at(-1).text, /did not show up yet/);
});

test('a helper seen before the reply comes ends Starting at once and the late reply changes nothing', async () => {
  let release;
  const st = S.starter({clock: fakeClock(), send: () => new Promise(r => { release = r; })});
  const p = st.start('t_1', [['run.start', {}]]);
  await tick();
  st.seen('t_1', true);
  assert.equal(st.starting('t_1'), false);
  release({ok: true});
  await p;
  assert.equal(st.starting('t_1'), false);
});

test('a send that throws ends Starting as a failure', async () => {
  const st = S.starter({clock: fakeClock(), send: async () => { throw new Error('net'); }});
  const ev = [];
  st.subscribe(e => ev.push(e.state));
  await st.start('t_1', [['run.start', {}]]);
  assert.deepEqual(ev, ['starting', 'failed']);
  assert.equal(st.starting('t_1'), false);
});

test('the short places line: N of M in use, the full sentence when every place is taken, nothing with no limit and no helper', () => {
  const S = require('../static/start-choice-state.js');
  const p = (used, max, waiting = []) => ({used, max, waiting, full: max !== null && used >= max});
  assert.equal(S.placesShort(p(4, 6)), '4 of 6 places in use');
  assert.equal(S.placesShort(p(2, 6, ['t_a'])), '2 of 6 places in use · 1 ticket waits');
  assert.equal(S.placesShort(p(0, null)), '');
  assert.equal(S.placesShort(p(1, null)), '1 helper working');
  assert.match(S.placesShort(p(6, 6)), /^All 6 helper places are in use\..*waits in line/);
});

test('ORCH-1362: a failed start names the steps that did not go through, so Try again sends a message only once', async () => {
  const st = S.starter({clock: fakeClock(), send: async op => ({ok: op !== 'run.start', text: op === 'run.start' ? 'No helper place free.' : ''})});
  const ev = [];
  st.subscribe(e => ev.push(e));
  await st.start('t_1', [['run.send', {text: 'hi'}], ['run.start', {}]]);
  const failed = ev.find(e => e.state === 'failed');
  assert.deepEqual(failed.rest, [['run.start', {}]], 'the sent message is not in what Try again sends');
});

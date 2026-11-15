// #692.1: a command step folds its end event into one block; a failed try followed by the working retry is one step.
const test = require('node:test'), assert = require('node:assert'), vm = require('node:vm'), fs = require('node:fs'), path = require('node:path');
const web = f => fs.readFileSync(path.join(__dirname, '..', 'src', 'orch_focus', 'web', f), 'utf8');

function live() {
  const S = {h: () => ({}), TID: 't_1', toast() {}, els: {}, act() {}, STATUS_WORD: {}, plainNames: x => x, keyOf: JSON.stringify,
    hhmm: x => x, evText: () => '', reduce: true, state: {}, views: {}, register: (n, m) => { S.views[n] = m; }};
  const ctx = vm.createContext({window: {FocusStore: S}, requestAnimationFrame: f => f(), document: {}});
  vm.runInContext(web('live.js'), ctx);
  return S.views.live;
}
const start = (at, id, text, command) => ({kind: 'tool.start', at, agent: 'main', text, data: {id, command}});
const end = (at, id, ok, output, text = 'x', ms = 1000) => ({kind: 'tool.end', at, agent: 'main', text, data: {id, ok, ms, output}});
const view = events => ({events, ticket: {history: []}});

test('a command and its end are one item with the output, the time and the exact command', () => {
  const items = live().feedItems(view([start('2026-11-15T10:00:00Z', 'a', 'Run tests', 'pytest -q'), end('2026-11-15T10:00:03Z', 'a', true, 'ok\n3 passed', 'ok 3 passed', 3000)]), null);
  assert.equal(items.length, 1);
  assert.deepEqual([items[0].command, items[0].out, items[0].ok, items[0].ms], ['pytest -q', 'ok\n3 passed', true, 3000]);
});

test('a failed try followed by the same command that worked is folded: "Fixed on the second try"', () => {
  const items = live().feedItems(view([
    start('2026-11-15T10:00:00Z', 'a', 'Run tests', 'pytest -q'), end('2026-11-15T10:00:03Z', 'a', false, '1 failed', 'Failed: 1 failed'),
    start('2026-11-15T10:01:00Z', 'b', 'Run tests', 'pytest -q'), end('2026-11-15T10:01:03Z', 'b', true, '3 passed')]), null);
  assert.equal(items.length, 1);
  assert.equal(items[0].id, 'b');
  assert.equal(items[0].tries.length, 1);
  assert.equal(items[0].tries[0].ok, false);
});

test('a failure that is not retried stays a failed block, and steps without a command stay plain', () => {
  const items = live().feedItems(view([
    start('2026-11-15T10:00:00Z', 'a', 'Run tests', 'pytest -q'), end('2026-11-15T10:00:03Z', 'a', false, '1 failed'),
    start('2026-11-15T10:02:00Z', 'c', 'Read a.py', null)]), null);
  assert.equal(items.length, 2);
  assert.equal(items[0].ok, false);
  assert.equal(items[1].command, null);
});

test('the page shows commands and output with textContent only', () => {
  const src = web('live.js');
  assert.doesNotMatch(src.slice(src.indexOf('function cmdBlock'), src.indexOf('function renderFeed')), /innerHTML/);
});

test('an unchecked (hook) end never joins a checked start, and a checked and an unchecked try are not folded', () => {
  const hook = e => ({...e, data: {...e.data, source: 'hook'}});
  const L = live();
  const items = L.feedItems(view([start('2026-11-15T10:00:00Z', 'a', 'Run tests', 'pytest -q'), hook(end('2026-11-15T10:00:03Z', 'a', true, '3 passed'))]), null);
  const block = items.find(i => i.command);
  assert.ok(block && block.ok === undefined && block.out === undefined, 'the checked block is not marked ok by an unchecked end');
  const folded = L.feedItems(view([
    start('2026-11-15T10:00:00Z', 'a', 'Run tests', 'pytest -q'), end('2026-11-15T10:00:03Z', 'a', false, '1 failed'),
    hook(start('2026-11-15T10:01:00Z', 'b', 'Run tests', 'pytest -q')), hook(end('2026-11-15T10:01:03Z', 'b', true, '3 passed'))]), null);
  assert.equal(folded.filter(i => i.command).length, 2);
  assert.ok(folded.every(i => !i.tries));
  const own = L.feedItems(view([hook(start('2026-11-15T10:00:00Z', 'c', 'Run tests', 'pytest -q')), hook(end('2026-11-15T10:00:03Z', 'c', true, 'ok'))]), null)[0];
  assert.equal(own.unchecked, 'agent');  // the block shows the same "not checked" mark as a plain step
  const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'orch_focus', 'web', 'live.js'), 'utf8');
  assert.match(src.slice(src.indexOf('function cmdBlock'), src.indexOf('function marked')), /uncheckedMark\(it\.unchecked\)/);
});

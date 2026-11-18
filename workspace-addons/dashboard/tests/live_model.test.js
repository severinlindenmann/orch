'use strict';
// ORCH-362: tool, model and open time of a working session (pages/live-model.js). The model is plain data.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const M = require(path.join(__dirname, '../src/orch_dashboard/web/pages/live-model.js'));
const now = Date.parse('2026-11-18T10:00:00Z');
const agents = [{name:'claude', label:'Claude Code', models:true}, {name:'codex', label:'Codex', models:false}];
const run = (extra = {}) => ({running:true, claim:{agent:'claude', mode:'live', started_at:'2026-11-18T09:35:00Z', live:{state:'working'}, ...extra}});

test('durations in plain words', () => {
  assert.equal(M.liveModelDur(25 * 60), '25 min');
  assert.equal(M.liveModelDur(65 * 60), '1 h 5 min');
  assert.equal(M.liveModelDur(120 * 60), '2 h');
});

test('a working session: tool and model, open time, stays warm', () => {
  const l = M.liveModelLine(run(), {model:{name:'opus', by:'orch'}}, agents, now, null);
  assert.equal(M.liveModelText(l), 'Claude Code · Opus');
  assert.equal(l.canPick, true);
  assert.equal(l.open, 'open 25 min');
  assert.equal(l.warm, 'stays warm while it works');
});

test('an idle session says when it closes; one that waits for you stays warm', () => {
  const idle = M.liveModelLine(run({live:{state:'idle'}}), {model:{name:'sonnet'}, warmth:{seconds_left:42 * 60}}, agents, now, null);
  assert.equal(idle.warm, 'closes in 42 min if left idle');
  assert.equal(M.liveModelLine(run({live:{state:'attention'}}), {}, agents, now, null).warm, 'stays warm while it waits for you');
});

test('a tool orch passes no model to shows only its name and offers no choice', () => {
  const l = M.liveModelLine(run({agent:'codex'}), {model:{name:'opus'}}, agents, now, null);
  assert.equal(M.liveModelText(l), 'Codex');
  assert.equal(l.canPick, false);
});

test('a waiting switch says which model comes after this step', () => {
  const l = M.liveModelLine(run({model_switch:{to:'haiku'}}), {model:{name:'haiku', by:'human:ana'}}, agents, now, null);
  assert.equal(M.liveModelText(l), 'Claude Code · Haiku');  // the ticket already says Haiku: nothing waits to show
  const w = M.liveModelLine(run({model_switch:{to:'opus'}}), {model:{name:'sonnet'}}, agents, now, null);
  assert.equal(M.liveModelText(w), 'Claude Code · Sonnet → Opus after this step');
});

test('the live data of every session wins when it is there (ORCH-359)', () => {
  const l = M.liveModelLine(run(), {model:{name:'sonnet'}}, agents, now, {tool:'Claude Code', model:'Opus', open_seconds:3900, status:'idle', closes_in_seconds:600});
  assert.equal(M.liveModelText(l), 'Claude Code · Opus');
  assert.equal(l.open, 'open 1 h 5 min');
  assert.equal(l.warm, 'closes in 10 min if left idle');
});

test('the page loads it before the layer and the server serves it', () => {
  const web = path.join(__dirname, '../src/orch_dashboard/web');
  const index = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  const at = index.indexOf('pages/live-model.js');
  assert.ok(at > 0 && at < index.indexOf('pages/live-layer.js'));
  assert.match(fs.readFileSync(path.join(web, '../server.py'), 'utf8'), /\|live-model\|/);
});

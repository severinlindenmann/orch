'use strict';
// ORCH-362: the model choice of a working session (pages/live-model.js). The model is plain data.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const M = require(path.join(__dirname, '../src/orch_dashboard/web/pages/live-model.js'));
const agents = [{name:'claude', label:'Claude Code', models:true}, {name:'codex', label:'Codex', models:false}];
const run = (extra = {}) => ({running:true, claim:{agent:'claude', mode:'live', live:{state:'working'}, ...extra}});

test('a working session: the button names the model', () => {
  const l = M.liveModelLine(run(), {model:{name:'opus', by:'orch'}}, agents, null);
  assert.equal(l.tool, 'Claude Code');
  assert.equal(l.canPick, true);
  assert.equal(M.liveModelPick(l), 'Model: Opus');
});

test('a tool orch passes no model to offers no choice', () => {
  const l = M.liveModelLine(run({agent:'codex'}), {model:{name:'opus'}}, agents, null);
  assert.equal(l.canPick, false);
  assert.equal(M.liveModelPick(l), '');
});

test('a waiting switch says which model comes after this step', () => {
  const l = M.liveModelLine(run({model_switch:{to:'haiku'}}), {model:{name:'haiku', by:'human:ana'}}, agents, null);
  assert.equal(M.liveModelPick(l), 'Model: Haiku');  // the ticket already says Haiku: nothing waits to show
  const w = M.liveModelLine(run({model_switch:{to:'opus'}}), {model:{name:'sonnet'}}, agents, null);
  assert.equal(M.liveModelPick(w), 'Model: Sonnet → Opus after this step');
});

test('the live data of every session wins when it is there (ORCH-359)', () => {
  const l = M.liveModelLine(run(), {model:{name:'sonnet'}}, agents, {tool:'Claude Code', model:'Opus'});
  assert.equal(M.liveModelPick(l), 'Model: Opus');
  assert.equal(l.name, 'sonnet');
});

test('the Empty helper (no ticket in the list) names its model from the sessions (ORCH-710)', () => {
  const t = M.liveModelSessionTicket([{id:'t_emp', kind:'empty', title:'Empty helper', model:'opus'}], 't_emp');
  assert.deepEqual(t.model, {name:'opus'});
  assert.equal(M.liveModelPick(M.liveModelLine(run(), t, agents, null)), 'Model: Opus');
  assert.equal(M.liveModelSessionTicket([{id:'t_chat', kind:'chat'}], 't_chat'), null);
  const layer = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/live-layer.js'), 'utf8');
  assert.match(layer, /sess\?\.running && \(!sess\.kind \|\| sess\.kind === 'empty'\) && typeof window\.liveModelRow/);
});

test('the page loads it before the layer and the server serves it', () => {
  const web = path.join(__dirname, '../src/orch_dashboard/web');
  const index = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  const at = index.indexOf('pages/live-model.js');
  assert.ok(at > 0 && at < index.indexOf('pages/live-layer.js'));
  assert.match(fs.readFileSync(path.join(web, '../server.py'), 'utf8'), /\|live-model\|/);
});

test('Undo of a model choice goes back to the model a person chose, else orch picks again (ORCH-1359)', () => {
  assert.equal(M.liveModelUndo({model:{name:'sonnet', by:'human:ana'}}), 'sonnet');
  assert.equal(M.liveModelUndo({model:{name:'opus', by:'orch'}}), 'auto');
  assert.equal(M.liveModelUndo({model:null}), 'auto');
  assert.equal(M.liveModelUndo(null), 'auto');
  assert.equal(M.liveModelUndo({model:{name:'gpt'}}), 'auto');
  const src = require('node:fs').readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/live-model.js'), 'utf8');
  assert.match(src, /'Model ' \+ liveModelLabel\(v\) \+ ' chosen for ' \+ key \+ '\.', 'ok', undo\)/, 'the toast offers Undo');
});

'use strict';
// ORCH-362: the Start choice of a layer pane (pages/live-start.js): continue, fresh start with tool and model, the
// helper places in use and the line. The model is plain data (module.exports when there is no page).
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const S = require(path.join(__dirname, '../src/orch_dashboard/web/pages/live-start.js'));

const run = (mode = 'live') => ({running:true, claim:{mode}});

test('places count every working helper (live and one-step), the limit and the line', () => {
  const p = S.liveStartPlaces({a:run(), b:run(), c:{running:false}, d:run('oneshot')}, {live_max:3}, {waiting:['t_x']});
  assert.deepEqual({...p, waiting:[...p.waiting]}, {used:3, max:3, waiting:['t_x'], full:true});
  assert.equal(S.liveStartPlaces({a:run(), b:run()}, {live_max:2}, null).full, true);
  assert.equal(S.liveStartPlaces({}, {live_max:null}, null).max, null);  // no limit (the default)
  assert.equal(S.liveStartPlaces(null, null, null).used, 0);
});

test('the places line says it plainly, singular and plural right', () => {
  const t = (used, max, waiting = []) => S.liveStartPlacesText({used, max, waiting, full:max !== null && used >= max});
  assert.equal(t(1, 6), 'A start uses 1 of 6 helper places. Now 1 of 6 is in use.');
  assert.equal(t(4, 6), 'A start uses 1 of 6 helper places. Now 4 of 6 are in use.');
  assert.equal(t(6, 6, ['a', 'b', 'c']), 'All 6 helper places are in use. 3 tickets wait in line. A start waits in line and begins by itself when a place is free.');
  assert.equal(t(1, 1, ['a']), 'The one helper place is in use. 1 ticket waits in line. A start waits in line and begins by itself when a place is free.');
  assert.equal(t(0, null), 'No helper is working now.');
  assert.equal(t(1, null), '1 helper is working now.');
  assert.equal(t(3, null, ['a']), '3 helpers are working now. 1 ticket waits in line.');
  assert.doesNotMatch(t(1, 6) + t(1, null), /\b1 (helpers|places|tickets)\b/);
});

test('where a ticket stands in the line', () => {
  const p = {used:2, max:2, waiting:['t_a', 't_b', 't_c'], full:true};
  assert.deepEqual({...S.liveStartInLine(p, 't_b')}, {at:2, of:3});
  assert.equal(S.liveStartInLine(p, 't_z'), null);
});

test('tools: only found ones, the chosen one is usual, model choice only where orch passes it', () => {
  const v = S.liveStartTools([
    {name:'claude', label:'Claude Code', found:true, chosen:false, models:true},
    {name:'codex', label:'Codex', found:true, chosen:true, models:false},
    {name:'gone', label:'Gone', found:false},
  ]);
  assert.deepEqual(v.tools.map(t => [t.name, t.models]), [['claude', true], ['codex', false]]);
  assert.equal(v.usual, 'codex');
  assert.equal(S.liveStartTools([{name:'claude', found:true}]).usual, 'claude');  // none chosen: the first
  assert.deepEqual({...S.liveStartTools(null)}, {tools:[], usual:''});
});

test('the ticket model is preselected; none set means Sonnet, orch picks again', () => {
  assert.deepEqual({...S.liveStartModel({model:{name:'opus', by:'human:ana'}})}, {name:'opus', auto:false});
  assert.deepEqual({...S.liveStartModel({model:{name:'opus', by:'orch'}})}, {name:'opus', auto:true});
  assert.deepEqual({...S.liveStartModel({})}, {name:'sonnet', auto:true});
  assert.equal(S.liveStartModel({model:{name:'gpt'}}).name, 'sonnet');
});

test('a fresh start sends only what the person changed: one click with the usual tool and model', () => {
  const cur = {name:'sonnet', auto:true};
  assert.deepEqual(S.liveStartFresh('t_a', {tool:'claude', model:'sonnet'}, 'claude', cur).map(x => [x[0], {...x[1]}]),
    [['run.start', {ticket:'t_a', fresh:true}]]);
  assert.deepEqual(S.liveStartFresh('t_a', {tool:'codex', model:'opus'}, 'claude', cur).map(x => [x[0], {...x[1]}]),
    [['ticket.model', {ticket:'t_a', model:'opus'}], ['run.start', {ticket:'t_a', fresh:true, agent:'codex'}]]);
});

test('Continue picks up the newest earlier session on this computer; a start in line is not a failure', () => {
  assert.equal(S.liveStartLast([{id:'now', current:true, reopen:false}, {id:'a', reopen:true}, {id:'b', reopen:true}]).id, 'a');
  assert.equal(S.liveStartLast([{id:'x', reopen:false}]), null);
  assert.equal(S.liveStartQueued('6 helpers are working at once, the most you allowed. ORCH-3 waits in line and starts when one is finished.'), true);
  assert.equal(S.liveStartQueued('That ticket does not exist.'), false);
});

test('the page loads the Start choice after the History list, before the layer, and the server serves it', () => {
  const fs = require('node:fs');
  const web = path.join(__dirname, '../src/orch_dashboard/web');
  const index = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  const at = index.indexOf('pages/live-start.js');
  assert.ok(at > index.indexOf('pages/live-history.js') && at < index.indexOf('pages/live-layer.js'));
  assert.match(fs.readFileSync(path.join(web, '../server.py'), 'utf8'), /live-history\|live-start\|/);
});

test('ORCH-2201: Why it waits names the open question, else the review, else nothing', () => {
  const t = {id:'t_abc123', status:'waiting', questions:[{id:'q1', digest:'d', text:'Run the gold steps\n on INT now?', options:['Now', 'Tonight'], answer:null}]};
  assert.deepEqual(S.liveStartWhy(t).question, {id:'q1', digest:'d', text:'Run the gold steps on INT now?', options:['Now', 'Tonight']});
  assert.equal(S.liveStartWhy({id:'t_abc123', status:'review', questions:[]}).review.text, 'Waits for your review');
  assert.equal(S.liveStartWhy({id:'t_abc123', status:'review', questions:[]}).href, '#ticket/t_abc123');
  assert.equal(S.liveStartWhy({id:'t_abc123', status:'active', questions:[{id:'q', text:'old', answer:'yes'}]}), null);
  assert.equal(S.liveStartWhy({id:'t_abc123', status:'active', questions:[{id:'q', text:'a plan', kind:'plan', answer:null}]}), null);
});

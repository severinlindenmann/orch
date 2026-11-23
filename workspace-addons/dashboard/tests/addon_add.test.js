'use strict';
// ORCH-1739: add several add-ons at once (pages/addon-add.js). The step list is plain data from the job file; the
// page never sends the add again by itself.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const FILE = path.join(__dirname, '../src/orch_dashboard/web/pages/addon-add.js');
const M = require(FILE);
const labels = {browse:'Browser', files:'Files', skills:'Skills'};
const steps = (ready, on, restart, extra = []) => [
  {key:'ready', label:'Getting Browser, Files and Skills ready', state:ready},
  {key:'on:browse', label:'Turning on Browser', state:on[0]},
  {key:'on:files', label:'Turning on Files', state:on[1]},
  {key:'on:skills', label:'Turning on Skills', state:on[2]},
  {key:'restart', label:'Restarting orch', state:restart}, ...extra];
const job = (state, st, more = {}) => ({v:1, id:'j_1', started:1000, names:['browse', 'files', 'skills'], state, steps:st, failed:null, reason:'', ended:null, here:true, ...more});
const looks = v => v.steps.map(s => s.look).join(' ');

test('getting ready: a spinner, the bar and the time so far, the rest waits', () => {
  const v = M.ajView(job('running', steps('running', ['waiting', 'waiting', 'waiting'], 'waiting')), labels, 1009);
  assert.equal(v.phase, 'going');
  assert.equal(v.title, 'Adding 3 add-ons');
  assert.equal(looks(v), 'now todo todo todo todo');
  assert.equal(v.steps[0].label, 'Getting Browser, Files and Skills ready');
  assert.equal(v.steps[0].bar, true);
  assert.equal(v.steps[0].sub, 'elapsed');
  assert.equal(v.elapsed, 9);
  assert.equal(v.clock, false);  // the time is under the bar, not next to the title
  assert.equal(v.steps[4].label, 'Restarting orch (about 10 seconds)');
  assert.equal(v.steps[4].sub, 'Your tickets and helpers keep going.');
  assert.equal(M.ajClock(v.elapsed), '0:09');
});

test('turning on: done, now, waiting; the time next to the title', () => {
  const v = M.ajView(job('running', steps('done', ['done', 'running', 'waiting'], 'waiting')), labels, 1027);
  assert.equal(looks(v), 'done done now todo todo');
  assert.equal(v.nowStep.label, 'Turning on Files');
  assert.equal(v.clock, true);
  assert.equal(M.ajSay(v), 'Turning on Files');
});

test('restarting: the page says it comes back by itself', () => {
  const v = M.ajView(job('restarting', steps('done', ['done', 'done', 'done'], 'running')), labels, 1031);
  assert.equal(v.phase, 'going');
  assert.equal(v.steps[4].look, 'now');
  assert.equal(v.steps[4].sub, 'This page comes back by itself. Your tickets and helpers keep going.');
});

test('finished: every step done, N add-ons are on', () => {
  const v = M.ajView(job('finished', steps('done', ['done', 'done', 'done'], 'done'), {ended:1041}), labels, 2000);
  assert.equal(v.phase, 'done');
  assert.equal(v.title, '3 add-ons are on');
  assert.equal(looks(v), 'done done done done done');
  assert.equal(v.elapsed, 41);  // the run's own time, not the time since
  assert.equal(M.ajView(job('finished', [], {names:['browse']}), labels, 1).title, '1 add-on is on');
});

test('failing: the failed add-on named, its reason under its step, the rest not done, putting things back', () => {
  const st = steps('failed', ['skipped', 'skipped', 'skipped'], 'skipped', [{key:'rollback', label:'Putting things back as they were', state:'running'}]);
  const v = M.ajView(job('running', st, {failed:'files', reason:'Files could not be added: the download failed.'}), labels, 1012);
  assert.equal(v.phase, 'failing');
  assert.equal(v.title, 'Files could not be added');
  assert.equal(looks(v), 'bad skip skip skip skip now');
  assert.equal(v.steps[0].reason, 'Files could not be added: the download failed.');
  assert.equal(v.steps[5].label, 'Putting things back as they were');
});

test('failed and put back: Nothing was changed, the others named', () => {
  const st = steps('failed', ['skipped', 'skipped', 'skipped'], 'skipped', [{key:'rollback', label:'x', state:'done'}]);
  const v = M.ajView(job('failed', st, {failed:'files', reason:'Files could not be added: the download failed.', ended:1019}), labels, 3000);
  assert.equal(v.phase, 'failed');
  assert.equal(v.title, 'Nothing was changed');
  assert.equal(v.note, 'Browser and Skills were not added either.');
  assert.equal(looks(v), 'bad skip skip skip skip done');
  assert.equal(v.clock, false);
});

test('stopped unexpectedly: a step left running is shown failed, the reason says what to do', () => {
  const v = M.ajView(job('failed', steps('done', ['done', 'running', 'waiting'], 'waiting'), {reason:'It stopped unexpectedly. Check the add-on list.'}), labels, 3000);
  assert.equal(looks(v), 'done done bad skip skip');
  assert.equal(v.title, 'Browser, Files and Skills could not be added');  // not "Nothing was changed": something may have
  assert.equal(v.steps[2].reason, 'It stopped unexpectedly. Check the add-on list.');
  const w = M.ajView(job('failed', steps('running', ['waiting', 'waiting', 'waiting'], 'waiting'), {reason:'The add-on install stopped unexpectedly. Nothing was changed.'}), labels, 3000);
  assert.equal(w.title, 'Nothing was changed');
});

test('a run from another workspace: one plain sentence', () => {
  const v = M.ajView(job('running', steps('running', ['waiting', 'waiting', 'waiting'], 'waiting'), {here:false}), labels, 1001);
  assert.equal(v.phase, 'other');
  assert.equal(M.ajSay(v), 'orch is adding add-ons from another workspace. This page comes back by itself.');
});

test('a name the page does not know keeps a plain capitalised name', () => {
  const v = M.ajView({names:['pull-requests'], state:'running', steps:[{key:'on:pull-requests', state:'running'}]}, {}, 0);
  assert.equal(v.steps[0].label, 'Turning on Pull-requests');
  assert.equal(M.ajView(null, {}, 0), null);
});

test('the pick list puts a needed add-on in front of the one that needs it, and says why', () => {
  const rows = [{name:'publish', label:'Shared links', requires:['relay']}, {name:'relay', label:'Contacts'}, {name:'browse', label:'Browser'}];
  assert.deepEqual(M.ajPlan(['publish', 'browse'], rows), {list:['relay', 'publish', 'browse'], why:{relay:'Shared links'}});
  assert.deepEqual(M.ajPlan(['publish', 'relay'], rows), {list:['relay', 'publish'], why:{}});  // picked itself: no "because"
  assert.deepEqual(M.ajPlan([], rows), {list:[], why:{}});
  const loop = [{name:'a', label:'A', requires:['b']}, {name:'b', label:'B', requires:['a']}];
  assert.deepEqual(M.ajPlan(['a'], loop).list.sort(), ['a', 'b']);  // two that need each other: no endless walk
  assert.equal(M.ajCount(1), '1 add-on');
  assert.equal(M.ajJoin(['A', 'B', 'C']), 'A, B and C');
});

// --- the page part in a small stand-in browser: what goes over the wire ---
function page({answers, jobs}) {
  const posts = [], gets = [], timers = [];
  const node = () => ({dataset:{}, children:[], append() {}, replaceChildren() {}, focus() {}, addEventListener() {}, querySelector: () => null, querySelectorAll: () => [], setAttribute() {}, contains: () => false, textContent:''});
  const ctx = vm.createContext({
    console, JSON, Date, Math, Number, String, Array, Set, Map, Object, RegExp, Promise,
    snapshot:false, state:{settings:{available:[{name:'browse', label:'Browser', consent:'x'}], addons:[]}, addons:[]},
    array: v => Array.isArray(v) ? v : [], rowLabel: r => r.label || r.name, render() {}, accept() {}, noteBoot() {},
    newActId: () => 'id', h: () => node(), settingsText: () => node(), addons: () => [],
    dialog: () => ({d:Object.assign(node(), {querySelector: () => node()})}),
    localStorage:{getItem: () => null, setItem() {}},
    document:{addEventListener() {}, activeElement:null, querySelectorAll: () => []},
    window:{orch:{open() {}, close() {}}},
    setTimeout: (f, ms) => { timers.push(f); return timers.length; }, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
    fetch: async (url, opts) => {
      if (opts && opts.method === 'POST') {
        posts.push(JSON.parse(opts.body));
        const a = answers.shift();
        if (a === 'lost') throw new Error('Failed to fetch');
        return {status:a.status, headers:{get: () => null}, json: async () => a.body, text: async () => a.text || ''};
      }
      gets.push(url);
      if (url.startsWith('/api/state')) return {ok:true, headers:{get: () => null}, json: async () => ({})};
      const j = jobs.length > 1 ? jobs.shift() : jobs[0];
      if (j === 'down') throw new Error('Failed to fetch');
      return {ok:true, headers:{get: () => null}, json: async () => ({job:j})};
    },
  });
  vm.runInContext(fs.readFileSync(FILE, 'utf8') + '\nthis.aj = aj; this.ajStart = ajStart; this.ajPoll = ajPoll; this.ajRetry = ajRetry; this.quiet = () => window.addonJobQuiet();', ctx);
  const runTimers = async n => { for (let i = 0; i < n && timers.length; i++) { await timers.shift()(); } };
  return {ctx, posts, gets, runTimers};
}
const live = job('running', steps('done', ['done', 'done', 'done'], 'running'));
const restarting = {...live, state:'restarting'};
const failed = job('failed', steps('failed', ['skipped', 'skipped', 'skipped'], 'skipped', [{key:'rollback', state:'done'}]), {failed:'files', reason:'Files could not be added: the download failed.'});

test('a lost answer is never sent again: the page looks for the run instead', async () => {
  const p = page({answers:['lost'], jobs:[null]});
  await p.ctx.ajStart(['browse']);
  assert.equal(p.posts.length, 1);
  assert.deepEqual(p.gets, ['/api/addon-job']);
  assert.equal(p.ctx.aj.err, 'Could not reach orch.');
  await p.runTimers(5);
  assert.equal(p.posts.length, 1);
});

test('a lost answer while the run did start: the page follows that run', async () => {
  const p = page({answers:['lost'], jobs:[live]});
  await p.ctx.ajStart(['browse']);
  assert.equal(p.posts.length, 1);
  assert.equal(p.ctx.aj.phase, 'job');
  assert.equal(p.ctx.aj.job.id, 'j_1');
});

test('while orch restarts the page is quiet, keeps reading the run with no time limit of 38 s, and never sends again', async () => {
  const downs = Array(40).fill('down');  // 40 reads at 1.5 s = 60 s away
  const p = page({answers:[{status:202, body:{job:live}}], jobs:[restarting, ...downs, job('finished', steps('done', ['done', 'done', 'done'], 'done'))]});
  await p.ctx.ajStart(['browse', 'files', 'skills']);
  assert.equal(p.ctx.quiet(), true);  // the restart step runs
  await p.runTimers(1);
  assert.equal(p.ctx.quiet(), true);
  await p.runTimers(40);
  assert.equal(p.ctx.aj.gaveUp, false);
  await p.runTimers(1);
  assert.equal(p.ctx.aj.job.state, 'finished');
  assert.equal(p.ctx.quiet(), false);
  assert.ok(p.gets.includes('/api/state?fresh=1'));  // the new add-ons are read once it is back
  assert.equal(p.posts.length, 1);
});

test('a refusal shows its words and nothing is followed', async () => {
  const p = page({answers:[{status:409, text:'orch is already adding add-ons. You can add more when this is done.'}], jobs:[null]});
  await p.ctx.ajStart(['browse']);
  assert.equal(p.ctx.aj.err, 'orch is already adding add-ons. You can add more when this is done.');
  assert.equal(p.ctx.aj.polling, false);
  assert.equal(p.posts.length, 1);
});

test('Try again sends the same names once, only when clicked', async () => {
  const p = page({answers:[{status:202, body:{job:live}}], jobs:[failed]});
  p.ctx.aj.job = failed;
  await p.runTimers(3);
  assert.equal(p.posts.length, 0);  // a failed run is never sent again by itself
  await p.ctx.ajRetry();
  assert.equal(p.posts.length, 1);
  assert.deepEqual(p.posts[0], {op:'addon.add', args:{names:['browse', 'files', 'skills']}});
});

test('Try again leaves out the add-ons that did get turned on', async () => {
  const p = page({answers:[{status:202, body:{job:live}}], jobs:[failed]});
  p.ctx.aj.job = failed;
  p.ctx.addons = () => [{name:'browse'}];
  await p.ctx.ajRetry();
  assert.deepEqual(p.posts[0], {op:'addon.add', args:{names:['files', 'skills']}});
});

test('the page waits as long as the core (30 minutes), then stops', async () => {
  const p = page({answers:[{status:202, body:{job:live}}], jobs:['down']});
  await p.ctx.ajStart(['browse']);
  p.ctx.aj.since = Date.now() - 12 * 60 * 1000;
  await p.runTimers(1);
  assert.notEqual(p.ctx.aj.gaveUp, true);  // a slow install at 12 minutes is still followed
  p.ctx.aj.since = Date.now() - 32 * 60 * 1000;
  await p.runTimers(1);
  assert.equal(p.ctx.aj.gaveUp, true);
  assert.equal(p.ctx.quiet(), false);  // the page asks the server again
  assert.equal(p.posts.length, 1);
});

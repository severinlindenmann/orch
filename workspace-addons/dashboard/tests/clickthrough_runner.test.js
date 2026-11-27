// The click-through runner itself (ORCH-490). g-github failed on unrelated pull requests: after it turned the Pull
// requests add-on off, the page (whose own state lags the server by a poll) still warmed that add-on's view once and
// Chromium logged the 404 as a console error. addonOff accepts exactly that one 404; any other 404 still fails.
// A timeout names the line of the click-through it waited on, so a red run says which step it was.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { recorder, where } = require('../clickthrough/run.cjs');

const BASE = 'http://127.0.0.1:1';
function fakePage() {
  const page = new EventEmitter();
  page.answer = (status, url, method = 'GET') => page.emit('response', {
    status: () => status, url: () => BASE + url, request: () => ({ method: () => method, headers: () => ({}), postData: () => '' }) });
  page.consoleError = text => page.emit('console', { type: () => 'error', text: () => text });
  return page;
}
const NOT_FOUND = 'Failed to load resource: the server responded with a status of 404 (Not Found)';

test('the 404 of the view of an add-on the click-through turned off is not an error, once', () => {
  const page = fakePage(), rec = recorder(page, BASE);
  rec.offAddons.add('pull-requests');
  page.answer(404, '/api/addon/pull-requests');
  page.consoleError(NOT_FOUND);
  assert.deepEqual(rec.errors, []);
  page.consoleError(NOT_FOUND);  // a second 404 with no matching answer still counts
  assert.equal(rec.errors.length, 1);
});

test('a 404 of another add-on or another address is still an error', () => {
  const page = fakePage(), rec = recorder(page, BASE);
  rec.offAddons.add('pull-requests');
  page.answer(404, '/api/addon/automation');
  page.consoleError(NOT_FOUND);
  page.answer(404, '/api/file');
  page.consoleError(NOT_FOUND);
  assert.equal(rec.errors.length, 2);
  assert.match(rec.errors[0], /404 GET \/api\/addon\/automation/);
});

test('a failed step names the line of the click-through it waited on', () => {
  const file = path.join(__dirname, '..', 'clickthrough', 'features', 'f-session-new.cjs');
  const e = new Error('locator.waitFor: Timeout 20000ms exceeded.');
  e.stack = `${e.message}\n    at Object.run (${file}:31:30)\n    at async main (/x/run.cjs:340:9)`;
  assert.match(where(e), /^ \(at f-session-new\.cjs:31: .+\)$/);
  assert.equal(where(new Error('no stack frame in a feature')), '');
});

// ORCH-1132: a click-through that fails by chance no longer turns the job red; it is tried once more on a fresh server
// and named in the summary. One that hangs is stopped by its time limit.
const { runAll, withTimeout } = require('../clickthrough/run.cjs');
const ct = file => ({ file, name: file });
const pass = c => ({ c, problems: [] });
const fail = c => ({ c, problems: ['boom'] });

test('a click-through that fails once and passes on the second try counts as passed and is named', async () => {
  const freshCalls = [], log = [];
  let between = 0;
  const { results, secondTry } = await runAll([ct('a.cjs'), ct('b.cjs'), ct('c.cjs')], {
    first: async c => (c.file === 'b.cjs' ? fail(c) : pass(c)),
    fresh: async c => { freshCalls.push(c.file); assert.equal(between, 1, 'the second try runs after the shared server stopped'); return pass(c); },
    between: async () => { between++; },
    log: l => log.push(l),
  });
  assert.deepEqual(freshCalls, ['b.cjs'], 'only the failed one is tried again');
  assert.deepEqual(secondTry, ['b.cjs']);
  assert.deepEqual(results.map(r => r.problems.length), [0, 0, 0]);
  assert.deepEqual(results.map(r => r.c.file), ['a.cjs', 'b.cjs', 'c.cjs'], 'the order stays');
});

test('a click-through that fails twice stays failed', async () => {
  const { results, secondTry } = await runAll([ct('a.cjs'), ct('b.cjs')], {
    first: async c => (c.file === 'a.cjs' ? fail(c) : pass(c)),
    fresh: async c => fail(c),
    log: () => {},
  });
  assert.deepEqual(secondTry, []);
  assert.deepEqual(results.filter(r => r.problems.length).map(r => r.c.file), ['a.cjs']);
});

test('more failures than the limit are a real break: none is tried again', async () => {
  let fresh = 0;
  const log = [];
  const { results } = await runAll(['a', 'b', 'c'].map(f => ct(f + '.cjs')), {
    first: async c => fail(c), fresh: async c => { fresh++; return pass(c); }, maxRetries: 2, log: l => log.push(l),
  });
  assert.equal(fresh, 0);
  assert.equal(results.filter(r => r.problems.length).length, 3);
  assert.match(log.join('\n'), /3 click-throughs failed: more than 2/);
});

test('a known unsteady failure does not count toward the limit and is not tried again (ORCH-1629, ORCH-1652)', async () => {
  const fresh = [];
  const { results, secondTry } = await runAll(['a', 'b', 'u'].map(f => ct(f + '.cjs')), {
    first: async c => fail(c), fresh: async c => { fresh.push(c.file); return pass(c); }, maxRetries: 2,
    unsteady: { 'u.cjs': 'ORCH-1' }, log: () => {},
  });
  assert.deepEqual(fresh, ['a.cjs', 'b.cjs'], 'two counted failures are within the limit; the unsteady one takes no server');
  assert.deepEqual(secondTry, ['a.cjs', 'b.cjs']);
  assert.deepEqual(results.filter(r => r.problems.length).map(r => r.c.file), ['u.cjs']);
});

// ORCH-1652 (run 45082995989): the first round took 12 of the job's 15 minutes and no failure got a second try.
// Second tries now run side by side on the lanes and each gets only the time left before the job's end.
test('second tries run on the lanes at once, each limited to the time left', async () => {
  const live = { now: 0, max: 0 }, limits = [];
  const { secondTry } = await runAll(['a', 'b', 'c'].map(f => ct(f + '.cjs')), {
    lanes: 2, first: async c => fail(c), end: 100000, now: () => 40000, log: () => {},
    fresh: async (c, limitMs) => {
      limits.push(limitMs);
      live.now++; live.max = Math.max(live.max, live.now);
      await new Promise(r => setTimeout(r, 10));
      live.now--;
      return pass(c);
    },
  });
  assert.equal(live.max, 2, 'two second tries at once');
  assert.deepEqual(limits, [60000, 60000, 60000], 'each gets the 60 seconds left, not the full 3 minutes');
  assert.deepEqual(secondTry.sort(), ['a.cjs', 'b.cjs', 'c.cjs']);
});

test('no second try starts when too little time is left', async () => {
  let fresh = 0;
  const log = [];
  const { results } = await runAll([ct('a.cjs')], {
    first: async c => fail(c), fresh: async c => { fresh++; return pass(c); }, end: 100000, now: () => 80000,
    log: l => log.push(l),
  });
  assert.equal(fresh, 0);
  assert.equal(results[0].problems.length, 1);
  assert.match(log.join('\n'), /no time left for a second try of a\.cjs/);
});

test('no second try starts after the deadline', async () => {
  let fresh = 0;
  const { results } = await runAll([ct('a.cjs')], {
    first: async c => fail(c), fresh: async c => { fresh++; return pass(c); }, deadline: 10, now: () => 11, log: () => {},
  });
  assert.equal(fresh, 0);
  assert.equal(results[0].problems.length, 1);
});

test('a hang is stopped by the time limit with a message that names it', async () => {
  await assert.rejects(withTimeout(new Promise(() => {}), 20, 'x-hang.cjs'), /x-hang\.cjs took longer than 0s and was stopped/);
  assert.equal(await withTimeout(Promise.resolve(7), 1000, 'quick'), 7);
});

// ORCH-1132: a known unsteady click-through still runs and is printed, but its failure does not make the run red.
const { verdict, UNSTEADY } = require('../clickthrough/run.cjs');
const fs = require('node:fs');

test('the known unsteady list is short and every entry names the ticket that fixes it and an existing file', () => {
  const entries = Object.entries(UNSTEADY);
  assert.ok(entries.length <= 3, `at most 3 known unsteady click-throughs, found ${entries.length}`);
  for (const [file, ticket] of entries) {
    assert.match(ticket, /^ORCH-\d+$/, `${file} names its ticket`);
    assert.ok(fs.existsSync(path.join(__dirname, '..', 'clickthrough', 'features', file)), `${file} exists`);
  }
});

test('a failed known unsteady click-through does not count, nor do the features only it covers', () => {
  const shaky = { file: 'r-x.cjs', covers: ['op:a', 'op:b'] }, good = { file: 'a.cjs', covers: ['op:b', 'op:c'] };
  const v = verdict([{ c: good, problems: [] }, { c: shaky, problems: ['404'] }], ['op:a', 'op:b', 'op:c'], { 'r-x.cjs': 'ORCH-1' });
  assert.equal(v.code, 0);
  assert.deepEqual(v.unsteady.map(r => r.c.file), ['r-x.cjs']);
  assert.deepEqual(v.missing, []);
  assert.deepEqual(v.excused, ['op:a']);
});

test('any other failure, or a feature nobody did, still makes the run red', () => {
  const v = verdict([{ c: { file: 'a.cjs', covers: ['op:a'] }, problems: ['boom'] }], ['op:a'], { 'r-x.cjs': 'ORCH-1' });
  assert.equal(v.code, 1);
  assert.deepEqual(v.failed.map(r => r.c.file), ['a.cjs']);
  assert.equal(verdict([{ c: { file: 'a.cjs', covers: [] }, problems: [] }], ['op:z'], {}).code, 1);
});

// ORCH-1402: the first round runs on several servers at once; each lane takes the next click-through when it is free,
// the results keep the list's order, and the second try still runs after every lane's server stopped.
test('lanes run the first round at once and keep the order', async () => {
  const seen = [], live = { now: 0, max: 0 };
  let between = 0;
  const { results, secondTry } = await runAll(['a', 'b', 'c', 'd', 'e'].map(f => ct(f + '.cjs')), {
    lanes: 2,
    first: async (c, k) => {
      live.now++; live.max = Math.max(live.max, live.now);
      await new Promise(r => setTimeout(r, c.file === 'a.cjs' ? 30 : 5));
      live.now--; seen.push([c.file, k]);
      return c.file === 'd.cjs' ? fail(c) : pass(c);
    },
    fresh: async c => { assert.equal(between, 1, 'the second try runs after the lanes stopped'); return pass(c); },
    between: async () => { between++; },
    log: () => {},
  });
  assert.equal(live.max, 2, 'two at once');
  assert.deepEqual(new Set(seen.map(x => x[1])), new Set([0, 1]), 'both lanes worked');
  assert.equal(seen.find(x => x[0] === 'a.cjs')[1], 0);
  assert.ok(seen.filter(x => x[1] === 1).length >= 3, 'the free lane took the next ones while a.cjs was slow');
  assert.deepEqual(results.map(r => r.c.file), ['a.cjs', 'b.cjs', 'c.cjs', 'd.cjs', 'e.cjs'], 'the order stays');
  assert.deepEqual(secondTry, ['d.cjs']);
});

test('more lanes than click-throughs start only as many as needed', async () => {
  const lanesUsed = new Set();
  await runAll([ct('a.cjs')], { lanes: 4, first: async (c, k) => { lanesUsed.add(k); return pass(c); }, fresh: async c => pass(c), log: () => {} });
  assert.deepEqual([...lanesUsed], [0]);
});

// ORCH-1652: d-private left a git folder with no commit in the shared lane workspace, so k-copies-cleanup made no copy
// whenever both landed on the same lane. After each click-through the lane gets its seeded git folder and settings back.
test('after a click-through the lane workspace gets its seeded git folder and settings of this computer back', () => {
  const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
  const { seedState, restoreSeed } = require('../clickthrough/run.cjs');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ct-seed-'));
  try {
    fs.mkdirSync(path.join(dir, 'Pilatus'), { recursive: true });
    fs.mkdirSync(path.join(dir, 'orch'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'orch', 'copies.json'), '{"a": {"diag_enabled": true}}');
    const srv = { dir }, seed = seedState(srv), log = [];
    assert.deepEqual(restoreSeed(srv, seed, 'quiet.cjs', l => log.push(l)), [], 'nothing changed: nothing put back');
    fs.mkdirSync(path.join(dir, 'Pilatus', '.git', 'objects'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'orch', 'copies.json'), '{"a": {"copies": "always"}}');
    const put = restoreSeed(srv, seed, 'd-private.cjs', l => log.push(l));
    assert.equal(put.length, 2);
    assert.ok(!fs.existsSync(path.join(dir, 'Pilatus', '.git')), 'the git folder it made is gone');
    assert.equal(fs.readFileSync(path.join(dir, 'orch', 'copies.json'), 'utf8'), '{"a": {"diag_enabled": true}}');
    assert.match(log.join('\n'), /after d-private\.cjs: removed the git folder/);
    fs.rmSync(path.join(dir, 'orch', 'copies.json'));
    restoreSeed(srv, seed, 'x.cjs', () => {});
    assert.ok(fs.existsSync(path.join(dir, 'orch', 'copies.json')), 'a removed settings file comes back');
    const none = seedState({ dir: fs.mkdtempSync(path.join(dir, 'n-')) });
    fs.mkdirSync(path.join(none.copies, '..'), { recursive: true });
    fs.writeFileSync(none.copies, '{}');
    restoreSeed({ dir: path.dirname(path.dirname(none.copies)) }, none, 'y.cjs', () => {});
    assert.ok(!fs.existsSync(none.copies), 'a settings file the seed did not have is removed');
    // the Chat as seeded: a day file written by a click-through goes, a changed one gets its seeded text back
    const chat = path.join(dir, 'Pilatus', '.orch', 'chat');
    fs.mkdirSync(path.join(chat, 'dm'), { recursive: true });
    fs.writeFileSync(path.join(chat, '2026-11-20.json'), '{"messages": []}');
    const withChat = seedState(srv);
    fs.writeFileSync(path.join(chat, '2026-11-20.json'), '{"messages": [1]}');
    fs.writeFileSync(path.join(chat, '2026-11-23.json'), '{"messages": [2]}');
    fs.writeFileSync(path.join(chat, 'dm', 'x.json'), '{}');
    const lines = [];
    assert.deepEqual(restoreSeed(srv, withChat, 'e-chat.cjs', l => lines.push(l)), ['put the Chat back as it was']);
    assert.match(lines.join('\n'), /after e-chat\.cjs: put the Chat back/);
    assert.ok(!fs.existsSync(path.join(chat, '2026-11-23.json')), 'the new day of messages is gone');
    assert.equal(fs.readFileSync(path.join(chat, '2026-11-20.json'), 'utf8'), '{"messages": []}');
    assert.ok(fs.existsSync(path.join(chat, 'dm', 'x.json')), 'only the day files of the workspace Chat are put back');
    assert.deepEqual(restoreSeed(srv, withChat, 'quiet.cjs', () => {}), [], 'the Chat as seeded: nothing put back');
    fs.rmSync(chat, { recursive: true, force: true });
    restoreSeed(srv, withChat, 'z.cjs', () => {});
    assert.equal(fs.readFileSync(path.join(chat, '2026-11-20.json'), 'utf8'), '{"messages": []}', 'a removed Chat folder comes back');
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('--part: the parts share the click-throughs out and each checks only its own features (ORCH-1118)', () => {
  const { part, partFeatures } = require('../clickthrough/run.cjs');
  const all = [{ file: 'a', covers: ['x'] }, { file: 'b', covers: ['y'] }, { file: 'c', covers: ['x', 'z'] }];
  const p1 = part(all, { n: 1, of: 2 });
  const p2 = part(all, { n: 2, of: 2 });
  assert.deepEqual(p1.map(c => c.file), ['a', 'c']);
  assert.deepEqual(p2.map(c => c.file), ['b']);
  const features = ['x', 'y', 'z', 'nobody'];
  assert.deepEqual(partFeatures(all, all, features, null), features);   // no part: every feature
  assert.deepEqual(partFeatures(all, p1, features, { n: 1, of: 2 }), ['x', 'z', 'nobody']);   // part 1 names the unclaimed one
  assert.deepEqual(partFeatures(all, p2, features, { n: 2, of: 2 }), ['y']);
});

test('a lane whose browser was left logged out gets a fresh context; a logged-in one is kept (#2456)', async () => {
  const { stayLoggedIn } = require('../clickthrough/run.cjs');
  const base = 'http://127.0.0.1:5000';
  const ctx = (ok, secret) => ({
    closed: false,
    request: { get: async () => ({ ok: () => ok }) },
    storageState: async () => ({ origins: [{ origin: base, localStorage: secret ? [{ name: 'orch_page_secret', value: secret }] : [] }] }),
    async close() { this.closed = true; },
  });
  const log = console.log;
  console.log = () => {};
  try {
    const fresh = ctx(true, 's2');
    const good = ctx(true, 's1');
    assert.equal(await stayLoggedIn(good, base, async () => fresh), good);
    assert.equal(good.closed, false);
    for (const bad of [ctx(false, 's1'), ctx(true, null)]) {   // refused reads (403), or the page secret is gone
      assert.equal(await stayLoggedIn(bad, base, async () => fresh, 'm-token-login.cjs'), fresh);
      assert.equal(bad.closed, true);
    }
  } finally { console.log = log; }
});

// ORCH-2363: quarantined click-throughs are out of every default run (so out of the merge queue) and run alone with
// --quarantined, nightly; the features only they cover are not asked for in a default run.
test('a default run leaves the quarantined click-throughs out, --quarantined runs only them, --only still names one', () => {
  const { pick } = require('../clickthrough/run.cjs');
  const all = ['a.cjs', 'f-x.cjs', 'q.cjs'].map(file => ({ file }));
  const parked = { 'f-x.cjs': 'ORCH-1' };
  const names = list => list.map(c => c.file);
  assert.deepEqual(names(pick(all, {}, parked)), ['a.cjs', 'q.cjs']);
  assert.deepEqual(names(pick(all, { quarantined: true }, parked)), ['f-x.cjs']);
  assert.deepEqual(names(pick(all, { only: new Set(['f-x']) }, parked)), ['f-x.cjs']);
});

test('a default run does not ask for a feature only a quarantined click-through covers', () => {
  const { notQuarantined } = require('../clickthrough/run.cjs');
  const all = [{ file: 'a.cjs', covers: ['op:a', 'op:b'] }, { file: 'f-x.cjs', covers: ['op:b', 'op:x'] }];
  assert.deepEqual(notQuarantined(all, ['op:a', 'op:b', 'op:x', 'op:nobody'], { 'f-x.cjs': 'ORCH-1' }), ['op:a', 'op:b', 'op:nobody']);
});

test('the quarantine list names the flaky click-throughs, each an existing file with its ticket', () => {
  const { QUARANTINED } = require('../clickthrough/run.cjs');
  assert.deepEqual(Object.keys(QUARANTINED).sort(), ['a-board-families.cjs', 'f-sync-page.cjs', 'p-looks-good-cases.cjs', 'q-automation-repeats.cjs', 's-role-page.cjs']);
  for (const [file, ticket] of Object.entries(QUARANTINED)) {
    assert.match(ticket, /^ORCH-\d+$/, `${file} names its ticket`);
    assert.ok(fs.existsSync(path.join(__dirname, '..', 'clickthrough', 'features', file)), `${file} exists`);
  }
});

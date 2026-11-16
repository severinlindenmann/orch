const test = require('node:test');
const assert = require('node:assert/strict');
const {dueWords, dueLate, quietWords} = require('../src/orch_dashboard/web/helpers.js');
const now = new Date(2026, 10, 15, 12, 0); // Sun 15 Nov 2026, 12:00

test('a due with a time: Due 18:30 today, Due Mon 18:30 on another day, Late since once it has passed', () => {
  assert.equal(dueWords('2026-11-15T18:30', 'active', now), 'Due 18:30');
  assert.equal(dueWords('2026-11-16T18:30', 'open', now), 'Due Mon 18:30');
  assert.equal(dueWords('2026-12-01T09:05', 'open', now), 'Due 1 Dec 2026, 09:05');
  assert.equal(dueWords('2026-11-15T09:00', 'active', now), 'Late since 09:00');
  assert.equal(dueWords('2026-11-14T18:30', 'review', now), 'Late since Sat 18:30');
  assert.equal(dueWords('2026-11-15T09:00', 'done', now), 'Due 09:00', 'a closed ticket is never late');
});

test('a day-only due has no time words and keeps its old meaning (late the day after)', () => {
  assert.equal(dueWords('2026-11-15', 'open', now), '');
  assert.equal(dueWords('', 'open', now), '');
  assert.equal(dueLate('2026-11-15', 'open', now), false);
  assert.equal(dueLate('2026-11-14', 'open', now), true);
  assert.equal(dueLate('2026-11-14', 'done', now), false);
});

test('a due with a time is late from that minute on', () => {
  assert.equal(dueLate('2026-11-15T11:59', 'active', now), true);
  assert.equal(dueLate('2026-11-15T12:00', 'active', now), false);
  assert.equal(dueLate('2026-11-15T18:30', 'active', now), false);
});

test('G2: "No news since" in local time, with the day when it is not today; empty for no or a bad time', () => {
  const at = new Date(2026, 10, 15, 9, 20), earlier = new Date(2026, 10, 13, 9, 20);
  assert.equal(quietWords(at.toISOString(), now), 'No news since 09:20');
  assert.equal(quietWords(earlier.toISOString(), now), 'No news since Fri 09:20');
  assert.equal(quietWords(new Date(2026, 9, 1, 9, 5).toISOString(), now), 'No news since 1 Oct 2026, 09:05');
  assert.equal(quietWords(undefined, now), '');
  assert.equal(quietWords('junk', now), '');
});

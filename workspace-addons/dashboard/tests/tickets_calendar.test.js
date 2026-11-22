const test = require('node:test');
const assert = require('node:assert/strict');
const {calendar: C} = require('../src/orch_dashboard/web/helpers.js');

// ORCH-1081 (owner picked draft C): the Tickets calendar. Today is Fri 20 Nov 2026, 12:00 local.
const now = new Date(2026, 10, 20, 12, 0);
const day = (plan, d) => plan.weeks.flatMap(w => w.days).find(x => x.day === d);
const keys = list => list.map(t => t.key);

test('a ticket lands on its local due day, with or without a time', () => {
  const items = [{key:'D-1', due:'2026-11-23T18:30', status:'ready'}, {key:'D-2', due:'2026-11-23', status:'active'}, {key:'D-3', due:'2026-11-20T18:30', status:'active'}];
  const plan = C.plan(items, {now});
  assert.deepEqual(keys(day(plan, '2026-11-23').items), ['D-1', 'D-2'], 'by time; no time after the timed ones');
  assert.deepEqual(keys(day(plan, '2026-11-20').items), ['D-3'], 'due 18:30 today is not late at noon');
  assert.equal(day(plan, '2026-11-20').today, true);
  assert.equal(day(plan, '2026-11-24').items.length, 0);
  assert.equal(C.dayOf('2026-11-23T23:59'), '2026-11-23');
  assert.equal(C.dayOf('2026-02-30'), '', 'a day that does not exist is on no day');
});

test('a late ticket goes to the Late list, not on its day; finished ones stay on their day', () => {
  const items = [{key:'L-1', due:'2026-11-12', status:'ready'}, {key:'L-2', due:'2026-11-20T09:00', status:'active'},
    {key:'L-3', due:'2026-11-17', status:'done'}, {key:'L-4', due:'2026-11-19', status:'review'}];
  const plan = C.plan(items, {now});
  assert.deepEqual(keys(plan.late), ['L-1', 'L-4', 'L-2'], 'oldest first; a time that passed today is late too');
  assert.deepEqual(day(plan, '2026-11-12').items, []);
  assert.deepEqual(day(plan, '2026-11-20').items, []);
  assert.deepEqual(keys(day(plan, '2026-11-17').items), ['L-3']);
  const thisWeek = plan.weeks.find(w => w.when === 'now');
  assert.equal(thisWeek.name, 'This week');
  assert.equal(thisWeek.counts, '2 late, 1 done');
  assert.equal(plan.weeks.find(w => w.mon === '2026-11-09').name, 'Last week');
  assert.equal(plan.weeks.find(w => w.mon === '2026-11-02').counts, 'Nothing due');
  // the status as shown counts: a ticket shown as done is not late
  assert.deepEqual(keys(C.plan(items, {now, statusOf:t => t.key === 'L-1' ? 'done' : t.status}).late), ['L-4', 'L-2']);
});

test('tickets without a due date are counted, not placed', () => {
  const plan = C.plan([{key:'N-1', status:'open'}, {key:'N-2', due:'', status:'ready'}, {key:'N-3', due:'2026-11-25', status:'ready'}], {now});
  assert.equal(plan.noDue, 2);
  assert.equal(plan.weeks.flatMap(w => w.days).reduce((n, d) => n + d.items.length, 0), 1);
});

test('a day with five tickets shows three and "+2 more"; four show in full', () => {
  const five = Array.from({length:5}, (_, i) => ({key:'M-' + i, due:'2026-11-26', status:'ready'}));
  const items = day(C.plan(five, {now}), '2026-11-26').items;
  assert.equal(items.length, 5);
  assert.equal(C.cut(items).length, 3);
  assert.equal(items.length - C.cut(items).length, 2);
  assert.equal(C.cut(items.slice(0, 4)).length, 4);
});

test('month and week: weeks as rows, titles and stepping', () => {
  const month = C.plan([], {now});
  assert.equal(month.title, 'November 2026');
  assert.deepEqual(month.weeks.map(w => w.mon), ['2026-10-26', '2026-11-02', '2026-11-09', '2026-11-16', '2026-11-23', '2026-11-30']);
  assert.deepEqual(month.weeks.map(w => w.when), ['past', 'past', 'past', 'now', 'next', 'later']);
  assert.equal(month.weeks[0].name, '26 Oct – 1 Nov');
  const week = C.plan([], {now, mode:'week', day:'2026-11-25'});
  assert.equal(week.title, '23 – 29 Nov 2026');
  assert.equal(week.weeks.length, 1);
  assert.equal(week.weeks[0].name, 'Next week');
  assert.equal(C.step('month', '2026-11-20', 1, '2026-11-20'), '2026-12-01');
  assert.equal(C.step('month', '2026-12-01', -1, '2026-11-20'), '2026-11-20', 'back to the month of today opens on today');
  assert.equal(C.step('month', '2027-01-31', -1, '2026-11-20'), '2026-12-01');
  assert.equal(C.step('week', '2026-11-20', -1), '2026-11-13');
  assert.equal(C.plan([], {now, day:'nonsense'}).day, '2026-11-20');
});

test('a broken due time is on no day and never shown as a time', () => {
  assert.equal(C.dayOf('2026-11-23T99:99'), '');
  assert.equal(C.dayOf('2026-11-23T24:00'), '');
  assert.equal(C.time('2026-11-23T99:99'), '');
  assert.equal(C.time('2026-11-23T23:59'), '23:59');
  const plan = C.plan([{key:'B-1', due:'2026-11-23T99:99', status:'ready'}], {now});
  assert.equal(plan.weeks.flatMap(w => w.days).some(d => d.items.length), false);
});

// Date math across daylight-saving changes and the new year, in zones that have them (the host zone may not).
const {execFileSync} = require('node:child_process');
for (const TZ of ['Europe/Zurich', 'America/New_York', 'Australia/Sydney', 'UTC']) {
  test('days, Mondays and steps stay right across DST and the new year in ' + TZ, () => {
    const script = `
      const {calendar: C} = require(${JSON.stringify(require.resolve('../src/orch_dashboard/web/helpers.js'))});
      const out = [];
      for (let d = '2026-01-01'; d < '2028-01-01'; d = C.add(d, 1)) out.push(d);
      const mondays = new Set(out.map(C.monday));
      const steps = [C.step('month', '2026-12-15', 1, ''), C.step('month', '2027-01-10', -1, ''), C.step('week', '2026-12-28', 1, ''),
        C.step('week', '2026-03-23', 1, ''), C.step('week', '2026-10-19', 1, ''), C.step('week', '2026-04-06', -1, '')];
      process.stdout.write(JSON.stringify({n: out.length, first: out[0], last: out[out.length - 1], mondays: [...mondays].map(m => new Date(m + 'T12:00').getDay()), steps,
        title: C.title('week', '2026-12-30')}));`;
    const r = JSON.parse(execFileSync(process.execPath, ['-e', script], {env: {...process.env, TZ}}).toString());
    assert.equal(r.n, 730, 'every day of 2026 and 2027 once, none skipped or doubled');
    assert.equal(r.last, '2027-12-31');
    assert.ok(r.mondays.every(d => d === 1), 'every week starts on a Monday');
    assert.deepEqual(r.steps, ['2027-01-01', '2026-12-01', '2027-01-04', '2026-03-30', '2026-10-26', '2026-03-30']);
    assert.equal(r.title, '28 Dec – 3 Jan 2027');
  });
}

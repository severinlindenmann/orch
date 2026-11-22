// Focused midnight and time-zone tests for the page labels, on the shared test clock (ORCH-451).
// The whole page suites at a fake hour (CI job clock) now run on merge queue groups, at night and on pull requests
// that change time code; these run on every pull request: the kit's UI.stamp and the dashboard's stamp, on both
// sides of local midnight, in four time zones, and the clock itself.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const {Clock, at, DAY, RealDate} = require('../../../tests/testclock.cjs');
const helpers = require('../../../../workspace-addons/dashboard/src/orch_dashboard/web/helpers.js');
const ZONES = ['UTC', 'America/Los_Angeles', 'Asia/Kolkata', 'Pacific/Auckland'];
const nextDay = {...DAY, day: DAY.day + 1};

function inZone(name, fn) {
  const before = process.env.TZ;
  process.env.TZ = name;   // node re-reads the zone when TZ is set
  try { fn(); } finally { if (before === undefined) delete process.env.TZ; else process.env.TZ = before; }
}

function kit(clock) {
  const window = {};
  vm.runInNewContext(readFileSync(new URL('../static/date.js', import.meta.url), 'utf8'), {window, document: {}, Date: clock.Date});
  return window.UI;
}

test('the shared clock stands still, turns the day when told and puts the real Date back', () => {
  const clock = new Clock(at(23, 59, 59));
  const undo = clock.install();
  try {
    assert.equal(new Date().getDate(), DAY.day);
    assert.equal(Date.now(), clock.ms);
    clock.advance(2000);
    assert.equal(new Date().getDate(), DAY.day + 1);
    assert.equal(new Date('2026-01-02T03:04:05Z').toISOString(), '2026-01-02T03:04:05.000Z');  // a given value stays real
  } finally { undo(); }
  assert.equal(globalThis.Date, RealDate);
});

test('zones really change here (or the tests below would all run in one zone)', () => {
  inZone('Pacific/Auckland', () => assert.equal(at(12).getTimezoneOffset(), -13 * 60));
  inZone('America/Los_Angeles', () => assert.equal(at(12).getTimezoneOffset(), 8 * 60));
});

for (const zone of ZONES) {
  test(`kit UI.stamp: today turns into yesterday at local midnight (${zone})`, () => inZone(zone, () => {
    const clock = new Clock(at(23, 59, 50)), UI = kit(clock), seen = at(23, 58).toISOString();
    assert.equal(UI.stamp(seen), 'today 23:58');
    assert.equal(UI.stamp(at(0, 5, 0, nextDay).toISOString()), 'tomorrow 00:05');
    clock.set(at(0, 0, 10, nextDay));
    assert.equal(UI.stamp(seen), 'yesterday 23:58');
    // local noon is another UTC day in Auckland (UTC+13): the label goes by the local day
    clock.set(at(12, 30));
    assert.equal(UI.stamp(at(12).toISOString()), 'today 12:00');
  }));

  test(`dashboard stamp: today turns into yesterday at local midnight (${zone})`, () => inZone(zone, () => {
    const seen = at(23, 58).toISOString();
    assert.equal(helpers.stamp(seen, at(23, 59, 50).getTime()), 'today 23:58');
    assert.equal(helpers.stamp(seen, at(0, 0, 10, nextDay).getTime()), 'yesterday 23:58');
    assert.equal(helpers.stamp(at(12).toISOString(), at(12, 30).getTime()), 'today 12:00');
  }));
}

test('kit UI.stamp counts days across a daylight-saving change (Los Angeles, 1 Nov 2026)', () => inZone('America/Los_Angeles', () => {
  // 31 Oct to 1 Nov has 25 hours there; a week later it is still "Sun", not a day off
  const clock = new Clock(at(9, 0, 0, {year: 2026, month: 11, day: 2})), UI = kit(clock);
  assert.equal(UI.stamp(at(23, 0, 0, {year: 2026, month: 11, day: 1}).toISOString()), 'yesterday 23:00');
  assert.equal(UI.stamp(at(10, 0, 0, {year: 2026, month: 10, day: 31}).toISOString()), 'Sat 10:00');
}));

'use strict';
/* One shared test clock for the page tests (node --test), the twin of testclock.py next to this file (ORCH-451).
   A page test that shows something by the day ("today 10:15", "in 3 hours", a weekday) runs on this clock, so it
   passes at whatever hour CI runs it:

     const {Clock, at} = require('../../../workspace/tests/testclock.cjs');   // or import from an .mjs test
     const clock = new Clock(at(23, 59, 59));          // local time on the fixed day DAY
     vm.runInNewContext(src, {window, document, Date: clock.Date});   // code loaded in a vm context, or
     const undo = clock.install();  ...  undo();        // code that reads the global Date
     clock.advance(2000);                               // the day turns over when the test says so

   new Date() with no argument and Date.now() read the clock; new Date(value) and everything else is the real Date. */

const RealDate = Date;
const DAY = {year: 2026, month: 11, day: 11};   // a Wednesday; no daylight-saving change within a week in CI's zones

/* A Date at hh:mm:ss local time on `day` (default DAY). */
function at(hour = 12, minute = 0, second = 0, day = DAY) {
  return new RealDate(day.year, day.month - 1, day.day, hour, minute, second, 0);
}

class Clock {
  constructor(start = at(12)) {
    this.ms = start instanceof RealDate ? start.getTime() : Number(start);
    const clock = this;
    this.Date = class extends RealDate {
      constructor(...a) { if (a.length) super(...a); else super(clock.ms); }
      static now() { return clock.ms; }
    };
  }
  now() { return new RealDate(this.ms); }
  iso() { return new RealDate(this.ms).toISOString(); }
  advance(ms) { this.ms += ms; return this.now(); }
  set(when) { this.ms = when instanceof RealDate ? when.getTime() : Number(when); }
  /* Put the global Date on this clock; returns the function that puts the real one back. */
  install() {
    const before = globalThis.Date;
    globalThis.Date = this.Date;
    return () => { globalThis.Date = before; };
  }
}

module.exports = {Clock, at, DAY, RealDate};

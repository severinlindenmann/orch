import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const Q = require('../static/question-card-state.js');

function fakeClock() {
  let t = 0, next = 1; const timers = new Map();
  return {
    now: () => t,
    setTimeout: (f, ms) => { const id = next++; timers.set(id, {f, at: t + ms}); return id; },
    clearTimeout: id => timers.delete(id),
    async advance(ms) {
      const end = t + ms;
      for (;;) {
        const due = [...timers.entries()].filter(([, v]) => v.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        timers.delete(due[0]); t = due[1].at; due[1].f();
        await Promise.resolve(); await Promise.resolve();
      }
      t = end;
    },
  };
}
const memStorage = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, v), removeItem: k => m.delete(k), m}; };
const tick = () => new Promise(r => setImmediate(r));

function make(sendImpl) {
  const clock = fakeClock(), storage = memStorage(), sent = [];
  const card = Q.create({key: 'q', clock, storage, newId: () => 'a1', send: async (a, id) => { sent.push([a, id]); return sendImpl ? sendImpl(a, id) : {status: 200, who: 'Marco', via: 'dashboard'}; }});
  return {card, clock, storage, sent};
}

test('undo within 5 s sends nothing', async () => {
  const {card, clock, sent, storage} = make();
  assert.ok(card.choose('Yes').ok);
  assert.equal(card.getState().phase, 'pending');
  await clock.advance(4000);
  assert.ok(card.undo());
  await clock.advance(10000); await tick();
  assert.equal(sent.length, 0);
  assert.equal(card.getState().phase, 'undone');
  assert.equal(storage.m.size, 0);
});

test('after 5 s exactly one send, with the action id', async () => {
  const {card, clock, sent} = make();
  card.choose('Yes');
  await clock.advance(4999); assert.equal(sent.length, 0);
  await clock.advance(1); await tick();
  await clock.advance(20000); await tick();
  assert.deepEqual(sent, [['Yes', 'a1']]);
  assert.deepEqual(card.getState(), {phase: 'sent', answer: 'Yes', who: 'Marco', via: 'dashboard'});
  assert.equal(card.undo(), false);
});

test('countdown shows the seconds left', async () => {
  const {card, clock} = make();
  card.choose('Yes');
  assert.equal(card.getState().secondsLeft, 5);
  await clock.advance(1000);
  assert.equal(card.getState().secondsLeft, 4);
});

test('409 shows the other answer: who and via', async () => {
  const {card, clock} = make(() => ({status: 409, other: {text: 'No', who: 'Marco', via: 'phone'}}));
  card.choose('Yes');
  await clock.advance(5000); await tick();
  const s = card.getState();
  assert.equal(s.phase, 'conflict');
  assert.equal(Q.otherLine(s.other), 'No · Marco · phone');
});

test('a reload with an unsent pending answer shows not sent', async () => {
  const a = make();
  a.card.choose('Yes');                       // tab closes here, nothing sent
  const clock = fakeClock(), sent = [];
  const reloaded = Q.create({key: 'q', clock, storage: a.storage, send: async x => sent.push(x)});
  assert.equal(reloaded.init().phase, 'notsent');
  assert.equal(reloaded.getState().answer, 'Yes');
  assert.equal(sent.length, 0);
  assert.equal(a.storage.m.size, 0);          // shown once
});

test('free text over 2000 characters is refused, 2000 is fine', async () => {
  const {card, sent, clock} = make();
  const r = card.choose('x'.repeat(2001));
  assert.equal(r.ok, false);
  assert.match(r.error, /2000/);
  assert.equal(card.getState().phase, 'idle');
  assert.ok(card.choose('x'.repeat(2000)).ok);
  await clock.advance(5000); await tick();
  assert.equal(sent.length, 1);
  assert.equal(card.choose('   ').ok, false);
});

test('server or network failure becomes an error state, not a silent loss', async () => {
  const {card, clock} = make(() => { throw new Error('down'); });
  card.choose('Yes');
  await clock.advance(5000); await tick();
  assert.equal(card.getState().phase, 'error');
});

test('a second tap while pending is ignored', () => {
  const {card} = make();
  card.choose('Yes');
  assert.equal(card.choose('No').ok, false);
  assert.equal(card.getState().answer, 'Yes');
});

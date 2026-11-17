// ORCH-102: a click shows the pressed button's busy state at once, and all tabs of a browser share one event
// stream (a browser opens at most 6 connections to the server; every tab held one for good).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const app = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/app.js'), 'utf8');
const slice = (from, to) => app.slice(app.indexOf(from), app.indexOf(to, app.indexOf(from)));

function control() {
  const attrs = {};
  return {
    isConnected: true, attrs,
    getAttribute: k => (k in attrs ? attrs[k] : null),
    setAttribute: (k, v) => { attrs[k] = String(v); },
    removeAttribute: k => { delete attrs[k]; },
  };
}

function busyHarness() {
  let onClick;
  const document = {addEventListener: (type, fn, capture) => { if (type === 'click' && capture) onClick = fn; }};
  const c = vm.createContext({document, Date});
  vm.runInContext(slice('let pressed = null;', 'async function act(') + '\nthis.busyOn = busyOn; this.busyOff = busyOff;', c);
  const press = el => onClick({target: {closest: () => el}});
  return {c, press};
}

test('the pressed button is busy at once and is plain again when the answer came', () => {
  const {c, press} = busyHarness();
  const b = control();
  press(b);
  const busy = c.busyOn();
  assert.equal(b.attrs['aria-busy'], 'true');
  assert.equal(b.attrs['aria-disabled'], 'true');  // the kit's disabled look: a visible change, no new CSS
  c.busyOff(busy);
  assert.deepEqual(b.attrs, {});
});

test('a button that was disabled before stays disabled; an old press or a second act marks nothing', () => {
  const {c, press} = busyHarness();
  const b = control();
  b.setAttribute('aria-disabled', 'false');
  press(b);
  const busy = c.busyOn();
  assert.equal(c.busyOn(), null, 'one press marks one act');
  c.busyOff(busy);
  assert.deepEqual(b.attrs, {'aria-disabled': 'false'});
  const real = Date.now;
  press(b);
  c.Date.now = () => real() + 5000;  // the act came long after the press (a timer, a poll)
  try { assert.equal(c.busyOn(), null); } finally { c.Date.now = real; }
});

test('act sets the busy state before it sends and clears it in finally', () => {
  const act = slice('async function act(', '\n}\n');
  assert.ok(act.indexOf('busyOn()') < act.indexOf("fetch('/api/act'"));
  assert.match(act, /finally \{\n\s+busyOff\(busy\);/);
});

// A small browser: tabs share locks and a BroadcastChannel; EventSource counts the open streams.
function browser() {
  const held = new Map(), queue = new Map(), channels = new Set(), streams = [];
  const locks = {
    request(name, fn) {
      return new Promise(done => {
        const grant = () => { held.set(name, true); Promise.resolve(fn()).then(v => { held.delete(name); const next = (queue.get(name) || []).shift(); if (next) next(); done(v); }); };
        if (held.get(name)) { if (!queue.has(name)) queue.set(name, []); queue.get(name).push(grant); } else grant();
      });
    },
  };
  class Channel {
    constructor() { this.onmessage = null; channels.add(this); }
    postMessage(data) { for (const ch of channels) if (ch !== this) queueMicrotask(() => ch.onmessage?.({data})); }
  }
  class ES {
    constructor(url) { this.url = url; this.open = true; this.listeners = {}; streams.push(this); queueMicrotask(() => this.onopen?.()); }
    addEventListener(type, fn) { this.listeners[type] = fn; }
    close() { this.open = false; }
    fire(type) { this.listeners[type]?.(); }
  }
  const tab = () => {
    const handlers = {};
    const win = {navigator: {locks}, BroadcastChannel: Channel, EventSource: ES,
      addEventListener: (type, fn) => { (handlers[type] = handlers[type] || []).push(fn); }};
    const seen = {revs: 0, up: null};
    const c = vm.createContext({});
    vm.runInContext(slice('function sharedEvents(', '\n}\n') + '\n}\nthis.sharedEvents = sharedEvents;', c);
    c.sharedEvents(win, () => seen.revs++, up => { seen.up = up; });
    return {seen, close: () => (handlers.pagehide || []).forEach(fn => fn({}))};
  };
  return {tab, open: () => streams.filter(s => s.open)};
}
const settle = () => new Promise(r => setTimeout(r, 5));

test('five tabs hold one event stream; every tab hears each change', async () => {
  const b = browser();
  const tabs = Array.from({length: 5}, b.tab);
  await settle();
  assert.equal(b.open().length, 1, 'one connection, not five');
  b.open()[0].fire('rev');
  await settle();
  assert.deepEqual(tabs.map(t => t.seen.revs), [1, 1, 1, 1, 1]);
  assert.ok(tabs.every(t => t.seen.up === true), 'every tab knows the stream is up (slow poll)');
});

test('when the tab with the stream closes, another tab opens it', async () => {
  const b = browser();
  const tabs = Array.from({length: 3}, b.tab);
  await settle();
  const first = b.open()[0];
  tabs[0].close();
  await settle();
  assert.equal(first.open, false);
  assert.equal(b.open().length, 1, 'the next tab took over');
  b.open()[0].fire('rev');
  await settle();
  assert.deepEqual(tabs.slice(1).map(t => t.seen.revs), [1, 1]);
});

test('without locks each tab keeps its own stream (old browsers)', () => {
  let opened = 0;
  const win = {navigator: {}, EventSource: class { constructor() { opened++; } addEventListener() {} }, addEventListener() {}};
  const c = vm.createContext({});
  vm.runInContext(slice('function sharedEvents(', '\n}\n') + '\n}\nthis.sharedEvents = sharedEvents;', c);
  c.sharedEvents(win, () => {}, () => {});
  assert.equal(opened, 1);
});

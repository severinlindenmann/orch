const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('modules register without bootstrapping and store notifies subscribers', () => {
  const root = {};
  let fetches = 0, intervals = 0;
  const context = vm.createContext({
    window: {FocusProof: {create: () => ({})}},
    document: {
      getElementById: id => id === 'fx' ? root : null,
      documentElement: {dataset: {}},
    },
    location: {pathname: '/'},
    matchMedia: () => ({matches: false}),
    fetch: () => { fetches++; return new Promise(() => {}); },
    setInterval: () => { intervals++; },
  });
  for (const name of ['store', 'jobs', 'session', 'settings', 'live', 'ticket']) {
    const file = path.join(__dirname, '../src/orch_focus/web', name + '.js');
    vm.runInContext(fs.readFileSync(file, 'utf8'), context, {filename: file});
  }
  const S = context.window.FocusStore;
  assert.deepEqual(Object.keys(S.views).sort(), ['jobs', 'live', 'session', 'settings', 'ticket']);
  assert.equal(S.root, root);
  assert.equal(fetches, 0);
  assert.equal(intervals, 0);
  const received = [];
  const unsubscribe = S.subscribe(v => received.push(v));
  const v = {ticket: {}};
  S.notify(v);
  assert.deepEqual(received, [v]);
  unsubscribe();
  S.notify({});
  assert.deepEqual(received, [v]);
});

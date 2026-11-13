// Focus pass 2: work log minutes from the recorded task markers, the "N new" pill, and the Terminal-mode columns.
const test = require('node:test'), assert = require('node:assert'), vm = require('node:vm'), fs = require('node:fs'), path = require('node:path');
const web = f => fs.readFileSync(path.join(__dirname, '..', 'src', 'orch_focus', 'web', f), 'utf8');

function live() {
  const pill = {hidden: true, textContent: ''}, pane = {scrollHeight: 1000, scrollTop: 0, clientHeight: 400, scrolled: 0, scrollTo(o) { this.scrolled++; }};
  const els = {newPill: pill, paneLive: pane, tabs: [{click() {}}]};
  const S = {h: () => ({}), TID: 't_1', toast() {}, els, act() {}, STATUS_WORD: {}, plainNames: x => x, keyOf: JSON.stringify,
    hhmm: x => x, evText: () => '', reduce: true, state: {follow: false}, views: {}, register: (n, m) => { S.views[n] = m; }};
  const ctx = vm.createContext({window: {FocusStore: S}, requestAnimationFrame: f => f(), document: {}});
  vm.runInContext(web('live.js'), ctx);
  return {S, pill, pane, live: S.views.live};
}
const ev = (kind, at, check, text) => ({kind, at, text: text || '', data: check ? {check} : {}});

test('work log minutes come from the recorded start and finish of each task', () => {
  const {live: L} = live();
  const v = {events: [ev('task.start', '2026-11-13T12:20:00Z', 'c1'), ev('task.done', '2026-11-13T12:26:00Z', 'c1'), ev('task.start', '2026-11-13T12:27:00Z', 'c2'), ev('tool.start', '2026-11-13T12:36:00Z', null, 'x')]};
  assert.equal(L.taskMinutes(v, 'c1'), '6 min');
  assert.equal(L.taskMinutes(v, 'c2'), '9 min');  // still working: counts to the newest event
  assert.equal(L.taskMinutes(v, 'c9'), '');  // no marker, nothing invented
});

test('with Follow off, new steps show an "N new" pill and never scroll; with it on they scroll', () => {
  const {live: L, pill, pane, S} = live();
  const items = n => Array.from({length: n}, (_, i) => ({at: '2026-11-13T12:' + String(10 + i), text: 's' + i}));
  L.followUpdate(items(3), true);
  assert.equal(pill.hidden, true);
  L.followUpdate(items(5), false);
  assert.equal(pill.hidden, false);
  assert.equal(pill.textContent, '2 new');
  assert.equal(pane.scrolled, 0);
  L.jumpToNew();
  assert.equal(pill.hidden, true);
  S.state.follow = true;
  L.followUpdate(items(6), false);
  assert.equal(pill.hidden, true);
  assert.ok(pane.scrolled >= 2);
});

test('Terminal mode has three columns at 1920 and two at 1280, composer sticky in its column', () => {
  const css = web('focus.css');
  assert.match(css, /@media\(min-width:1500px\)\{[^}]*fx-terminal \.fx-body\{[^}]*minmax\(400px,460px\)/);
  assert.match(css, /grid-template-areas:"rail human" "stage human"/);
  assert.match(css, /\.fx\.fx-terminal \.fx-human>\.fx-compose[^{]*\{position:sticky;bottom:0/);
});

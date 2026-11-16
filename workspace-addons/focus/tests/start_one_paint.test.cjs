// ORCH-18: the Focus start page shows once. Before, the ticket lists drew at once and a few seconds later the
// Live now answer moved the working tickets into cards and narrowed the page: it looked like a second page.
const test = require('node:test'), assert = require('node:assert'), vm = require('node:vm'), fs = require('node:fs'), path = require('node:path');
const web = f => fs.readFileSync(path.join(__dirname, '..', 'src', 'orch_focus', 'web', f), 'utf8');

function node() {
  return {hidden: false, children: [], isConnected: true, classList: {toggle() {}}, append(...c) { this.children.push(...c); },
    replaceChildren(...c) { this.children = c; }, querySelector: () => null, querySelectorAll: () => [], contains: () => false,
    insertBefore(c) { this.children.push(c); }};
}
function liveNow(fetch) {
  const S = {h: () => node(), P: '', hhmm: x => x, toast() {}, act() {}, state: {}, views: {}, register: (n, m) => { S.views[n] = m; }};
  const timers = [];
  const ctx = vm.createContext({window: {FocusStore: S}, document: {hidden: false, addEventListener() {}, activeElement: null},
    fetch, setTimeout, setInterval: (f) => { timers.push(f); return timers.length; }, clearInterval() {}});
  vm.runInContext(web('live-now.js'), ctx);
  return S.views.livenow;
}
const settled = (p, ms) => Promise.race([p.then(() => true), new Promise(done => setTimeout(() => done(false), ms))]);

test('the start page waits until the first Live now answer is drawn', async () => {
  let answer;
  const L = liveNow(() => new Promise(done => { answer = done; }));
  L.mount(node());
  const ready = L.ready(1000);
  assert.equal(await settled(ready, 30), false, 'still waiting while the answer is on its way');
  answer({ok: true, json: async () => ({cards: []})});
  assert.equal(await settled(ready, 200), true, 'ready once the answer is in');
});

test('a slow or broken Live now answer never keeps the tickets hidden', async () => {
  const hang = liveNow(() => new Promise(() => {}));
  hang.mount(node());
  assert.equal(await settled(hang.ready(40), 400), true, 'gives up after the wait');
  const broken = liveNow(() => Promise.reject(new Error('down')));
  broken.mount(node());
  assert.equal(await settled(broken.ready(1000), 200), true, 'a failed answer counts as done');
});

test('the lists are drawn only after the Live now wait, and the in-app jump to a ticket does not wait', () => {
  const js = web('ticket.js');
  const wait = js.indexOf('S.views.livenow.ready(LIVE_WAIT_MS)'), jump = js.indexOf('location.replace(P + \'/t/\' + next.ticket.id'), groups = js.indexOf("['waiting', 'Needs you', 'Answer']");
  assert.ok(wait > 0 && jump > 0 && groups > 0);
  assert.ok(jump < wait && wait < groups);
});

test('live cards no longer change the page width', () => {
  assert.doesNotMatch(web('focus.css'), /fx-pick-live/);
  assert.doesNotMatch(web('live-now.js'), /fx-pick-live/);
});

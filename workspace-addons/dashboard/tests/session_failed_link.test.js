// A sign-in link that is refused (used twice, ended) must show its words, not leave the stopped page on empty boxes.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function run(status, text, opts = {}) {
  const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'orch_dashboard', 'web', 'session.js'), 'utf8');
  const added = [];
  const el = () => ({ style: {}, setAttribute() {}, appendChild() {}, remove() {}, set textContent(v) { this.text = v; } });
  const body = { firstChild: null, insertBefore(b) { added.push(b); } };
  const document = { getElementById: () => null, createElement: el, querySelectorAll: () => [], body, documentElement: body };
  const listeners = {}, posted = [], stopped = [], saved = {};
  const window = {
    stop() { stopped.push(true); },
    addEventListener(n, f) { listeners[n] = f; },
    fetch: (u, i) => { posted.push(i && i.body); return Promise.resolve({ ok: status === 200, status, text: () => Promise.resolve(text), json: () => Promise.resolve({ secret: 's3' }), clone() { return this; } }); },
  };
  const loc = { hash: opts.hash !== undefined ? opts.hash : '#launch=' + 'a'.repeat(30), pathname: '/', search: '', reloaded: 0, reload() { this.reloaded++; }, href: 'http://127.0.0.1:1/' };
  const ctx = {
    window, document, localStorage: { getItem: () => '', setItem: (k, v) => { saved[k] = v; } }, sessionStorage: { getItem: () => '', removeItem() {} },
    location: loc,
    history: { replaceState() { loc.hash = ''; } }, Headers: class { set() {} }, URL, Object, JSON, Promise,
  };
  vm.runInNewContext(src, ctx);
  if (opts.paste) {  // a sign-in link pasted into the open tab: only the hash changes, no load
    loc.hash = opts.paste;
    const ev = { stoppedNow: false, stopImmediatePropagation() { this.stoppedNow = true; } };
    listeners.hashchange(ev);
    opts.event = ev;
  }
  const out = { added, posted, stopped, loc, listeners, saved };
  return new Promise((r) => setTimeout(() => r(opts.full ? out : added), 20));
}

test('a refused sign-in link shows the server words', async () => {
  const added = await run(403, 'Someone else tried to use this sign-in link. Open the dashboard again from orch.');
  assert.strictEqual(added.length, 1);
});

test('an accepted sign-in link shows no notice', async () => {
  assert.strictEqual((await run(200, '{}')).length, 0);
});

// #1918: a sign-in link pasted into an already open tab (only the hash changes) signs in instead of "Page not found".
test('a sign-in link pasted into an open tab signs in and reloads', async () => {
  const opts = { hash: '#home', paste: '#launch=' + 'b'.repeat(30), full: true };
  const out = await run(200, '{}', opts);
  assert.strictEqual(out.posted.length, 1);
  assert.match(out.posted[0], /"token":"b{30}"/);
  assert.strictEqual(out.loc.hash, '');             // the token left the address bar before the app could route to it
  assert.strictEqual(opts.event.stoppedNow, true);  // the app's router never sees this hash change
  assert.strictEqual(out.stopped.length, 0);        // a loaded page is not stopped
  assert.strictEqual(out.saved.orch_page_secret, 's3');  // the page secret is kept for after the reload
  assert.strictEqual(out.loc.reloaded, 1);
});

test('an ordinary page change in an open tab is left to the app', async () => {
  const opts = { hash: '#home', paste: '#tickets', full: true };
  const out = await run(200, '{}', opts);
  assert.strictEqual(out.posted.length, 0);
  assert.strictEqual(opts.event.stoppedNow, false);
  assert.strictEqual(out.loc.hash, '#tickets');
});

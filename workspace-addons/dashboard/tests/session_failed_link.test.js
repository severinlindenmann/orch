// A sign-in link that is refused (used twice, ended) must show its words, not leave the stopped page on empty boxes.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function run(status, text) {
  const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'orch_dashboard', 'web', 'session.js'), 'utf8');
  const added = [];
  const el = () => ({ style: {}, setAttribute() {}, appendChild() {}, remove() {}, set textContent(v) { this.text = v; } });
  const body = { firstChild: null, insertBefore(b) { added.push(b); } };
  const document = { getElementById: () => null, createElement: el, querySelectorAll: () => [], body, documentElement: body };
  const window = {
    stop() {},
    fetch: () => Promise.resolve({ ok: status === 200, status, text: () => Promise.resolve(text), json: () => Promise.resolve({}), clone() { return this; } }),
  };
  const ctx = {
    window, document, localStorage: { getItem: () => '' }, sessionStorage: { getItem: () => '' },
    location: { hash: '#launch=' + 'a'.repeat(30), pathname: '/', search: '', reload() {}, href: 'http://127.0.0.1:1/' },
    history: { replaceState() {} }, Headers: class { set() {} }, URL, Object, JSON, Promise,
  };
  vm.runInNewContext(src, ctx);
  return new Promise((r) => setTimeout(() => r(added), 20));
}

test('a refused sign-in link shows the server words', async () => {
  const added = await run(403, 'Someone else tried to use this sign-in link. Open the dashboard again from orch.');
  assert.strictEqual(added.length, 1);
});

test('an accepted sign-in link shows no notice', async () => {
  assert.strictEqual((await run(200, '{}')).length, 0);
});

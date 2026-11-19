// A sign-in link that is refused (used twice, ended) must show its words, not leave the stopped page on empty boxes.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const nav = {};
function run(status, text, made = []) {
  const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'orch_dashboard', 'web', 'session.js'), 'utf8');
  const added = [];
  const el = (tag) => { const e = { tag, style: {}, setAttribute() {}, appendChild() {}, remove() {}, set textContent(v) { this.text = v; }, get textContent() { return this.text; } }; made.push(e); return e; };
  const body = { firstChild: null, insertBefore(b) { added.push(b); } };
  const document = { getElementById: () => null, createElement: el, querySelectorAll: () => [], body, documentElement: body };
  const window = {
    stop() {},
    fetch: () => Promise.resolve({ ok: status === 200, status, text: () => Promise.resolve(text), json: () => Promise.resolve({}), clone() { return this; } }),
  };
  const ctx = {
    window, document, localStorage: { getItem: () => '' }, sessionStorage: { getItem: () => '' },
    location: { hash: '#launch=' + 'a'.repeat(30), pathname: '/', search: '', reload() {}, href: 'http://127.0.0.1:1/' },
    history: { replaceState() {} }, navigator: nav, Headers: class { set() {} }, URL, Object, JSON, Promise,
  };
  vm.runInNewContext(src, ctx);
  return new Promise((r) => setTimeout(() => r(added), 20));
}

test('a refused sign-in link shows the server words', async () => {
  const added = await run(403, 'Someone else tried to use this sign-in link. Sign in again: run orch dashboard open in your terminal.');
  assert.strictEqual(added.length, 1);
});

test('an accepted sign-in link shows no notice', async () => {
  assert.strictEqual((await run(200, '{}')).length, 0);
});

test('a notice that names the sign-in command offers to copy it', async () => {
  const made = [];
  await run(403, 'Someone else tried to use this sign-in link. Sign in again: run orch dashboard open in your terminal.', made);
  const copy = made.find((e) => e.tag === 'button' && e.text === 'Copy command');
  assert.ok(copy, 'a Copy command button');
  let copied = '';
  nav.clipboard = { writeText: (t) => { copied = t; return Promise.resolve(); } };
  copy.onclick();
  await new Promise((r) => setTimeout(r, 5));
  delete nav.clipboard;
  assert.strictEqual(copied, 'orch dashboard open');
  assert.strictEqual(copy.text, 'Copied');
});

test('a notice without the command has no copy button', async () => {
  const made = [];
  await run(403, 'This sign-in link did not work.', made);
  assert.ok(!made.some((e) => e.text === 'Copy command'));
});

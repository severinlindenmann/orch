// A browser the dashboard does not know (401), or one Personal refuses (403), must see the sign-in notice, not the
// "can't be shown right now / Reload the page" error (a reload never helps).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SRC = fs.readFileSync(process.env.PERSONAL_JS || path.join(__dirname, '..', 'src', 'orch_personal', 'web', 'personal.js'), 'utf8');

function node(tag) {
  return {tag, className: '', children: [], attrs: {}, hidden: false, textContent: '',
    append(...k) { this.children.push(...k.filter(c => c != null)); },
    replaceChildren(...k) { this.children = k.filter(c => c != null); },
    setAttribute(n, v) { this.attrs[n] = v; }, addEventListener() {}, firstChild: {}, get text() {
      return this.textContent + this.children.map(c => typeof c === 'string' ? c : c.text || '').join(' ');
    }};
}

async function run(status) {
  const ids = {};
  const document = {
    documentElement: {dataset: {prefix: ''}},
    getElementById: id => ids[id] || (ids[id] = node(id)),
    createElement: node,
  };
  const fetch = async () => ({ok: false, status, json: async () => { throw new Error('not json'); }});
  const ctx = vm.createContext({document, fetch, addEventListener() {}, location: {pathname: '/', hash: ''},
    AbortSignal: {timeout: () => undefined}, Node: Object, window: {}, decodeURIComponent});
  vm.runInContext(SRC, ctx);
  await new Promise(r => setTimeout(r, 20));
  return ids.view.text;
}

for (const status of [401, 403]) {
  test(`status ${status} shows the sign-in notice`, async () => {
    const text = await run(status);
    assert.match(text, /Sign in to see Personal/);
    assert.match(text, /sign-in link from orch/);
    assert.doesNotMatch(text, /Reload the page/);
  });
}

test('a server error keeps the reload error', async () => {
  const text = await run(500);
  assert.match(text, /can’t be shown right now/);
  assert.match(text, /Reload the page/);
});

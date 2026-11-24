// Personal with nothing added (ORCH-1853): one way to use a first note in a ticket instead of a second
// "Add a part"; nothing is turned on until a folder is chosen. With a part added, Home keeps its tiles.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'src', 'orch_personal', 'web', 'personal.js'), 'utf8');
const TILE = {part: 'notes', label: 'Notes', state: 'ok', status: '3 notes', line: 'Campaign brief', uses: 'only notes you attach to a ticket'};

function node(tag) {
  return {tag, className: '', children: [], attrs: {}, dataset: {}, hidden: false, textContent: '', on: {},
    append(...k) { this.children.push(...k.filter(c => c != null)); },
    replaceChildren(...k) { this.children = k.filter(c => c != null); },
    setAttribute(n, v) { this.attrs[n] = v; }, addEventListener(t, f) { this.on[t] = f; }, firstChild: {},
    showModal() { this.open = true; }, focus() {},
    get text() { return this.textContent + this.children.map(c => typeof c === 'string' ? c : c.text || '').join(' '); }};
}
const all = (n, ok, out = []) => { if (n && typeof n === 'object') { if (ok(n)) out.push(n); (n.children || []).forEach(c => all(c, ok, out)); } return out; };

async function home(parts) {
  const ids = {}, posts = [];
  const document = {documentElement: {dataset: {prefix: ''}}, getElementById: id => ids[id] || (ids[id] = node(id)), createElement: node};
  const today = {parts, needs_you: [], activity: [], ways: [], soon: [], later: []};
  const fetch = async (url, init) => {
    if (init && init.method === 'POST') posts.push(init.body);
    return {ok: true, status: 200, json: async () => today};
  };
  const ctx = vm.createContext({document, fetch, addEventListener() {}, location: {pathname: '/', hash: ''},
    AbortSignal: {timeout: () => undefined}, Node: Object, window: {}, decodeURIComponent, matchMedia: () => ({matches: true})});
  vm.runInContext(SRC, ctx);
  await new Promise(r => setTimeout(r, 20));
  return {view: ids.view, ids, posts};
}

test('nothing added: one route to a first note, no second Add a part, nothing turned on', async () => {
  const {view, ids, posts} = await home([]);
  assert.match(view.text, /Use a note in a ticket/);
  assert.match(view.text, /Helpers read none of them yet/);  // reading the folder is not attaching a note
  assert.match(view.text, /Only that note is copied to the ticket you pick/);
  assert.doesNotMatch(view.text, /Files and Tasks|Nothing is added yet/);
  assert.equal(all(view, n => /part-tile-add/.test(n.className)).length, 0);
  const primary = all(view, n => n.tag === 'button' && /primary/.test(n.className));
  assert.deepEqual(primary.map(b => b.text.trim()), ['Choose notes folder']);
  primary[0].on.click();
  assert.equal(ids['folder-dialog'].open, true);
  assert.deepEqual(posts, []);  // opening the folder choice turns nothing on
});

test('a part added: Home keeps its tiles and the Add a part tile', async () => {
  const {view} = await home([TILE]);
  assert.equal(all(view, n => /part-tile-add/.test(n.className)).length, 1);
  assert.doesNotMatch(view.text, /Use a note in a ticket/);
});

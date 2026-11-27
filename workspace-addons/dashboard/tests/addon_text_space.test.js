// Add-on page text is cleaned one text node at a time (pages/settings.js paintAddon). A title with a ticket number is
// split around it (blocks.js keepRefs: 'ORCH-1098' in its own span, then ' team chat draft'), so the cleaning must keep
// the space at either end of a node (report r-1127-0539-ws-3: 'ORCH-1098team chat draft' on the Services page).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const web = path.join(__dirname, '../src/orch_dashboard/web');
const app = fs.readFileSync(path.join(web, 'app.js'), 'utf8');
const settings = fs.readFileSync(path.join(web, 'pages/settings.js'), 'utf8');

const slice = (src, from, to) => { const i = src.indexOf(from); assert.ok(i >= 0, from); const j = src.indexOf(to, i); assert.ok(j > i, to); return src.slice(i, j); };

function load() {
  const ctx = vm.createContext({});
  vm.runInContext(slice(app, 'let wsNames', '// The tags clean() hides') + '\nthis.clean = clean; this.cleanTextNode = cleanTextNode;', ctx);
  return ctx;
}

test('the text after a ticket number keeps its space', () => {
  const c = load();
  assert.equal(c.cleanTextNode(' team chat draft'), ' team chat draft');
  assert.equal('ORCH-1098' + c.cleanTextNode(' team chat draft'), 'ORCH-1098 team chat draft');
  assert.equal(c.cleanTextNode('Browser sign-in drafts ('), 'Browser sign-in drafts (');
  assert.equal(c.cleanTextNode('Ask ') + 'DM-2' + c.cleanTextNode(' now'), 'Ask DM-2 now');
});

test('a node that is only a space stays one space; an id alone still leaves', () => {
  const c = load();
  assert.equal(c.cleanTextNode(' '), ' ');
  assert.equal(c.cleanTextNode('t_abcdef12'), '');
  assert.equal(c.cleanTextNode('[E2E] Export [1731400000]'), 'Export');
});

test('the add-on page cleans its text nodes with the space-keeping cleaner', () => {
  const paint = slice(settings, 'function paintAddon(', 'pendingRepeat &&');
  assert.match(paint, /currentNode\.data = cleanTextNode\(walker\.currentNode\.data\)/);
});

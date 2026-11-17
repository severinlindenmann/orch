const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const web = path.join(__dirname, '../src/orch_dashboard/web');
const app = fs.readFileSync(path.join(web, 'app.js'), 'utf8');
const form = fs.readFileSync(path.join(web, 'pages/newticket.js'), 'utf8');

// persona test F6: no keyboard shortcuts.
const from = app.indexOf('function shortcutFor'), to = app.indexOf('\n}\n', from) + 3;
const ctx = vm.createContext({});
vm.runInContext(app.slice(from, to) + '\nthis.f = shortcutFor;', ctx);
const key = (k, extra = {}) => ({key:k, defaultPrevented:false, altKey:false, ctrlKey:false, metaKey:false, ...extra});
test('"/" is search and "n" is a new ticket', () => {
  assert.equal(ctx.f(key('/'), false, false), 'search');
  assert.equal(ctx.f(key('n'), false, false), 'new');
  assert.equal(ctx.f(key('x'), false, false), '');
});
test('no shortcut while typing, with a window open or with a modifier key', () => {
  assert.equal(ctx.f(key('/'), true, false), '');
  assert.equal(ctx.f(key('n'), false, true), '');
  assert.equal(ctx.f(key('n', {metaKey:true}), false, false), '');
  assert.equal(ctx.f(key('n', {ctrlKey:true}), false, false), '');
  assert.equal(ctx.f(key('n', {defaultPrevented:true}), false, false), '');
});
test('the app listens for shortcuts and skips a shared copy', () => {
  assert.match(app, /if \(!what \|\| snapshot\) return;/);
  assert.match(app, /document\.querySelector\('dialog\[open\]'\)/);
});
test('New ticket saves with Cmd+Enter or Ctrl+Enter', () => {
  assert.match(form, /event\.key === 'Enter' && \(event\.metaKey \|\| event\.ctrlKey\)[^}]*form\.requestSubmit\(\)/);
});

'use strict';
// ORCH-742 (look B): the ticket list says quietly where Prepare stands on a saved ticket in Backlog.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/tickets.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/widgets.css'), 'utf8');
const c = {h:(tag, attrs, ...children) => ({tag, attrs, children})};
vm.createContext(c);
vm.runInContext(source.slice(source.indexOf('function prepareWord'), source.indexOf('const changesLine')), c);
test('list: Preparing… and Prepared after the title, nothing for other states or once it left Backlog', () => {
  assert.deepEqual(c.prepareWord({id:'t', status:'open', prepare:{state:'preparing'}}).children, ['· Preparing…']);
  const done = c.prepareWord({id:'t', status:'open', prepare:{state:'prepared'}});
  assert.deepEqual(done.children, ['· Prepared']);
  assert.equal(done.attrs.title, 'Described by the helper, not checked');
  for (const t of [{status:'open', prepare:{state:'not_prepared'}}, {status:'open', prepare:{state:'waiting'}}, {status:'active', prepare:{state:'prepared'}}, {status:'open'}, {status:'open', prepare:'x'}]) assert.equal(c.prepareWord({id:'t', ...t}), null);
});
test('the Prepare looks live in the master sheet, tokens only', () => {
  for (const cls of ['.prepare-line', '.prepared-word', '.prepare-word', 'details.found-fold', '.found-src', '.found-closed-list']) assert.ok(css.includes(cls), cls);
  const block = css.slice(css.indexOf('/* Prepare on a saved ticket'));
  assert.doesNotMatch(block, /#[0-9a-f]{3,6}\b/i, 'no colour outside the tokens');
});

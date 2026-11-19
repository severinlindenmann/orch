// ORCH-908: counts use the normal font, the narrow To do lane heading stays on one line, and the
// New ticket Done when box has room for its whole placeholder.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const web = path.join(__dirname, '..', 'src', 'orch_dashboard', 'web');
const read = f => fs.readFileSync(path.join(web, f), 'utf8');

function rule(css, selector) {
  const i = css.indexOf(selector + '{');
  assert.ok(i >= 0, selector + ' rule exists');
  return css.slice(i, css.indexOf('}', i));
}

test('lane, card and tab counts are not monospace', () => {
  for (const [file, sel] of [['style.css', '.status-count'], ['style.css', '.task-progress .meta'],
                             ['pages/ticket.css', '.ticket-page .tab-count']]) {
    assert.doesNotMatch(rule(read(file), sel), /font-mono|monospace/, sel);
  }
});

test('collapsed lane heading does not wrap', () => {
  assert.match(rule(read('pages/tickets.css'), '.board .kanban-col.col-collapsed .col-head h2'), /white-space:nowrap/);
});

test('Done when box on New ticket has three rows', () => {
  assert.match(read('pages/newticket.js'), /done\.rows = 3;/);
});

// ORCH-908: counts use the normal font, the narrow To do lane heading stays on one line, and the
// New ticket Done when box has room for its whole placeholder (the dialog's 44px input minimum shrank it).
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

// ORCH-576 replaced the board columns (and their collapsed lane) with status rows; the row count stays on one line.
test('status row count does not wrap', () => {
  const css = fs.readFileSync(path.join(__dirname, '..', '..', '..', 'workspace', 'src', 'orch_ui', 'static', 'widgets.css'), 'utf8');
  assert.match(css, /\.tile-num\{[^}]*white-space:nowrap/);
});

test('Done when box on New ticket keeps the tall minimum of the first box', () => {
  assert.match(read('pages/newticket.js'), /el\('textarea', 'input new-ticket-text'\); done\.name = 'done_when'/);
  assert.match(read('pages/newticket.css'), /\.new-ticket \.new-ticket-text\{min-height:96px\}/);
});

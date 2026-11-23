// ORCH-1464: a quiet ticket's "No news since Friday 14:32" is long. As one nowrap line it stretched the Last change
// column until the Tickets table was wider than the page at 1280 px and the Answer buttons were cut off.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const js = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/tickets.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/components.css'), 'utf8');

test('a quiet ticket row marks its Last change cell, so the long text can wrap', () => {
  assert.match(js, /className:'meta when' \+ \(t\.quiet_since \? ' quiet' : ''\)/);
});

test('the quiet Last change cell wraps within a bounded width', () => {
  const rule = css.split('\n').find(l => l.startsWith('.ticket-table .when.quiet{')) || '';
  assert.match(rule, /white-space:normal/);
  assert.match(rule, /max-width:\d+px/);
});

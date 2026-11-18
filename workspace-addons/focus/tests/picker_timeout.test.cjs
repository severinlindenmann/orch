'use strict';
// ORCH-398: the start page never stays on the grey bars when the tickets call does not answer.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_focus/web/ticket.js'), 'utf8');

test('the tickets call has a time limit', () => {
  assert.match(src, /fetch\(P \+ '\/api\/tickets', \{signal: AbortSignal\.timeout\(TICKETS_WAIT_MS\)\}\)/);
  assert.match(src, /const TICKETS_WAIT_MS = \d+;/);
});

test('a failed or timed-out call removes the grey bars and says so', () => {
  const at = src.indexOf('Could not load tickets');
  const handler = src.slice(src.lastIndexOf('.catch(', at), at);
  assert.match(handler, /fx-skel'\)\?\.remove\(\)/);
});

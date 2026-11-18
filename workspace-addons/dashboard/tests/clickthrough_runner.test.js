// The click-through runner itself (ORCH-490). g-github failed on unrelated pull requests: after it turned the Pull
// requests add-on off, the page (whose own state lags the server by a poll) still warmed that add-on's view once and
// Chromium logged the 404 as a console error. addonOff accepts exactly that one 404; any other 404 still fails.
// A timeout names the line of the click-through it waited on, so a red run says which step it was.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { recorder, where } = require('../clickthrough/run.cjs');

const BASE = 'http://127.0.0.1:1';
function fakePage() {
  const page = new EventEmitter();
  page.answer = (status, url, method = 'GET') => page.emit('response', {
    status: () => status, url: () => BASE + url, request: () => ({ method: () => method, headers: () => ({}), postData: () => '' }) });
  page.consoleError = text => page.emit('console', { type: () => 'error', text: () => text });
  return page;
}
const NOT_FOUND = 'Failed to load resource: the server responded with a status of 404 (Not Found)';

test('the 404 of the view of an add-on the click-through turned off is not an error, once', () => {
  const page = fakePage(), rec = recorder(page, BASE);
  rec.offAddons.add('pull-requests');
  page.answer(404, '/api/addon/pull-requests');
  page.consoleError(NOT_FOUND);
  assert.deepEqual(rec.errors, []);
  page.consoleError(NOT_FOUND);  // a second 404 with no matching answer still counts
  assert.equal(rec.errors.length, 1);
});

test('a 404 of another add-on or another address is still an error', () => {
  const page = fakePage(), rec = recorder(page, BASE);
  rec.offAddons.add('pull-requests');
  page.answer(404, '/api/addon/automation');
  page.consoleError(NOT_FOUND);
  page.answer(404, '/api/file');
  page.consoleError(NOT_FOUND);
  assert.equal(rec.errors.length, 2);
  assert.match(rec.errors[0], /404 GET \/api\/addon\/automation/);
});

test('a failed step names the line of the click-through it waited on', () => {
  const file = path.join(__dirname, '..', 'clickthrough', 'features', 'f-session-new.cjs');
  const e = new Error('locator.waitFor: Timeout 20000ms exceeded.');
  e.stack = `${e.message}\n    at Object.run (${file}:31:30)\n    at async main (/x/run.cjs:340:9)`;
  assert.match(where(e), /^ \(at f-session-new\.cjs:31: .+\)$/);
  assert.equal(where(new Error('no stack frame in a feature')), '');
});

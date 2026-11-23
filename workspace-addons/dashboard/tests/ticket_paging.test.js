'use strict';
// ORCH-523: the Tickets page draws each group a page at a time, fetches older finished tickets from /api/tickets and
// runs a typed search on the server. These tests run the paging part of pages/tickets.js with a fake fetch.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const src = fs.readFileSync(path.join(WEB, 'pages/tickets.js'), 'utf8');
const kitReview = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/review.js'), 'utf8');
const part = src.slice(src.indexOf('// ORCH-523: with 10,000 tickets'), src.indexOf('const changesPending'));

function page({rows = [], ticket_counts = null, answers = []} = {}) {
  const calls = [], renders = [];
  const ctx = vm.createContext({
    snapshot: false, state: {tickets: rows, ticket_counts}, renders, calls, setTimeout: fn => fn(), clearTimeout() {},
    array: v => Array.isArray(v) ? v : [], savedView: () => '', render: () => renders.push(1),
    h: (tag, attrs, text) => ({tag, attrs, text}), URLSearchParams,
    fetch: async url => { calls.push(String(url)); const out = answers.shift() || {items: [], total: 0, next: null}; return {ok: true, json: async () => out}; },
  });
  vm.runInContext('var ticketSearch = "", ticketMine = false, ticketPerson = "", ticketGroup = ""; const tickets = () => state.tickets;\n' + part +
    '\nthis.api = {loadFinished, pageRows, finishedTotal, moreFinished, wantSearch, searchServed, hits, finished, moreMark, moreHandlers, rowsCap, capOf, set q(v) { ticketSearch = v; }, set who(v) { ticketPerson = v; }};', ctx);
  return ctx;
}
const settle = () => new Promise(r => setImmediate(r));

test('older finished tickets come a page at a time and join the rows the state holds', async () => {
  const ctx = page({rows: [{id: 't_a', status: 'done'}], ticket_counts: {total: 500, by_status: {done: 120}},
    answers: [{items: [{id: 't_a', status: 'done', title: 'old copy'}, {id: 't_b', status: 'done'}], total: 120, next: 50}]});
  const {api} = ctx;
  assert.equal(api.finishedTotal(), 120, 'the state count before any fetch');
  assert.equal(api.moreFinished(1), true);
  api.loadFinished();
  await settle();
  assert.match(ctx.calls[0], /\/api\/tickets\?status=done&offset=0&limit=50/);
  assert.deepEqual(Array.from(api.pageRows(), t => t.id), ['t_a', 't_b']);
  assert.equal(api.pageRows()[0].title, undefined, 'the state row wins over the fetched copy');
  assert.equal(api.finished.next, 2);
});

test('the last page ends the fetching; a person filter starts over with its own count', async () => {
  const ctx = page({answers: [{items: [{id: 't_x', status: 'done'}], total: 1, next: null}, {items: [], total: 0, next: null}]});
  const {api} = ctx;
  api.loadFinished();
  await settle();
  assert.equal(api.moreFinished(1), false);
  api.loadFinished();
  assert.equal(ctx.calls.length, 1, 'no fetch after the end');
  api.who = 'anna';
  assert.equal(api.finishedTotal(), null, 'the unfiltered state count is not the person\'s');
  api.loadFinished();
  await settle();
  assert.match(ctx.calls[1], /who=anna/);
});

test('a typed search asks the server once per words and serves its hits', async () => {
  const ctx = page({answers: [{items: [{id: 't_old', status: 'done', title: 'Invoice'}], total: 1, next: null}]});
  const {api} = ctx;
  api.q = 'invoice';
  assert.equal(api.searchServed(), false);
  api.wantSearch(); api.wantSearch();
  await settle();
  assert.equal(ctx.calls.length, 1);
  assert.match(ctx.calls[0], /q=invoice/);
  assert.equal(api.searchServed(), true);
  assert.deepEqual(Array.from(api.hits.rows, t => t.id), ['t_old']);
  api.q = 'invoices';
  assert.equal(api.searchServed(), false, 'other words wait for their own answer');
});

test('the more mark first draws the next rows it holds, then fetches', () => {
  const ctx = page(), {api} = ctx;
  let fetched = 0;
  const mark = api.moreMark('list-done', 10, () => fetched++);
  assert.equal(mark.attrs['data-more'], 'list-done');
  api.moreHandlers.get('list-done')();
  assert.equal(api.capOf('list-done'), 100);
  assert.equal(fetched, 0);
  api.moreMark('list-done', 0, () => fetched++);
  api.moreHandlers.get('list-done')();
  assert.equal(fetched, 1);
});

test('list, board and phone rows are cut and carry a more mark; render arms the watcher', () => {
  assert.match(src, /roots\.slice\(0, cap\)/);
  assert.match(src, /moreMark\('lane-' \+ status/);
  assert.match(src, /moreMark\('phone-' \+ status/);
  assert.match(fs.readFileSync(path.join(WEB, 'app.js'), 'utf8'), /armLoadMore\(main\)/);
  assert.match(kitReview, /list\.slice\(0,ansShown\)/, 'the Answered tab draws a page at a time');
});

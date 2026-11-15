// The ticket page's dense reference list (master .ref-list): order, key, state tone, texts via textContent only.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const slice = (from, to) => src.slice(src.indexOf(from), src.indexOf(to));
const code = [slice('const oneLine =', 'const linkType'), slice('const REF_ICONS', 'function refMark'), slice('function refModel', 'function refRow')].join('\n');
const h = (tag, attrs, ...children) => ({tag, attrs, children: children.flat(Infinity).filter(c => c != null)});
const c = vm.createContext({array: v => Array.isArray(v) ? v : [], clean: v => v ?? '', statusWord: t => ({done: 'Done', active: 'Working'})[t.status] || 'To do',
  ticketOf: id => ({t_30: {key: 'ORD-30', title: 'Relay retries too fast', status: 'done'}})[id], URL, h});
vm.runInContext(code + '\nthis.api = {refKey, refGroup, refTone, refModel, sentence};', c);
const {refKey, refGroup, refTone, refModel, sentence} = c.api;
const view = (label, status, title) => ({label, type: label, status, title, icon: label.toLowerCase()});
const issue = {kind: 'url', url: 'https://github.com/acme/billing/issues/812', view: view('GitHub', 'open', 'Export invoices as CSV')};
const pr = {kind: 'url', url: 'https://github.com/acme/billing/pull/815', view: view('GitHub', 'in review', 'Invoice CSV export')};
const jira = {kind: 'url', url: 'https://acme.atlassian.net/browse/BILL-207', view: view('Jira', null, 'Finance needs an export')};
const figma = {kind: 'url', url: 'https://www.figma.com/design/k2Lq9/Billing', view: view('Figma', null, 'Billing design')};
const ticket = {kind: 'ticket', ticket: 't_30'};

test('keys come from issue, pull request and Jira addresses only', () => {
  assert.equal(refKey(issue.url), '#812');
  assert.equal(refKey(pr.url), '#815');
  assert.equal(refKey(jira.url), 'BILL-207');
  assert.equal(refKey(figma.url), '');
  assert.equal(refKey('not a url'), '');
});

test('order: issues, pull requests, tickets, then other links', () => {
  const order = [figma, ticket, pr, jira, issue].map(refGroup);
  assert.deepEqual(order, [3, 2, 1, 0, 0]);
});

test('state tones: done, active, bad, none', () => {
  assert.equal(refTone('Merged'), 'done');
  assert.equal(refTone('Closed'), 'done');
  assert.equal(refTone('In review'), 'active');
  assert.equal(refTone('In progress'), 'active');
  assert.equal(refTone('Not found'), 'bad');
  assert.equal(refTone('Open'), '');
  assert.equal(refTone(''), '');
});

test('the full text (tool, key, title, state) is one string for the tooltip and aria-label', () => {
  assert.equal(refModel({}, issue).text, 'GitHub issue · #812 Export invoices as CSV · Open');
  assert.equal(refModel({}, pr).text, 'GitHub pull request · #815 Invoice CSV export · In review');
  assert.equal(refModel({}, ticket).text, 'Ticket · ORD-30 Relay retries too fast · Done');
  assert.equal(refModel({}, figma).text, 'Figma · Billing design');
  assert.equal(sentence('in review'), 'In review');
  assert.equal(sentence(null), '');
});

test('the page builds rows with textContent-safe nodes only (no innerHTML of link text)', () => {
  const block = slice('// ---- References as the master', 'function referenceRow');
  assert.doesNotMatch(block, /innerHTML|insertAdjacentHTML/);
  assert.match(block, /className:'ref-list'/);
  assert.match(block, /data-action':'link-add'/);
  assert.doesNotMatch(src, /'Ticket ' \+ t\.key/);  // the footer line under Properties is gone
});

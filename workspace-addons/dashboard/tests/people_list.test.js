'use strict';
// ORCH-1161: people of the person list act as human:pr_<id>; history shows their name, old names stay.
const test = require('node:test');
const assert = require('node:assert');
const H = require('../src/orch_dashboard/web/helpers.js');

test('person ids read as the name; old actors keep theirs', () => {
  H.setPersonNames({pr_k3f9q2m1xa: 'Lea', pr_aaaaaaaaaa: 'Max (removed)', bad: 'x'});
  assert.strictEqual(H.historyWho('human:pr_k3f9q2m1xa', null), 'Lea');
  assert.strictEqual(H.historyWho('human:pr_aaaaaaaaaa', null), 'Max (removed)');
  assert.strictEqual(H.personName('human:pr_k3f9q2m1xa', {}), 'Lea');
  assert.strictEqual(H.plainNames('Changed by human:pr_k3f9q2m1xa'), 'Changed by Lea');
  assert.strictEqual(H.historyWho('human:lume', null), 'Lume');  // an old line keeps its old name
  assert.strictEqual(H.historyWho('agent:claude', null), 'Claude');
  H.setPersonNames(null);
  assert.strictEqual(H.historyWho('human:pr_k3f9q2m1xa', null), 'Someone');  // no list here (a shared copy)
});

test('a stamped line reads as the stamped person, a rename shows at once', () => {
  H.setPersonNames({pr_aaaaaaaaaa: 'Sev'});
  const rows = H.historyView([{at: '2026-11-21T10:00:00Z', by: 'human:lume', person: 'pr_aaaaaaaaaa', device: 'machine', text: 'Created'}], [], null);
  assert.strictEqual(rows[0].who, 'Sev');
  const old = H.historyView([{at: '2026-11-21T10:00:00Z', by: 'human:lume', text: 'Created'}], [], null);
  assert.strictEqual(old[0].who, 'Lume');  // an old line without a person keeps its name
  H.setPersonNames({pr_aaaaaaaaaa: 'Severin'});
  assert.strictEqual(H.historyView([{at: '2026-11-21T10:00:00Z', by: 'human:lume', person: 'pr_aaaaaaaaaa', text: 'Created'}], [], null)[0].who, 'Severin');
  H.setPersonNames(null);
});

test('listedName: a person id or a phone line stamp reads as the name; anything else is not listed (ORCH-1164)', () => {
  H.setPersonNames({pr_k3f9q2m1xa: 'Lea'});
  assert.strictEqual(H.listedName('human:pr_k3f9q2m1xa'), 'Lea');  // an answer's answered_by
  assert.strictEqual(H.listedName('pr_k3f9q2m1xa'), 'Lea');  // a line's person stamp
  assert.strictEqual(H.listedName('agent:relay from ph_aaaaaaaaaa'), null);
  assert.strictEqual(H.listedName(undefined), null);
  H.setPersonNames(null);
  assert.strictEqual(H.listedName('pr_k3f9q2m1xa'), null);
});

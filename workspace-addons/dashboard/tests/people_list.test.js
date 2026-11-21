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
  assert.strictEqual(H.historyWho('human:pr_k3f9q2m1xa', null), 'Pr k3f9q2m1xa');  // list off: shown as written
});

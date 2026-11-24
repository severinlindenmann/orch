// ORCH-1689: while the helper's own login is broken, Start / Try again / Chat say why and are not offered.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const helpers = require('../src/orch_dashboard/web/helpers.js');
const S = require(path.join(__dirname, '../../../workspace/src/orch_ui/static/start-choice-state.js'));

const logins = items => ({items});
const claude = state => ({name:'claude', label:'Claude', kind:'login', state, helper:'claude', chosen:true});

test('a renew or unreachable helper login gives a plain reason', () => {
  assert.match(helpers.helperStartReason(logins([claude('renew')])), /stopped working/);
  assert.match(helpers.helperStartReason(logins([claude('unreachable')])), /cannot be reached/);
});

test('a working helper, no logins or an unrelated connection give no reason', () => {
  assert.equal(helpers.helperStartReason(logins([claude('works')])), '');
  assert.equal(helpers.helperStartReason(null), '');
  assert.equal(helpers.helperStartReason(logins([{name:'wiki', label:'Wiki', kind:'connection', state:'renew'}])), '');
});

test('the Start choice greys the start with the reason, but not the model pick', () => {
  const reason = 'The Claude login stopped working.';
  assert.equal(S.why('main', {unavailable:reason}), reason);
  assert.equal(S.why('fresh', {unavailable:reason}), reason);
  assert.notEqual(S.why('model', {unavailable:reason}), reason);
  assert.notEqual(S.why('main', {}), reason);
});

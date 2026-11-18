// ORCH-417: a helper's history line reads "Helper - <person>" when a person started its run, "Helper" when it ran on its own.
const test = require('node:test');
const assert = require('node:assert/strict');
const {agentWho} = require('../src/orch_dashboard/web/helpers.js');

test('a helper working for a person reads Helper - <person>', () => {
  assert.equal(agentWho({by: 'agent:claude', for: 'Severin', text: 'x'}), 'Helper - Severin');
  assert.equal(agentWho({by: 'agent:codex', for: 'Anna'}, n => n.toUpperCase()), 'Helper - ANNA');
});

test('a helper on its own reads Helper; a person is not a helper', () => {
  assert.equal(agentWho({by: 'agent:automation', text: 'x'}), 'Helper');
  assert.equal(agentWho({by: 'agent:claude', for: ''}), 'Helper');
  assert.equal(agentWho({by: 'human:Severin', for: 'Anna'}), null);
  assert.equal(agentWho({by: 'orch'}), null);
  assert.equal(agentWho(null), null);
});

// ORCH-547: a role standing in for the person names itself, on history lines and on answers.
const {answeredWho} = require('../src/orch_dashboard/web/helpers.js');

test('a role standing in reads <Role> for <person>', () => {
  assert.equal(agentWho({by: 'agent:manager', for: 'Severin'}), 'Manager for Severin');
  assert.equal(agentWho({by: 'agent:reviewer', for: 'Severin'}), 'Away mode for Severin');
  assert.equal(agentWho({by: 'agent:script', for: 'Severin'}), 'Script for Severin');
  assert.equal(agentWho({by: 'agent:reviewer'}), 'Away mode');
});

test('an answer given for the person says who gave it; the person\'s own answer is null', () => {
  assert.equal(answeredWho({answered_by: 'agent:manager', answered_for: 'human:Severin'}), 'Manager for Severin');
  assert.equal(answeredWho({answered_by: 'agent:reviewer', answered_for: 'human:Severin'}), 'Away mode for Severin');
  assert.equal(answeredWho({answered_by: 'agent:script', answered_for: 'human:Severin'}), 'Script for Severin');
  assert.equal(answeredWho({answered_by: 'agent:claude', answered_for: 'human:Severin'}), 'Helper for Severin');
  assert.equal(answeredWho({answered_by: 'agent:manager', answered_for: 'human:Severin'}, () => 'You'), 'Manager for You');
  assert.equal(answeredWho({answered_by: 'human:Severin'}), null);
  assert.equal(answeredWho(null), null);
});

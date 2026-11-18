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

const test = require('node:test');
const assert = require('node:assert/strict');
const helpers = require('../src/orch_dashboard/web/helpers.js');

test('ORCH-156: placed tickets keep their place in their lane; new arrivals stay on top in the given order', () => {
  const list = [
    {id:'new1'},
    {id:'b', lane_order:{lane:'todo', n:2}},
    {id:'other', lane_order:{lane:'backlog', n:1}},  // placed in another lane: counts as new here
    {id:'a', lane_order:{lane:'todo', n:1}},
    {id:'c', lane_order:{lane:'todo', n:3}},
  ];
  assert.deepEqual(helpers.laneSorted(list, 'todo').map(t => t.id), ['new1', 'other', 'a', 'b', 'c']);
  assert.deepEqual(helpers.laneSorted(list, 'backlog').map(t => t.id), ['new1', 'b', 'a', 'c', 'other']);
  assert.deepEqual(helpers.laneSorted([], 'todo'), []);
});
test('ORCH-156: laneMove puts a card right before another, or at the end', () => {
  assert.deepEqual(helpers.laneMove(['a', 'b', 'c', 'd'], 'd', 'b'), ['a', 'd', 'b', 'c']);
  assert.deepEqual(helpers.laneMove(['a', 'b', 'c'], 'a', null), ['b', 'c', 'a']);
  assert.deepEqual(helpers.laneMove(['a', 'b', 'c'], 'b', 'b'), ['a', 'b', 'c']);  // onto itself: nothing moves
  assert.deepEqual(helpers.laneMove(['a', 'b'], 'x', 'a'), ['x', 'a', 'b']);  // a card from outside joins the lane
});

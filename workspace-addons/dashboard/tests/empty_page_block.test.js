'use strict';
// D4 (26 Nov, owner pick A): an add-on view that is one empty list is an empty page: the empty state alone, never a box
// in a box that names the page twice (Lessons). A list among other blocks keeps its title and box.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const harness = path.join(__dirname, 'blocks_harness.js'), blocks = path.join(__dirname, '../src/orch_dashboard/web/blocks.js');
function draw(view) {
  const f = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'orch-empty-')), 'view.json');
  fs.writeFileSync(f, JSON.stringify(view));
  return JSON.parse(execFileSync(process.execPath, [harness, blocks, f], {encoding: 'utf8'}));
}
const empty = {title: 'No lessons yet', text: 'Your helper adds a lesson. Nothing to do for you.'};
const texts = n => [n.text, ...n.kids.map(texts)].join(' ');

test('one empty list: only the empty state, no section, no second name', () => {
  const tree = draw({blocks: [{type: 'list', title: 'Lessons', count: 0, items: [], empty}]});
  assert.equal(tree.kids.length, 1);
  assert.match(tree.kids[0].cls, /blk-empty/);
  assert.ok(!tree.kids[0].cls.split(' ').includes('blk'), 'no block section around it');
  assert.doesNotMatch(texts(tree), /Lessons/);
  assert.match(texts(tree), /No lessons yet/);
});

test('an empty list next to other blocks keeps its title', () => {
  const tree = draw({blocks: [{type: 'stat', label: 'Runs', value: '2'}, {type: 'list', title: 'Recent starts', items: [], empty}]});
  assert.match(texts(tree), /Recent starts/);
});

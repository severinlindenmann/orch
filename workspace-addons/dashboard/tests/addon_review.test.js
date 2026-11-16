const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const web = f => fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web', f), 'utf8');
const settings = web('pages/settings.js'), blocks = web('blocks.js');

// "Allow this script" (an add-on button with review: true): the page asks the add-on what the
// button does, shows it in full, and sends back only the key of what it showed.
test('a review button asks first, shows the answer in full and sends back only the shown key', () => {
  const i = settings.indexOf('async function addonReview(');
  const body = settings.slice(i, settings.indexOf('\n}\n', i));
  assert.match(settings, /if \(control\.dataset\.review\) return addonReview\(id, control\);/);
  assert.match(body, /act\('addon\.act', \{\.\.\.args, review:true\}\)/);   // phase 1: nothing runs
  assert.match(body, /act_answer\?\.addon === id/);   // only the open add-on's own answer
  assert.match(body, /\/:\(\[0-9a-f\]\{64\}\)\$\//);   // the key at the end of the add-on's target
  assert.match(body, /settingsConfirm\(String\(got\.review\.title\), text, 'scroll-all', 'Allow'/);   // in full, not behind Details
  assert.match(body, /act\('addon\.act', \{\.\.\.args, value:key\}\)/);   // phase 2: the shown key, nothing else
  assert.ok(body.indexOf('review:true') < body.indexOf('value:key'));
});

test('blocks.js puts the review flag on the button only when the view asks for it', () => {
  assert.match(blocks, /if \(args\.review === true\) node\.dataset\.review = 'true';/);
});

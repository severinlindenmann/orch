const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const web = f => fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web', f), 'utf8');
const settings = web('pages/settings.js'), app = web('app.js');

// addon.prompt (Lessons' Edit): one prefilled text line, Save disabled when empty or over 200, the add-on's refusal shown inside
test('the prompt dialog sends the add-on verb with the new text and shows a refusal in the dialog', () => {
  const i = settings.indexOf('function promptDialog(');
  const body = settings.slice(i, settings.indexOf('let sharedLinks', i));
  assert.match(body, /value,\s*'aria-label'/);   // prefilled with args.value
  assert.match(body, /act\('addon\.act', \{addon:id, verb, target, value:text\}\)/);
  assert.match(body, /addonPrompt: target/);   // the target is the one checked id the block put on the button
  assert.match(body, /PROMPT_MAX = 200|n > PROMPT_MAX/);
  assert.match(body, /save\.disabled = n === 0 \|\| n > PROMPT_MAX/);
  assert.match(body, /Write at least one character/);
  assert.match(body, /failed\.textContent = result\.text/);
  assert.ok(body.indexOf('failed.textContent') < body.indexOf('window.orch.close(d)'), 'a refusal keeps the dialog open');
  assert.match(settings, /const PROMPT_MAX = 200;/);
});

test('the click on a prompt button opens the dialog; the dashboard code never names an add-on', () => {
  assert.match(app, /closest\('\[data-addon-prompt\]'\)/);
  assert.match(app, /promptDialog\(prompt\)/);
  for (const name of ['lessons', 'Lessons']) assert.ok(!settings.includes(name) && !app.includes(name), name);
});

test('place = settings keeps an add-on out of the nav, its page route stays', () => {
  assert.match(app, /addons\(\)\.filter\(a => a\.dashboard && a\.dashboard\.place !== 'settings' && a !== contactsAddon\)/);
  assert.match(settings, /href:'#addon\/' \+ encodeURIComponent\(addon\.name\), 'data-key':'addon-detail-open'/);
});

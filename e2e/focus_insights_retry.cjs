// ORCH-1860: Insights keeps the last good reading when one read fails. The real Insights page on the e2e sample
// workspace (e2e/focus_insights/insights_server.py) in headless Chromium; the test fails single reads in the
// browser. Covers: a failed list refresh (numbers and chosen tab kept, read time and Try again by the table), a
// first failure (an error, never zeros or the first-day tiles), Try again that works, a lost sign-in (every private
// value gone), a late answer (dropped), and another workspace answering (what was read before is dropped).
// usage: node --test e2e/focus_insights_retry.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { start, playwright } = require('./focus_insights_shots.cjs');
const headless = require('./headless.cjs'); // the keychain options (ORCH-615)

const SIGNIN = 'Sign in to do this: open the dashboard with a sign-in link from orch.';
let srv, browser;

test.before(async () => {
  srv = await start('workspace-addons/insights', 'e2e/focus_insights/insights_server.py', 'insights-retry');
  browser = await headless.launch(playwright().chromium);
});
test.after(async () => { if (browser) await browser.close(); if (srv) srv.stop(); });

// A page whose reads can be failed one by one: rule(name) -> 'ok' | 'fail' | 'signin' | async fn(route).
async function open(rules = {}, viewport = { width: 1280, height: 800 }) {
  const page = await browser.newPage({ viewport });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/api/**', async route => {
    const name = new URL(route.request().url()).pathname.replace('/api/', '');
    const rule = rules[name] || rules['*'] || 'ok';
    if (typeof rule === 'function') return rule(route);
    if (rule === 'fail') return route.fulfill({ status: 500, body: 'no' });
    if (rule === 'signin') return route.fulfill({ status: 401, contentType: 'text/plain', body: SIGNIN });
    return route.continue();
  });
  page.errors = errors;
  return page;
}
// the list is drawn and the page's own refresh has ended (a refresh asked for meanwhile would wait 30 s)
const loaded = async page => {
  await page.waitForSelector('#rows tr[data-name]', { timeout: 20000 });
  await page.waitForFunction(() => !loading);
};
const text = (page, sel) => page.locator(sel).innerText();
const refresh = async page => { await page.waitForFunction(() => !loading); await page.evaluate(() => refresh()); };
const banner = page => page.locator('#list-error .banner.error');

test('a failed list refresh keeps the numbers, the tab and the rows, with the read time and Try again', async () => {
  const rules = {};
  const page = await open(rules);
  await page.goto(srv.base + '/');
  await loaded(page);
  await page.click('#tab-keys');
  await page.waitForSelector('#rows tr[data-name="stripe-key"]');
  const metrics = await text(page, '#metrics');
  const y = await page.evaluate(() => scrollY);
  rules['list/keys'] = 'fail';
  await refresh(page);
  await banner(page).waitFor();
  assert.equal(await page.locator('#overview').isVisible(), true, 'the overview stays');
  assert.equal(await page.locator('#message').isVisible(), false);
  assert.equal(await text(page, '#metrics'), metrics, 'the numbers that did not fail stay');
  assert.equal(await page.getAttribute('#tab-keys', 'aria-selected'), 'true', 'the chosen tab stays');
  assert.equal(await page.locator('#rows tr[data-name]').count(), 3, 'the keys read before stay');
  const words = await banner(page).innerText();
  assert.match(words, /Couldn’t refresh the keys/);
  assert.match(words, /Showing what was read today \d\d:\d\d\./);
  assert.match(words, /Insights could not read the workspace record\./);
  assert.equal(await page.evaluate(() => document.activeElement.id), 'tab-keys', 'the focus stays on the tab');
  assert.equal(await page.evaluate(() => scrollY), y, 'the page does not scroll');

  // Try again that works: the banner goes, the rows stay, the tab stays, the page does not jump
  rules['list/keys'] = 'ok';
  await banner(page).getByRole('button', { name: 'Try again' }).focus();
  const y2 = await page.evaluate(() => scrollY);
  await page.keyboard.press('Enter');
  await page.waitForSelector('#list-error', { state: 'hidden' });
  assert.equal(await page.locator('#rows tr[data-name]').count(), 3);
  assert.equal(await page.getAttribute('#tab-keys', 'aria-selected'), 'true');
  assert.notEqual(await page.evaluate(() => document.activeElement.tagName), 'BODY', 'the focus is not dropped');
  // the banner goes, so the page gets shorter; the keys table stays in view (no jump to the top or elsewhere)
  const row = await page.locator('#rows tr[data-name="stripe-key"]').boundingBox();
  assert.ok(row.y >= 0 && row.y + row.height <= 800, `the keys stay in view (row at ${row.y}, scroll ${y2})`);
  assert.deepEqual(page.errors, []);
  await page.close();
});

test('a failed skills read with nothing read before is an error, never zero or the first-day tiles', async () => {
  const rules = { 'list/skills': 'fail' };
  const page = await open(rules);
  await page.goto(srv.base + '/');
  await banner(page).waitFor({ timeout: 20000 });
  const words = await banner(page).innerText();
  assert.match(words, /Couldn’t read the skills/);
  assert.match(words, /Nothing is shown here until it can be read\./);
  assert.equal(await page.locator('#panel').isVisible(), false, 'no empty table');
  assert.equal(await page.locator('#empty').isVisible(), false, 'not the first-day tiles');
  assert.match(await text(page, '#metrics'), /27/, 'the overview numbers that were read are shown');
  const skills = await text(page, '#skill-chart');
  assert.doesNotMatch(skills, /No skill use is recorded/);
  assert.match(skills, /can’t be shown until the skills are read/);
  // Try again that works fills the list in place
  rules['list/skills'] = 'ok';
  await banner(page).getByRole('button', { name: 'Try again' }).click();
  await loaded(page);
  assert.equal(await page.locator('#list-error').isVisible(), false);
  assert.match(await text(page, '#skill-chart'), /Weekly summary/);
  await page.close();
});

test('a first overview failure shows the error with Try again, then the loading shape, then the page', async () => {
  const rules = { overview: 'fail' };
  const page = await open(rules);
  await page.goto(srv.base + '/');
  await page.waitForSelector('#message .empty-state.err', { timeout: 20000 });
  assert.equal(await page.locator('#overview').isVisible(), false);
  assert.equal(await page.locator('#empty').isVisible(), false);
  let release;
  rules.overview = async route => { await new Promise(r => { release = r; }); return route.continue(); };
  await page.locator('#message').getByRole('button', { name: 'Try again' }).click();
  await page.waitForSelector('#loading', { state: 'visible' });
  release();
  await loaded(page);
  assert.equal(await page.locator('#message').isVisible(), false);
  await page.close();
});

test('a failed overview refresh keeps the numbers with the read time by them', async () => {
  const rules = {};
  const page = await open(rules);
  await page.goto(srv.base + '/');
  await loaded(page);
  const metrics = await text(page, '#metrics');
  rules.overview = 'fail';
  await refresh(page);
  await page.waitForSelector('#overview-error .banner.error');
  assert.match(await text(page, '#overview-error'), /Couldn’t refresh the numbers[\s\S]*Showing what was read today/);
  assert.equal(await text(page, '#metrics'), metrics);
  rules.overview = 'ok';
  await page.locator('#overview-error').getByRole('button', { name: 'Try again' }).click();
  await page.waitForSelector('#overview-error', { state: 'hidden' });
  await page.close();
});

test('a lost sign-in drops every private value and offers no Try again', async () => {
  const rules = {};
  const page = await open(rules);
  await page.goto(srv.base + '/');
  await loaded(page);
  await page.waitForSelector('#team:not([hidden])');
  rules['*'] = 'signin';
  await refresh(page);
  await page.waitForSelector('#message .empty-state.err');
  assert.match(await text(page, '#message'), /Sign in to do this/);
  assert.equal(await page.locator('#message button').count(), 0);
  for (const sel of ['#rows', '#metrics', '#bars', '#services', '#team-stats', '#people-rows', '#needs']) {
    assert.equal(await page.locator(`${sel} > *`).count(), 0, `${sel} is emptied`);
  }
  assert.equal(await page.locator('#team').isVisible(), false);
  const html = await page.content();
  for (const word of ['stripe-key', 'Weekly summary', 'Google Drive']) assert.ok(!html.includes(word), `${word} is gone`);
  await page.close();
});

test('a late answer is dropped: after a lost sign-in, and when a newer read already answered', async () => {
  const rules = {};
  const page = await open(rules);
  await page.goto(srv.base + '/');
  await loaded(page);
  // a keys read still on its way when the sign-in is lost must not draw its keys
  let release;
  rules['list/keys'] = async route => { await new Promise(r => { release = r; }); return route.continue(); };
  await page.evaluate(() => { retryList('keys'); });
  while (!release) await page.waitForTimeout(50);
  rules['list/connections'] = 'signin';
  await page.evaluate(() => retryList('connections'));
  await page.waitForSelector('#message .empty-state.err');
  release();
  await page.waitForTimeout(800);
  assert.ok(!(await page.content()).includes('stripe-key'), 'the late keys are not drawn');
  assert.equal(await page.locator('#overview').isVisible(), false);
  await page.close();

  // an older failed read that answers after a newer good one does not bring the banner back
  const rules2 = {};
  const page2 = await open(rules2);
  await page2.goto(srv.base + '/');
  await loaded(page2);
  await page2.click('#tab-keys');
  rules2['list/keys'] = 'fail';
  await refresh(page2);
  await banner(page2).waitFor();
  let slow;
  rules2['list/keys'] = async route => {
    rules2['list/keys'] = 'ok';
    await new Promise(r => { slow = r; });
    return route.fulfill({ status: 500, body: 'no' });
  };
  await banner(page2).getByRole('button', { name: 'Try again' }).click();
  while (!slow) await page2.waitForTimeout(50);
  await page2.evaluate(() => retryList('keys'));
  await page2.waitForSelector('#list-error', { state: 'hidden' });
  slow();
  await page2.waitForTimeout(800);
  assert.equal(await page2.locator('#list-error').isVisible(), false, 'the older failure is dropped');
  assert.equal(await page2.locator('#rows tr[data-name]').count(), 3);
  await page2.close();
});

test('another workspace answering drops what was read before and reads afresh', async () => {
  const rules = {};
  const page = await open(rules);
  await page.goto(srv.base + '/');
  await loaded(page);
  await page.click('#tab-keys');
  rules['list/keys'] = 'fail';
  await refresh(page);
  await banner(page).waitFor();
  let views = 0;
  rules['*'] = async route => {
    const answer = await route.fetch();
    let body = await answer.text();
    try { const data = JSON.parse(body); if (data.ws) { data.ws = 'otherworkspc'; views++; } body = JSON.stringify(data); } catch { /* not JSON */ }
    return route.fulfill({ response: answer, body });
  };
  delete rules['list/keys'];
  await refresh(page);
  await page.waitForFunction(() => document.querySelector('#rows tr[data-name]') && document.getElementById('list-error').hidden);
  assert.ok(views >= 2, 'read afresh after the change');
  assert.equal(await page.locator('#overview').isVisible(), true);
  assert.equal(await page.locator('#overview-error').isVisible(), false);
  await page.close();
});

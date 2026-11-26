// The Sync page against the real server, signed in once (ORCH-386): turn the Sync add-on on in Settings > Add-ons,
// open the Sync page, and its status call (the one that answered 403 after a reused sign-in link, ORCH-382) must
// go through; a reload asks again and goes through again. Then Sync is turned off so later click-throughs see the
// seeded workspace as it was. The browser context signed in with ONE launch token, as a person does.
// Since ORCH-413 the page reads that status with GET /api/addon-read (not POST /api/act addon.act), so wait for it.
const statusRead = (page, fn) => Promise.all([
  page.waitForResponse(r => r.request().method() === 'GET' && r.url().includes('/api/addon-read?addon=sync&verb=status'), { timeout: 60000 }),
  fn(),
]).then(([r]) => r);

module.exports = {
  name: 'Sync page: opens signed in, its status call is not refused',
  covers: ['addon.set'],
  async run({ page, open, reload, act, must, text, orchAsPerson, workspace }) {
    await open('#settings/addons');
    const sw = () => page.getByRole('switch', { name: 'Backup on or off' });
    must((await sw().innerText()).trim() === 'Off', 'Sync should start off');
    await sw().click();
    const dlg = page.locator('dialog[open]');
    try {
      await act('addon.set', () => dlg.getByRole('button', { name: 'Turn on' }).click());
      await this.syncOn({ page, open, reload, act, must, text, orchAsPerson, sw, workspace });
    } catch (e) {
      // a failure half-way must not leave Sync on for the next click-through on this lane (ORCH-1652)
      for (const a of [['sync', 'set', '--mode', 'off'], ['sync', 'stop'], ['addon', 'remove', 'sync']]) {
        try { orchAsPerson(...a); } catch (_) { /* already off */ }
      }
      // the page server keeps its add-on list 10 s: a fresh state drops it, or the next click-through on this lane
      // still asks Sync for its status and gets a 422 (j-renew, 23 Nov run 45123932612)
      await page.evaluate(() => fetch('/api/state?fresh=1', { cache: 'no-store' })).catch(() => {});
      throw e;
    }
  },
  async syncOn({ page, open, reload, act, must, text, orchAsPerson, sw, workspace }) {
    const first = await statusRead(page, () => open('#addon/sync'));
    must(first.status() === 200, `the Sync page's status call answered ${first.status()}`);
    must(/Sync/.test(await text()), 'the Sync page shows no Sync card');
    const again = await statusRead(page, () => reload());
    must(again.status() === 200, `the Sync page's status call answered ${again.status()} after a reload`);
    // a copy on this computer only (ORCH-896): pick it, Save, reload: it is on; then Off, Save: it is off again
    await page.getByText('On this computer only').first().click();
    await page.getByRole('button', { name: 'Save' }).click();
    // the card reads the status again every 15 s, and a busy computer is slower: poll for up to a minute (#2587: the
    // loop had synced, the click-through still waited). Since ORCH-2107 the page shows no 'Last synced' line when all
    // went well; a finished sync is a visible row with a green dot in the history card (hidden copies don't count).
    const synced = () => page.locator('[data-key="sync-history-row"] .dot.ok >> visible=true').count().then(n => n > 0, () => false);
    let shown = '';
    for (const end = Date.now() + 60000; !(await synced()) && Date.now() < end;) await page.waitForTimeout(500);
    if (!(await synced())) {
      shown = await text();
      let st = '';
      try { st = orchAsPerson('sync', 'status', '--json').replace(/\s+/g, ' ').slice(0, 600); } catch (e2) { st = String(e2.message || e2).slice(0, 300); }
      // the loop's own words say why it did not start (#2587: seen on Linux only)
      let log = '';
      try { log = require('node:fs').readFileSync(require('node:path').join(workspace, '.orch', 'run', 'sync', 'loop.log'), 'utf8').trim().split('\n').slice(-8).join(' | ').slice(-800); } catch (e2) { log = 'no loop.log (' + (e2.code || e2.message) + ')'; }
      throw new Error('Sync on this computer did not start; orch sync status: ' + st + '; its log: ' + log + '; the page says: ' + shown.replace(/\s+/g, ' ').slice(0, 300));
    }
    await reload();
    must(/Sync: local/.test(orchAsPerson('sync', 'status')), 'Sync is not on this computer after Save: ' + orchAsPerson('sync', 'status'));
    await page.getByText(/^Off$/).first().click();
    await page.getByRole('button', { name: 'Save' }).click();
    let st = '';
    for (const end = Date.now() + 15000; !/Sync is off/.test(st = orchAsPerson('sync', 'status')) && Date.now() < end;) await page.waitForTimeout(250);
    must(/Sync is off/.test(st), 'Sync is not off after Save: ' + st);
    await reload();
    await open('#settings/addons');
    await act('addon.set', () => sw().click());
    await reload();
    must((await sw().innerText()).trim() === 'Off', 'Sync is not off again after a reload');
  },
};

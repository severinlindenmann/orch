// The Sync page against the real server, signed in once (ORCH-386): turn the Sync add-on on in Settings > Add-ons,
// open the Sync page, and its status call (the one that answered 403 after a reused sign-in link, ORCH-382) must
// go through; a reload asks again and goes through again. Then Sync is turned off so later click-throughs see the
// seeded workspace as it was. The browser context signed in with ONE launch token, as a person does.
// Since ORCH-413 the status is read with GET /api/addon-read (no click), so the test waits for that answer.
const statusRead = (page, fn) => Promise.all([
  page.waitForResponse(r => r.url().includes('/api/addon-read?') && r.url().includes('verb=status'), { timeout: 60000 }),
  fn(),
]).then(([r]) => ({ status: r.status() }));
module.exports = {
  name: 'Sync page: opens signed in, its status call is not refused',
  covers: [],
  async run({ page, open, reload, act, must, text }) {
    await open('#settings/addons');
    const sw = () => page.getByRole('switch', { name: 'Sync on or off' });
    must((await sw().innerText()).trim() === 'Off', 'Sync should start off');
    await sw().click();
    const dlg = page.locator('dialog[open]');
    await act('addon.set', () => dlg.getByRole('button', { name: 'Turn on' }).click());
    const first = await statusRead(page, () => open('#addon/sync'));
    must(first.status === 200, `the Sync page's status call answered ${first.status}`);
    must(/Sync/.test(await text()), 'the Sync page shows no Sync card');
    const again = await statusRead(page, () => reload());
    must(again.status === 200, `the Sync page's status call answered ${again.status} after a reload`);
    await open('#settings/addons');
    await act('addon.set', () => sw().click());
    await reload();
    must((await sw().innerText()).trim() === 'Off', 'Sync is not off again after a reload');
  },
};

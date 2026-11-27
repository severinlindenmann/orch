// Helper logins: a check of this workspace's own (a harmless command that fails, set up here in the throw-away
// home) shows on Home as something that needs renewing. The person presses "Check again" and the page asks orch
// to run every check once more and says what came out. The real helper logins (Renew) are never opened here.

module.exports = {
  name: 'Logins: check again',
  covers: ['page:home', 'logins.check'],
  async run({ page, open, reload, act, must, text, orchAsPerson: orch }) {   // checks of its own: a person's step
    await open('#home');
    const ws = await page.evaluate(() => state.settings?.folder || null) || await (async () => { await open('#settings/general'); return page.evaluate(() => state.settings.folder); })();
    must(/\.orch-test[\\/]clickthrough-/.test(ws), 'not the throw-away workspace: ' + ws);
    orch('logins', 'add', 'portal', '--command', 'false', '--label', 'Team portal', '--how', 'Log in to the team portal in your browser.');
    orch('logins');   // keeps the result the page shows
    // the check and its result are watched files (#1402): the page's server builds its state again by itself
    let names = [];
    for (let i = 0; i < 60 && !names.includes('portal'); i++) {
      if (i) await page.waitForTimeout(500);
      names = await page.evaluate(async () => ((await (await fetch('/api/state', { cache: 'no-store' })).json()).logins?.items || []).map(x => x.name));
    }
    must(names.includes('portal'), 'the page never showed the check added in the terminal: ' + names.join(', '));
    await open('#settings/agent');
    await reload();
    const check = page.getByRole('button', { name: 'Check again' }).first();
    must(await check.count() > 0, 'no Check again button for the failing check:\n' + (await text()).slice(0, 600));
    await act('logins.check', () => check.click());
    await reload();
    must((await text()).includes('Team portal'), 'the check is gone after a reload');
    orch('logins', 'remove', 'portal');   // leave the workspace as it was for the next click-through
    orch('logins');
  },
};

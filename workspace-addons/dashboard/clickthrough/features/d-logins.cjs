// Helper logins: a check of this workspace's own (a harmless command that fails, set up here in the throw-away
// home) shows on Home as something that needs renewing. The person presses "Check again" and the page asks orch
// to run every check once more and says what came out. The real helper logins (Renew) are never opened here.
const { execFileSync } = require('node:child_process');
const path = require('node:path');

module.exports = {
  name: 'Logins: check again',
  covers: ['page:home', 'logins.check'],
  async run({ page, open, reload, act, must, text }) {
    await open('#home');
    const ws = await page.evaluate(() => state.settings?.folder || null) || await (async () => { await open('#settings/general'); return page.evaluate(() => state.settings.folder); })();
    must(/\.orch-test[\\/]clickthrough-/.test(ws), 'not the throw-away workspace: ' + ws);
    const home = path.dirname(ws), repo = path.resolve(__dirname, '..', '..', '..', '..');
    const orch = (...a) => execFileSync('env', ['-i', 'PATH=' + path.join(home, 'bin') + path.delimiter + process.env.PATH, 'HOME=' + home, 'USERPROFILE=' + home, 'ORCH_HOME=' + home + '/orch', 'ORCH_HOME_STRICT=1',
      'UV_CACHE_DIR=' + (process.env.UV_CACHE_DIR || path.join(require('node:os').homedir(), '.cache', 'uv')), 'uv', 'run', '-q', '--project', repo + '/workspace', 'python', '-I', '-m', 'orch', ...a], { cwd: ws, encoding: 'utf8' });
    orch('logins', 'add', 'portal', '--command', 'false', '--label', 'Team portal', '--how', 'Log in to the team portal in your browser.');
    orch('logins');   // keeps the result the page shows
    const cfg = path.join(ws, '.orch', 'config.toml'), now = new Date();
    require('node:fs').utimesSync(cfg, now, now);   // the page only re-reads settings when a settings file changes
    for (let i = 0; i < 60; i++) {   // the page's server re-reads settings in the background after a settings file changed
      const names = await page.evaluate(async () => ((await (await fetch('/api/state', { cache: 'no-store' })).json()).logins?.items || []).map(x => x.name));
      if (names.includes('portal')) break;
      await page.waitForTimeout(500);
    }
    await open('#settings/agent');
    await reload();
    const check = page.getByRole('button', { name: 'Check again' }).first();
    must(await check.count() > 0, 'no Check again button for the failing check:\n' + (await text()).slice(0, 600));
    await act('logins.check', () => check.click());
    await reload();
    must((await text()).includes('Team portal'), 'the check is gone after a reload');
    orch('logins', 'remove', 'portal');   // leave the workspace as it was for the next click-through
    orch('logins');
    require('node:fs').utimesSync(cfg, new Date(), new Date());
  },
};

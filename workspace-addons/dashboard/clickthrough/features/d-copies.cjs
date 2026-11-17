// Both clicks are meant to be refused here (there is no running helper and the ticket is not done): the page says why.
// A helper's changes wait in a separate copy: the ticket page offers "Ask your helper to update" and "Apply changes".
// The waiting copy is made here in the throw-away workspace only: a plain git repo with one commit, a branch for the
// ticket with one more commit, and the ticket's note that its changes wait (written through orch's own ticket code).
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

module.exports = {
  name: 'Ticket: changes waiting in a copy (ask to update, apply)',
  covers: ['copies.ask-update', 'copies.approve', 'page:ticket'],
  async run({ page, open, reload, act, must, text }) {
    await open('#settings/general');
    const ws = await page.evaluate(() => state.settings.folder);
    must(/\.orch-test[\\/]clickthrough-/.test(ws), 'not the throw-away workspace: ' + ws);
    const home = path.dirname(ws), repo = path.resolve(__dirname, '..', '..', '..', '..');
    const base = { PATH: process.env.PATH, HOME: home, USERPROFILE: home, ORCH_HOME: home + '/orch', ORCH_HOME_STRICT: '1',
      UV_CACHE_DIR: process.env.UV_CACHE_DIR || path.join(os.homedir(), '.cache', 'uv') };
    const run = (cmd, args, env = {}) => execFileSync('env', ['-i', ...Object.entries({ ...base, ...env }).map(([k, v]) => `${k}=${v}`), cmd, ...args], { cwd: ws, encoding: 'utf8' });
    const orch = (...a) => run('uv', ['run', '-q', '--project', repo + '/workspace', 'python', '-I', '-m', 'orch', ...a]);
    const git = (...a) => run('git', a, { GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_SYSTEM: '/dev/null', GIT_AUTHOR_NAME: 'Test', GIT_AUTHOR_EMAIL: 'test@example.com', GIT_COMMITTER_NAME: 'Test', GIT_COMMITTER_EMAIL: 'test@example.com' });

    const tid = JSON.parse(orch('ticket', 'new', 'Tidy the menu text', '--json')).id;
    if (!fs.existsSync(path.join(ws, '.git'))) git('init', '-q');
    fs.writeFileSync(path.join(ws, 'menu.txt'), 'Soup\n');
    git('add', 'menu.txt'); git('commit', '-q', '-m', 'Start');
    const was = git('rev-parse', '--abbrev-ref', 'HEAD').trim();
    git('switch', '-q', '-c', 'orch/' + tid);
    fs.writeFileSync(path.join(ws, 'menu.txt'), 'Soup\nCake\n');
    git('commit', '-q', '-am', 'Add the cake');
    git('switch', '-q', was);
    run('uv', ['run', '-q', '--project', repo + '/workspace', 'python', '-I', '-c',
      'import sys; from pathlib import Path; from orch import tickets\n' +
      'def fn(t): t.setdefault("work", {}).update(bring_back={"state": "waiting", "reason": "Your work is waiting to be brought back.", "reason_code": "update", "at": tickets.now()})\n' +
      'tickets.apply_op(Path(sys.argv[1]), sys.argv[2], fn, by=tickets.SYSTEM)', ws, tid]);
    fs.utimesSync(path.join(ws, '.orch', 'config.toml'), new Date(), new Date());   // the page re-reads when a settings file changes

    await open('#ticket/' + tid);
    await reload();
    const ask = page.getByRole('button', { name: 'Ask your helper to update' });
    must(await ask.count() > 0, 'the waiting changes are not on the ticket:\n' + (await text()).slice(0, 500));
    const asked = await act('copies.ask-update', () => ask.click(), { refused: true });
    must(asked.text.length > 5, 'asking the helper to update gave no readable answer');
    await page.getByRole('button', { name: 'Apply changes' }).first().click();
    const applied = await act('copies.approve', () => page.locator('dialog[open]').getByRole('button', { name: 'Apply changes' }).click(), { refused: true });
    must((await page.locator('body').innerText()).includes(applied.text), 'the page did not say why the changes were not applied: ' + applied.text);
  },
};

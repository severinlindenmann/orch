// Settings > General, private files: the team repo holds orch files and the workspace asks to run its own helper
// command (added here, as a teammate would). The person allows the command on this computer, then moves the orch files out ("Move to private").
// The git repo is made here inside the throw-away workspace only (git init + add; nothing is committed or pushed).
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Settings: private files (allow a command, move to private)',
  covers: ['page:settings/general', 'private.allow', 'private.move'],
  async run({ page, open, reload, act, must, text }) {
    await open('#settings/general');
    const ws = await page.evaluate(() => state.settings.folder);
    must(/\.orch-test[\\/]clickthrough-/.test(ws), 'not the throw-away workspace: ' + ws);
    const env = { PATH: path.join(path.dirname(ws), 'bin') + path.delimiter + process.env.PATH, HOME: path.dirname(ws), GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_SYSTEM: '/dev/null' };
    // a teammate's helper command arrives with the team files: not allowed on this computer yet (harmless command)
    fs.appendFileSync(path.join(ws, '.orch', 'config.toml'), '\n[agents.teamtool]\nadapter = "generic"\ncommand = "sh -c true"\n');
    for (const a of [['init', '-q'], ['add', '-A', '-f', '.orch']]) execFileSync('git', a, { cwd: ws, env });
    await reload();
    await page.locator('[data-action="private-allow"]').waitFor({ timeout: 30000 });

    await page.locator('[data-action="private-allow"]').click();
    await act('private.allow', () => page.locator('dialog[open]').getByRole('button', { name: 'Allow', exact: true }).click());
    await reload();
    must((await page.locator('[data-action="private-allow"]').count()) === 0, 'the command is still waiting for a yes after a reload');
    must((await text()).includes('Private files are in your team repo'), 'the team repo card did not show');

    await page.locator('[data-action="private-move"]').click();
    await act('private.move', () => page.locator('dialog[open]').getByRole('button', { name: 'Move to private' }).click());
    await reload();
    must(!(await text()).includes('Private files are in your team repo'), 'the files are still in the team repo after a reload');
  },
};

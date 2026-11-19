// Tool updates (ORCH-589), with nothing from outside (run.cjs sets ORCH_NO_TOOL_CHECK):
// - a made-up tool "Acme CLI" installed by a stand-in Homebrew in the throw-away home (its command links into
//   <home>/brew/Cellar/acme/...), named by an approved check file of the workspace with its own update block;
// - orch's saved answer says 1.1.0 is newer, with one line of notes (written through orch itself);
// - Settings > About & updates shows the tool, the notes and "Update to 1.1.0"; the person presses it; the stand-in
//   brew installs 1.1.0 and the page says "Acme CLI is now 1.1.0." The check file and the tool are removed at the end.
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Tools: see a newer version of a tool with its notes and update it',
  covers: ['tools.update'],
  async run({ page, open, reload, act, must, text, home, workspace, python }) {
    const brew = path.join(home, 'brew');
    const version = path.join(home, 'acme-version');
    const tool = path.join(brew, 'Cellar', 'acme', '1.0.0', 'bin', 'acme');
    const link = path.join(home, 'bin', 'acme');
    const checks = path.join(workspace, '.orch', 'checks');
    const checkFile = path.join(checks, 'acme.json');
    const madeChecks = !fs.existsSync(checks);
    fs.writeFileSync(version, '1.0.0\n');
    fs.mkdirSync(path.join(brew, 'bin'), { recursive: true });
    fs.mkdirSync(path.dirname(tool), { recursive: true });
    fs.writeFileSync(path.join(brew, 'bin', 'brew'), `#!/bin/sh\necho "upgrading $*"\necho 1.1.0 > "${version}"\n`, { mode: 0o755 });
    fs.writeFileSync(tool, `#!/bin/sh\necho "acme $(cat "${version}")"\n`, { mode: 0o755 });
    fs.symlinkSync(tool, link);
    fs.mkdirSync(checks, { recursive: true });
    fs.writeFileSync(checkFile, JSON.stringify({
      label: 'Acme', kind: 'tool', command: ['acme', '--version'],
      update: { label: 'Acme CLI', installs: [{ via: 'brew', formula: 'acme' }] } }));
    try {
      // the person approved the check file; orch's saved answer says 1.1.0 is out (no outside question here)
      python('import sys; from pathlib import Path; from orch import checkfiles, toolupdates as t\n' +
        'root = Path(sys.argv[1]); checkfiles._remember(root, "acme", checkfiles.digest(root, "acme"))\n' +
        'orig = t._check\n' +
        'def check(r, p, last):\n' +
        '    row = orig(r, p, last)\n' +
        '    row.update(newest="1.1.0", update=True, compare="newer", can_update=bool(row["via"]),\n' +
        '               notes=[{"version": "1.1.0", "lines": ["Starts twice as fast"]}], more=0)\n' +
        '    return row\n' +
        't._check = check\n' +
        'got = t.status(root, refresh=True, only="acme")["tools"]\n' +
        'assert got and got[0]["can_update"], got\n', workspace);

      await open('#settings/about');
      const row = page.locator('[data-key="tool-acme"]');
      await row.waitFor({ timeout: 30000 }).catch(async () => { throw new Error('no Acme CLI row in Settings:\n' + (await text()).slice(0, 600)); });
      must((await row.innerText()).includes('Starts twice as fast'), 'the notes of the newer version are not shown');
      const start = row.locator('[data-key="tool-update"]');
      must(/Update to 1\.1\.0/.test(await start.innerText()), 'the button does not name the version');
      await act('tools.update', () => start.click());
      const result = row.locator('[data-key="tool-result"]');
      await result.waitFor({ timeout: 60000 }).catch(async () => { throw new Error('the update never said how it ended:\n' + (await row.innerText()).slice(0, 600)); });
      must((await result.innerText()).includes('Acme CLI is now 1.1.0'), 'the end of the update is not said: ' + await result.innerText());
      await reload();
      await row.waitFor({ timeout: 30000 });
      must((await row.innerText()).includes('1.1.0'), 'after a reload the new version is not shown');
      must(await row.locator('[data-key="tool-update"]').count() === 0, 'the Update button is still there after the update');
    } finally {
      python('import sys; from pathlib import Path; from orch import checkfiles\n' +
        'checkfiles._remember(Path(sys.argv[1]), "acme", None)\n', workspace);
      fs.rmSync(checkFile, { force: true });
      if (madeChecks) fs.rmSync(checks, { recursive: true, force: true });
      fs.rmSync(link, { force: true });
    }
  },
};

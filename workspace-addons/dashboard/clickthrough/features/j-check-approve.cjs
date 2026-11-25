// Approve a workspace check file from the page (#1549): a new file in .orch/checks waits for the person. Settings >
// Helper shows it as "Not approved yet" with an Approve button; the window shows what it runs, Approve sends the CLI's
// own `orch checks approve <name> --hash <h>`, and after a reload the check no longer waits.
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Checks: approve a new check file',
  covers: ['checks.approve'],
  async run({ page, workspace, open, reload, act, must, text, orch, until }) {
    await open('#settings/agent');
    const dir = path.join(workspace, '.orch', 'checks');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'team-wiki.json'), JSON.stringify({ label: 'Team wiki', command: ['true'] }));
    orch('logins');   // the checks once; the page shows their result
    const cfg = path.join(workspace, '.orch', 'config.toml');
    if (fs.existsSync(cfg)) fs.utimesSync(cfg, new Date(), new Date());   // the page re-reads settings when a settings file changes
    const waiting = s => (s.logins?.items || []).find(x => x.name === 'team-wiki' && x.approve === 'new');
    await until(waiting, 'the new check file waiting for Approve', 60);
    await reload();
    must(/Not approved yet/.test(await text()), 'the check does not say Not approved yet');
    const approve = page.getByRole('button', { name: 'Approve the Team wiki check' }).first();
    await approve.waitFor({ timeout: 20000 }).catch(async () => { throw new Error('no Approve button:\n' + (await text()).slice(0, 600)); });
    await approve.click();
    const dlg = page.locator('dialog[open]');
    await dlg.getByText('orch runs this to see whether it works:').waitFor({ timeout: 10000 });
    must((await dlg.innerText()).includes('true'), 'the window does not show what the check runs');
    await act('checks.approve', () => dlg.getByRole('button', { name: 'Approve', exact: true }).click());
    await dlg.getByText(/Approved\. orch checks Team wiki from now on\./).waitFor({ timeout: 60000 })
      .catch(async () => { throw new Error('not approved:\n' + (await dlg.innerText()).slice(0, 400)); });
    await dlg.getByRole('button', { name: 'Done' }).click();
    await until(s => !(s.logins?.items || []).some(x => x.name === 'team-wiki' && x.approve), 'the check approved');
    await reload();
    must(!/Not approved yet/.test(await text()), 'the check still waits after a reload');
    orch('checks', 'remove', 'team-wiki');   // leave the workspace as it was for the next click-through
    orch('logins');
  },
};

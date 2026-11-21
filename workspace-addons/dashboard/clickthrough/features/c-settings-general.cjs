// Settings > General: suggest and save the workspace name and description, flip the four workflow switches and the
// debug log (each reloaded, then flipped back), make a problem report and delete the saved reports.
module.exports = {
  name: 'Settings General: profile, switches, debug log, reports',
  covers: ['page:settings/general', 'workspace.propose', 'workspace.set', 'workflow.set', 'reviewer.set',
    'release_merge.set', 'diag.set', 'diag.delete_reports'],
  async run({ page, open, reload, act, must, workspace, git }) {
    const sw = key => page.locator(`[data-key="${key}"]`);
    const checked = async key => (await sw(key).getAttribute('aria-checked')) === 'true';
    // flip a switch, reload: it stayed flipped; flip it back, reload: the default is there again
    const flip = async (op, key, review) => {
      const was = await checked(key);
      const click = async () => {
        await sw(key).click();
        if (review) await page.locator('[data-key="settings-review-ok"]').click();
      };
      await act(op, click);
      await reload();
      must((await checked(key)) === !was, `${key} did not stay flipped after a reload`);
      await act(op, click);
      await reload();
      must((await checked(key)) === was, `${key} did not go back to its first state`);
    };

    await open('#settings/general');

    // workspace name and description: Suggest fills the form, Save writes both
    await act('workspace.propose', () => page.locator('[data-key="pf-suggest"]').click());
    await page.locator('[data-key="pf-name"]').fill('Pilatus Lunch Club');
    await page.locator('[data-key="pf-description"]').fill('Lunches and tables for the team');
    await act('workspace.set', () => page.locator('[data-key="pf-save"]').click());
    await page.locator('[data-key="lk-status"]').getByText('Saved.').waitFor();  // name, then description, are sent one after the other
    await reload();
    let seen = await page.locator('[data-key="settings-profile"]').innerText();
    must(seen.includes('Pilatus Lunch Club') && seen.includes('Lunches and tables for the team'), 'the saved name and description are gone after a reload');
    // put it back (name Pilatus, no description)
    await page.locator('[data-key="pf-edit"]').click();
    await page.locator('[data-key="pf-name"]').fill('Pilatus');
    await page.locator('[data-key="pf-description"]').fill('');
    await act('workspace.set', () => page.locator('[data-key="pf-save"]').click());
    await page.locator('[data-key="lk-status"]').getByText('Saved.').waitFor();  // name, then description, are sent one after the other
    await reload();
    seen = await page.locator('[data-key="settings-profile"]').innerText();
    must(seen.includes('Pilatus') && !seen.includes('Lunch Club'), 'the name did not go back to Pilatus');

    await flip('workflow.set', 'settings-switch-workflow', true);  // shows a review first
    // the two pull-request switches show only in a workspace with pull requests (ORCH-971): give it a GitHub remote
    // for them, then take it away again so later click-throughs see the seeded workspace as it was
    const fs = require('node:fs'), path = require('node:path'), dotGit = path.join(workspace, '.git');
    const madeGit = !fs.existsSync(dotGit);
    if (madeGit) git(workspace, 'init', '-q');
    git(workspace, 'remote', 'add', 'origin', 'https://github.com/example/pilatus.git');
    try {
      await reload();
      await flip('reviewer.set', 'settings-switch-reviewer');
      await flip('release_merge.set', 'settings-switch-release-merge');
    } finally {
      git(workspace, 'remote', 'remove', 'origin');
      if (madeGit) fs.rmSync(dotGit, { recursive: true, force: true });
    }
    await reload();
    must(!(await sw('settings-switch-reviewer').count()), 'the pull-request switches still show without pull requests');

    // a saved report makes "Delete all" usable; deleting it leaves 0 reports after a reload
    await page.locator('#report-problem').click();
    const dlg = page.locator('dialog[open]');
    await dlg.locator('[data-key="report-happened"]').fill('Click-through check');
    await dlg.getByRole('button', { name: 'Create report' }).click();
    await dlg.getByText('Report ready').waitFor({ timeout: 60000 });
    await dlg.getByRole('button', { name: /Close|Done/ }).first().click().catch(() => page.keyboard.press('Escape'));
    await reload();
    const count = () => page.locator('[data-key="settings-diag-reports"]').innerText();
    for (let i = 0; i < 6 && /^0 reports/.test(await count()); i++) { await page.waitForTimeout(2000); await reload(); }  // the count is read from the folder
    must(!/^0 reports/.test(await count()), 'the made report is not counted, also not after 10 seconds');
    await act('diag.delete_reports', () => page.locator('[data-key="settings-diag-delete-reports"]').click());
    await reload();
    must(/^0 reports/.test(await page.locator('[data-key="settings-diag-reports"]').innerText()), 'the reports are still there after Delete all');

    await flip('diag.set', 'settings-switch-diag');
  },
};

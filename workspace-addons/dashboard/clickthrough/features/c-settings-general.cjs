// Settings > General: suggest and save the workspace name and description, flip the four workflow switches and the
// debug log (each reloaded, then flipped back), make a problem report and delete the saved reports.
module.exports = {
  name: 'Settings General: profile, switches, debug log, reports',
  covers: ['page:settings/general', 'workspace.propose', 'workspace.set', 'workflow.set', 'reviewer.set', 'reviewer.kinds',
    'release_merge.set', 'diag.set', 'diag.delete_reports'],
  async run({ page, open, reload, act, must, workspace, git }) {
    const sw = key => page.locator(`[data-key="${key}"]`);
    const checked = async key => (await sw(key).getAttribute('aria-checked')) === 'true';
    // after a reload the page draws its last copy first, then the newer state (#2589): wait for the switch to say it
    const shows = async (key, want) => {
      for (const end = Date.now() + 15000; ;) {
        const v = await sw(key).getAttribute('aria-checked', { timeout: 2000 }).catch(() => null);
        if ((v === 'true') === want && v !== null) return true;
        if (Date.now() > end) return false;
        await page.waitForTimeout(250);
      }
    };
    // flip a switch, reload: it stayed flipped; flip it back, reload: the default is there again
    const flip = async (op, key, review) => {
      const was = await checked(key);
      const click = async () => {
        await sw(key).click();
        if (review) await page.locator('[data-key="settings-review-ok"]').click();
      };
      await act(op, click);
      await reload();
      must(await shows(key, !was), `${key} did not stay flipped after a reload`);
      await act(op, click);
      await reload();
      must(await shows(key, was), `${key} did not go back to its first state`);
    };

    await open('#settings/general');

    // workspace name and description: Suggest fills the form, Save writes both
    await act('workspace.propose', () => page.locator('[data-key="pf-suggest"]').click());
    await page.locator('[data-key="pf-name"]').fill('Pilatus Lunch Club');
    await page.locator('[data-key="pf-description"]').fill('Lunches and tables for the team');
    await act('workspace.set', () => page.locator('[data-key="pf-save"]').click());
    await page.locator('[data-key="lk-status"]').getByText('Saved.').waitFor();  // name, then description, are sent one after the other (a reload before brings them back, #1402)
    await reload();
    let seen = await page.locator('[data-key="settings-profile"]').innerText();
    must(seen.includes('Pilatus Lunch Club') && seen.includes('Lunches and tables for the team'), 'the saved name and description are gone after a reload');
    // put it back (name Pilatus, no description)
    await page.locator('[data-key="pf-edit"]').click();
    await page.locator('[data-key="pf-name"]').fill('Pilatus');
    await page.locator('[data-key="pf-description"]').fill('');
    await act('workspace.set', () => page.locator('[data-key="pf-save"]').click());
    await page.locator('[data-key="lk-status"]').getByText('Saved.').waitFor();  // name, then description, are sent one after the other (a reload before brings them back, #1402)
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
      // the kinds it accepts: Small feature on, reload, still on; off again (ORCH-645)
      const kind = page.locator('[data-kind="small_feature"]');
      await act('reviewer.kinds', () => kind.click());
      await reload();
      must(await kind.isChecked(), 'Small feature is not on after a reload');
      await act('reviewer.kinds', () => kind.click());
      await reload();
      must(!(await kind.isChecked()), 'Small feature is still on after it was turned off');
      await flip('release_merge.set', 'settings-switch-release-merge');
    } finally {
      git(workspace, 'remote', 'remove', 'origin');
      if (madeGit) fs.rmSync(dotGit, { recursive: true, force: true });
    }
    await reload();

    // a saved report makes "Delete all" usable; deleting it leaves 0 reports after a reload
    await page.locator('#report-problem').click();
    const dlg = page.locator('dialog[open]');
    await dlg.locator('[data-key="report-happened"]').fill('Click-through check');
    await dlg.getByRole('button', { name: 'Create report' }).click();
    await dlg.getByText('Report ready').waitFor({ timeout: 60000 });
    await dlg.getByRole('button', { name: /Close|Done/ }).first().click().catch(() => page.keyboard.press('Escape'));
    await reload();
    // the reports folder is watched (#1402): the open page is told and draws the new count by itself, no reload
    const reports = page.locator('[data-key="settings-diag-reports"]');
    const counted = await reports.filter({ hasNotText: /^0 reports/ }).waitFor({ timeout: 15000 }).then(() => true, () => false);
    must(counted, 'the made report is not counted: ' + await reports.innerText());
    await act('diag.delete_reports', () => page.locator('[data-key="settings-diag-delete-reports"]').click());
    await reload();
    must(/^0 reports/.test(await page.locator('[data-key="settings-diag-reports"]').innerText()), 'the reports are still there after Delete all');

    await flip('diag.set', 'settings-switch-diag');
  },
};

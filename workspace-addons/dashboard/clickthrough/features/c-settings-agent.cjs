// Settings > Helper: add your own helper with a harmless command (echo), it becomes the default, Test it (answers),
// change what a helper may do and how many work at once. Each is reloaded; the two choices are put back after, and
// the demo's stand-in helper is the default again at the end (later click-throughs start helpers that must keep running).
// Never tests a built-in agent tool (the page would run the real program). Full ("never asks") is not chosen.
module.exports = {
  name: 'Settings Helper: add, test, permissions, helpers at once, prepare on save',
  covers: ['page:settings/agent', 'config.agent.add', 'config.agent', 'config.agent.test', 'config.permissions', 'live.set', 'prepare.set'],
  async run({ page, open, reload, act, must, orchAsPerson }) {
    await open('#settings/agent');
    const k = key => page.locator(`[data-key="${key}"]`);

    // add a helper that only echoes: Name + Command, Save, Add helper (the page then makes it the default too)
    await k('settings-add-agent').click();
    await page.getByPlaceholder(/Name, e\.g\./).fill('echo-helper');
    await page.getByPlaceholder(/^report-tool --task/).fill('echo hello');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await act('config.agent.add', () => page.getByRole('button', { name: 'Add helper' }).click());
    await page.getByText('echo-helper added and set as the default.').waitFor({ timeout: 20000 });  // config.agent comes right after
    await reload();
    must(await k('settings-agent-echo-helper').isChecked(), 'the added helper is not the chosen one after a reload');

    // Test: runs `echo hello` in an empty folder and says it answered
    await act('config.agent.test', () => k('settings-test-echo-helper').click());
    await page.getByText(/answered in/).first().waitFor({ timeout: 30000 });

    // choosing a helper by hand (config.agent): the page only offers the built-in agent tools as radios besides it, and
    // picking those would make Start run the real tool, so the add above (which sends config.agent) is the click.

    // what a helper may do: pick "Asks for risky things", reload, back to what it was
    const perm = async () => {
      for (const m of ['ask', 'auto']) if (await k('settings-permissions-' + m).isChecked()) return m;
      return 'ask';
    };
    const was = await perm();
    const other = was === 'auto' ? 'ask' : 'auto';
    await act('config.permissions', () => k('settings-permissions-' + other).check({ force: true }));
    await reload();
    must((await perm()) === other, 'the permission choice did not stay after a reload');
    await act('config.permissions', () => k('settings-permissions-' + was).check({ force: true }));
    await reload();
    must((await perm()) === was, 'the permission choice did not go back');

    // helpers at once: 3, reload, back to No limit
    const sel = k('settings-live-max');
    await act('live.set', () => sel.selectOption('3'));
    await reload();
    must((await sel.inputValue()) === '3', 'Helpers at once did not stay at 3 after a reload');
    await act('live.set', () => sel.selectOption('none'));
    await reload();
    must((await sel.inputValue()) === 'none', 'Helpers at once did not go back to No limit');

    // Prepare tickets when I save (ORCH-741): on by default; off, reload, back on
    const prep = k('settings-switch-prepare');
    must((await prep.getAttribute('aria-checked')) === 'true', 'Prepare tickets when I save is not on by default');
    await act('prepare.set', () => prep.click());
    await reload();
    must((await prep.getAttribute('aria-checked')) === 'false', 'Prepare tickets when I save did not stay off');
    await act('prepare.set', () => prep.click());
    await reload();
    must((await prep.getAttribute('aria-checked')) === 'true', 'Prepare tickets when I save did not go back on');

    // the stand-in helper is the default again: echo ends at once, so a later Empty helper would be gone before its pane
    orchAsPerson('config', 'agent', 'standin');
  },
};

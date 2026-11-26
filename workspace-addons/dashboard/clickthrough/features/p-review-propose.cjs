// Reviewer mode (owner, 25 Nov 2026): Settings > General "Nothing closes by itself" turns the Reviewer to propose
// (`orch config set workflow.reviewer_mode propose`). Turned on, it stays on after a reload and shows on the Review
// card too; turned off again from there, the workspace is back on accept.
module.exports = {
  name: 'Review: Nothing closes by itself switch',
  covers: ['reviewer_mode.set'],
  async run({ page, open, reload, act, must, orchAsPerson }) {
    const mode = () => orchAsPerson('config', 'get', 'workflow.reviewer_mode').trim().split(/\s+/).pop();
    const setSw = page.locator('[data-key="settings-switch-propose"]');
    await open('#settings/general');
    await setSw.waitFor();
    must((await setSw.getAttribute('aria-checked')) === 'false', 'Nothing closes by itself is on before anyone turned it on');
    await act('reviewer_mode.set', () => setSw.click());
    await reload();
    must((await page.locator('[data-key="settings-switch-propose"]').getAttribute('aria-checked')) === 'true',
      'Nothing closes by itself did not stay on after a reload');
    must(mode() === 'propose', `the workspace is not on propose: ${mode()}`);

    await open('#review');
    const sw = page.locator('[data-key="review-switch-propose"]');
    await sw.waitFor();
    must((await sw.getAttribute('aria-checked')) === 'true', 'the Review card does not show Nothing closes by itself on');
    await act('reviewer_mode.set', () => sw.click());
    await reload();
    must((await page.locator('[data-key="review-auto"]').count()) === 0, 'the Auto Reviewer card still shows with every switch off');
    must(mode() === 'accept', `the workspace is not back on accept: ${mode()}`);
  },
};

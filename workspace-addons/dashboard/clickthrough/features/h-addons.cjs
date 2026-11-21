// Add-ons of this checkout, installed in the demo home (server.py) and turned on here like a person would in a
// terminal: Focus (a background add-on with a live screen) and Lessons (a page with its own buttons).
// - Home says Focus is not running; the person presses Start, and after a reload the note is gone.
// - Focus settings: the person switches "Let me type into the helper's screen", reloads, and it kept the new value;
//   there is no Preview switch (the new Focus is the only Focus).
// - Lessons: the person deletes a lesson with its own Delete button, reloads, and it is gone.
// - Uninstall: Lessons is turned off and the uninstall is refused with plain words, because this demo runs orch from
//   its source folder, not from an installed tool folder that could be rebuilt without it.
const clickConfirm = async page => {
  const dlg = page.locator('dialog[open]');
  if (await dlg.count()) await dlg.getByRole('button').filter({ hasNotText: /cancel|keep/i }).last().click();
};

module.exports = {
  name: 'Add-ons: start Focus, its Typing and Plain terminal switches, a Lessons button, uninstall refused',
  covers: ['addon.start', 'typing.set', 'terminal-typing.set', 'addon.act', 'addon.uninstall'],
  async run({ page, open, reload, act, must, text, orchAsPerson, addonOn, until, addonOff, shot }) {
    addonOn('focus');
    addonOn('lessons');
    orchAsPerson('lessons', 'add', 'Check the oven is off before you leave');
    await open('#home');
    await until(s => ['focus', 'lessons'].every(n => (s.addons || []).some(a => a.name === n)) && typeof s.settings?.typing_on === 'boolean',
      'Focus and Lessons turned on');

    // Start: Focus runs in the background; it is not running yet
    await until(s => (s.services || []).some(x => x.addon === 'focus' && x.running === false && !x.idle), 'Focus not running yet');
    await reload();
    const banner = page.locator('[data-key="background"]');
    await banner.waitFor({ timeout: 20000 }).catch(async () => { throw new Error('no "not running" note on Home:\n' + (await text()).slice(0, 500)); });
    await act('addon.start', () => banner.getByRole('button', { name: 'Start' }).click());
    await until(s => (s.services || []).some(x => x.addon === 'focus' && x.running === true), 'Focus running after Start');
    await reload();
    must(await page.locator('[data-key="background"]').count() === 0, 'the "not running" note is still on Home after Start and a reload');

    // the Focus Typing switch and the plain terminal's own switch (ORCH-261), and no Preview switch
    await open('#settings/addons/focus');
    for (const [key, op] of [['addon-detail-typing', 'typing.set'], ['addon-detail-terminal-typing', 'terminal-typing.set']]) {
      const sw = page.locator(`[data-key="${key}"]`);
      await sw.waitFor({ timeout: 20000 });
      const before = await sw.getAttribute('aria-checked');
      await act(op, () => sw.click());
      await reload();
      await sw.waitFor({ timeout: 20000 });
      must(await sw.getAttribute('aria-checked') !== before, `${op}: the switch is back to ${before} after a reload`);
    }
    must(await page.locator('[data-key="addon-detail-live-preview"]').count() === 0, 'Focus settings still show a Preview switch');
    await shot('focus-switches');
    const shell = page.locator('[data-key="addon-detail-terminal-typing"]');  // put the shell switch back off
    if (await shell.getAttribute('aria-checked') === 'true') { await act('terminal-typing.set', () => shell.click()); await reload(); }

    // a button of the Lessons page (the add-on's own action)
    await open('#addon/lessons');
    const lesson = page.getByText('Check the oven is off before you leave');
    await lesson.first().waitFor({ timeout: 20000 }).catch(async () => { throw new Error('the lesson is not on the Lessons page:\n' + (await text()).slice(0, 500)); });
    if (!(await page.getByRole('button', { name: 'Delete' }).count())) await lesson.first().click();   // the row opens to show its buttons
    await act('addon.act', async () => { await page.getByRole('button', { name: 'Delete' }).first().click(); await page.waitForTimeout(300); await clickConfirm(page); });
    await reload();
    await page.waitForTimeout(1500);
    must(await lesson.count() === 0, 'the lesson is still there after Delete and a reload');

    // Uninstall: turned off first, then refused here with plain words
    await open('#settings/addons/lessons');
    const un = page.locator('[data-key="addon-detail-remove"]');
    await un.waitFor({ timeout: 20000 });
    const hit = await act('addon.uninstall', async () => { await un.click(); await page.waitForTimeout(300); await clickConfirm(page); }, { refused: true });
    must(/tool folder|reinstall/i.test(hit.text), 'the refusal does not say why: ' + hit.text);
    // the page shows that answer as a toast; turning the add-on off first restarts the add-on pages, which can take
    // the toast with it on a slow machine, so the answer's words are what is checked
    orchAsPerson('stop');
    await addonOff('focus');   // off again for the next click-through
    await until(s => !(s.addons || []).some(a => a.name === 'lessons'), 'lessons off again');
  },
};

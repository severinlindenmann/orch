// Saved places in the workspace switcher (ORCH-1273): a person adds a place by pasting its address, a bad address is
// refused, the place stays after a reload, can be renamed and removed (with Undo), Share my places gives a link with a
// QR code, and places that come in a link wait for the keep question and leave the address bar.
module.exports = {
  name: 'Workspace switcher: Saved places, Add place, keep question and Share my places',
  covers: ['page:home'],
  async run({ page, open, must }) {
    await open('#home');
    const box = page.getByTestId('ws-switch');
    const menu = page.getByTestId('ws-menu');
    await box.click();
    await menu.waitFor();
    must(await menu.getByText('On this computer').isVisible(), 'the menu does not show On this computer');
    must(await menu.getByText('Saved places').isVisible(), 'the menu does not show Saved places');
    must(await menu.getByText('Nothing saved yet').isVisible(), 'a fresh browser does not say nothing is saved yet');

    // Add place: a bad address is refused in plain words, a good one is saved
    await menu.getByTestId('ws-add').click();
    await menu.getByLabel('Address').fill('javascript:alert(1)');
    await menu.getByRole('button', { name: 'Save' }).click();
    must(await menu.getByRole('alert').textContent().then(t => /Only web addresses/.test(t)), 'a javascript: address is not refused');
    await menu.getByLabel('Address').fill('https://fs.office.example.ch/#home');
    await menu.getByLabel('Name (optional)').fill('Fernscout');
    await menu.getByRole('button', { name: 'Save' }).click();
    await menu.getByTestId('ws-place').filter({ hasText: 'Fernscout' }).waitFor();
    await menu.getByTestId('ws-add').click();
    await menu.getByLabel('Address').fill('https://relay.example.ch/admin');
    await menu.locator('label', { hasText: 'Relay' }).click();
    await menu.getByRole('button', { name: 'Save' }).click();
    await menu.getByText('Relay · Sign in once').waitFor();

    // still there after a reload (kept in this browser)
    await page.reload();
    await box.click();
    await menu.getByTestId('ws-place').filter({ hasText: 'Fernscout' }).waitFor();
    must((await menu.getByTestId('ws-place').filter({ hasText: 'Fernscout' }).getAttribute('href')) === 'https://fs.office.example.ch', 'the saved address is not kept in one form');

    // Rename, then Remove with Undo
    await menu.getByRole('button', { name: 'More for Fernscout' }).click();
    await page.getByRole('menuitem', { name: 'Rename' }).click();
    await menu.getByLabel('Name of Fernscout').fill('Fernscout office');
    await menu.getByRole('button', { name: 'Save' }).click();
    await menu.getByTestId('ws-place').filter({ hasText: 'Fernscout office' }).waitFor();
    await menu.getByRole('button', { name: 'More for Fernscout office' }).click();
    await page.getByRole('menuitem', { name: 'Remove' }).click();
    must(!(await menu.getByTestId('ws-place').filter({ hasText: 'Fernscout office' }).count()), 'Remove did not remove the place');
    await page.locator('.ui-toast').getByRole('button', { name: 'Undo' }).click();
    await menu.getByTestId('ws-place').filter({ hasText: 'Fernscout office' }).waitFor();

    // Share my places: a link that carries the places, and a QR code
    await menu.getByTestId('ws-share').click();
    const link = await menu.getByRole('textbox', { name: 'Link to your places' }).inputValue();
    must(/#home&places=[A-Za-z0-9_-]+$/.test(link), 'Share my places gives no link with the places');
    must(await menu.locator('svg.qr').count() === 1, 'Share my places shows no QR code');
    must(await menu.getByText('Anyone with this link sees these addresses.').isVisible(), 'Share does not say who sees the addresses');

    // A link with a new place: it leaves the address bar, and nothing is saved before Keep
    const packed = await page.evaluate(() => window.OrchPlaces.pack([{ id: 'pilatus0001', url: 'https://pilatus.example.ch', kind: 'workspace', name: 'Pilatus', changed: Date.now() }], Date.now()));
    await page.keyboard.press('Escape');  // the menu closes; the link below changes only the part after #, so the page is not loaded again
    await open('#home&places=' + packed);
    await page.waitForFunction(() => !location.hash.includes('places='));
    await box.click();
    await menu.getByText('1 new place from a link').waitFor();
    must(!(await menu.getByTestId('ws-place').filter({ hasText: 'Pilatus' }).count()), 'a place from a link was saved without a tap');
    await menu.getByRole('button', { name: 'Review' }).click();
    must(await menu.getByText('https://pilatus.example.ch').isVisible(), 'the keep question does not show the full address');
    await menu.getByRole('button', { name: 'Keep Pilatus' }).click();
    await menu.getByTestId('ws-place').filter({ hasText: 'Pilatus' }).waitFor();
    await page.reload();
    await box.click();
    must(!(await menu.getByText('new place from a link').count()), 'the keep question came back after Keep');
    must(await menu.getByTestId('ws-place').filter({ hasText: 'Pilatus' }).count() === 1, 'the kept place is gone after a reload');
  },
};

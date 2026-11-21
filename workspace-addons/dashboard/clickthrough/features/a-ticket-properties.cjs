// A person makes a ticket, then on its page changes the title, sets owner, release, helper strength (empty ones come
// from the + Add menu, ORCH-581) and status, adds a reference to another ticket and takes it off again; after a reload
// every change is still there.
module.exports = {
  name: 'Ticket page: change properties and references',
  covers: ['page:ticket', 'ticket.edit', 'ticket.model', 'ticket.patch', 'ref.add', 'ref.rm'],
  async run({ page, ids, open, reload, act, must, text }) {
    await open('#home');
    await page.getByRole('button', { name: 'New ticket' }).first().click();
    const dlg = page.locator('.new-ticket-page');  // the New ticket page (ORCH-1037)
    await dlg.getByPlaceholder(/What should the helper do/).fill('Print the lunch posters');
    await act('ticket.new', () => dlg.getByRole('button', { name: 'Save without starting' }).click());
    await page.waitForFunction(() => location.hash.startsWith('#ticket/'), null, { timeout: 15000 });  // the saving moment, then the new ticket
    await open('#tickets');
    await page.getByText('Print the lunch posters').first().click();
    await page.waitForFunction(() => /^#ticket\//.test(location.hash));
    await page.getByRole('button', { name: 'Change title' }).waitFor();
    const mine = page.url().split('#ticket/')[1];

    await page.getByRole('button', { name: 'Change title' }).click();
    await act('ticket.edit', async () => { await page.getByLabel('Title', { exact: true }).fill('Print the lunch posters (A3)'); await page.keyboard.press('Enter'); });

    const add = async key => { await page.locator(`[data-key="props-add-${mine}"] > summary`).click(); await page.locator(`[data-key="prop-add-${key}-${mine}"]`).click(); };
    await add('owner');   // + Add opens the owner editor at once
    await act('ticket.edit', async () => { await page.getByLabel('Owner', { exact: true }).fill('Anna'); await page.keyboard.press('Enter'); });

    await act('ticket.edit', () => add('release'));
    await add('model');
    await act('ticket.model', () => page.getByLabel('Helper strength').first().selectOption('opus'));
    await page.getByLabel('More ticket actions').click();
    await act('ticket.patch', () => page.getByRole('menuitem', { name: 'Working' }).click());

    await add('links');   // + Add opens the reference dialog
    const ref = page.locator('dialog[open]');
    await ref.getByPlaceholder(/Search tickets/).fill('Plan the team lunch');
    await ref.getByRole('button', { name: /Plan the team lunch/ }).click();
    await act('ref.add', () => ref.getByRole('button', { name: 'Add', exact: true }).click());

    await reload();
    const t = await text();
    must(t.includes('Print the lunch posters (A3)'), 'the new title is gone after a reload');
    must(t.includes('Anna'), 'the owner is gone after a reload');
    must(t.includes('Plan the team lunch'), 'the reference is not on the ticket after a reload');
    must(await page.getByRole('switch', { name: 'This ticket is a release' }).getAttribute('aria-checked') === 'true', 'the release switch went back off');
    must(await page.getByLabel('Helper strength').first().inputValue() === 'opus', 'the helper strength went back');
    must(await page.getByText('Working', { exact: true }).count() > 0, 'the status Working is gone after a reload');

    await act('ref.rm', () => page.getByRole('button', { name: /Remove reference/ }).first().click());
    await reload();
    must(await page.getByRole('button', { name: /Remove reference/ }).count() === 0, 'the reference is still on the ticket after it was removed and the page reloaded');
  },
};

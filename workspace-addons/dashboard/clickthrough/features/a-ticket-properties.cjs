// A person makes a ticket, then on its page changes the title, sets owner, release, helper strength, kind (empty ones
// come from the + Add menu, ORCH-581) and status, adds a reference to another ticket and takes it off again; after a
// reload every change is still there.
module.exports = {
  name: 'Ticket page: change properties and references',
  covers: ['page:ticket', 'ticket.edit', 'ticket.model', 'ticket.kind', 'ticket.patch', 'ref.add', 'ref.rm'],
  async run({ page, ids, open, reload, act, must, text, until }) {
    await open('#home');
    await page.getByRole('button', { name: 'New ticket' }).first().click();
    const dlg = page.locator('.new-ticket-page');  // the New ticket page (ORCH-1037)
    await dlg.getByPlaceholder(/What should the helper do/).fill('Print the lunch posters');
    await act('ticket.new', () => dlg.getByRole('button', { name: 'Save ticket' }).click());
    await page.waitForFunction(() => location.hash.startsWith('#ticket/'), null, { timeout: 15000 });  // the saving moment, then the new ticket
    await open('#tickets');
    await page.getByText('Print the lunch posters').first().click();
    await page.waitForFunction(() => /^#ticket\//.test(location.hash));
    await page.getByRole('button', { name: 'Change title' }).waitFor();
    const mine = page.url().split('#ticket/')[1];
    // Save ticket asks the helper to prepare the ticket (ORCH-738, ORCH-1852): let that short run end first, so the
    // changes below are the person's and "In progress" means Working with no helper running.
    await until(s => (s.runs || {})[mine]?.running, 'the prepare run', 15).catch(() => {});  // a busy computer may refuse it: then nothing runs
    await until(s => !(s.runs || {})[mine]?.running, 'the prepare run over', 90);

    await page.getByRole('button', { name: 'Change title' }).click();
    await act('ticket.edit', async () => { await page.getByLabel('Title', { exact: true }).fill('Print the lunch posters (A3)'); await page.keyboard.press('Enter'); });

    // a menu can close again before its item is clicked (the page draws the rail again while it fills in, as in
    // a-ticket-header-fit, ORCH-1610; #2589): open it again, as a person would, until the item takes the click
    const pick = async (opener, item, what) => {
      for (let i = 0; i < 4; i++) {
        if (!(await item.isVisible())) await opener().catch(() => {});
        if (await item.click({ timeout: 3000 }).then(() => true, () => false)) return;
      }
      throw new Error(`${what} did not take the click:\n` + (await text()).slice(0, 600));
    };
    const add = key => pick(() => page.locator(`[data-key="props-add-${mine}"]:not([open]) > summary`).click({ timeout: 5000 }),
      page.locator(`[data-key="prop-add-${key}-${mine}"]`), `+ Add > ${key}`);
    await add('owner');   // + Add opens the owner editor at once
    await act('ticket.edit', async () => { await page.getByLabel('Owner', { exact: true }).fill('Anna'); await page.keyboard.press('Enter'); });

    await act('ticket.edit', () => add('release'));
    await add('model');
    await act('ticket.model', () => page.getByLabel('Helper strength').first().selectOption('opus'));
    await add('kind');
    await act('ticket.kind', () => page.getByLabel('Kind', { exact: true }).first().selectOption('small_bug'));
    await act('ticket.patch', () => pick(() => page.getByLabel('More ticket actions').click({ timeout: 5000 }),
      page.getByRole('menuitem', { name: 'Working' }), 'More ticket actions > Working'));

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
    must(await page.getByLabel('Kind', { exact: true }).first().inputValue() === 'small_bug', 'the kind went back');
    // ORCH-415: Working with no helper running shows 'In progress' on the ticket page
    must(await page.getByText('In progress', { exact: true }).count() > 0, 'the status In progress is gone after a reload');

    await act('ref.rm', () => page.getByRole('button', { name: /Remove reference/ }).first().click());
    await reload();
    must(await page.getByRole('button', { name: /Remove reference/ }).count() === 0, 'the reference is still on the ticket after it was removed and the page reloaded');
  },
};

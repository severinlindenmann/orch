// "You" in the sidebar: add two people by name (each becomes you), switch back to the first, reload, it is still you.
module.exports = {
  name: 'Sidebar: add a person and switch person',
  covers: ['person.add', 'person.set'],
  async run({ page, open, reload, act, must }) {
    await open('#home');
    const you = () => page.locator('[data-testid="person-switch"]').innerText();
    const add = async name => {
      await page.locator('[data-testid="person-switch"]').click();
      await page.locator('[data-testid="person-add"]').click();
      await page.locator('[data-testid="person-name"]').fill(name);
      await act('person.add', () => page.locator('[data-testid="person-add-save"]').click());
    };
    await add('Anna');
    await add('Ben');
    await page.waitForFunction(() => /Ben/.test(document.querySelector('[data-testid="person-switch"]')?.innerText || ''));
    await page.locator('[data-testid="person-switch"]').click();
    await act('person.set', () => page.locator('[data-testid="person-Anna"]').click());
    await reload();
    must(/Anna/.test(await you()), 'after a reload the sidebar does not say You: Anna');
    await page.locator('[data-testid="person-switch"]').click();
    must(await page.locator('[data-testid="person-Ben"]').count() === 1, 'the added person Ben is not in the list after a reload');
  },
};

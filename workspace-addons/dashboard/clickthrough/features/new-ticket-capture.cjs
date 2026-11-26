// ORCH-1852: capture first. On #new the text box has the focus, Save ticket sits beside it (right under it on a phone;
// the options come after, under "Optional"), and with a helper Start now is outlined under Save with its cost said. Text left on
// the page comes back; a refused save keeps it, and pressing Save again makes exactly one ticket that did not start.
module.exports = {
  name: 'New ticket: write one sentence, save it, nothing starts',
  covers: ['ticket.new', 'page:new'],
  async run({ page, open, reload, act, must, text, shot, seen }) {
    const wish = 'Spring campaign: one email to the newsletter list';
    await open('#new');
    const form = page.locator('.new-ticket-page');
    const box = form.getByPlaceholder(/What should the helper do/);
    must(await box.evaluate(el => el === document.activeElement), 'the text box does not have the focus on New ticket');
    const save = form.getByRole('button', { name: 'Save ticket' });
    const start = form.getByRole('button', { name: 'Start now' });
    must(await start.isVisible(), 'with a helper, Start now is not offered');
    must(/primary/.test(await save.getAttribute('class')) && !/primary/.test(await start.getAttribute('class')), 'Save ticket must be the filled button, not Start now');
    const words = await form.locator('.new-ticket-what').innerText();
    must(/no work starts/.test(words) || /Nothing starts/.test(words), 'the line under the buttons does not say Save starts nothing');
    must(/may cost money/.test(words), 'the cost of Start now is not said');
    const order = await form.evaluate(f => {
      const y = el => el.getBoundingClientRect().top;
      const q = s => f.querySelector(s);
      const bottom = el => el.getBoundingClientRect().bottom;
      return [bottom(q('.new-ticket-text')), y(q('.new-ticket-save [type=submit]')), bottom(q('.new-ticket-save [type=submit]')), y(q('.new-ticket-more'))];
    });
    must(order[1] <= order[0] + 24 && order[2] < order[3], 'Save ticket is not beside or right under the request, before the options');

    // Text left on the page comes back on the next New ticket.
    await box.fill(wish);
    await open('#tickets');
    await open('#new');
    must((await box.inputValue()) === wish, 'the unsent text did not come back');
    must(await form.getByText('Your unsent text from before is back.').isVisible(), 'the page does not say the text came back');

    // Keyboard: Tab from the text box reaches Save ticket; picture of the focus on the main action.
    await box.focus();
    for (let i = 0; i < 12 && !(await save.evaluate(el => el === document.activeElement)); i++) await page.keyboard.press('Tab');
    must(await save.evaluate(el => el === document.activeElement), 'Save ticket cannot be reached with Tab');
    await shot('focus-save', save);

    // The first save is refused: the reason shows, the text stays, nothing was made.
    let refuse = true;
    await page.route(/\/api\/act$/, route => {
      if (refuse && route.request().headers()['x-orch-op'] === 'ticket.new') {
        refuse = false;
        return route.fulfill({ status: 409, contentType: 'text/plain', body: 'The folder is busy. Press Save ticket again.' });
      }
      return route.fallback();
    });
    await act('ticket.new', () => save.click(), { refused: true });
    await seen(['The folder is busy. Press Save ticket again.']);
    must((await box.inputValue()) === wish, 'the text was lost after a refused save');
    await shot('save-refused', save);

    // Again, with the keyboard (Cmd or Ctrl + Enter saves; it never starts the helper): one ticket, still in Backlog.
    await box.focus();
    await act('ticket.new', () => page.keyboard.press(process.platform === 'darwin' ? 'Meta+Enter' : 'Control+Enter'));
    await page.unroute(/\/api\/act$/);
    await page.waitForFunction(() => location.hash.startsWith('#ticket/'), null, { timeout: 15000 });
    const id = await page.evaluate(() => location.hash.slice('#ticket/'.length));
    const st = await page.evaluate(async () => (await fetch('/api/state', { cache: 'no-store' })).json());
    const made = (st.tickets || []).filter(t => t.title === wish);
    must(made.length === 1, `pressing Save again made ${made.length} tickets, not one`);
    must(made[0].id === id && made[0].status === 'open' && !made[0].started, 'Save ticket started the helper or left Backlog');
    await reload();
    must((await text()).includes(wish), 'the saved ticket is not shown after a reload');
  },
};

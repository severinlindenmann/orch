// ORCH-1852 capture first, laid out as ORCH-2162 option A (owner, 25 Nov): on #new the text box has the focus; under the
// request Save ticket and Start now sit side by side, each with one line saying what it does (Start now outlined, with its
// cost); the helper and the optional settings are the right column. Text left on the page comes back; a refused save keeps
// it, and pressing Save again makes exactly one ticket that did not start.
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
    const words = (await form.locator('.new-ticket-what').allInnerTexts()).join(' ');
    must(/no work starts/.test(words) || /Nothing starts/.test(words), 'the line under the buttons does not say Save starts nothing');
    must(/may cost money/.test(words), 'the cost of Start now is not said');
    const order = await form.evaluate(f => {
      const y = el => el.getBoundingClientRect().top;
      const q = s => f.querySelector(s);
      const bottom = el => el.getBoundingClientRect().bottom;
      const sv = q('.new-ticket-buttons [type=submit]'), st = [...f.querySelectorAll('.new-ticket-buttons button')].find(b => b.textContent.trim() === 'Start now');
      return [bottom(q('.new-ticket-text')), y(sv), bottom(sv), y(st), innerHeight];
    });
    must(order[1] >= order[0] && order[2] <= order[4], 'Save ticket is not under the request in the first screen');
    must(Math.abs(order[1] - order[3]) < 8, 'Save ticket and Start now are not side by side');

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

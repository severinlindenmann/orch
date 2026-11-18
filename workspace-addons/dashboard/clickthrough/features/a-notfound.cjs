// A person opens an address that does not exist (a bad page and a bad ticket): the page says so and has a way back.
module.exports = {
  name: 'Page not found: a bad address says so and leads home',
  covers: ['page:notfound'],
  async run({ page, open, must, text }) {
    await open('#nope');
    must((await text()).includes('We couldn’t find that page'), 'a bad address does not say the page was not found');
    await page.getByRole('link', { name: 'Go to Home' }).click();
    await page.waitForFunction(() => location.hash === '#home');
    await page.waitForTimeout(500);
    must(!(await text()).includes('We couldn’t find that page'), 'the way back did not leave the not-found page');
    await open('#ticket/t_doesnotexist');
    must((await text()).includes('find that ticket'), 'a bad ticket address does not say the ticket was not found');
    await page.getByRole('link', { name: 'Go to Tickets' }).click();
    await page.waitForFunction(() => location.hash === '#tickets');
  },
};

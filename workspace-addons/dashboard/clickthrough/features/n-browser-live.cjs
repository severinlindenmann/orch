// The helper's browser, live (ORCH-1493): a person opens a ticket's browser page. With no browser open (this
// throw-away workspace has the browser add-on off) the page says so in one line, offers no Stop, and the stream and
// state need the sign-in. The real pictures, tabs, events and Stop are proven with a real headless browser in the
// add-on's tests (workspace-addons/browse/tests/test_live_view.py) and the dashboard relay in test_browseview.py.
module.exports = {
  name: 'Browser: a ticket without a browser says so, with no Stop',
  covers: ['page:browser'],
  async run({ page, open, must, text, orch }) {
    const tid = JSON.parse(orch('ticket', 'new', 'Read the opening hours', '--json')).id;
    await open('#browser/' + tid);
    await page.waitForFunction(() => document.querySelector('.bview')?.dataset.state === 'none'
      || document.querySelector('.bview')?.dataset.state === 'ended');
    const words = await text();
    must(/The browser add-on is not turned on in this workspace\.|No browser is open for this ticket\./.test(words),
      'the browser page does not say why there is no picture');
    must(!(await page.getByRole('button', { name: 'Stop browser' }).count()), 'Stop shows with no browser open');
    const state = await page.evaluate(async t => (await fetch('/api/browse/state?ticket=' + t)).json(), tid);
    must(state.open === false, 'the state says a browser is open');
  },
};

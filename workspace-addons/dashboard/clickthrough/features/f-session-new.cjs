// A session without a ticket from the live bar's New menu (ORCH-364, draft D). The bar shows with the Focus add-on;
// the demo has none, so the page's state says it is on (nothing else is changed). The
// click is real: the server runs this checkout's `orch session new terminal` in the demo workspace. The plain terminal
// is the kind that starts no process (a placeholder until the terminal stage), so no helper runs. After a reload the
// session is still listed by orch and shown in the bar's Helpers menu.
const LIVE = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
  description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
  dashboard: { label: 'Focus', icon: 'target', order: 20 } };

module.exports = {
  name: 'New menu: start a plain terminal without a ticket',
  covers: ['session.new'],
  async run({ page, open, reload, act, must, orch }) {
    await page.route(/\/api\/state(\?.*)?$/, async route => {
      const res = await route.fetch();
      if (res.status() !== 200) return route.fulfill({ response: res });
      const st = await res.json();
      // a full state, or a changes-only answer (ORCH-517) whose changed keys are in st.set; an unchanged answer
      // keeps the page's own copy, which already holds the stand-ins
      const into = st.delta ? st.set : st;
      if (!st.unchanged && into) {
        if (!st.delta || 'addons' in into) into.addons = [...(into.addons || []).filter(a => a.name !== LIVE.name), LIVE];
      }
      route.fulfill({ response: res, json: st });
    });
    await open('#home');
    await page.locator('#live-bar [data-lbar-new]').click();
    await page.locator('#live-bar [data-key="lbar-new-menu"]').waitFor();
    await act('session.new', () => page.locator('#live-bar [data-lbar-kind="terminal"]').click());
    const pane = page.locator('#live-dock .live-pane .live-pt', { hasText: 'Plain terminal' });
    await pane.first().waitFor({ timeout: 20000 });
    must(!(await page.locator('#live-dock [data-key="live-open-ticket"]').count()), 'a session without a ticket offers Open ticket');

    const listed = JSON.parse(orch('session', 'list', '--json'));
    must(listed.sessions.some(s => s.kind === 'terminal' && s.open), 'orch does not list the plain terminal as open');
    await reload();
    // the bar's Helpers menu lists it (ORCH-2198: the bar row has no chips)
    await page.locator('#live-bar [data-lbar-list="helpers"]').click();
    await page.locator('#live-bar [data-key="lbar-pop"]', { hasText: 'Plain terminal' }).first().waitFor({ timeout: 20000 });
  },
};

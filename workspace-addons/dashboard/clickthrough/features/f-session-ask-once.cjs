// The waiting question in a Focus pane shows once (ORCH-708): a helper that needs you shows its question in the pane's
// question box with the options under it, and the pane's "now" line does not say the same words again above it.
// The bar shows with the Focus add-on and the Preview switch; the demo has neither, so the page's state says both are
// on. The click-through makes its own ticket and asks its own question on it (the seeded lunch question is answered by
// another click-through earlier in the run), and the sessions answer says that ticket's helper waits on it (no helper
// runs here). The answer is real: an option button sends it, and after a reload the question box is gone.
const LIVE = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
  description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
  dashboard: { label: 'Focus', icon: 'target', order: 20 } };
const QUESTION = 'Which hall should we book?';
const idOf = out => (/\[(t_[A-Za-z0-9]+)\]/.exec(out) || [])[1];

module.exports = {
  name: 'Focus pane: the waiting question shows once, answered there',
  covers: ['answer'],
  async run({ page, open, reload, act, must, shot, orch }) {
    let waiting = true;
    await page.route(/\/api\/state(\?.*)?$/, async route => {
      const res = await route.fetch();
      if (res.status() !== 200) return route.fulfill({ response: res });
      const st = await res.json();
      const into = st.delta ? st.set : st;
      if (!st.unchanged && into) {
        if (!st.delta || 'addons' in into) into.addons = [...(into.addons || []).filter(a => a.name !== LIVE.name), LIVE];
        if (!st.delta || 'settings' in into) into.settings = { ...(into.settings || {}), focus_preview_on: true };
      }
      route.fulfill({ response: res, json: st });
    });
    const own = idOf(orch('ticket', 'new', 'Book the hall for the summer party'));
    must(own, 'the new ticket has no id');
    orch('ask', own, QUESTION, '--option', 'Town hall', '--option', 'Boat house');
    const ticket = JSON.parse(orch('ticket', 'show', own, '--json'));
    const t = ticket.ticket || ticket;
    await page.route(/\/api\/sessions(\?.*)?$/, route => route.fulfill({ json: { groups: [], sessions: [{
      id: own, key: t.key, title: t.title, kind: null, open: true,
      status: waiting ? 'needs-you' : 'working', question: waiting ? QUESTION : null, detail: waiting ? null : 'Writing the invite',
      tool: 'Helper', model: 'Haiku', open_seconds: 300, lines: ['Asked which restaurant; waiting for the answer.'],
    }] } }));

    await open('#home');
    await page.locator(`#live-bar [data-lbar-open="${own}"]`).first().click();
    const pane = page.locator(`#live-dock [data-live-body="${own}"]`);
    const ask = pane.locator('[data-live-ask] .live-ask-q');
    await ask.waitFor({ timeout: 20000 });
    must((await ask.innerText()).trim() === QUESTION, 'the question box does not show the waiting question');
    must(await pane.locator('[data-key^="live-ask-option-"]').count() === 2, 'the two options are not under the question');
    must(!(await pane.locator('[data-live-now]').isVisible()), 'the now line repeats the question above the question box');
    const seen = (await pane.innerText()).split(QUESTION).length - 1;
    must(seen === 1, `the question shows ${seen} times in the pane`);
    await shot('ask-once', pane);

    waiting = false;
    await act('answer', () => pane.locator('[data-key="live-ask-option-1"]').click());
    await reload();
    await page.locator(`#live-dock [data-live-body="${own}"] [data-live-now]`, { hasText: 'Writing the invite' })
      .waitFor({ timeout: 20000 });
    must(!(await page.locator(`#live-dock [data-live-body="${own}"] [data-live-ask]`).isVisible()),
      'the question box still shows after the answer and a reload');
  },
};

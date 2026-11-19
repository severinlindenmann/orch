// The Empty helper's model in the live bar's New menu (ORCH-710, draft D feature 12): the menu says what the Empty
// helper runs on, the usual model preselected; the person picks Haiku and starts it. The click is real: the server
// runs this checkout's `orch session new empty --model haiku` in the demo workspace (a stand-in helper). orch then
// lists the Empty helper on Haiku and its pane opens, found by the session and not by its title (the model line of a running pane: tests/live_model.test.js;
// the stand-in helper ends by itself within seconds, so it is not waited for here). The session is closed again at the end.
// The demo's stand-in tools take no model: first the menu says so; then the page's state marks them as taking one
// (as orch says for a tool it passes the model to), so the picker shows.
// EMPTY_SHOTS=<folder> keeps pictures of the open menu and the pane at 1280 and 390 (for the UX checklist).
const path = require('node:path');
const LIVE = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
  description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
  dashboard: { label: 'Focus', icon: 'target', order: 20 } };

module.exports = {
  name: 'New menu: the Empty helper shows its model and starts on the one picked',
  covers: ['session.new'],
  async run({ page, open, reload, act, must, orch }) {
    let models = false;
    const shots = process.env.EMPTY_SHOTS || '';
    const shoot = async name => {
      if (!shots) return;
      await page.screenshot({ path: path.join(shots, name + '-1280.png') });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForTimeout(300);
      await page.screenshot({ path: path.join(shots, name + '-390.png') });
      await page.setViewportSize({ width: 1280, height: 900 });
      await page.waitForTimeout(300);
    };
    await page.route(/\/api\/state(\?.*)?$/, async route => {
      const res = await route.fetch();
      if (res.status() !== 200) return route.fulfill({ response: res });
      const st = await res.json();
      const into = st.delta ? st.set : st;
      if (!st.unchanged && into) {
        if (!st.delta || 'addons' in into) into.addons = [...(into.addons || []).filter(a => a.name !== LIVE.name), LIVE];
        if (!st.delta || 'settings' in into) {
          const s = into.settings || {};
          into.settings = { ...s, focus_preview_on: true,
            ...(models && Array.isArray(s.agents) ? { agents: s.agents.map(a => ({ ...a, models: true })) } : {}) };
        }
      }
      route.fulfill({ response: res, json: st });
    });
    await open('#home');
    await page.locator('#live-bar [data-lbar-new]').click();
    const menu = page.locator('#live-bar [data-key="lbar-new-menu"]');
    await menu.waitFor();
    must((await menu.innerText()).includes('Empty helper: this tool uses its own model.'), 'a tool without models does not say so');
    models = true;
    await reload();
    await page.locator('#live-bar [data-lbar-new]').click();
    await menu.waitFor();
    must((await menu.innerText()).includes('Empty helper runs on'), 'the New menu does not say what the Empty helper runs on');
    const usual = await menu.locator('[data-lbar-model]').inputValue();
    must(/\(usual\)/.test(await menu.locator('[data-lbar-model] option:checked').innerText()), 'the usual model is not preselected');
    await shoot('empty-menu');
    must(usual !== 'haiku', 'the demo would start on Haiku anyway');
    await menu.locator('[data-lbar-model]').selectOption('haiku');
    await act('session.new', () => menu.locator('[data-lbar-kind="empty"]').click());
    const listed = JSON.parse(orch('session', 'list', '--json'));
    const empty = listed.sessions.find(s => s.kind === 'empty' && s.model === 'haiku');
    must(empty, 'orch does not list the Empty helper on Haiku');
    // By the session, not by its title: the stand-in helper may already have ended (the pane then says so).
    await page.locator(`#live-dock .live-pane[data-session="${empty.id}"]`).waitFor({ timeout: 20000 });
    await shoot('empty-pane');
    orch('session', 'close', 'empty');
  },
};

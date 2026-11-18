// The History tab of a session pane (draft D, ORCH-363): open a ticket's session in the layer, open History, press
// Reopen on an earlier session. Here the page's state is told the live-session add-on and the Preview switch are on,
// and the earlier sessions are a fixed list (n-session-history.cjs does the same with the real add-on and a real
// earlier conversation, and reopens it). The Reopen goes to the real server: orch refuses it
// because that session is not this ticket's, and the page must show orch's plain refusal and keep the list.
module.exports = {
  name: 'Session pane: History and Reopen',
  covers: ['session.reopen'],
  async run({ page, ids, open, act, must }) {
    const live = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
      description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
      dashboard: { label: 'Focus', icon: 'target', order: 20 } };
    await page.route(/\/api\/state(\?.*)?$/, async route => {
      const res = await route.fetch();
      if (res.status() !== 200) return route.fulfill({ response: res });
      const st = await res.json();
      st.addons = [...(st.addons || []).filter(a => a.name !== live.name), live];
      st.settings = { ...(st.settings || {}), focus_preview_on: true };
      route.fulfill({ response: res, json: st });
    });
    await page.route('**/addon/focus/**', route => route.fulfill({ contentType: 'text/html',
      body: '<!doctype html><title>Focus</title><main>Focus</main>' }));
    const at = h => new Date(Date.now() - h * 3600e3).toISOString();
    await page.route(/\/api\/sessions\/t_[a-z0-9]+$/, route => route.fulfill({ json: { available: true, sessions: [
      { id: 's-mon', label: 'Helper', last_used: at(30), title: 'Read the menu and pick three dishes', turns: 12, current: false, reopenable: true },
    ] } }));
    await page.addInitScript(() => { try { Object.keys(localStorage).filter(k => k.indexOf('orch.live.layer') === 0).forEach(k => localStorage.removeItem(k)); } catch (e) { /* none */ } });

    await open('#home');
    await page.waitForFunction(() => window.LiveLayer && document.getElementById('live-dock'), null, { timeout: 10000 });
    await page.evaluate(id => window.LiveLayer.open(id), ids.budget);
    const pane = page.locator('#live-dock .live-pane').first();
    const history = pane.locator('[data-key="live-history"]');
    if (await history.count()) await history.click();
    else {
      await pane.locator('[data-key="live-pane-more"]').click();
      await pane.locator('[data-key="live-history-item"]').click();
    }
    const reopen = pane.getByRole('button', { name: /^Reopen the session from/ });
    await reopen.waitFor({ timeout: 10000 });
    must(await pane.getByText('Read the menu and pick three dishes').count(), 'the History tab does not show the earlier session');

    await act('session.reopen', () => reopen.click(), { refused: true });
    await page.getByText(/does not belong to this ticket/).first().waitFor({ timeout: 5000 });
    must(await pane.locator('.live-hist-row').count(), 'the earlier sessions are gone after a refused Reopen');
    must(await reopen.isEnabled(), 'Reopen stays off after a refused Reopen');
  },
};

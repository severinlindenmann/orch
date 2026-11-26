// The live bar's one Helpers menu (ORCH-2198, owner pick J b): the bar holds no chips or counts, only Helpers and New.
// The menu groups the sessions as Needs you, Working and Quiet with their counts, each row opens its pane (the
// Manager too: before, its chip did nothing), and the menu opens fully inside the window with the bar at the bottom
// and with the bar at the top (full screen; before, the list opened above the bar, off the screen). The page's state
// is told the live-session add-on and the Preview switch are on; no helper can run here, so the sessions answer is the
// test's own (one that needs you, one working, the Manager idle).
const LIVE = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
  description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
  dashboard: { label: 'Focus', icon: 'target', order: 20 } };
const IDS = { need: 't_hlp2198a', work: 't_hlp2198b', manager: 't_mgr2198a' };

module.exports = {
  name: 'Helpers menu: one menu in the bar, inside the window at the bottom and the top, each row opens its pane',
  covers: ['page:home'],
  async run({ page, open, must, shot }) {
    const sess = (id, key, title, status, word, extra = {}) => ({ id, key, title, kind: null, name: null, pinned: false, parent: null, small: [],
      status, word, detail: '', waiting_on: [], question: null, tool: 'Helper', model: 'Sonnet', mode: 'live', opened_at: null,
      open_seconds: 600, idle_seconds: status === 'idle' ? 180 : null, closes_in_seconds: null, last_at: null, lines: [], open: true, ...extra });
    const list = [
      sess(IDS.need, 'LUNCH-17', 'Sync the menu to the board', 'needs-you', 'Needs you', { question: 'Book the hall now?' }),
      sess(IDS.work, 'LUNCH-19', 'Auto-heal the order list', 'working', 'Working'),
      sess(IDS.manager, '', 'Manager', 'idle', 'Idle', { kind: 'manager', pinned: true }),
    ];
    await page.route(/\/api\/state(\?.*)?$/, async route => {
      const res = await route.fetch();
      if (res.status() !== 200) return route.fulfill({ response: res });
      const st = await res.json();
      const into = st.delta ? st.set : st;  // a full state, or a changes-only answer (ORCH-517)
      if (!st.unchanged && into) {
        if (!st.delta || 'addons' in into) into.addons = [...(into.addons || []).filter(a => a.name !== LIVE.name), LIVE];
        if (!st.delta || 'settings' in into) into.settings = { ...(into.settings || {}), focus_preview_on: true };
        if (!st.delta || 'sessions' in into) into.sessions = [...(into.sessions || []), { id: IDS.manager, kind: 'manager', title: 'Manager', open: true }];
      }
      route.fulfill({ response: res, json: st });
    });
    await page.route(/\/api\/sessions(\?.*)?$/, route => route.fulfill({ json: { lines: 8, age_ms: 0, groups: [], now: new Date().toISOString(), sessions: list } }));
    await page.route(/\/api\/sessions\/t_[a-z0-9]+$/, route => route.fulfill({ json: { available: true, sessions: [] } }));
    await page.route('**/addon/focus/**', route => route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Focus</title><main>Focus</main>' }));
    await page.addInitScript(() => { try { Object.keys(localStorage).filter(k => k.indexOf('orch.live.layer') === 0).forEach(k => localStorage.removeItem(k)); } catch (e) { /* none */ } });

    const helpers = page.locator('#live-bar [data-lbar-list="helpers"]');
    const menu = page.locator('#live-bar [data-key="lbar-pop"]');
    // the whole menu is inside the window (and its last row can be reached)
    const inside = async where => {
      const r = await menu.evaluate(el => { const b = el.getBoundingClientRect(); return { top: b.top, bottom: b.bottom, left: b.left, right: b.right, h: innerHeight, w: innerWidth }; });
      must(r.top >= 0 && r.bottom <= r.h + 1 && r.left >= 0 && r.right <= r.w + 1, `the Helpers menu ${where} is not inside the window (${JSON.stringify(r)})`);
    };
    const openMenu = async () => { if ((await helpers.getAttribute('aria-expanded')) !== 'true') await helpers.click(); await menu.waitFor(); };

    // 1. The bar: only the Helpers button (with the ◆: something needs you), no chips or counts
    await open('#home');
    await helpers.waitFor({ timeout: 15000 });
    must((await helpers.getAttribute('aria-label')) === 'Helpers: something needs you', 'the Helpers button does not say something needs you');
    must(!(await page.locator('#live-bar .lbar-sw [data-lbar-open]').count()), 'the bar still shows session chips');
    must((await page.locator('#live-bar .lbar-sw').innerText()).replace(/\s+/g, '') === '◆Helpers', 'the bar row holds more than the Helpers button');

    // 2. The menu at the bottom: groups with counts, inside the window
    await openMenu();
    const heads = await menu.locator('.lbar-gh').evaluateAll(els => els.map(e => e.innerText.replace(/\s+/g, ' ').trim().toLowerCase()));
    must(heads.join('|') === 'needs you 1|working 1|quiet 1', `the groups read "${heads.join(' | ')}"`);
    await inside('at the bottom');
    await shot('helpers-bottom', page.locator('#live-bar'));

    // 3. The Manager's row opens its pane (its chip did nothing before)
    await menu.locator(`[data-lbar-open="${IDS.manager}"]`).click();
    await page.locator(`#live-dock .live-pane[data-session="${IDS.manager}"]`).waitFor({ timeout: 15000 });
    must(!(await menu.count()), 'the menu stays open after a row was picked');

    // 4. Full screen: the bar is at the top, the menu opens below it, inside the window; a row opens its pane
    await page.evaluate(() => window.LiveLayer.place('full'));
    await page.locator('#live-dock[data-mode="full"]').waitFor({ timeout: 10000 });
    await openMenu();
    must((await menu.getAttribute('data-at')) === 'below', 'with the bar at the top the menu does not open below it');
    await inside('in full screen');
    await shot('helpers-full', page.locator('#live-dock'));
    await menu.locator(`[data-lbar-open="${IDS.work}"]`).click();
    await page.locator(`#live-dock .live-pane[data-session="${IDS.work}"]`).waitFor({ timeout: 15000 });

    // 5. The Needs you row opens its pane too; Escape closes the menu and gives the keyboard back to Helpers
    await openMenu();
    await page.keyboard.press('Escape');
    await menu.waitFor({ state: 'detached', timeout: 5000 });
    await openMenu();
    await menu.locator(`[data-lbar-open="${IDS.need}"]`).click();
    await page.locator(`#live-dock .live-pane[data-session="${IDS.need}"]`).waitFor({ timeout: 15000 });
    await page.evaluate(() => window.LiveLayer.place('bottom'));
  },
};

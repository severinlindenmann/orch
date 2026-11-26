// Stop and End session for every kind of session (ORCH-817): the Manager, the empty helper, the chat helper and the
// plain terminal, from the pane header, a wall tile's More menu and the bar's Helpers menu (a row's More, a right-click
// on a row). The page's state is told the live-session add-on and the Preview switch are on. The plain terminal is real
// (`orch session new terminal`; End really ends it). No real helper can run here, so the three helpers are stand-ins
// in the page's state and sessions answer, under made-up ids: their End goes to the real server (`orch session end
// <kind>`, which answers that nothing is open), and their Stop goes to the real server too, which refuses it in plain
// words because no live session is on (`orch run interrupt`). An ended helper keeps its pane with Start again and
// History.
const LIVE = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
  description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
  dashboard: { label: 'Focus', icon: 'target', order: 20 } };
const IDS = { manager: 't_mgr817aa', empty: 't_emp817aa', chat: 't_cht817aa' };
const TITLES = { manager: 'Manager', empty: 'Empty helper', chat: 'Chat helper' };

module.exports = {
  name: 'Stop and End session from the pane, the wall and the bar, for all four kinds',
  covers: ['run.interrupt', 'session.end'],
  async run({ page, open, act, must, orch, shot }) {
    const ended = new Set();
    // the Manager works, the empty helper sits idle, the chat helper's login changed
    const live = kind => ({ id: IDS[kind], key: '', title: TITLES[kind], kind, name: null, pinned: true, parent: null, small: [],
      status: kind === 'manager' ? 'working' : 'idle', word: kind === 'manager' ? 'Working' : 'Idle',
      detail: kind === 'manager' ? 'Looking at every helper' : kind === 'empty' ? 'Nothing running for 3 min' : 'Nothing running for 12 min',
      waiting_on: [], question: null, tool: 'Helper', model: 'Sonnet', mode: 'live', opened_at: null, open_seconds: 600,
      idle_seconds: kind === 'manager' ? null : 180, closes_in_seconds: null, last_at: null,
      lines: kind === 'chat' ? ['⏺ Reading the question.', '  ⎿ API Error: 401 · Your login changed. Please run /login'] : kind === 'manager' ? ['⏺ Bash(orch run list)', '  ⎿ 2 helpers are live'] : [] });
    const kinds = Object.keys(IDS);
    // the page's state: from its poll, and the fresh state an action's answer carries
    const dress = st => {
      const into = st && (st.delta ? st.set : st);  // a full state, or a changes-only answer (ORCH-517)
      if (!st || st.unchanged || !into || typeof into !== 'object') return st;
      if (!st.delta || 'addons' in into) into.addons = [...(into.addons || []).filter(a => a.name !== LIVE.name), LIVE];
      if (!st.delta || 'settings' in into) into.settings = { ...(into.settings || {}), focus_preview_on: true };
      if (!st.delta || 'sessions' in into) into.sessions = [...(into.sessions || []).filter(s => s.kind === 'terminal'),
        ...kinds.map(k => ({ id: IDS[k], kind: k, title: TITLES[k], open: !ended.has(k) }))];
      return st;
    };
    await page.route(/\/api\/state(\?.*)?$/, async route => {
      const res = await route.fetch();
      if (res.status() !== 200) return route.fulfill({ response: res });
      route.fulfill({ response: res, json: dress(await res.json()) });
    });
    await page.route(/\/api\/act$/, async route => {
      const res = await route.fetch();
      if (res.status() !== 200) return route.fulfill({ response: res });
      route.fulfill({ response: res, json: dress(await res.json()) });  // the answer is the new state
    });
    // the sessions answer is the test's own (the three stand-in helpers, and the real plain terminal while orch lists it open)
    let termId = '';
    const termOpen = () => !!termId && JSON.parse(orch('session', 'list', '--json')).sessions.some(x => x.kind === 'terminal' && x.open);
    await page.route(/\/api\/sessions(\?.*)?$/, route => {
      const t = termOpen() ? [{ ...live('empty'), id: termId, title: 'Plain terminal', kind: 'terminal', status: 'idle', word: 'Open', detail: '', tool: null, model: null, lines: [] }] : [];
      route.fulfill({ json: { lines: 8, age_ms: 0, groups: [], now: new Date().toISOString(), sessions: [...kinds.filter(k => !ended.has(k)).map(live), ...t] } });
    });
    await page.route(/\/api\/sessions\/t_[a-z0-9]+$/, route => route.fulfill({ json: { available: true, sessions: [
      { id: 's-mgr', label: 'Helper', last_used: new Date(Date.now() - 2 * 3600e3).toISOString(), title: 'Looked after the helpers this morning', turns: 9, current: false, reopenable: true },
    ] } }));
    await page.route('**/addon/focus/**', route => route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Focus</title><main>Focus</main>' }));
    await page.addInitScript(() => { try { Object.keys(localStorage).filter(k => k.indexOf('orch.live.layer') === 0).forEach(k => localStorage.removeItem(k)); } catch (e) { /* none */ } });
    orch('session', 'new', 'terminal');  // the real plain terminal
    const term = JSON.parse(orch('session', 'list', '--json')).sessions.find(s => s.kind === 'terminal');
    must(term && term.open, 'the plain terminal did not open');
    termId = term.id;
    // the page's sessions list follows (a read already under way is not doubled, so ask until it has changed)
    const seen = (id, on) => page.waitForFunction(([i, o]) => { window.LiveSessions?.refresh?.(); return !!window.LiveSessions?.get(i) === o; }, [id, on], { polling: 300, timeout: 15000 });

    // 1. The pane of the Manager: Stop (refused in plain words: no live session here), End asks once, then ends.
    await open('#home');
    await page.waitForFunction(() => window.LiveLayer && document.getElementById('live-dock') && window.LiveSessions?.ready, null, { timeout: 15000 });
    await page.evaluate(id => window.LiveLayer.open(id), IDS.manager);
    const pane = page.locator('#live-dock .live-pane').first();
    // ORCH-1616: the pane header keeps pin, add beside and close; Stop and End session are in its More menu
    const more = async (p, key) => { await p.locator('[data-key="live-pane-more"]').click(); await p.locator(`[data-key="live-more-menu"] [data-key="${key}"]`).waitFor({ timeout: 10000 }); return p.locator(`[data-key="live-more-menu"] [data-key="${key}"]`); };
    await pane.locator('[data-key="live-pane-more"]').waitFor({ timeout: 10000 });
    const stop1 = await more(pane, 'live-more-stop');
    await act('run.interrupt', () => stop1.click(), { refused: true });
    await page.getByText(/no step to stop/).first().waitFor({ timeout: 5000 });
    await (await more(pane, 'live-more-end')).click();
    await pane.locator('[data-key="live-end-ask"]').waitFor();
    must(await pane.getByText('End Manager?').count(), 'End does not ask once before it ends the Manager');
    await shot('pane-end-ask', pane);
    await pane.locator('[data-key="live-end-no"]').click();
    must(!(await pane.locator('[data-key="live-end-ask"]').count()), 'Keep it does not close the question');
    await (await more(pane, 'live-more-end')).click();
    await act('session.end', () => pane.locator('[data-key="live-end-yes"]').click());
    ended.add('manager'); await seen(IDS.manager, false);
    // an ended helper keeps its pane: Start again and History with the earlier conversation
    await pane.getByText('Manager has ended').waitFor({ timeout: 15000 });
    await pane.getByText('Looked after the helpers this morning').waitFor({ timeout: 10000 });
    must(await pane.locator('[data-key="live-start-again"]').count(), 'the ended Manager has no Start again');
    await shot('pane-ended-history', pane);

    // 2. The pane of the empty helper (idle): the idle note says what to type and offers Start again and End.
    await page.evaluate(id => window.LiveLayer.open(id), IDS.empty);
    const ep = page.locator('#live-dock .live-pane').first();
    await ep.locator('[data-key="live-restart"]').waitFor({ timeout: 10000 });
    must(await ep.getByText(/Type a message below to give it work/).count(), 'the idle pane does not say what to type');
    // ORCH-1362: Stop is never greyed; pressed while nothing runs it says so in the page and sends nothing
    const stop2 = await more(ep, 'live-more-stop');
    must(!(await stop2.isDisabled()), 'Stop is greyed when nothing runs');
    await stop2.click();
    await page.getByText(/Nothing is running right now, so there is nothing to stop/).first().waitFor({ timeout: 5000 });
    await shot('pane-idle-note', ep);

    // 3. The wall: the chat helper's tile More: Stop (not greyed, ORCH-1362: says nothing runs), End session asks, then ends.
    await (await more(ep, 'live-more-min')).click();  // the pane to the bar: the wall in full view
    await open('#addon/focus');
    const tileMore = page.locator(`main [data-key="tile-end-${IDS.chat}"]`);
    await tileMore.waitFor({ timeout: 15000 });
    await tileMore.click();
    const tmenu = page.locator('main [data-key="live-end-menu"]');
    await tmenu.waitFor();
    must(!(await tmenu.locator('[data-key="live-end-stop"]').isDisabled()), 'Stop is greyed for a helper whose login changed');
    must(await tmenu.locator('[data-key="live-end-stop"]').getByText('Nothing is running right now.').count(), 'Stop does not say nothing runs for a helper whose login changed');
    await shot('wall-tile-menu', tmenu);
    await tmenu.locator('[data-key="live-end-end"]').click();
    await page.locator('main [data-key="live-end-ask"]').waitFor();
    await act('session.end', () => page.locator('main [data-key="live-end-yes"]').click());
    ended.add('chat'); await seen(IDS.chat, false);
    await page.locator(`main [data-key="tile-end-${IDS.chat}"]`).waitFor({ state: 'detached', timeout: 15000 });
    // the empty helper's tile: End from the tile
    await page.locator(`main [data-key="tile-end-${IDS.empty}"]`).click();
    await page.locator('main [data-key="live-end-menu"] [data-key="live-end-end"]').click();
    await act('session.end', () => page.locator('main [data-key="live-end-yes"]').click());
    ended.add('empty'); await seen(IDS.empty, false);

    // 4. The bar: the plain terminal's row in the Helpers menu (right-click), End session for real; no Stop for a terminal.
    await open('#home');
    await page.locator('#live-bar [data-lbar-list="helpers"]').click();
    const chip = page.locator(`#live-bar [data-lbar-open="${term.id}"]`);
    await chip.first().waitFor({ timeout: 15000 });
    await chip.first().click({ button: 'right' });
    const bmenu = page.locator('#live-bar [data-key="live-end-menu"]');
    await bmenu.waitFor();
    must(!(await bmenu.locator('[data-key="live-end-stop"]').count()), 'a plain terminal offers Stop');
    await shot('bar-chip-menu', bmenu);
    await bmenu.locator('[data-key="live-end-end"]').click();
    await page.locator('#live-bar [data-key="live-end-ask"]').getByText('The terminal closes. Its output is not kept.').waitFor();
    await act('session.end', () => page.locator('#live-bar [data-key="live-end-yes"]').click());
    const after = JSON.parse(orch('session', 'list', '--json')).sessions.find(s => s.kind === 'terminal');
    must(after && !after.open, 'orch still lists the plain terminal as open after End session');

    // 5. The Helpers menu row's More: the Manager again (started), Stop from the bar.
    ended.delete('manager'); await seen(IDS.manager, true);
    await page.evaluate(() => window.paintLiveBar?.(true));
    await page.locator('#live-bar [data-lbar-list="helpers"]').click();
    await page.locator(`#live-bar [data-key="bar-end-${IDS.manager}"]`).click();
    await act('run.interrupt', () => page.locator('#live-bar [data-key="live-end-menu"] [data-key="live-end-stop"]').click(), { refused: true });
  },
};

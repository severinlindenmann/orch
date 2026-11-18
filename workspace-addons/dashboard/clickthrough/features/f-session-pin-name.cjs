// Pin and rename a session in the new Focus (draft D, ORCH-361): pin a working session on the wall, open it, click its
// name in the pane header, type a new one and press Enter; reload: it is still pinned and named. The seeded home has
// no live-session add-on and no running helper (not-yet.json: add-ons are not installed here), so the page's state is
// told the add-on and the Preview switch are on, and the sessions list stands in for two seeded tickets. The clicks go
// to the real server, which keeps pins and names in the workspace; the stand-in list reads that file, as the real
// sessions API does, so what shows after the reload is what the server really kept.
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Focus: pin and rename a session',
  covers: ['session.pin', 'session.name'],
  async run({ page, ids, open, reload, act, must, workspace }) {
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
    const kept = () => {
      try { return JSON.parse(fs.readFileSync(path.join(workspace, '.orch', 'run', 'dashboard', 'sessions.json'), 'utf8')); }
      catch (e) { return { pins: {}, names: {} }; }
    };
    const rows = [[ids.budget, 'Ask finance for the lunch budget'], [ids.table, 'Book a table']];
    await page.route(/\/api\/sessions(\?.*)?$/, route => {
      const k = kept();
      route.fulfill({ json: { lines: 8, age_ms: 0, sessions: rows.map(([id, title]) => ({
        id, key: '', title, status: 'working', word: 'Working', detail: 'Reading the menu', waiting_on: [], question: null,
        lines: ['⏺ Read(menu.pdf)'], tool: 'Helper', model: 'Opus', mode: 'live', opened_at: null, open_seconds: 600,
        idle_seconds: null, closes_in_seconds: 3600, last_at: null, kind: '',
        pinned: (k.pins || {})[id] === true, name: (k.names || {})[id] || null })) } });
    });
    await page.addInitScript(() => { try { for (const k of Object.keys(localStorage)) if (k.indexOf('orch.live.') === 0) localStorage.removeItem(k); } catch (e) { /* none */ } });

    const tile = `[data-key="live-wall"] [data-tile="${ids.budget}"]`, inBand = b => `[data-key="live-wall"] [data-band="${b}"] [data-tile="${ids.budget}"]`;
    await open('#addon/focus');
    await page.waitForSelector(inBand('need'), { timeout: 15000 });
    await act('session.pin', () => page.click(`${tile} [data-wall-pin]`));
    await page.waitForSelector(inBand('pin'), { timeout: 5000 });
    must(kept().pins[ids.budget] === true, 'the server did not keep the pin');

    await page.click(`${tile} [data-wall-open]`);
    const pane = `#live-dock .live-pane[data-session="${ids.budget}"]`;
    await page.click(`${pane} [data-key="live-rename"]`);
    await page.fill(`${pane} [data-key="live-ren-input"]`, 'Lunch money');
    await act('session.name', () => page.press(`${pane} [data-key="live-ren-input"]`, 'Enter'));
    must(kept().names[ids.budget] === 'Lunch money', 'the server did not keep the name');

    await reload();
    await page.waitForSelector(inBand('pin'), { timeout: 15000 });
    must((await page.textContent(`${tile} .wall-tt`)).trim() === 'Lunch money', 'the tile lost its name after a reload');
  },
};

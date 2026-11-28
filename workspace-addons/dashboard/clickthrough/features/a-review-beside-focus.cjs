// Review beside the Focus panel and above the Live bar (owner's walk of 28 Nov: O-04 D, W-036, W-042), in the real
// page: with the panel on the right the page area is tight, so Review is one column, the card first and the list after
// it in the same page scroll; with the panel at the bottom the list stands beside the card again and the answer
// buttons stay above the bar. Checked at 1440 and 1920, the side menu open and closed, with no sideways scroll.
// The page's state is told the live-session add-on and its Preview switch are on; no helper can run here, so the
// sessions answer is the test's own (as in f-helpers-menu.cjs).
const LIVE = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
  description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
  dashboard: { label: 'Focus', icon: 'target', order: 20 } };
const IDS = { work: 't_rvw2801a', manager: 't_mgr2801a' };

module.exports = {
  name: 'Review beside the Focus panel: one column with the card first; above the Live bar the buttons stay in sight',
  covers: ['page:review'],
  async run({ page, open, orch, orchAsPerson, python, until, must, shot }) {
    const made = [];
    try { await walk(); } finally { tidy(); }
    // the tickets made here are closed again, so later click-throughs find the lists they expect
    function tidy() { for (const tid of made) { try { orchAsPerson('ticket', 'status', tid, 'dropped'); } catch (e) { /* already closed */ } } }
    async function walk() {
    for (let i = 1; i <= 7; i++) {
      const tid = python('import sys; from pathlib import Path; from orch import tickets; print(tickets.create(Path.cwd(), sys.argv[1], "agent:standin")["id"])', 'Beside ' + i + ': poster for month ' + i).trim();
      orch('check', 'add', tid, 'Draw the poster');
      orch('check', 'done', tid, 'c1', '--note', 'Poster ' + i + ' drawn.');
      orch('ticket', 'summary', tid, 'Month ' + i + ' has a poster with the three new dishes.');
      orch('ticket', 'status', tid, 'done');
      made.push(tid);
    }
    const sess = (id, key, title, status, word, extra = {}) => ({ id, key, title, kind: null, name: null, pinned: false, parent: null, small: [],
      status, word, detail: '', waiting_on: [], question: null, tool: 'Helper', model: 'Sonnet', mode: 'live', opened_at: null,
      open_seconds: 600, idle_seconds: status === 'idle' ? 180 : null, closes_in_seconds: null, last_at: null, lines: [], open: true, ...extra });
    const list = [sess(IDS.work, 'LUNCH-19', 'Auto-heal the order list', 'working', 'Working'), sess(IDS.manager, '', 'Manager', 'idle', 'Idle', { kind: 'manager', pinned: true })];
    await page.route(/\/api\/state(\?.*)?$/, async route => {
      const res = await route.fetch();
      if (res.status() !== 200) return route.fulfill({ response: res });
      const st = await res.json();
      const into = st.delta ? st.set : st;
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

    const was = page.viewportSize();
    await page.setViewportSize({ width: 1440, height: 900 });
    await open('#home');
    await until(s => made.every(id => (s.review?.cards || []).some(c => c.id === 'core:review:' + id)), 'seven results wait for review', 120);
    await open('#review');
    await page.locator('.review-side [data-review-row]').first().waitFor();
    await page.waitForFunction(() => window.LiveLayer && window.LiveSessions?.ready, null, { timeout: 15000 });
    await page.evaluate(id => window.LiveLayer.open(id), IDS.manager);
    await page.locator('#live-dock .live-pane').first().waitFor({ timeout: 15000 });

    const look = () => page.evaluate(() => {
      const box = q => { const n = document.querySelector(q); if (!n || !n.offsetParent) return null; const b = n.getBoundingClientRect(); return { top: Math.round(b.top), bottom: Math.round(b.bottom), left: Math.round(b.left), right: Math.round(b.right) }; };
      const pad = parseFloat(getComputedStyle(document.body).getPropertyValue('--live-pad')) || 0, padr = parseFloat(getComputedStyle(document.body).getPropertyValue('--live-padr')) || 0;
      const main = document.querySelector('main');
      return { mode: window.LiveLayer.mode, w: innerWidth, h: innerHeight, pad, padr, narrow: document.body.dataset.liveNarrow != null, stack: document.body.dataset.liveStack != null,
        side: box('.review-side[data-key="review-side"]'), next: box('[data-review-next]'), deck: box('#deck'), acts: box('.swipe-actions'), card: box('.swipe-card:not(.under):not(.under2)'),
        sideways: main ? main.scrollWidth - main.clientWidth : 0, pageSideways: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        rows: document.querySelectorAll('[data-review-queue] [data-review-row],[data-review-queue] [data-review-group]').length, lists: document.querySelectorAll('[data-review-queue]').length };
    });
    const settle = () => page.waitForTimeout(500);

    // the Focus panel on the right at 1440 and 1920, menu open and closed: one column, the card first, the list after it
    for (const width of [1440, 1920]) {
      await page.setViewportSize({ width, height: width === 1440 ? 900 : 1080 });
      await page.evaluate(() => window.LiveLayer.place('right'));
      await page.locator('#live-dock[data-mode="right"]').waitFor({ timeout: 10000 });
      for (const menu of ['open', 'closed']) {
        const closed = await page.evaluate(() => document.querySelector('.shell')?.dataset.side === 'rail');
        if ((menu === 'closed') !== closed) await page.locator('#side-toggle, [data-key="side-toggle"], .side-toggle').first().click();
        await settle();
        const r = await look(), at = `Focus on the right at ${width}, menu ${menu}: `;
        must(r.lists === 1, at + 'the list is drawn ' + r.lists + ' times');
        must(r.rows === 5, at + r.rows + ' rows, not five');
        if (r.narrow || r.stack) {
          must(!r.side && r.next && r.deck && r.deck.top < r.next.top, at + 'the list is not after the card ' + JSON.stringify(r));
        } else {
          must(r.side && !r.next && r.card && r.side.right <= r.card.left, at + 'the list is not beside the card ' + JSON.stringify(r));
        }
        must(r.sideways <= 1 && r.pageSideways <= 1, at + 'the page scrolls sideways ' + JSON.stringify(r));
        must(r.card && r.card.right <= r.w - r.padr + 1, at + 'the card runs under the panel ' + JSON.stringify(r));
        if (width === 1440 && menu === 'open') await shot('focus-right');
      }
      if (await page.evaluate(() => document.querySelector('.shell')?.dataset.side === 'rail')) await page.locator('#side-toggle, [data-key="side-toggle"], .side-toggle').first().click();
    }

    // the Live bar and panel at the bottom: the list beside the card again, the answer buttons above the bar
    for (const width of [1440, 1920]) {
      await page.setViewportSize({ width, height: width === 1440 ? 900 : 1080 });
      await page.evaluate(() => window.LiveLayer.place('bottom'));
      await page.locator('#live-dock[data-mode="bottom"]').waitFor({ timeout: 10000 });
      await settle();
      const r = await look(), at = `Live at the bottom at ${width}: `;
      must(r.side && !r.next && r.rows === 5, at + 'the list is not beside the card with five rows ' + JSON.stringify(r));
      must(r.pad > 0 && r.acts && r.acts.bottom <= r.h - r.pad + 1, at + 'the answer buttons are under the bar ' + JSON.stringify(r));
      must(r.sideways <= 1 && r.pageSideways <= 1, at + 'the page scrolls sideways ' + JSON.stringify(r));
      // O-04: the list beside the card ends above the Live panel (it scrolls in itself, nothing of it under the panel)
      await page.locator('.review-side').getByRole('button', {name:/^All /}).click();
      await settle();
      const all = await look();
      must(all.side && all.side.bottom <= all.h - all.pad + 1, at + 'the list runs under the Live panel ' + JSON.stringify(all));
      if (width === 1440) await shot('live-bottom');
      await page.locator('.review-side').getByRole('button', {name:'First five'}).click();
    }
    // W-042: a phone with the Live bar: the answer buttons stand above the tab bar and the Live bar
    await page.evaluate(() => window.LiveLayer.place('bar'));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('[data-review-next] [data-review-row]').first().waitFor();
    await settle();
    const ph = await page.evaluate(() => {
      const b = q => { const n = document.querySelector(q); return n && n.getClientRects().length ? { top: Math.round(n.getBoundingClientRect().top), bottom: Math.round(n.getBoundingClientRect().bottom) } : null; };
      return { h: innerHeight, acts: b('.swipe-actions'), tabbar: b('#tabbar'), live: b('#live-dock'), wide: document.documentElement.scrollWidth - document.documentElement.clientWidth };
    });
    must(ph.acts && ph.tabbar && ph.live && ph.live.bottom <= ph.tabbar.top + 1 && ph.acts.bottom <= ph.live.top + 1, 'phone: the answer buttons are under the bars ' + JSON.stringify(ph));
    must(ph.wide <= 1, 'phone: the page scrolls sideways ' + JSON.stringify(ph));
    await shot('phone-bars');
    await page.evaluate(() => window.LiveLayer.place('bar'));
    await page.setViewportSize(was);
    }
  },
};

// Phone width fits (issues #1024, #1081, #1070, #1218, #1368): at 390 and 320 px wide Home, Tickets, Review
// with a card in the deck, Chat and Focus do not scroll sideways, no button, link or heading is
// cut at the right edge, and every ticket link on Tickets is a 44 px touch target. Focus is turned on through the page's
// state (as l-phone-clear does); its epic strip is checked in e2e/focus_d (step 28).
const LIVE = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
  description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
  dashboard: { label: 'Focus', icon: 'target', order: 20 } };
const SIZES = [[390, 844], [320, 700]];

// Runs in the page: what scrolls sideways or is cut at the right edge (an element inside its own scroller is fine).
function fit() {
  const vw = window.innerWidth;
  const shown = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const inScroller = el => { for (let q = el.parentElement; q && q !== document.body; q = q.parentElement) { const o = getComputedStyle(q).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return true; } return false; };
  const cut = [...document.querySelectorAll('main button, main a, main h1, main h2, main h3, header button, header a, #tabbar a, #tabbar button')]
    .filter(el => shown(el) && el.getBoundingClientRect().right > vw + 1 && !inScroller(el))
    .map(el => (el.innerText || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 40));
  return { sideways: document.documentElement.scrollWidth - vw, cut };
}

module.exports = {
  name: 'Phone width: Home, Tickets, Review, Chat and Focus fit at 390 and 320 px, ticket links are 44 px touch targets',
  covers: ['page:home', 'page:tickets', 'page:review', 'page:chat'],
  async run({ page, open, must, orch, python, until, shot }) {
    const tid = python('from pathlib import Path; from orch import tickets; print(tickets.create(Path.cwd(), "Write the autumn newsletter for every customer in the region", "agent:standin")["id"])').trim();
    orch('check', 'add', tid, 'Write the texts');
    orch('check', 'done', tid, 'c1', '--summary', 'All texts written.', '--note', 'Read all texts once.');
    orch('ticket', 'summary', tid, 'The newsletter is ready.');
    orch('ticket', 'status', tid, 'done');
    await page.route(/\/api\/state(\?.*)?$/, async route => {
      const res = await route.fetch();
      if (res.status() !== 200) return route.fulfill({ response: res });
      const st = await res.json();
      const into = st.delta ? st.set : st;
      if (!st.unchanged && into && (!st.delta || 'addons' in into)) into.addons = [...(into.addons || []).filter(a => a.name !== LIVE.name), LIVE];
      route.fulfill({ response: res, json: st });
    });
    await open('#home');
    await until(s => (s.review?.cards || []).some(c => c.id === 'core:review:' + tid), 'the newsletter waits for review');
    const problems = [];
    for (const [width, height] of SIZES) {
      await page.setViewportSize({ width, height });
      for (const hash of ['#home', '#tickets', '#review', '#chat', '#addon/focus']) {
        await open(hash);
        if (hash === '#review') await page.locator('.swipe-card:not(.under):not(.under2)').first().waitFor({ timeout: 15000 });
        await page.waitForTimeout(400);
        const r = await page.evaluate(fit);
        if (r.sideways > 1) problems.push(`${width} ${hash}: scrolls sideways (${r.sideways} px too wide)`);
        for (const c of r.cut) problems.push(`${width} ${hash}: cut at the right edge: ${c}`);
        if (hash === '#tickets') {
          const low = await page.$$eval('main a.short-title, main .ticket-table td:first-child a', as => as.filter(a => a.getBoundingClientRect().height > 0 && a.getBoundingClientRect().height < 43.5).map(a => a.innerText.trim().slice(0, 30)));
          for (const t of low) problems.push(`${width} #tickets: ticket link under 44 px high: ${t}`);
        }
      }
    }
    must(!problems.length, 'the phone width does not fit:\n' + problems.join('\n'));
    await page.setViewportSize({ width: 390, height: 844 });
    await open('#tickets');
    await shot('tickets');
    await open('#review');
    await page.locator('.swipe-card:not(.under):not(.under2)').first().waitFor({ timeout: 15000 });
    await shot('review');
  },
};

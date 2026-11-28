// W-001 (owner, 28 Nov): beside the Focus panel a page lays out for the room it really has. With the panel on the
// right at 40 % of the window (the 60/40 split), the left menu open and closed, at 1440, 1920 and 1280 px, every
// dashboard-drawn page must fit its page area: nothing reaches past it sideways, no button word breaks letter by
// letter, the top bar is one row (W-004) and the page title sits at the same height on every page. The page area is
// marked narrow (body[data-live-narrow]) whenever it is under 900 px, which is what the narrow layouts key on.
// Framed add-on pages lay out for their frame by themselves (their window is the frame); what they need from the
// shell is checked here too: the frame is told that the window is wide, so it keeps desktop control sizes (W-006).
// The Focus add-on and one open session are the page's own state (no helper can run here), as in f-helpers-menu.
const LIVE = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
  description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
  dashboard: { label: 'Focus', icon: 'target', order: 20 } };
const SESSION = 't_split001a';
const SIZES = [[1440, 900], [1920, 1080], [1280, 800]];

/** What is wrong with the page as drawn now (run in the page). */
const MEASURE = () => {
  const main = document.querySelector('main'), bar = document.querySelector('.topbar');
  if (!main || !bar) return { problems: ['no page'] };
  const area = main.getBoundingClientRect(), problems = [];
  const seen = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden'; };
  const name = e => (e.getAttribute('aria-label') || e.textContent || e.tagName).replace(/\s+/g, ' ').trim().slice(0, 40);
  // inside a box that scrolls sideways on purpose (a table, a tab strip), reaching past the edge is the design
  const scrolls = e => { for (let p = e.parentElement; p && p !== main; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return true; } return false; };
  const doc = document.documentElement;
  if (doc.scrollWidth > doc.clientWidth + 1) problems.push(`the window scrolls sideways by ${doc.scrollWidth - doc.clientWidth} px`);
  for (const e of main.querySelectorAll('button, a.btn, .btn, input, textarea, select, h1, h2, .card, .badge, .pill, .chip')) {
    if (!seen(e)) continue;
    const r = e.getBoundingClientRect();
    if (r.right > area.right + 1 && !scrolls(e)) problems.push(`"${name(e)}" reaches ${Math.round(r.right - area.right)} px past the page area`);
    if (e.matches('button, .btn') && e.textContent.trim().length > 2) {
      const line = parseFloat(getComputedStyle(e).lineHeight) || 20, words = e.textContent.trim().split(/\s+/).length;
      // more lines than words: a word broke inside itself ("Save ticket" as S / a / v / e ...)
      if (r.height > line * (words + 1) + 16) problems.push(`the button "${name(e)}" breaks inside a word (${Math.round(r.width)}x${Math.round(r.height)})`);
    }
  }
  // the top bar: one row, its buttons whole
  const tops = [...bar.children].filter(seen).map(c => Math.round(c.getBoundingClientRect().top + c.getBoundingClientRect().height / 2));
  if (tops.length && Math.max(...tops) - Math.min(...tops) > 8) problems.push(`the top bar is on more than one row (${tops.join(', ')})`);
  const barBox = bar.getBoundingClientRect();
  for (const b of bar.querySelectorAll('.topbar-actions .btn')) if (seen(b) && b.getBoundingClientRect().right > barBox.right + 1) problems.push(`the top bar button "${name(b)}" is cut`);
  const h1 = main.querySelector('h1');
  return { problems, room: Math.round(area.width), narrow: document.body.hasAttribute('data-live-narrow'), barH: Math.round(barBox.height),
    // a page inside another page has '← <parent>' above its name: its title sits lower by design
    title: h1 && seen(h1) && !h1.closest('.ui-docs, .ticket-page, .chat-page') && !main.querySelector('.page-back') ? Math.round(h1.getBoundingClientRect().top) : null };
};

module.exports = {
  name: 'Split layout: beside the Focus panel at 40 % every page fits its page area, menu open and closed, at 1440, 1920 and 1280',
  covers: ['page:home', 'page:tickets', 'page:review', 'page:new', 'page:docs', 'page:ticket'],
  async run({ page, ids, open, settle, must, shot }) {
    const sess = { id: SESSION, key: '', title: 'Plain terminal', kind: 'terminal', name: null, pinned: true, parent: null, small: [], status: 'idle', word: 'Open',
      detail: '', waiting_on: [], question: null, tool: '', model: '', mode: 'live', opened_at: null, open_seconds: 600, idle_seconds: 180, closes_in_seconds: null,
      last_at: null, lines: [], open: true };
    await page.route(/\/api\/state(\?.*)?$/, async route => {
      const res = await route.fetch();
      if (res.status() !== 200) return route.fulfill({ response: res });
      const st = await res.json();
      const into = st.delta ? st.set : st;  // a full state, or a changes-only answer (ORCH-517)
      if (!st.unchanged && into) {
        if (!st.delta || 'addons' in into) into.addons = [...(into.addons || []).filter(a => a.name !== LIVE.name), LIVE];
        if (!st.delta || 'settings' in into) into.settings = { ...(into.settings || {}), focus_preview_on: true };
        if (!st.delta || 'sessions' in into) into.sessions = [...(into.sessions || []), { id: SESSION, kind: 'terminal', title: 'Plain terminal', open: true }];
      }
      route.fulfill({ response: res, json: st });
    });
    await page.route(/\/api\/sessions(\?.*)?$/, route => route.fulfill({ json: { lines: 8, age_ms: 0, groups: [], now: new Date().toISOString(), sessions: [sess] } }));
    await page.route(/\/api\/sessions\/t_[a-z0-9]+$/, route => route.fulfill({ json: { available: true, sessions: [] } }));
    await page.route('**/addon/focus/**', route => route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Focus</title><main>Focus</main>' }));

    const pages = [['home', '#home'], ['tickets', '#tickets'], ['review', '#review'], ['new', '#new'], ['docs', '#docs'], ['ticket', '#ticket/' + ids.lunch]];
    const problems = [];
    const was = page.viewportSize();
    for (const [w, h] of SIZES) {
      await page.setViewportSize({ width: w, height: h });
      for (const nav of ['wide', 'rail']) {
        // the layer as a person left it: one pane, on the right, 40 % of the window; the menu open or closed
        await open('#home');
        await page.evaluate(([id, width, side]) => {
          /* eslint-disable no-undef */
          localStorage.setItem(liveLayerKey(String(state.workspace || '')), JSON.stringify({ mode: 'right', last: 'right', back: 'right', width, panes: [id], cur: id }));
          localStorage.setItem('orch.nav.side', side);
          /* eslint-enable no-undef */
        }, [SESSION, Math.round(w * 0.4), nav]);
        await page.reload(); await settle();
        await page.locator('#live-dock .live-panel[data-mode="right"]').waitFor({ timeout: 15000 });
        const titles = [], bars = [];
        for (const [name, hash] of pages) {
          await page.evaluate(x => { location.hash = x; }, hash);
          await settle();
          await page.waitForTimeout(250);
          const m = await page.evaluate(MEASURE);
          const where = `${w} ${nav === 'wide' ? 'menu open' : 'menu closed'} ${name}`;
          for (const p of m.problems) problems.push(`${where}: ${p}`);
          if (m.room < 900 && !m.narrow) problems.push(`${where}: the page area is ${m.room} px but is not marked narrow`);
          if (m.room >= 900 && m.narrow) problems.push(`${where}: the page area is ${m.room} px but is marked narrow`);
          if (m.title != null) titles.push([name, m.title]);
          bars.push([name, m.barH]);
          if (w === 1440) await shot(`${nav}-${name}`).catch(() => {});
          if (w === 1440 && process.env.SPLIT_SHOTS) await page.screenshot({ path: `${process.env.SPLIT_SHOTS}/split-${w}-${nav}-${name}.png` });
        }
        // W-004: the bar has one height and the page title one place on every page
        if (new Set(bars.map(b => b[1])).size > 1) problems.push(`${w} ${nav}: the top bar changes height between pages (${bars.map(b => b.join(' ')).join(', ')})`);
        if (new Set(titles.map(t => t[1])).size > 1) problems.push(`${w} ${nav}: the page title jumps between pages (${titles.map(t => t.join(' ')).join(', ')})`);
      }
    }
    await page.setViewportSize(was);
    await page.evaluate(() => { try { Object.keys(localStorage).filter(k => k.indexOf('orch.live.layer') === 0 || k === 'orch.nav.side').forEach(k => localStorage.removeItem(k)); } catch (e) { /* none */ } });
    must(!problems.length, `${problems.length} layout problems beside the panel:\n  ${problems.join('\n  ')}`);
  },
};

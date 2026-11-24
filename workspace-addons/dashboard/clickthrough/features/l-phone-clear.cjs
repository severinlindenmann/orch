// Nothing hides under the Live bar or the phone tabs (ORCH-1698): on Home, Tickets, Review, Chat, Settings and an
// add-on page, at 1440, 1024 and 390 px wide, the end of the page can be scrolled clear of the bars; on a phone the
// tab of the shown section is marked (More for every page that is none of the three), Home offers New ticket, and every
// Chat suggestion shows above the writing box. The Live bar is switched on like f-session-end does (stand-in state).
const LIVE = { name: 'focus', label: 'Focus', icon: 'target', active: true, removable: true, shipped: false,
  description: 'A live page for one ticket.', page: { path: '/', label: 'Open Focus', live_session: true },
  dashboard: { label: 'Focus', icon: 'target', order: 20 } };
const FILES = { name: 'files', label: 'Files', icon: 'folder', active: true, removable: true, shipped: false,
  description: 'Every file.', page: { path: '/', label: 'Open Files' }, dashboard: { label: 'Files', icon: 'folder', order: 30 } };
// ORCH-1694: an add-on page that is no full-height shell (Insights) ends above the Live bar too, without scrolling the dashboard
const NOTES = { name: 'notes', label: 'Notes', icon: 'folder', active: true, removable: true, shipped: false,
  description: 'Every note.', page: { path: '/', label: 'Open Notes' }, dashboard: { label: 'Notes', icon: 'folder', order: 40 } };
const MGR = { id: 't_mgr1698aa', key: '', title: 'Manager', kind: 'manager', name: null, pinned: true, parent: null, small: [],
  status: 'working', word: 'Working', detail: 'Looking at every helper', waiting_on: [], question: null, tool: 'Helper', model: 'Sonnet',
  mode: 'live', opened_at: null, open_seconds: 600, idle_seconds: null, closes_in_seconds: null, last_at: null, lines: [] };
const SIZES = [[1440, 900], [1024, 768], [390, 844]];

module.exports = {
  name: 'Live bar and phone tabs: nothing hidden, the shown section marked, New ticket and Chat suggestions reachable',
  covers: ['page:chat'],
  async run({ page, open, must, orch }) {
    for (let i = 0; i < 25; i++) orch('ticket', 'new', 'Weekly task number ' + i, '--json');
    const dress = st => {
      const into = st && (st.delta ? st.set : st);
      if (!st || st.unchanged || !into || typeof into !== 'object') return st;
      if (!st.delta || 'addons' in into) into.addons = [...(into.addons || []).filter(a => ![LIVE.name, FILES.name, NOTES.name].includes(a.name)), LIVE, FILES, NOTES];
      if (!st.delta || 'settings' in into) into.settings = { ...(into.settings || {}), focus_preview_on: true };
      if (!st.delta || 'sessions' in into) into.sessions = [{ id: MGR.id, kind: 'manager', title: 'Manager', open: true }];
      return st;
    };
    await page.route(/\/api\/state(\?.*)?$/, async route => {
      const res = await route.fetch();
      if (res.status() !== 200) return route.fulfill({ response: res });
      route.fulfill({ response: res, json: dress(await res.json()) });
    });
    await page.route(/\/api\/sessions(\?.*)?$/, route => route.fulfill({ json: { lines: 8, age_ms: 0, groups: [], now: new Date().toISOString(), sessions: [MGR] } }));
    await page.route('**/addon/files/**', route => route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Files</title><body style="margin:0"><script>parent.postMessage({orch:"embed-shell",path:"/addon/files/"},"*")</script><div style="height:3000px">Files</div>' }));
    await page.route('**/addon/notes/**', route => route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Notes</title><body style="margin:0"><div style="height:3000px">Notes</div>' }));
    await page.addInitScript(() => { try { Object.keys(localStorage).filter(k => k.indexOf('orch.live.layer') === 0).forEach(k => localStorage.removeItem(k)); } catch (e) { /* none */ } });

    const pages = ['#home', '#tickets', '#review', '#chat', '#settings/general', '#addon/files', '#addon/notes'];
    const problems = [];
    for (const [w, h] of SIZES) {
      await page.setViewportSize({ width: w, height: h });
      for (const hash of pages) {
        await open(hash);
        await page.waitForFunction(() => document.getElementById('live-bar'), null, { timeout: 15000 }).catch(() => {});
        await page.waitForTimeout(400);
        // the add-on's own page reports it is a full-height shell (pages/settings.js adds this class on its message)
        await page.evaluate(() => document.querySelectorAll('iframe.embed[src^="/addon/files/"]').forEach(f => f.classList.add('embed-shell')));
        await page.waitForTimeout(100);
        const r = await page.evaluate(() => {
          const bars = ['live-bar', 'tabbar'].map(id => document.getElementById(id)).filter(e => e && e.offsetParent !== null || (e && getComputedStyle(e).position === 'fixed' && e.getBoundingClientRect().height));
          const top = Math.min(innerHeight, ...bars.map(b => b.getBoundingClientRect().top));
          // an add-on page scrolls inside its frame: the frame itself ends above the bars before the dashboard is scrolled
          document.scrollingElement.scrollTop = 0;
          const frame = document.querySelector('iframe.embed:not(.embed-loading)');
          const frameEnd = frame ? frame.getBoundingClientRect().bottom : 0;
          const scrollers = [document.scrollingElement, ...document.querySelectorAll('.page, main, .shell > div')].filter(Boolean);
          for (const s of scrollers) s.scrollTop = s.scrollHeight;
          const page = document.querySelector('.page') || document.querySelector('main');
          const real = [...(page?.children || [])].filter(e => e.getBoundingClientRect().height > 0 && getComputedStyle(e).position !== 'fixed' && getComputedStyle(e).position !== 'absolute');
          const lowest = Math.max(0, ...real.map(e => e.getBoundingClientRect().bottom));
          const tabs = document.getElementById('tabbar');
          return { top, lowest, frameEnd, bars: bars.map(b => b.id), live: !!document.getElementById('live-bar'),
            current: tabs ? [...tabs.children].filter(c => c.getAttribute('aria-current') === 'page' || c.dataset.current != null || c.getAttribute('aria-expanded') === 'true').map(c => c.dataset.tab) : null };
        });
        problems.push(`${w} ${hash}: live=${r.live} bars=${r.bars} lowest=${Math.round(r.lowest)} barTop=${Math.round(r.top)} ${r.lowest > r.top + 1 || r.frameEnd > r.top + 1 ? 'COVERED' : 'ok'} frameEnd=${Math.round(r.frameEnd)} current=${JSON.stringify(r.current)}`);
      }
    }
    const covered = problems.filter(x => x.includes('COVERED'));
    must(!covered.length, 'something stays under the bars:\n' + covered.join('\n'));
    // the phone: the shown section is marked on the tabs
    await page.setViewportSize({ width: 390, height: 844 });
    const marked = async hash => { await open(hash); await page.waitForTimeout(300); return page.evaluate(() => [...document.querySelectorAll('#tabbar > *')].filter(c => c.getAttribute('aria-current') === 'page' || c.dataset.current).map(c => c.dataset.tab).join(',')); };
    for (const [hash, tab] of [['#home', 'home'], ['#tickets', 'tickets'], ['#review', 'review'], ['#chat', 'more'], ['#settings/general', 'more'], ['#addon/files', 'more']]) {
      const got = await marked(hash);
      must(got === tab, hash + ' should mark ' + tab + ' on the phone tabs, marks "' + got + '"');
    }
    // Home on a phone offers New ticket (the top bar is hidden there) and it opens the New ticket page
    await open('#home');
    const fresh = page.locator('[data-key="new-ticket-phone"]');
    must(await fresh.isVisible(), 'Home on a phone has no New ticket');
    await fresh.click();
    await page.waitForFunction(() => location.hash === '#new', null, { timeout: 10000 });
    // the empty Chat shows all three suggestions, the last one clear of the writing box
    await open('#chat');
    await page.waitForTimeout(500);
    const gap = await page.evaluate(() => { const ps = [...document.querySelectorAll('.chat-prompt')], area = document.querySelector('.chat-composer-area, .chat-compose'); const bars = ['live-bar', 'tabbar'].map(id => document.getElementById(id)).filter(Boolean); const top = Math.min(...bars.map(b => b.getBoundingClientRect().top)); window.scrollTo(0, 1e6); return { n: ps.length, last: ps.length ? ps[ps.length - 1].getBoundingClientRect().bottom : 0, box: area ? area.getBoundingClientRect().top : 0, top }; });
    must(gap.n === 3, 'the Chat page shows ' + gap.n + ' suggestions, not 3');
    must(gap.last <= gap.box + 1, 'the third suggestion ends at ' + gap.last + ' under the writing box that starts at ' + gap.box);
    must(gap.box < gap.top, 'the writing box sits under the bars');
  },
};

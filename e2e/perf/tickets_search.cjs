// ORCH-2159: short, isolated browser regression/measurement on 360 sample tickets.
// PW_DIR=<node_modules> node e2e/perf/tickets_search.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {launch} = require('../headless.cjs');
const {chromium} = require(path.join(process.env.PW_DIR || path.join(os.homedir(), 'orch-dev/e2e/dashboard/node_modules'), 'playwright'));
const root = path.resolve(__dirname, '../..');
const web = path.join(root, 'workspace-addons/dashboard/src/orch_dashboard/web');
const kit = path.join(root, 'workspace/src/orch_ui/static');
const state = JSON.parse(fs.readFileSync(path.join(root, 'workspace-addons/dashboard/tests/fixtures/state-chat-settings.json')));
state.needs = []; state.runs = {}; state.addons = [];
state.tickets = Array.from({length:360}, (_, i) => ({
  id:'t_sample' + i, key:'DEMO-' + (i + 1),
  title:['Arrange delivery', 'About the catalogue', 'ABC supplier invoice'][i % 3] + ' ' + (i + 1),
  owner:'Anna', status:['open', 'ready', 'active', 'review', 'done'][i % 5],
  created_at:state.now, updated_at:state.now, checklist:[], questions:[], children:[],
}));
(async () => {
  const browser = await launch(chromium);
  try {
    const page = await browser.newPage(), errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== 'http://tickets.test') return route.abort();
      const json = body => route.fulfill({contentType:'application/json', body:JSON.stringify(body)});
      if (url.pathname === '/api/state') return json(state);
      if (url.pathname === '/api/tickets') {
        const q = (url.searchParams.get('q') || '').toLowerCase();
        const items = state.tickets.filter(t => (t.title + ' ' + t.key).toLowerCase().includes(q));
        const offset = Number(url.searchParams.get('offset')) || 0, limit = Number(url.searchParams.get('limit')) || 50;
        return json({items:items.slice(offset, offset + limit), total:items.length, next:offset + limit < items.length ? offset + limit : null});
      }
      if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/session/')) return json({});
      const file = url.pathname.startsWith('/kit/') ? path.join(kit, url.pathname.slice(5)) : path.join(web, url.pathname === '/' ? 'index.html' : url.pathname);
      if (!fs.existsSync(file)) return route.fulfill({status:404, body:''});
      return route.fulfill({contentType:{'.html':'text/html', '.js':'text/javascript', '.css':'text/css', '.svg':'image/svg+xml'}[path.extname(file)] || 'text/plain', body:fs.readFileSync(file)});
    });
    for (const width of [1280, 1920, 390, 320]) {
      await page.setViewportSize({width, height:width === 1920 ? 1080 : width < 500 ? 844 : 800});
      await page.goto('http://tickets.test/#tickets');
      const input = page.locator('[data-key="ticket-search"]');
      await input.waitFor();
      await page.waitForTimeout(300);
      await input.focus();
      const report = await page.evaluate(async () => {
        const input = document.querySelector('[data-key="ticket-search"]'), start = performance.now();
        for (const q of ['a', 'ab', 'abc']) { input.value = q; input.dispatchEvent(new Event('input', {bubbles:true})); }
        const handlerMs = performance.now() - start;
        await new Promise((resolve, reject) => {
          const watch = () => {
            const text = document.querySelector('#content').innerText;
            if (!text.includes('Arrange delivery') && !text.includes('About the catalogue') && text.includes('ABC supplier invoice')) return resolve();
            if (performance.now() - start > 3000) return reject(new Error('Search results did not update'));
            requestAnimationFrame(watch);
          };
          watch();
        });
        return {handlerMs, resultsMs:performance.now() - start, sameInput:document.activeElement === input,
          value:input.value, overflow:document.documentElement.scrollWidth > innerWidth};
      });
      assert.equal(report.value, 'abc');
      assert.equal(report.sameInput, true, 'typing must keep the input and keyboard focus');
      assert.equal(report.overflow, false);
      // Report timings rather than a hardware-dependent absolute CI threshold (R8.3).
      console.log(JSON.stringify({width, tickets:360, ...report}));
      await input.fill('no-ticket-matches-this');
      await page.getByText('No tickets match', {exact:true}).waitFor();
      await input.fill('abc');
      await page.waitForFunction(() => document.querySelector('#content').innerText.includes('ABC supplier invoice'));
      await page.evaluate(() => { location.hash = '#tickets?q=About'; });
      await page.waitForFunction(() => document.querySelector('[data-key="ticket-search"]').value === 'About');
      await input.fill('');
      await page.waitForFunction(() => document.querySelector('#content').innerText.includes('Arrange delivery'));
    }
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });

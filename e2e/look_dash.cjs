// LOOK-2 browser half: drives the workspace dashboard (Settings > General, sidebar switcher) with Playwright.
// usage: PW_DIR=<dir holding node_modules/playwright's parent> node look_dash.cjs <dashboard url> <shots dir or ''> <description>
// prints one JSON line with what it saw; exit 1 on a failed step.
const { chromium } = require(require('path').join(process.env.PW_DIR, 'playwright'));
const [base, shots, desc] = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const out = {};
  const b = await chromium.launch();
  for (const [w, h] of [[1280, 800], [720, 900]]) {
    const p = await b.newPage({ viewport: { width: w, height: h } });
    const errs = []; p.on('pageerror', e => errs.push(e.message));
    await p.goto(base + '/#settings');
    await p.waitForSelector('[data-testid=settings-look]');
    if (w === 1280) {
      // pick Wallet / Amber from Money
      await p.click('[data-testid=look-change]');
      await p.click('[data-key=lk-cat-money]');
      await p.click('[data-key=lk-icon-wallet]');
      await p.click('[data-key=lk-color-amber]');
      if (shots) await p.screenshot({ path: `${shots}/e2e-picker-${w}.png` });
      await p.click('[data-key=lk-save]');
      await p.waitForSelector('[data-key=lk-status]');
      out.status = await p.textContent('[data-key=lk-status]');
      out.favicon = (await p.getAttribute('link[rel=icon]', 'href')).slice(0, 40);
      out.title = await p.title();
      // description: a proposal
      await p.click('[data-key=lk-desc-edit]');
      await p.fill('[data-key=lk-desc-input]', desc);
      await p.click('[data-key=lk-desc-save]');
      await p.waitForSelector('[data-testid=look-pending]', { timeout: 15000 });
      out.pending = await p.textContent('[data-testid=look-pending]');
      // shared pages switch off
      await p.click('[data-testid=look-shared-pages]');
      await sleep(1500);
      out.shared = await p.getAttribute('[data-testid=look-shared-pages]', 'aria-checked');
      // switcher
      await p.click('[data-testid=ws-switch]');
      await p.waitForSelector('[data-testid=ws-menu]');
      out.items = await p.$$eval('[data-testid=ws-item] .ws-item-name', n => n.map(x => x.textContent));
      out.itemLooks = await p.$$eval('[data-testid=ws-item] .wsb', n => n.map(x => [x.getAttribute('data-c'), !!x.querySelector('svg')]));
      if (shots) await p.screenshot({ path: `${shots}/e2e-switcher-${w}.png` });
    } else {
      await p.waitForSelector('[data-testid=look-change]');
      out.narrow = await p.$$eval('[data-testid=settings-look]', n => n.length);
      const overflow = await p.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
      out.noOverflow = overflow;
      if (shots) await p.screenshot({ path: `${shots}/e2e-settings-${w}.png` });
    }
    out['errors' + w] = errs;
    await p.close();
  }
  await b.close();
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });

// LOOK-2 browser half: drives the workspace dashboard (Settings > General, sidebar switcher) with Playwright.
// usage: PW_DIR=<dir holding node_modules/playwright's parent> node look_dash.cjs <dashboard url> <shots dir or ''> <description> <sign-in link>
// The sign-in link (orch start --print-launch-url) gives the 1280 page a session; without it every click is refused (watch-only).
// prints one JSON line with what it saw; exit 1 on a failed step.
const { chromium } = require(require('path').join(process.env.PW_DIR, 'playwright'));
const [base, shots, desc, launch] = process.argv.slice(2);
const WAIT = 60000;  // a computer busy with other helpers answers slowly (load 34-40 took LOOK-2 past 15 s)
(async () => {
  const out = {};
  const b = await chromium.launch();
  for (const [w, h] of [[1280, 800], [720, 900]]) {
    const p = await b.newPage({ viewport: { width: w, height: h } });
    const errs = []; p.on('pageerror', e => errs.push(e.message));
    if (w === 1280 && launch) {  // sign in the way a person does: the page hands the one-time token over and reloads
      await p.goto(launch);
      await p.waitForFunction(() => !location.hash.includes('launch=') && !!localStorage.length, null, { timeout: WAIT });
    }
    await p.goto(base + '/#settings');
    await p.waitForSelector('[data-testid=settings-profile]');
    if (w === 1280) {
      // pick Wallet / Amber from Money
      await p.click('[data-testid=look-change]');
      await p.click('[data-key=lk-more]');  // the category chips show only after More icons
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
      await p.click('[data-key=pf-edit]');
      await p.fill('[data-key=pf-description]', desc);
      await p.click('[data-key=pf-save]');
      await p.waitForFunction(() => /Waiting for relay/.test(document.querySelector('[data-testid=profile-relay-state]')?.textContent || ''), null, { timeout: WAIT });
      out.pending = await p.textContent('[data-testid=profile-relay-state]');
      // shared pages switch off
      const sharedBefore = await p.getAttribute('[data-testid=look-shared-pages]', 'aria-checked');
      await p.click('[data-testid=look-shared-pages]');
      await p.waitForFunction(b => document.querySelector('[data-testid=look-shared-pages]')?.getAttribute('aria-checked') !== b,
        sharedBefore, { timeout: WAIT });
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

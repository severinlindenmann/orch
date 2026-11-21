// P10 browser half: opens shared-link and app pages of the local publish server like a person, at 1440 and 390 wide.
// usage: PW_DIR=<node_modules folder with playwright> node pub_pages.cjs <pages.json> <shots dir or ''>
// pages.json: [{"name": "viewer", "url": "http://127.0.0.1:N/f/<id>#k=<key>", "expect": ["text", ...], "status": 404?}, ...]
// Prints one JSON line: [{name, width, found: [texts seen], missing: [...], hscroll, errors: [...]}]. Exit 1 when the
// browser itself could not start; the checks are the Python half's.
const { chromium } = require(require('path').join(process.env.PW_DIR, 'playwright'));
const headless = require('./headless.cjs'); // the keychain options (ORCH-615)
const fs = require('fs');
const [specFile, shots] = process.argv.slice(2);
const pages = JSON.parse(fs.readFileSync(specFile, 'utf8'));
(async () => {
  const b = await headless.launch(chromium);
  const out = [];
  for (const [w, h] of [[1440, 900], [390, 844]]) {
    const ctx = await b.newContext({ viewport: { width: w, height: h } });
    for (const pg of pages) {
      const p = await ctx.newPage();
      const errors = [];
      p.on('pageerror', e => errors.push(e.message));
      // a gone file (404) or a paused app (503) answers with that status on purpose ("status" in pages.json): only
      // there a failed load is expected; everywhere else it counts
      p.on('console', m => { if (m.type() === 'error' && !(pg.status && /Failed to load resource/.test(m.text()))) errors.push(m.text()); });
      await p.goto(pg.url, { waitUntil: 'load', timeout: 30000 }).catch(e => errors.push('goto: ' + e.message.split('\n')[0]));
      const found = [];
      for (const t of pg.expect) {
        // the file page decrypts in the browser after load: wait for the words, not for a fixed time
        if (await p.getByText(t, { exact: false }).first().waitFor({ timeout: 15000 }).then(() => true, () => false)) found.push(t);
      }
      const hscroll = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      if (shots) await p.screenshot({ path: `${shots}/p10-${pg.name}-${w}.png`, fullPage: true });
      out.push({ name: pg.name, width: w, found, missing: pg.expect.filter(t => !found.includes(t)), hscroll, errors });
      await p.close();
    }
    await ctx.close();
  }
  await b.close();
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e.message); process.exit(1); });

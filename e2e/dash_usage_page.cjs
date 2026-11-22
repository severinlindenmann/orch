// USG-1 browser half: changes every rule on the dashboard's Usage page once, like a person (ORCH-893).
// usage: PW_DIR=<node_modules holding playwright> node dash_usage_page.cjs <dashboard url> <sign-in link> page|home [shots dir]
//   page: limit, a refused limit, order, on/off, end date and Keep it, no end, a ready-made spread, Switch by itself
//   home: the Usage warning row on Home and its Got it
// Prints one JSON line with what it saw; exits 1 on a failed step (the message says which).
const path = require('path');
const { chromium } = require(path.join(process.env.PW_DIR, 'playwright'));
const headless = require('./headless.cjs'); // the keychain options (ORCH-615)
const [base, launch, part, shots] = process.argv.slice(2);
const T = 30000;

async function until(what, fn, ms = T) {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (await fn().catch(() => false)) return; await new Promise(r => setTimeout(r, 300)); }
  throw new Error('timed out: ' + what);
}
function check(cond, msg) { if (!cond) throw new Error(msg); }

(async () => {
  const out = { errors: [], steps: [], noOverflow: true, refused: '' };
  const b = await headless.launch(chromium);
  const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
  p.on('pageerror', e => out.errors.push(e.message));
  const step = s => out.steps.push(s);
  const shot = async name => { if (shots) await p.screenshot({ path: `${shots}/usage-${name}.png`, fullPage: true }); };
  // the dashboard and every frame in it (Usage is its own frame): nothing wider than its own window
  const wide = async () => {
    for (const fr of p.frames()) {
      const ok = await fr.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1).catch(() => true);
      if (!ok) return false;
    }
    return true;
  };
  try {
    await p.goto(launch);  // sign in the way a person does; without it every click is refused (watch-only)
    await p.waitForFunction(() => !location.hash.includes('launch=') && !!localStorage.length, null, { timeout: 15000 });

    if (part === 'home') {
      await p.goto(base + '/#home');
      // Home shows the row's text (the title 'Usage: every account is at or near its limit' stays in orch needs)
      const row = p.getByText('Usage has no account to switch to', { exact: false }).first();
      await row.waitFor({ timeout: T });
      await shot('home-warning');
      await p.getByRole('button', { name: 'Got it' }).first().click();
      await until('warning gone from Home', async () => !(await row.isVisible()));
      step('Home warning, Got it');
    } else {
      await p.goto(base + '/#addon/usage');
      // the page is the Usage add-on's own frame
      await until('usage frame', async () => !!p.frames().find(f => /\/addon\/usage\//.test(f.url())));
      const f = p.frames().find(fr => /\/addon\/usage\//.test(fr.url()));
      await f.locator("[aria-label='Use maria earlier']").waitFor({ timeout: T });
      const toast = () => f.locator('.ui-toast').last();
      const saved = async loc => { await loc.press('Tab'); await p.waitForTimeout(1200); };

      // a limit: 150 % is refused in plain words, 85 % is kept
      const lim = f.locator("[aria-label='Limit for maria, per 5 hours']");
      await lim.fill('150'); await saved(lim);
      await toast().waitFor({ timeout: T });
      out.refused = await toast().innerText();
      await lim.fill('85'); await saved(lim);
      step('limit refused, then kept');

      // order, on/off. The page drops a click while it still saves the one before (busy), so wait for the result
      // and click again only while it is not there (never twice once it moved)
      const names = () => f.locator('[data-acc] h3').allInnerTexts();
      await until('backup moved up', async () => {
        const at = (await names()).indexOf('backup');
        if (at === 2) await f.locator("[aria-label='Use backup earlier']:not([disabled])").click({ timeout: 2000 }).catch(() => {});
        await p.waitForTimeout(1000);
        return (await names()).indexOf('backup') === 1;
      }, 60000);
      step('order');
      const ai = f.locator("[aria-label='Use OpenAI credit']");
      await until('OpenAI credit off', async () => {
        if (await ai.isChecked() && await ai.isEnabled()) await ai.click({ timeout: 2000 }).catch(() => {});
        await p.waitForTimeout(1000);
        return !(await ai.isChecked()) && await ai.isEnabled();
      }, 60000);
      step('off');

      // an end date for maria (the 28th of next month), then Keep it, no end; an account without a limit has nothing to end
      const ends = () => f.locator('button', { hasText: 'Add an end' });
      await until('Add an end on maria', async () => (await ends().count()) >= 1 && await ends().first().isEnabled());
      await ends().first().click();  // cards in order: maria first
      const dlg = f.locator('dialog[open]');
      await dlg.waitFor({ timeout: T });
      await shot('end-date-picker');
      await dlg.getByRole('button', { name: 'Next month' }).click();
      await dlg.locator('button[aria-label^="28 "]').first().click();
      await f.getByText('Then the rule before it again.').first().waitFor({ timeout: T });
      step('end date set');
      await f.getByRole('button', { name: 'Keep it, no end' }).first().click();
      await until('end gone', async () => (await f.getByText('Then the rule before it again.').count()) === 0);
      step('Keep it, no end');

      // a ready-made spread
      await f.getByRole('button', { name: /Even spread/ }).first().click();
      await f.getByText('In use', { exact: true }).first().waitFor({ timeout: T });
      step('Even spread');

      // Switch by itself
      const sw = f.locator('#auto');
      check(!(await sw.isChecked()), 'Switch by itself was on before the click');
      await sw.click();
      await until('switch on', () => sw.isChecked());
      step('Switch by itself on');

      out.noOverflow = await wide();
      await shot('1440');
      await p.setViewportSize({ width: 390, height: 844 }); await p.waitForTimeout(600);
      out.noOverflow = out.noOverflow && await wide();
      await shot('390');
    }
  } catch (err) {
    await shot('failed').catch(() => {});
    console.error(err.stack || String(err)); console.error('steps done: ' + out.steps.join(', '));
    await b.close(); process.exit(1);
  }
  await b.close();
  console.log(JSON.stringify(out));
})();

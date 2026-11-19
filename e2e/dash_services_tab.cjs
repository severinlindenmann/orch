// SVC-1 browser half: presses every button of the dashboard's Services tab once, on real services.
// usage: PW_DIR=<node_modules holding playwright> node dash_services_tab.cjs <dashboard url> <sign-in link> <web port> <ticket id> [shots dir]
// Prints one JSON line with what it saw; exits 1 on a failed step (the message says which).
const path = require('path');
const { chromium } = require(path.join(process.env.PW_DIR, 'playwright'));
const headless = require('./headless.cjs'); // the keychain options (ORCH-615)
const [base, launch, port, ticket, shots] = process.argv.slice(2);
const WEB = 'svc1-web', TICK = 'svc1-ticker', T = 30000;

const answers = async () => { try { await fetch(`http://127.0.0.1:${port}/`, { signal: AbortSignal.timeout(1500) }); return true; } catch { return false; } };
async function until(what, fn, ms = T) {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (await fn()) return; await new Promise(r => setTimeout(r, 300)); }
  throw new Error('timed out: ' + what);
}

(async () => {
  const out = { errors: [], steps: [] };
  const b = await headless.launch(chromium);
  const p = await b.newPage({ viewport: { width: 1280, height: 900 } });
  p.on('pageerror', e => out.errors.push(e.message));
  const step = s => out.steps.push(s);
  const row = id => p.locator(`[data-split-row="${id}"]`);
  const panel = id => p.locator(`[data-split-panel="${id}"]`);
  const state = id => row(id).locator('.subline').innerText();
  const waitState = (id, word) => until(`${id} shows ${word}`, async () => (await state(id).catch(() => '')).startsWith(word));
  const pick = async id => { await p.click(`[data-split-row="${id}"] [data-split-pick]`); await panel(id).waitFor({ state: 'visible' }); };
  // one click on an add-on button: wait for its request to be answered (the page ignores a second click meanwhile)
  const press = async loc => {
    const [res] = await Promise.all([
      p.waitForResponse(r => r.url().endsWith('/api/act') && r.request().headers()['x-orch-op'] === 'addon.act', { timeout: 60000 }),
      loc.click()]);
    check(res.status() === 200, `the click was refused: ${res.status()} ${(await res.text()).slice(0, 200)}`);
    await until('page idle', () => p.evaluate(() => !document.querySelector('[data-addon-act][disabled]')));
  };
  const shot = async name => { if (shots) await p.screenshot({ path: `${shots}/services-${name}.png`, fullPage: true }); };
  try {
    await p.goto(launch);  // sign in the way a person does; without it every click is refused (watch-only)
    await p.waitForFunction(() => !location.hash.includes('launch=') && !!localStorage.length, null, { timeout: 15000 });
    await p.goto(base + '/#addon/services');
    await row(WEB).waitFor({ timeout: T }); await row(TICK).waitFor({ timeout: T });
    await waitState(WEB, 'Running'); await waitState(TICK, 'Running');
    step('both services listed as Running');

    // every row field of the web preview's panel
    await pick(WEB);
    out.facts = await panel(WEB).locator('.split-facts dt').allInnerTexts();
    out.madeBy = await panel(WEB).locator('.split-facts dd').nth(2).innerText();
    // the ticker's log fills within a few seconds (the page reloads its view every 15 s)
    await pick(TICK);
    await until('ticker log lines', async () => {
      await p.reload(); await panel(TICK).waitFor({ state: 'visible', timeout: T }).catch(async () => pick(TICK));
      return (await panel(TICK).locator('.log-lines li').count()) > 0;
    });
    out.log = (await panel(TICK).locator('.log-lines li').allInnerTexts()).slice(-3);
    step('row fields and log lines shown');

    // pictures at three widths (the panel of the web preview open), then back to 1280
    await pick(WEB);
    for (const [w, h] of [[1280, 900], [1920, 1080]]) { await p.setViewportSize({ width: w, height: h }); await shot(String(w)); }
    await p.setViewportSize({ width: 390, height: 844 });
    await p.goto(base + '/#addon/services'); await row(WEB).waitFor();
    out.noOverflow = await p.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
    await shot('390-list');
    await pick(WEB);
    out.noOverflow = out.noOverflow && await p.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
    await shot('390-panel');
    await panel(WEB).locator('.phone-only [data-split-pick=""]').click();   // ← All services
    await until('phone list again', async () => !(await panel(WEB).isVisible()) && await row(WEB).isVisible());
    step('390: list, panel and back to the list');
    await p.setViewportSize({ width: 1280, height: 900 });
    await p.goto(base + '/#addon/services'); await row(WEB).waitFor();

    // Stop in the list row, Start in the panel (ticker)
    await press(row(TICK).locator('[data-verb=stop]'));
    await waitState(TICK, 'Stopped'); step('row Stop');
    await pick(TICK);
    await press(panel(TICK).locator('[data-verb=start]'));
    await waitState(TICK, 'Running'); step('panel Start');

    // Restart, Stop in the panel and Start in the list row (web preview, checked on its port)
    await pick(WEB);
    await press(panel(WEB).locator('[data-verb=restart]'));
    await waitState(WEB, 'Running'); await until('web answers after Restart', answers); step('panel Restart');
    await pick(WEB);
    await press(panel(WEB).locator('[data-verb=stop]'));
    await waitState(WEB, 'Stopped'); await until('web silent after Stop', async () => !(await answers())); step('panel Stop');
    await press(row(WEB).locator('[data-verb=start]'));
    await waitState(WEB, 'Running'); await until('web answers after Start', answers); step('row Start');

    // Starts by itself: on, then off again (ticker)
    await pick(TICK);
    const sw = () => panel(TICK).locator('[role=switch]');
    check(await sw().getAttribute('aria-checked') === 'false', 'ticker starts by itself before the click');
    await press(sw());
    await until('switch on', async () => (await sw().getAttribute('aria-checked').catch(() => '')) === 'true'); step('switch on');
    await press(sw());
    await until('switch off', async () => (await sw().getAttribute('aria-checked').catch(() => '')) === 'false'); step('switch off');

    // Open log: the log of that service gets the focus
    await panel(TICK).locator('[data-split-log]').click();
    await until('log focused', () => p.evaluate(id => document.activeElement?.dataset?.log === id, TICK)); step('Open log');

    // Made by opens the ticket
    await pick(WEB);
    await panel(WEB).locator('.split-facts dd a').first().click();
    await until('ticket page', () => p.evaluate(t => location.hash.includes(t), ticket)); step('Made by link');
    await p.goto(base + '/#addon/services'); await row(TICK).waitFor();

    // Remove: Keep it changes nothing, Remove takes it off the list
    await pick(TICK);
    await panel(TICK).locator('[data-verb=remove]').click();
    const dlg = p.locator('dialog[open]');
    await dlg.waitFor(); out.removeLines = await dlg.locator('li').allInnerTexts();
    await dlg.getByRole('button', { name: 'Keep it' }).click();
    await dlg.waitFor({ state: 'detached' }).catch(() => dlg.waitFor({ state: 'hidden' }));
    check(await row(TICK).count() === 1, 'Keep it removed the ticker'); step('Remove > Keep it');
    await panel(TICK).locator('[data-verb=remove]').click();
    await dlg.waitFor();
    await press(dlg.getByRole('button', { name: 'Remove' }));
    await until('ticker gone', async () => (await row(TICK).count()) === 0); step('Remove');

    // footnote: Open Automation
    await p.getByRole('link', { name: 'Open Automation' }).click();
    await until('automation tab', () => p.evaluate(() => location.hash.includes('addon/automation'))); step('Open Automation');
  } catch (err) {
    await shot('failed').catch(() => {});
    console.error(err.stack || String(err)); console.error('steps done: ' + out.steps.join(', '));
    await b.close(); process.exit(1);
  }
  await b.close();
  console.log(JSON.stringify(out));
})();

function check(cond, msg) { if (!cond) throw new Error(msg); }

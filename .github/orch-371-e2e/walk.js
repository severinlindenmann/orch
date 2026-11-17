const {chromium} = require(process.env.PW || (process.env.HOME + '/orch-dev/e2e/dashboard/node_modules/playwright'));
const BASE = process.argv[2], OUT = process.argv[3], STEP = process.argv[4] || 'static';
const W = {d: [1280, 800], w: [1920, 1080], p: [390, 844]};
const log = (...a) => console.log(...a);
(async () => {
  const b = await chromium.launch({args: ['--use-mock-keychain', '--password-store=basic'], ...(process.env.CHROME ? {executablePath: process.env.CHROME} : {})});
  const errs = [];
  const ctx = await b.newContext();
  if (process.env.LAUNCH) { const p = await ctx.newPage(); await p.goto(BASE + '/#launch=' + process.env.LAUNCH); await p.waitForTimeout(2500); log('login', await p.evaluate(() => location.hash)); await p.close(); }
  async function page(size) {
    const p = await ctx.newPage(); await p.setViewportSize({width: W[size][0], height: W[size][1]});
    p.on('pageerror', e => errs.push(String(e))); p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
    return p;
  }
  async function shot(p, name) { await p.waitForTimeout(600); await p.screenshot({path: `${OUT}/${name}.png`, fullPage: true}); log('shot', name, 'innerWidth', await p.evaluate(() => innerWidth)); }
  async function go(p, hash) { await p.goto(BASE + '/' + hash); await p.waitForTimeout(2200); }
  const all = async (hash, name) => { for (const s of ['d', 'w', 'p']) { const p = await page(s); await go(p, hash); await shot(p, `${name}-${W[s][0]}`); await p.close(); } };
  const text = async p => (await p.evaluate(() => document.querySelector('main').innerText)).replace(/\n+/g, ' | ');
  const dialog = 'dialog[open], [role=dialog], [role=alertdialog]';
  if (STEP === 'static') {
    await all('#addon/services', '01-services-failing-chosen');
    await all('#addon/services?svc=web-preview', '02-service-stopped');
    await all('#addon/services?svc=talky', '03-service-running');
    await all('#addon/services?svc=found-sleeper', '04-service-taken-over');
    const p0 = await page('d'); await go(p0, '#addon/services');
    const fid = await p0.$$eval('main a[href*="svc=process"]', a => a.length ? decodeURIComponent(a[0].getAttribute('href').split('svc=')[1]) : null); await p0.close();
    if (fid) await all('#addon/services?svc=' + encodeURIComponent(fid), '05-found-on-this-computer');
    let p = await page('d'); await go(p, '#addon/services?svc=talky');
    await p.click('main button[aria-label="Open log of Talky bot"]'); await shot(p, '06-log-open-1280'); log('LOG', await text(p)); await p.close();
    p = await page('p'); await go(p, '#addon/services?svc=talky');
    await p.click('main button[aria-label="Open log of Talky bot"]'); await shot(p, '06-log-open-390'); await p.close();
    p = await page('d'); await go(p, '#addon/services?svc=web-preview');
    await p.click('main button[aria-label="Remove Web preview"]'); await p.waitForTimeout(700);
    log('DIALOG', await p.evaluate(sel => { const d = document.querySelector(sel); return d ? d.innerText : 'none'; }, dialog));
    await shot(p, '07-remove-asks-first-1280'); await p.close();
    p = await page('p'); await go(p, '#addon/services?svc=web-preview');
    await p.click('main button[aria-label="Remove Web preview"]'); await shot(p, '07-remove-asks-first-390'); await p.close();
  }
  if (STEP === 'clicks') {
    const p = await page('d'); await go(p, '#addon/services?svc=web-preview');
    const click = async (sel, name) => {
      await p.click(sel); await p.waitForTimeout(3500);
      const toast = await p.evaluate(() => [...document.querySelectorAll('.toast, [role=status], [role=alert]')].map(e => e.innerText).join(' / '));
      await go(p, '#addon/services?svc=web-preview'); await shot(p, name);
      const sw = await p.$eval('main [data-split-panel="web-preview"] button[role=switch]', e => e.getAttribute('aria-checked')).catch(() => '?');
      log(name, '| row:', (await text(p)).match(/Web preview \| [^|]+/)?.[0], '| switch:', sw, '| toast:', toast);
    };
    const P = 'main [data-split-panel="web-preview"] ';
    await click(P + 'button[aria-label="Start Web preview"]', '08-click-start-1280');
    await click(P + 'button[aria-label="Starts by itself: Web preview"]', '09-click-starts-by-itself-on-1280');
    await click(P + 'button[aria-label="Restart Web preview"]', '10-click-restart-1280');
    await click(P + 'button[aria-label="Starts by itself: Web preview"]', '11-click-starts-by-itself-off-1280');
    await click(P + 'button[aria-label="Stop Web preview"]', '12-click-stop-1280');
    await p.close();
  }
  if (STEP === 'question') {
    for (const s of ['d', 'p']) { const p = await page(s); await go(p, '#ticket/t_af0obx'); await shot(p, `13-question-on-ticket-${W[s][0]}`); if (s === 'd') log('TICKET', (await text(p)).slice(0, 900)); await p.close(); }
    const p = await page('d'); await go(p, '#ticket/t_af0obx');
    const btn = await p.$('main button:text-is("Stop")'); log('stop-btn', !!btn);
    if (btn) { await btn.click(); await p.waitForTimeout(2500); await shot(p, '14-answered-stop-1280'); }
    await p.close();
  }
  if (STEP === 'answer') {  // argv[5] = ticket id, argv[6] = option text
    const p = await page('d'); await go(p, '#ticket/' + process.argv[5]);
    await shot(p, 'L-question-on-ticket-1280');
    await p.locator('main button.qoption', {hasText: process.argv[6]}).first().click(); await p.waitForTimeout(2500);
    await shot(p, 'L-answered-1280'); await p.close();
  }
  if (STEP === 'after') {
    await all('#addon/services', process.argv[5] || '15-after-answer');
  }
  if (STEP === 'takeoff') {
    const p = await page('d');
    for (const [id, nm] of [['web-preview', 'Web preview'], ['talky', 'Talky bot'], ['order-sync', 'Order sync'], ['found-sleeper', 'Found sleeper']]) {
      await go(p, '#addon/services?svc=' + id);
      await p.click(`main button[aria-label="Remove ${nm}"]`); await p.waitForTimeout(700);
      const yes = p.getByRole('dialog').getByRole('button', {name: 'Remove', exact: true});
      log('dialog', nm, await yes.count()); await yes.last().click();
      await p.waitForTimeout(3500);
    }
    await p.close();
    await all('#addon/services', '16-empty-after-taking-all-off');
    const q = await page('d'); await go(q, '#addon/services'); log('EMPTY', await text(q)); await q.close();
  }
  log('ERRORS', JSON.stringify(errs));
  await b.close();
})();

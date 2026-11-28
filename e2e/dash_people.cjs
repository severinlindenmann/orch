// V3-P9 browser half (ORCH-1164): after the two-person story, the owner's dashboard shows it like a person sees it.
// usage: PW_DIR=<node_modules holding playwright> node dash_people.cjs <dashboard url> <sign-in link> <ticket id> [shots dir]
//   Settings > People: Lea (write), Max (write, decide), Lea's phone cut off, Max's phone his.
//   The ticket: Lea's texts and Max's answer under their names, never a person id.
//   Pictures at 1280, 1920 and 390 wide when a shots folder is given.
// Prints one JSON line with what it saw; exits 1 on a failed step (the message says which).
const path = require('path');
const { chromium } = require(path.join(process.env.PW_DIR, 'playwright'));
const headless = require('./headless.cjs'); // the keychain options (ORCH-615)
const [base, launch, tid, shots] = process.argv.slice(2);
const T = 30000;
const WIDTHS = [[1280, 800], [1920, 1080], [390, 844]];

function check(cond, msg) { if (!cond) throw new Error(msg); }

(async () => {
  const out = { errors: [], steps: [], noOverflow: true, shots: [] };
  const b = await headless.launch(chromium);
  const p = await b.newPage({ viewport: { width: 1280, height: 800 } });
  p.on('pageerror', e => out.errors.push(e.message));
  const wide = () => p.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1).catch(() => true);
  const pictures = async name => {
    for (const [w, h] of WIDTHS) {
      await p.setViewportSize({ width: w, height: h });
      await p.waitForTimeout(400);
      if (!(await wide())) out.noOverflow = false;
      if (shots) {
        const file = `${shots}/people-${name}-${w}.png`;
        await p.screenshot({ path: file, fullPage: true });
        out.shots.push(path.basename(file));
      }
    }
    await p.setViewportSize({ width: 1280, height: 800 });
  };
  try {
    await p.goto(launch);  // sign in the way a person does
    await p.waitForFunction(() => !location.hash.includes('launch=') && !!localStorage.length, null, { timeout: 15000 });

    await p.goto(base + '/#settings/people');
    const box = p.locator('#settings-panel-people');
    await box.getByText('Max', { exact: false }).first().waitFor({ timeout: T });
    const row = name => box.locator('[data-key^="settings-people-row-"]').filter({ hasText: name });
    check((await row('Lea').innerText()).includes('May write.'), 'Lea\'s row does not say she may write');
    check(await row('Max').getByRole('checkbox', { name: 'Decide' }).isChecked(), 'Max has no Decide tick');
    check(!(await row('Lea').getByRole('checkbox', { name: 'Decide' }).isChecked()), 'Lea has a Decide tick');
    const phones = await p.locator('[data-key="settings-people-phones"]').innerText();
    check(phones.includes('Cut off'), `Lea's phone does not show as cut off: ${phones}`);
    check(phones.includes('Max’s phone'), `Max's phone is not his: ${phones}`);
    out.steps.push('Settings > People');
    await pictures('settings');

    // O-07 (owner, 28 Nov): the whole history is on the Activity tab
    await p.goto(base + '/#ticket/' + tid + '?tab=activity');
    await p.getByText('Book the table at Rossi', { exact: false }).first().waitFor({ timeout: T });
    await p.waitForTimeout(800);
    const text = await p.locator('body').innerText();
    // each name on its own line: Max on the answer to the card, Lea on the line her text made
    const answer = await p.locator('#ticket-panel-activity .ticket-event').filter({ hasText: 'Answered a question' }).first().innerText();
    check(/Max · Answered a question/.test(answer), `the answer does not name Max: ${answer}`);
    const made = await p.locator('#ticket-panel-activity .ticket-event').filter({ hasText: 'Ticket created' }).first().innerText();
    check(/Lea · Ticket created/.test(made), `the line Lea's text made does not name her: ${made}`);
    check(!/pr_[a-z0-9]{10}/.test(text), 'the ticket shows a person id instead of a name');
    out.steps.push('ticket');
    await pictures('ticket');
  } catch (e) {
    out.errors.push(String(e && e.message || e));
    console.log(JSON.stringify(out));
    await b.close();
    process.exit(1);
  }
  console.log(JSON.stringify(out));
  await b.close();
})();

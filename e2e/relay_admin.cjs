// R18 browser half: the relay admin page done like a person, on the local relay's admin port.
// usage: PW_DIR=<node_modules folder with playwright> node relay_admin.cjs <admin url> <token file> <workspace A> <workspace B> <group> <shots dir or ''>
// Signs in with the token form, creates a group and puts A and B in it, allows A -> B under Who can do what and saves,
// then makes a phone code that can reach A. Every page is also opened at 390 wide (no sideways scrolling).
// Prints one JSON line with what it saw; the checks against the relay's admin API are the Python half's.
const { chromium } = require(require('path').join(process.env.PW_DIR, 'playwright'));
const headless = require('./headless.cjs'); // the keychain options (ORCH-615)
const fs = require('fs');
const [admin, tokenFile, A, B, group, shots] = process.argv.slice(2);
const token = fs.readFileSync(tokenFile, 'utf8').trim();

// mark the select or button that belongs to the element whose own text is `label` (a group header, a rule row)
async function markNear(p, label, selector, mark) {
  const ok = await p.evaluate(([label, selector, mark]) => {
    const own = [...document.querySelectorAll('main *')].find(el => [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim() === label));
    for (let el = own; el && el.tagName !== 'MAIN'; el = el.parentElement) {
      const hit = [...el.querySelectorAll(selector)].find(x => x.offsetParent !== null);
      if (hit) { hit.setAttribute('data-e2e', mark); return true; }
    }
    return false;
  }, [label, selector, mark]);
  if (!ok) throw new Error(`no ${selector} next to "${label}"`);
  return `[data-e2e="${mark}"]`;
}

(async () => {
  const b = await headless.launch(chromium);
  const out = { errors: [], narrow: {} };
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
  const p = await ctx.newPage();
  p.on('pageerror', e => out.errors.push(e.message));
  p.on('console', m => { if (m.type() === 'error') out.errors.push(m.text()); });
  const shot = async n => { if (shots) await p.screenshot({ path: `${shots}/r18-${n}-1440.png`, fullPage: true }); };

  // sign in the way a person does: paste the admin token into the form
  await p.goto(admin + '/admin#overview');
  const field = p.locator('input[type=password]').first();
  await field.waitFor({ timeout: 15000 });
  await field.fill(token);
  await field.press('Enter');
  await p.getByRole('link', { name: 'Groups' }).first().waitFor({ timeout: 15000 });
  out.signedIn = true;

  // Groups: create one, put both workspaces in it
  await p.goto(admin + '/admin#groups');
  await p.locator('input[name=groupName]').fill(group);  // labelled Group name or New group, by whether groups exist
  await p.getByRole('button', { name: 'Create group' }).click();
  await p.getByRole('heading', { name: new RegExp(`^${group}\\s*·`) }).waitFor({ timeout: 15000 });  // "Team · 0 workspaces"
  for (const ws of [A, B]) {
    await p.getByRole('combobox', { name: `Add a workspace to ${group}` }).selectOption({ label: ws });
    await p.getByText(`${ws} joined ${group}.`).first().waitFor({ timeout: 15000 });
  }
  out.groupDone = true;
  await shot('groups');

  // Who can do what: allow A -> B, save
  await p.goto(admin + '/admin#rules');
  await p.getByText(`${A} → ${B}`, { exact: true }).filter({ visible: true }).first().waitFor({ timeout: 15000 });
  await p.click(await markNear(p, `${A} → ${B}`, 'button', 'allow'));
  await p.getByRole('button', { name: 'Save changes' }).click();
  await p.getByText('Saved').first().waitFor({ timeout: 15000 });
  out.ruleSaved = true;
  await shot('rules');

  // Phones: a code that can reach A
  await p.goto(admin + '/admin#phones');
  await p.getByLabel('Phone name').filter({ visible: true }).first().fill('E2E phone');
  await p.getByText(A, { exact: true }).filter({ visible: true }).first().click();
  await p.getByRole('button', { name: 'Show code' }).click();
  await p.getByText('orch://pair').first().waitFor({ timeout: 15000 });
  out.pairLink = ((await p.locator('main').innerText()).match(/orch:\/\/pair\S+/) || [''])[0];
  await shot('phones');

  // the same pages at phone width: no sideways scrolling
  await p.setViewportSize({ width: 390, height: 844 });
  for (const r of ['overview', 'groups', 'rules', 'messages', 'phones', 'problems']) {
    await p.goto(admin + '/admin#' + r);
    await p.waitForTimeout(800);
    out.narrow[r] = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    if (shots) await p.screenshot({ path: `${shots}/r18-${r}-390.png`, fullPage: true });
  }
  await b.close();
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e.message); process.exit(1); });

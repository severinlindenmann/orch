// New ticket with files and parts (ORCH-891): an empty Start is refused in place; a text, two files and two parts saved
// without starting make an epic with the files and two tickets in it; the page opens on the epic and lists them; the
// unsent text of a left New ticket page (#new, ORCH-1037) comes back.
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'New ticket: files and parts make an epic, empty Start refused, unsent text kept',
  covers: ['ticket.new', 'page:ticket'],
  async run({ page, open, reload, act, must, text, orch, home }) {
    const starts = [];
    // Save without starting may send a prepare-only run (ORCH-738): that one is not a helper start
    page.on('request', r => {
      if (!r.url().endsWith('/api/act') || r.headers()['x-orch-op'] !== 'run.start') return;
      let body = {};
      try { body = JSON.parse(r.postData() || '{}'); } catch {}
      const args = body.args || body;
      if (!args.prepare) starts.push(r.url());
    });
    await open('#tickets');
    await page.getByRole('button', { name: 'New ticket' }).first().click();
    await page.waitForFunction(() => location.hash === '#new');
    let dlg = page.locator('.new-ticket-page');
    await dlg.waitFor();

    // empty: Start says what is missing and the page stays open
    await dlg.locator('button[type="submit"]').click();
    const why = await dlg.getByPlaceholder(/What should the helper do/).evaluate(el => el.validationMessage);
    must(/Describe what needs doing/.test(why), 'an empty Start does not say what is missing: ' + why);
    must(await dlg.isVisible() && (await page.evaluate(() => location.hash)) === '#new', 'an empty Start left the page');

    // a text, two files, two parts
    await dlg.getByPlaceholder(/What should the helper do/).fill('Autumn fair: everything for our stand');
    const dir = fs.mkdtempSync(path.join(home, 'files-'));
    const plan = path.join(dir, 'stand-plan.txt'), list = path.join(dir, 'packing-list.txt');
    fs.writeFileSync(plan, 'Stand 4.12, 3 x 4 m, power needed\n');
    fs.writeFileSync(list, 'Banner, flyers, coffee machine\n');
    await dlg.locator('input[type="file"]').first().setInputFiles([plan, list]);
    await dlg.getByText('stand-plan.txt').waitFor({ timeout: 10000 });
    const addPart = dlg.locator('.new-ticket-add-step');
    await addPart.click();
    await addPart.click();
    const parts = dlg.locator('.new-ticket-step textarea, .new-ticket-step input[type="text"], [class*="step"] textarea');
    must((await parts.count()) >= 2, 'two parts were not added');
    await parts.nth(0).fill('Book the stand');
    await parts.nth(1).fill('Order the banner');
    await act('ticket.new', () => dlg.getByRole('button', { name: 'Save without starting' }).click());
    await page.waitForFunction(() => /#ticket\//.test(location.hash), null, { timeout: 30000 });
    await reload();

    // the epic, its files and its two tickets, from the files on disk
    const all = JSON.parse(orch('ticket', 'list', '--all', '--json'));
    const epic = all.find(t => t.title === 'Autumn fair: everything for our stand');
    must(epic, 'no ticket was made from the text');
    must(epic.epic === true, 'the ticket with parts is not an epic');
    must(!starts.length && !epic.started && epic.status === 'open', 'Save without starting started a helper');
    must(page.url().includes(epic.id), 'the page did not open the new epic: ' + page.url());
    const kids = all.filter(t => t.parent === epic.id).map(t => t.title).sort();
    must(JSON.stringify(kids) === JSON.stringify(['Book the stand', 'Order the banner']), 'the epic\'s tickets are ' + kids.join(', '));
    const files = orch('ticket', 'artifacts', epic.id);
    must(files.includes('stand-plan.txt') && files.includes('packing-list.txt'), 'the files are not kept with the epic: ' + files);
    // the page polls: the epic's tickets may be drawn a moment after the epic itself
    const listed = await page.waitForFunction(() => {
      const t = document.querySelector('main')?.innerText || '';
      return t.includes('Parts') && t.includes('Book the stand') && t.includes('Order the banner');
    }, null, { timeout: 30000 }).then(() => true, () => false);
    const shown = await text();
    must(listed, 'the epic page does not list its tickets: ' + shown.replace(/\s+/g, ' ').slice(0, 300));
    must(shown.includes('stand-plan.txt'), 'the epic page does not show its files');

    // a left New ticket page keeps the unsent text
    await page.getByRole('button', { name: 'New ticket' }).first().click();
    await page.waitForFunction(() => location.hash === '#new');
    dlg = page.locator('.new-ticket-page');
    await dlg.getByPlaceholder(/What should the helper do/).fill('Half written thought');
    await dlg.getByRole('button', { name: 'Cancel' }).click();
    await page.waitForFunction(() => location.hash !== '#new');
    await page.getByRole('button', { name: 'New ticket' }).first().click();
    await page.waitForFunction(() => location.hash === '#new');
    dlg = page.locator('.new-ticket-page');
    must((await dlg.getByPlaceholder(/What should the helper do/).inputValue()) === 'Half written thought', 'the unsent text is gone after leaving the page');
    await dlg.getByRole('button', { name: 'Discard' }).click().catch(() => {});
    await dlg.getByRole('button', { name: 'Cancel' }).click();
  },
};

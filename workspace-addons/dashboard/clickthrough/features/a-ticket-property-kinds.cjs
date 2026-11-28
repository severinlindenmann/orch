// O-08 (owner, 28 Nov: "adding a new property is buggy"): on a test ticket a person adds every kind of property from
// "+ Add", cancels one, changes it, hits a save that fails, reloads, and takes it off again. Every kind is walked to
// its end and what breaks is collected and named (the field and what went wrong), not only the first break.
// Its first run (28 Nov, before the fixes) named 20 breaks; their causes are fixed in pages/ticket.js (propDrop,
// propChoice, propChoiceOpen, FIELD_NAME) and listed in the pull request.
// The kinds: Owner, Due, Done when (typed in place), Part of, Priority, Helper strength, Kind (a choice), Release and
// "I review the result" (a switch), Reference (a window). W-031 rides along: no "More" in the column, nothing sideways.
const idOf = out => (/\[(t_[A-Za-z0-9]+)\]/.exec(out) || [])[1];

module.exports = {
  name: 'Ticket page: add, cancel, change, fail, reload and remove every kind of property',
  covers: ['ticket.edit', 'ticket.model', 'ticket.kind', 'ref.add', 'ref.rm', 'page:ticket'],
  async run({ page, open, reload, act, must, orch, shot }) {
    const parent = idOf(orch('ticket', 'new', 'Team day in June'));
    const tid = idOf(orch('ticket', 'new', 'Order the name badges'));
    await page.setViewportSize({ width: 1280, height: 900 });
    await open('#ticket/' + tid);
    const rail = page.locator('#ticket-rail-' + tid);
    await rail.waitFor();
    const found = [];
    const note = (field, what) => { found.push(field + ': ' + what); };
    const row = key => rail.locator(`[data-key="prop-${key}-${tid}"]`);
    const menu = rail.locator(`[data-key="props-add-${tid}"]`);
    const item = key => rail.locator(`[data-key="prop-add-${key}-${tid}"]`);
    // is this property offered in + Add right now? (opens the menu, looks, closes it again)
    const offered = async key => {
      if (!(await menu.count())) return false;
      if (!(await item(key).isVisible())) await menu.locator('summary').click();
      const yes = await item(key).isVisible();
      if (await menu.evaluate(d => d.open)) await menu.locator('summary').click();
      return yes;
    };
    const add = async key => {
      for (let i = 0; i < 4; i++) {
        if (!(await item(key).isVisible())) await menu.locator('summary').click({ timeout: 5000 }).catch(() => {});
        if (await item(key).click({ timeout: 3000 }).then(() => true, () => false)) return;
      }
      throw new Error('+ Add > ' + key + ' did not take the click');
    };
    // the next save of `op` is answered "it did not work" by the server stand-in below (once)
    let failOp = null;
    await page.route('**/api/act', async route => {
      const op = route.request().headers()['x-orch-op'];
      if (failOp && op === failOp) { failOp = null; return route.fulfill({ status: 400, contentType: 'text/plain; charset=utf-8', body: 'That could not be saved just now. Try again.' }); }
      return route.continue();
    });
    const failing = (op, fn) => { failOp = op; return act(op, fn, { refused: true }); };
    const toastShown = async () => page.getByText('That could not be saved just now. Try again.').first().waitFor({ timeout: 5000 }).then(() => true, () => false);
    const words = async key => (await row(key).count()) ? (await row(key).innerText()).replace(/\s+/g, ' ').trim() : '';
    // a choice (the master select): open it, pick the option by its words
    const choose = async (key, label, option) => {
      await row(key).locator('.ui-select-trigger').click();
      await page.getByRole('option', { name: option, exact: true }).click();
    };
    const chosen = async key => (await row(key).locator('.ui-select-trigger').innerText()).trim();
    const typed = label => rail.getByLabel(label, { exact: true });
    // the page settles a moment after a save (the answer, then a redraw): wait until `ok` holds, at most 4 s
    const settled = async (read, ok) => { let v; for (let i = 0; i < 20; i++) { v = await read(); if (ok(v)) return v; await page.waitForTimeout(200); } return v; };

    // ---- Owner: typed in place
    await add('owner');
    if (!(await typed('Owner').isVisible().catch(() => false))) note('Owner', '+ Add did not open its box');
    else if (!(await typed('Owner').evaluate(n => n === document.activeElement))) note('Owner', 'its box opened without the keyboard in it');
    await page.keyboard.press('Escape');  // Cancel
    await page.waitForTimeout(300);
    if (await row('owner').count()) note('Owner', 'after Cancel an empty row stays in the column');
    if (!(await offered('owner'))) note('Owner', 'after Cancel + Add no longer offers it');
    if (await row('owner').count()) await row('owner').locator('[data-action="inline"]').click(); else await add('owner');
    await act('ticket.edit', async () => { await typed('Owner').fill('Anna'); await page.keyboard.press('Enter'); });
    if (!/Anna/.test(await settled(() => words('owner'), v => /Anna/.test(v)))) note('Owner', 'the saved name does not show: "' + (await words('owner')) + '"');
    await row('owner').locator('[data-action="inline"]').click();
    await failing('ticket.edit', async () => { await typed('Owner').fill('Bert'); await page.keyboard.press('Enter'); });
    if (!(await toastShown())) note('Owner', 'a save that failed says nothing');
    await page.waitForTimeout(300);
    if (!/Anna/.test(await words('owner')) || /Bert/.test(await words('owner'))) note('Owner', 'after a save that failed the row reads "' + (await words('owner')) + '", saved is Anna');

    // ---- Done when: a longer text typed in place
    await add('done_when');
    const dw = rail.locator(`[data-key="inline-done_when-${tid}"] textarea`);
    if (!(await dw.isVisible().catch(() => false))) note('Done when', '+ Add did not open its box');
    else {
      const label = await dw.getAttribute('aria-label');
      if (label !== 'Done when') note('Done when', 'its box is named "' + label + '" for a screen reader');
      await page.keyboard.press('Escape');
      await page.waitForTimeout(300);
      if (await row('done-when').count()) note('Done when', 'after Cancel an empty row stays in the column');
      if (!(await offered('done_when'))) note('Done when', 'after Cancel + Add no longer offers it');
      if (await row('done-when').count()) await row('done-when').locator('[data-action="inline"]').click(); else await add('done_when');
      await act('ticket.edit', async () => { await dw.fill('Every guest has a badge with the right name; ' + 'spare badges are in the box. '.repeat(8)); await page.keyboard.press('Enter'); });
      if (!/Every guest has a badge/.test(await settled(() => words('done-when'), v => /Every guest has a badge/.test(v)))) note('Done when', 'the saved text does not show');
      if (await row('done-when').getByRole('button', { name: /Show more|^More$/ }).count()) note('Done when', 'a long text is folded behind a toggle');
    }

    // ---- Due: a day from the calendar
    await add('due');
    const cal = page.locator('.cal');
    if (!(await cal.isVisible().catch(() => false))) note('Due', '+ Add did not open the calendar');
    else {
      await page.keyboard.press('Escape');
      await page.waitForTimeout(300);
      if (await row('due').count()) note('Due', 'after Cancel an empty row stays in the column');
      if (!(await offered('due'))) note('Due', 'after Cancel + Add no longer offers it');
      if (await row('due').count()) await row('due').locator('[data-action="inline"]').click(); else await add('due');
      await cal.getByRole('button', { name: 'Next month' }).click();
      await act('ticket.edit', () => cal.locator('.cal-x').nth(14).click());
      const due = await settled(() => words('due'), v => /\d/.test(v));
      if (!/\d/.test(due) || /Set a due date|Not set/.test(due)) note('Due', 'the picked day does not show: "' + due + '"');
    }
    const dueSaved = await words('due');

    // ---- the choices: Part of, Priority, Helper strength, Kind
    const CHOICES = [
      ['partOf', 'part-of', 'Part of', 'ticket.edit', /Team day in June/, 'Not part of another ticket', 'Not part of another ticket'],
      ['priority', 'priority', 'Priority', 'ticket.edit', 'High, starts first', 'Low, starts last', 'Normal'],
      ['model', 'model', 'Helper strength', 'ticket.model', 'Stronger', 'Faster', 'Auto'],
      ['kind', 'kind', 'Kind', 'ticket.kind', 'Bug', 'Other', 'Not set yet'],
    ];
    const saved = {};
    for (const [key, rowKey, label, op, first, second, unset] of CHOICES) {
      await add(key);
      await page.waitForTimeout(300);
      if (!(await row(rowKey).count())) { note(label, '+ Add did not show its row'); continue; }
      const list = page.locator('.ui-select-list:popover-open');
      if (!(await list.count())) {
        note(label, '+ Add showed the row with "' + (await chosen(rowKey)) + '" and did not open its choices (it reads as already set)');
        await row(rowKey).locator('.ui-select-trigger').click();
      } else {
        // closed without a choice: the row goes away again and + Add offers it again
        await page.keyboard.press('Escape');
        await page.waitForTimeout(300);
        if (await row(rowKey).count()) note(label, 'closed without a choice, a row that reads "' + (await chosen(rowKey)) + '" stays in the column');
        else if (!(await offered(key))) note(label, 'closed without a choice, + Add no longer offers it');
        if (await row(rowKey).count()) await row(rowKey).locator('.ui-select-trigger').click(); else await add(key);
        await list.waitFor({ timeout: 5000 }).catch(() => {});
      }
      const opt = first instanceof RegExp ? page.getByRole('option', { name: first }) : page.getByRole('option', { name: first, exact: true });
      await act(op, () => opt.first().click());
      const fits = v => (first instanceof RegExp ? first.test(v) : v === first);
      saved[rowKey] = await settled(() => chosen(rowKey), fits);
      if (!fits(saved[rowKey])) note(label, 'the saved choice does not show: "' + saved[rowKey] + '"');
      // and it stays: an older refresh landing a moment later must not flip the row back
      await page.waitForTimeout(1200);
      if ((await chosen(rowKey)) !== saved[rowKey]) note(label, 'a moment after the save the row reads "' + (await chosen(rowKey)) + '", saved is "' + saved[rowKey] + '"');
      // a save that fails: the row goes back to what is saved, and says so
      await row(rowKey).locator('.ui-select-trigger').click();
      await failing(op, () => page.getByRole('option', { name: second, exact: true }).click());
      if (!(await toastShown())) note(label, 'a save that failed says nothing');
      const after = await settled(() => chosen(rowKey), v => v === saved[rowKey]);
      if (after !== saved[rowKey]) note(label, 'after a save that failed the row reads "' + after + '", saved is "' + saved[rowKey] + '"');
      void unset;
    }

    // ---- the switches: Release (from + Add) and I review the result (always there)
    await act('ticket.edit', () => add('release'));
    const release = rail.getByRole('switch', { name: 'This ticket is a release' });
    await rail.locator('[role=switch][aria-label="This ticket is a release"][aria-checked="true"]').waitFor({ timeout: 5000 }).catch(() => {});
    if (!(await release.count()) || (await release.getAttribute('aria-checked')) !== 'true') note('Release', '+ Add did not turn it on');
    else {
      await failing('ticket.edit', () => release.click());
      if (!(await toastShown())) note('Release', 'a save that failed says nothing');
      await page.waitForTimeout(300);
      if ((await release.getAttribute('aria-checked')) !== 'true') note('Release', 'after a save that failed the switch reads off, saved is on');
    }
    const review = rail.getByRole('switch', { name: 'I review the result' });
    await act('ticket.edit', () => review.click());
    await page.waitForTimeout(300);
    if ((await review.getAttribute('aria-checked')) !== 'false') note('I review the result', 'the switch did not turn off');

    // ---- Reference: a window; Cancel first, then a real one
    await add('links');
    const win = page.locator('dialog[open]');
    if (!(await win.isVisible().catch(() => false))) note('Reference', '+ Add did not open its window');
    else {
      await win.getByRole('button', { name: 'Cancel' }).click();
      await page.waitForTimeout(300);
      const card = rail.locator('[data-key="links-card"]');
      if (await card.count() && !(await card.locator('[data-key^="ref-"]').count())) note('Reference', 'after Cancel an empty References block stays in the column');
      if (!(await card.count()) && !(await offered('links'))) note('Reference', 'after Cancel + Add no longer offers it');
      if (await card.count()) await card.locator('[data-action="link-add"]').click(); else await add('links');
      await win.getByPlaceholder(/Search tickets/).fill('Team day in June');
      await win.getByRole('button', { name: /Team day in June/ }).click();
      await act('ref.add', () => win.getByRole('button', { name: 'Add', exact: true }).click());
    }

    // ---- W-031: the column as a whole
    const col = await rail.evaluate(n => ({ sideways: n.scrollWidth - n.clientWidth,
      wide: [...n.querySelectorAll('*')].filter(e => e.getBoundingClientRect().right > n.getBoundingClientRect().left + n.clientWidth + 1).map(e => e.tagName.toLowerCase() + '.' + String(e.className).split(' ').join('.') + ' +' + Math.round(e.getBoundingClientRect().right - n.getBoundingClientRect().left - n.clientWidth)).slice(0, 12), more: [...n.querySelectorAll('summary')].map(s => s.textContent.trim()).filter(t => /^(More|Show more)$/.test(t)).length,
      beside: [...n.querySelectorAll('dl > div')].filter(d => { const dt = d.querySelector('dt'), dd = d.querySelector('dd'); return dt && dd && !dd.querySelector('.switch') && Math.abs(dt.getBoundingClientRect().top - dd.getBoundingClientRect().top) < 4; }).map(d => d.querySelector('dt').textContent.trim()) }));
    if (col.sideways > 1) note('Properties', 'the column scrolls ' + col.sideways + ' px sideways (' + col.wide.join(', ') + ')');
    if (col.more) note('Properties', 'a "More" toggle is in the column');
    if (col.beside.length) note('Properties', 'these labels sit beside their value, not above it: ' + col.beside.join(', '));
    await shot('properties-filled', rail);

    // ---- reload: what is saved is what shows
    await reload();
    await rail.waitFor();
    await page.waitForTimeout(500);
    if (!/Anna/.test(await words('owner'))) note('Owner', 'gone after a reload');
    if (!/Every guest has a badge/.test(await words('done-when'))) note('Done when', 'gone after a reload');
    if (dueSaved && (await words('due')) !== dueSaved) note('Due', 'reads "' + (await words('due')) + '" after a reload, was "' + dueSaved + '"');
    for (const [, rowKey, label] of CHOICES) {
      if (!saved[rowKey]) continue;
      const now = (await row(rowKey).count()) ? await chosen(rowKey) : '(no row)';
      if (now !== saved[rowKey]) note(label, 'reads "' + now + '" after a reload, saved was "' + saved[rowKey] + '"');
    }
    if ((await rail.getByRole('switch', { name: 'This ticket is a release' }).getAttribute('aria-checked').catch(() => null)) !== 'true') note('Release', 'off after a reload');
    if ((await rail.getByRole('switch', { name: 'I review the result' }).getAttribute('aria-checked')) !== 'false') note('I review the result', 'on again after a reload');
    if (!(await rail.locator('[data-key="links-card"]').getByText('Team day in June').count())) note('Reference', 'gone after a reload');

    // ---- take them off again: empty the typed ones, the first choice of each list, the switches, the reference
    await row('owner').locator('[data-action="inline"]').click();
    await act('ticket.edit', async () => { await typed('Owner').fill(''); await page.keyboard.press('Enter'); });
    await row('done-when').locator('[data-action="inline"]').click();
    await act('ticket.edit', async () => { await rail.locator(`[data-key="inline-done_when-${tid}"] textarea`).fill(''); await page.keyboard.press('Enter'); });
    if (await row('due').count()) {
      await row('due').locator('[data-action="inline"]').click();
      await act('ticket.edit', () => page.locator('.cal').getByRole('button', { name: /^(Clear|No date)/ }).click());
    }
    for (const [, rowKey, label, op, , , unset] of CHOICES) {
      if (rowKey === 'kind' || !(await row(rowKey).count())) continue;  // a kind is changed, never taken off
      await row(rowKey).locator('.ui-select-trigger').click();
      await act(op, () => page.getByRole('option', { name: unset, exact: true }).click());
      void label;
    }
    await act('ticket.edit', () => rail.getByRole('switch', { name: 'This ticket is a release' }).click());
    await act('ticket.edit', () => rail.getByRole('switch', { name: 'I review the result' }).click());
    await act('ref.rm', () => rail.getByRole('button', { name: /Remove reference/ }).first().click());
    await reload();
    await rail.waitFor();
    await page.waitForTimeout(500);
    for (const [key, rowKey, label] of [['owner', 'owner', 'Owner'], ['done_when', 'done-when', 'Done when'], ['due', 'due', 'Due'], ['partOf', 'part-of', 'Part of'], ['priority', 'priority', 'Priority'], ['model', 'model', 'Helper strength'], ['release', 'release', 'Release']]) {
      if (await row(rowKey).count()) note(label, 'still in the column after it was taken off and the page reloaded: "' + (await words(rowKey)) + '"');
      else if (!(await offered(key))) note(label, 'taken off, but + Add does not offer it again');
    }
    if ((await rail.getByRole('switch', { name: 'I review the result' }).getAttribute('aria-checked')) !== 'true') note('I review the result', 'did not turn on again');
    if (await rail.getByRole('button', { name: /Remove reference/ }).count()) note('Reference', 'still there after it was removed and the page reloaded');
    void parent;
    must(!found.length, found.length + (found.length === 1 ? ' thing breaks' : ' things break') + ' when properties are added and removed:\n        - ' + found.join('\n        - '));
  },
};

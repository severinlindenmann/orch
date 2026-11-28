// The Tickets list and Board after the walk of 28 Nov:
// - O-13 (ORCH-2438): every status group opens and closes three times in a row, the rows come back each time, also
//   right after a reload and while a search is on.
// - O-15 C: no button on a row or on a group line; each row ends in one state mark, all marks in one column.
// - O-14 D (ORCH-2439): Top tickets only (off at first) hides sub-tickets; the epic opens its ticket; with it off a
//   sub-ticket says what it is part of.
// - O-16 C: a Board card is two lines with its state icon top right (with a word for screen readers) and the name of
//   what it is part of; the card opens the ticket.
// - W-022 C: under 900 px of page area the list is compact two-line rows with the mark at the right edge; nothing
//   scrolls sideways (also at 390 and 320).
const idOf = out => (/\[(t_[A-Za-z0-9]+)\]/.exec(out) || [])[1];

module.exports = {
  name: 'Tickets list: groups fold three times, state marks, Top tickets only, compact rows, two-line Board cards',
  covers: ['page:tickets'],
  async run({ page, open, reload, must, orch, orchAsPerson, until, shot }) {
    const epic = idOf(orch('ticket', 'new', 'Walk list: summer party', '--epic'));
    const kids = ['Walk list: book the garden', 'Walk list: order the cake for the summer party with the long name that never fits one line'].map(t => idOf(orch('ticket', 'new', t, '--parent', epic)));
    const asked = idOf(orch('ticket', 'new', 'Walk list: pick the music'));
    orch('ask', asked, 'Jazz or pop for the party?', '--option', 'Jazz', '--option', 'Pop');
    const result = idOf(orchAsPerson('ticket', 'new', 'Walk list: print the invitations'));
    orchAsPerson('ticket', 'status', result, 'review');
    orchAsPerson('ticket', 'status', kids[0], 'active');  // a sub-ticket in another status group than its epic
    await page.setViewportSize({ width: 1440, height: 900 });
    await open('#tickets?layout=list');
    await until(s => [epic, ...kids, asked, result].every(id => (s.tickets || []).some(t => t.id === id)), 'the seeded tickets');
    await reload();
    const rows = () => page.locator('table tr[data-key^="tree-"]').count();
    const toggles = page.locator('table button.group-toggle');
    await toggles.first().waitFor({ timeout: 15000 });

    // O-13: three times each, then again after a reload and with a search on
    const foldAll = async when => {
      const keys = await toggles.evaluateAll(list => list.map(b => b.dataset.key));
      must(keys.length >= 2, 'fewer than two groups in the list (' + when + ')');
      for (const key of keys) {
        const t = page.locator(`table button[data-key="${key}"]`);
        if (await t.getAttribute('aria-expanded') !== 'true') { await t.click(); await page.waitForTimeout(120); }  // a group that starts folded (Done) is opened first
        const full = await rows();
        for (let i = 1; i <= 3; i++) {
          await t.click();
          await page.waitForTimeout(120);
          must(await t.getAttribute('aria-expanded') === 'false', `${key} did not close on click ${i} (${when})`);
          const less = await rows();
          must(less < full, `${key} closed but its rows stayed, click ${i} (${when}): ${less} of ${full}`);
          await t.click();
          await page.waitForTimeout(120);
          must(await t.getAttribute('aria-expanded') === 'true', `${key} did not open again on click ${i} (${when})`);
          must(await rows() === full, `${key} opened but ${full - await rows()} rows did not come back, click ${i} (${when})`);
        }
      }
    };
    await foldAll('first');
    await reload();
    await toggles.first().waitFor();
    await foldAll('after a reload');
    // right after the list refreshed itself: a change arrives while the page is open
    orch('ticket', 'new', 'Walk list: one more ticket');
    await until(s => (s.tickets || []).some(t => t.title === 'Walk list: one more ticket'), 'the list refreshed itself');
    await foldAll('after the list refreshed itself');
    const search = page.getByRole('searchbox', { name: 'Search tickets' });
    await search.fill('Walk list');
    await page.waitForTimeout(400);
    await foldAll('with a search on');
    await search.fill('');
    await page.waitForTimeout(400);

    // O-15 C: no row or group button; one mark per row, in one column
    const list = await page.evaluate(() => {
      const trs = [...document.querySelectorAll('table tr[data-key^="tree-"]')];
      const marks = trs.map(tr => tr.querySelector('td.ticket-mark .pill')).filter(Boolean);
      return { rows: trs.length, marks: marks.length, lefts: [...new Set(marks.map(m => Math.round(m.getBoundingClientRect().left)))],
        words: [...new Set(marks.map(m => m.innerText.trim()))],
        rowButtons: trs.flatMap(tr => [...tr.querySelectorAll('button, a.btn')]).map(b => (b.innerText || b.getAttribute('aria-label') || '').trim()).filter(w => /^(Answer|Test results|Start|Review|Open)/.test(w)),
        groupButtons: [...document.querySelectorAll('table tr.group-row button:not(.group-toggle), table tr.group-row a.btn')].map(b => b.innerText.trim()) };
    });
    must(list.rows > 3 && list.marks === list.rows, `not every row ends in a state mark: ${list.marks} of ${list.rows}`);
    must(list.lefts.length === 1, 'the state marks do not stand in one line: left edges ' + list.lefts.join(', '));
    must(!list.rowButtons.length, 'a row still has a button: ' + list.rowButtons.join(', '));
    must(!list.groupButtons.length, 'a group line still has a button: ' + list.groupButtons.join(', '));
    must(list.words.includes('Question') && list.words.includes('Result'), 'the marks do not say Question and Result: ' + list.words.join(', '));
    await shot('list');
    // the row opens the ticket at its question
    await page.locator(`table tr[data-key="tree-${asked}"] a`).first().click();
    await page.waitForFunction(() => /^#ticket\//.test(location.hash), null, { timeout: 10000 });
    await page.getByText('Jazz or pop for the party?').first().waitFor({ timeout: 15000 });

    // O-14 D: Top tickets only
    await open('#tickets?layout=list');
    const top = page.locator('[data-key="ticket-top"]');
    await top.waitFor();
    must(!/top=1/.test(page.url()) && await top.getAttribute('aria-checked') !== 'true', 'Top tickets only is on before anybody chose it');
    const row = id => page.locator(`table tr[data-key="tree-${id}"]`);
    must(await row(kids[0]).count() === 1, 'a sub-ticket is missing from the normal list');
    must(/summer party/.test(await row(kids[0]).innerText()), 'a sub-ticket in another status group does not name what it is part of: ' + await row(kids[0]).innerText());
    await top.click();
    await page.waitForFunction(() => /top=1/.test(location.hash), null, { timeout: 10000 });
    await row(kids[0]).waitFor({ state: 'detached', timeout: 10000 }).catch(() => {});
    must(await row(kids[0]).count() === 0 && await row(kids[1]).count() === 0, 'Top tickets only still lists sub-tickets');
    must(await row(epic).count() === 1 && await row(asked).count() === 1, 'Top tickets only hides an epic or a ticket that stands alone');
    must(/2 sub-tickets|2 tickets|2 parts/.test(await row(epic).innerText()), 'the epic does not say what is inside it: ' + await row(epic).innerText());
    await shot('top-only');
    await reload();
    await row(epic).waitFor({ timeout: 15000 });
    must(await row(kids[0]).count() === 0, 'Top tickets only is gone after a reload');
    await row(epic).locator('a').first().click();
    await page.waitForFunction(() => /^#ticket\//.test(location.hash), null, { timeout: 10000 });
    await page.getByText('Walk list: book the garden').first().waitFor({ timeout: 15000 });  // the epic's own page lists its sub-tickets

    // O-16 C: the Board, still Top tickets only, then all
    await open('#tickets?layout=board&top=1');
    await page.locator(`[data-key="card-${epic}"]`).waitFor({ timeout: 15000 });
    must(await page.locator(`[data-key="card-${kids[0]}"]`).count() === 0, 'the Board with Top tickets only still shows a sub-ticket');
    await open('#tickets?layout=board');
    const card = page.locator(`[data-key="card-${kids[1]}"]`);
    await card.waitFor({ timeout: 15000 });
    const tile = await card.evaluate(el => {
      const title = el.querySelector('.tile-title'), state = el.querySelector('[data-key^="state-"]'), r = el.getBoundingClientRect(), s = state?.getBoundingClientRect();
      return { height: Math.round(r.height), titleLines: Math.round(title.getBoundingClientRect().height / parseFloat(getComputedStyle(title).lineHeight)),
        word: state?.getAttribute('aria-label') || '', topRight: !!s && s.top - r.top < r.height / 2 && r.right - s.right < 24, partOf: el.querySelector('.tile-part-of')?.innerText || '',
        buttons: [...el.querySelectorAll('button, a.btn')].map(b => b.innerText.trim()).filter(w => /^(Answer|Test results|Start)/.test(w)), full: el.querySelector('.tile-title a')?.title || '' };
    });
    must(tile.titleLines === 1 && tile.height <= 72, 'a Board card is not two lines: ' + JSON.stringify(tile));
    must(tile.word && tile.topRight, 'a Board card has no state icon with a word in its top right corner: ' + JSON.stringify(tile));
    must(/summer party/.test(tile.partOf), 'a sub-ticket card does not name what it is part of: ' + JSON.stringify(tile));
    must(!tile.buttons.length, 'a Board card still has a button: ' + tile.buttons.join(', '));
    must(/never fits one line/.test(tile.full), 'the cut title has no full title to read: ' + tile.full);
    await shot('board');
    await card.locator('.tile-foot').click({ position: { x: 4, y: 4 } }).catch(() => card.click());
    await page.waitForFunction(() => /^#ticket\//.test(location.hash), null, { timeout: 10000 });
    await page.getByText('never fits one line').first().waitFor({ timeout: 15000 });  // the full title on the ticket

    // W-022 C: the compact rows under 900 px of page area, and the phone widths
    for (const [width, height] of [[860, 800], [390, 844], [320, 700]]) {
      await page.setViewportSize({ width, height });
      await open('#tickets?layout=list');
      await page.locator('.short-group').first().waitFor({ timeout: 15000 });
      const fit = await page.evaluate(() => {
        const vw = window.innerWidth, m = document.querySelector('main');
        const table = m.querySelector('table.ticket-table'), shown = table && table.getBoundingClientRect().width > 0;
        const short = [...m.querySelectorAll('.short-group .short-row')].filter(r => r.getBoundingClientRect().width);
        return { page: document.documentElement.scrollWidth - vw, sideways: m.scrollWidth - m.clientWidth, table: !!shown, rows: short.length,
          marks: short.filter(r => { const p = r.querySelector('.pill'); return p && p.getBoundingClientRect().right <= vw; }).length,
          buttons: short.flatMap(r => [...r.querySelectorAll('button, a.btn')]).map(b => b.innerText.trim()).filter(w => /^(Answer|Test results|Start)/.test(w)) };
      });
      must(!fit.table, `at ${width} the wide table is still drawn`);
      must(fit.page <= 1 && fit.sideways <= 1, `at ${width} the list scrolls sideways: ` + JSON.stringify(fit));
      must(fit.rows > 3 && fit.marks === fit.rows, `at ${width} not every compact row ends in a state mark in view: ` + JSON.stringify(fit));
      must(!fit.buttons.length, `at ${width} a compact row has a button: ` + fit.buttons.join(', '));
      if (width === 860) await page.screenshot({ path: (process.env.CLICKTHROUGH_SHOT_860 || '/dev/null') }).catch(() => {});
    }
    await page.setViewportSize({ width: 1280, height: 900 });
    await open('#tickets?layout=list');
    orchAsPerson('answer', asked, 'q1', 'Jazz');  // leave nothing open for the click-throughs after this one
    orchAsPerson('ticket', 'status', result, 'done');
  },
};

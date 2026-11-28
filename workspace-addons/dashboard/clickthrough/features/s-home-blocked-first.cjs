// Home after the walk of 28 Nov (O-01 D, ORCH-2433): blocked work first, each one line with one action; questions
// and results are never rows or cards on Home, only one line that opens Review; a ticket the Reviewer left for the
// person is on Review too; a finished ticket is one title and one short result on one line. Checked at 1440, 1920,
// 390 and 320 (no page scrolls sideways, nothing runs past the right edge).
module.exports = {
  name: 'Home: blocked work first, one line to Review, finished titles',
  covers: ['page:home'],
  async run({ page, open, reload, must, orch, orchAsPerson, python, workspace, until, shot }) {
    // every other open question is answered or taken back first, so the Review line counts what this walk makes
    for (const t of JSON.parse(orch('ticket', 'list', '--json'))) {
      for (const q of t.questions || []) {
        if (q.answer != null) continue;
        try { orchAsPerson('answer', t.id, q.id, q.recommended || (q.options || [])[0] || 'OK'); }
        catch (_) { try { orch('ask', t.id, 'Not needed for this click-through.', '--take-back', q.id); } catch (_e) { /* a card stays */ } }
      }
    }
    const asked = JSON.parse(orch('ticket', 'new', 'Blocked walk: pick the banner colour', '--json')).id;
    orch('ask', asked, 'Which colour should the summer banner have?', '--option', 'Sea blue', '--option', 'Sun yellow', '--recommend', 'Sea blue');
    const left = JSON.parse(orchAsPerson('ticket', 'new', 'Blocked walk: paint the meeting room', '--json')).id;
    orchAsPerson('ticket', 'status', left, 'review');
    // what the Reviewer's pass keeps when it leaves a ticket for the person (orch/reviewer.py remember_left)
    python('import json, sys; from pathlib import Path; from orch import runs\n' +
      'p = runs.run_dir(Path(sys.argv[1])) / "reviewer.json"; p.parent.mkdir(parents=True, exist_ok=True)\n' +
      'd = json.loads(p.read_text()) if p.exists() else {}\n' +
      'd[sys.argv[2]] = {"left": "too big for a small fix (25 files, 4070 lines; small is 10 and 300)."}\n' +
      'p.write_text(json.dumps(d))', workspace, left);
    const done = JSON.parse(orchAsPerson('ticket', 'new', 'Blocked walk: order new chairs for the meeting room after the paint has dried and the old ones are gone', '--json')).id;
    orch('check', 'add', done, 'Order them');
    orch('check', 'done', done, 'c1', '--summary', 'Twelve chairs ordered, they arrive on Friday.', '--note', 'From the supplier.');
    orchAsPerson('ticket', 'status', done, 'done');
    // a tool that stopped working: the one kind of blocked row a click-through can make without a helper
    orchAsPerson('logins', 'add', 'portal', '--command', 'false', '--label', 'Team portal', '--how', 'Log in to the team portal in your browser.');
    orchAsPerson('logins');

    await open('#home');
    await until(s => (s.logins?.items || []).some(i => i.name === 'portal') && (s.needs || []).some(n => n.ticket === asked), 'the stopped tool and the question in the page state');
    await reload();
    const blocked = page.locator('[data-key="blocked"]');
    const row = blocked.locator('[data-key="login-stopped-portal"]');
    await row.waitFor({ timeout: 15000 });
    const said = await row.innerText();
    must(/Team portal .*(stopped working|cannot be reached)/.test(said), 'the blocked row does not say what stopped: ' + said);
    must(!/terminal|this computer/i.test(said), 'the blocked row sends the person to a terminal: ' + said);
    must(await row.locator('button, a.btn').count() === 1, 'a blocked row has more or less than one action: ' + said);
    must(/^Blocked now/.test(await blocked.innerText()), 'the first card is not Blocked now');

    const main = await page.locator('main').innerText();
    must(!/Which colour should the summer banner have|Sea blue|Sun yellow/.test(main), 'a question or its answers are drawn on Home');
    must(!/paint the meeting room/.test(main), 'a result to review (the Reviewer left it) is a row on Home');
    must(await page.locator('main [data-need-row^="core:q:"], main .answer-option').count() === 0, 'Home has a question card');
    const line = page.locator('[data-key="review-line"]');
    must(/\d+ .*waits? in Review/.test(await line.innerText()), 'no line that says what waits in Review: ' + await line.innerText());

    const fin = page.locator(`[data-key="finished-today"] [data-key="ticket-${done}"]`);
    await fin.waitFor();
    must(/Twelve chairs ordered, they arrive on Friday\. From the supplier\./.test(await fin.innerText()), 'the finished row has no result: ' + await fin.innerText());
    must(await page.locator('[data-key="finished-today"] [data-key^="ticket-"]').count() <= 5, 'Finished shows more than five tickets');
    must(await page.locator('[data-key="what-changed"], [data-key="in-progress"], [data-key="not-started"]').count() === 0, 'Home still has a card the walk removed');
    must(await page.locator('[data-key="tiles"] .stat-tile').count() === 0 && await page.locator('[data-key="tiles"] [data-key^="tile-"]').count() === 4, 'the numbers are not one row of four');

    const order = await page.evaluate(() => ['blocked', 'review-line', 'tiles', 'finished-today'].map(k => document.querySelector(`main [data-key="${k}"]`).getBoundingClientRect().top));
    must(order.every((y, i) => !i || y > order[i - 1]), 'the order is not blocked work, Review line, numbers, Finished: ' + order.join(', '));

    for (const [width, height] of [[1440, 900], [1920, 1080], [390, 844], [320, 700]]) {
      await page.setViewportSize({ width, height });
      await open('#home');
      await fin.waitFor();
      const fit = await page.evaluate(() => {
        const vw = window.innerWidth, m = document.querySelector('main');
        // what a one-line title or result cuts with … is inside its own box; the box itself must fit
        const over = [...m.querySelectorAll('h1, h2, h3, p, a, button, span')].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.right > vw + 1 && !e.parentElement.closest('.truncate'); })
          .map(e => e.tagName + ' "' + (e.innerText || '').trim().slice(0, 40) + '"');
        const row = m.querySelector('.home-finished'), title = row.querySelector('h3'), numbers = m.querySelector('[data-key="tiles"]');
        return { over, page: document.documentElement.scrollWidth - vw, rowHeight: row.getBoundingClientRect().height, titleLines: Math.round(title.getBoundingClientRect().height / parseFloat(getComputedStyle(title).lineHeight)),
          numbersHeight: numbers.getBoundingClientRect().height };
      });
      must(!fit.over.length, `at ${width} something on Home runs past the right edge: ` + fit.over.slice(0, 5).join(', '));
      must(fit.page <= 1, `at ${width} Home is ${fit.page} px wider than the window`);
      must(fit.titleLines === 1, `at ${width} a finished title takes ${fit.titleLines} lines: ` + JSON.stringify(fit));
      if (width >= 1440) must(fit.numbersHeight < 40, `at ${width} the numbers are not one row (${fit.numbersHeight} px high)`);
    }
    await page.setViewportSize({ width: 1280, height: 900 });
    await open('#home');
    await fin.waitFor();
    await shot('home');

    // the one line opens Review, where the question and the Reviewer's ticket are
    await line.getByRole('link', { name: 'Open Review' }).click();
    await page.waitForFunction(() => location.hash.startsWith('#review'), null, { timeout: 10000 });
    await page.getByText('Which colour should the summer banner have?').first().waitFor({ timeout: 15000 });

    // the blocked row's one action leads to the place that fixes it
    await open('#home');
    await row.locator('button, a.btn').click();
    if (/Sign in/.test(said)) await page.waitForFunction(() => location.hash.startsWith('#settings'), null, { timeout: 10000 });

    orchAsPerson('logins', 'remove', 'portal');   // leave the workspace as it was for the next click-through
    orchAsPerson('logins');
    orchAsPerson('answer', asked, 'q1', 'Sea blue');
    orchAsPerson('ticket', 'status', left, 'done');
  },
};

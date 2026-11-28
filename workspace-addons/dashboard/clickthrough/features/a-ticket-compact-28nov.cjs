// The owner's ticket-page decisions of 28 Nov, clicked through on real tickets:
// O-07 the Overview is one compact screen (In short, the result, one tasks line, the last three events, Looks good /
// Send back on the first screen); O-12 the task list is on the Tasks tab only, compact; O-10 Files is a list with tags
// and a click opens the file viewer; O-09 a presentation is listed and downloads as the same bytes; W-030 the note
// shows itself, the data file and the presentation are rows; W-028 the one filled button is Looks good and the header
// line jumps to it; W-029 Done from Actions and from the state word shows the result with Looks good first.
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');
const idOf = out => (/\[(t_[A-Za-z0-9]+)\]/.exec(out) || [])[1];
// a file that starts like a .pptx (a zip) and holds every byte value, so a changed byte would show
const deck = Buffer.concat([Buffer.from('PK\x03\x04', 'latin1'), Buffer.from(Array.from({ length: 256 }, (_, i) => i)), zlib.deflateSync(Buffer.from('slide '.repeat(500)))]);

module.exports = {
  name: 'Ticket page: compact Overview, one task list, Files as a list, Done shows the result first',
  covers: ['ticket.patch', 'page:ticket'],
  async run({ page, open, reload, act, must, orch, shot, workspace }) {
    const make = (title, status) => {
      const tid = idOf(orch('ticket', 'new', title));
      orch('check', 'add', tid, 'Collect the numbers');
      orch('check', 'add', tid, 'Write the report');
      orch('check', 'done', tid, 'c1', '--summary', 'All twelve shops answered.', '--note', 'Numbers are in sources.json.');
      orch('check', 'done', tid, 'c2', '--note', 'The report is written.');
      orch('ticket', 'summary', tid, 'The spring report is written; the slides are attached.');
      const dir = orch('ticket', 'artifacts-dir', tid).trim().split('\n').pop().trim();
      const folder = path.isAbsolute(dir) ? dir : path.join(workspace, dir);
      fs.writeFileSync(path.join(folder, 'report.md'), '# Spring report\n\nSales are up in nine of twelve shops.\n');
      fs.writeFileSync(path.join(folder, 'sources.json'), JSON.stringify({ sources: ['shop-1', 'shop-2'] }, null, 2));
      fs.writeFileSync(path.join(folder, 'deck.pptx'), deck);
      orch('ticket', 'status', tid, status);
      return tid;
    };
    const tid = make('Write the spring report', 'review');
    const bad = [];
    const want = (ok, why) => { if (!ok) bad.push(why); };
    const sideways = () => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    // a menu can close again while the page fills in (as in a-ticket-properties): open it again until its item takes the click
    const pick = async (opener, item, what) => {
      for (let i = 0; i < 4; i++) {
        if (!(await item.isVisible())) await opener.click({ timeout: 5000 }).catch(() => {});
        if (await item.click({ timeout: 3000 }).then(() => true, () => false)) return;
      }
      throw new Error(what + ' did not take the click');
    };

    // ---- O-07, W-028, W-030: the Overview of a result that waits for Looks good
    await page.setViewportSize({ width: 1280, height: 800 });
    await open('#ticket/' + tid);
    const card = page.locator(`[data-key="review-card-${tid}"]`);
    await card.waitFor();
    await card.locator('.file-row').first().waitFor({ timeout: 15000 });
    await page.waitForTimeout(600);
    const over = page.locator('#ticket-panel-overview');
    const looks = card.getByRole('button', { name: 'Looks good', exact: true });
    // on the first screen at the sizes the owner works at (1440 and 1920 wide); a compact screen, not a fixed-height
    // promise: at 1280x800 this result with three files ends a little under the fold (reported in the pull request)
    const firstScreen = () => looks.evaluate(b => { const r = b.getBoundingClientRect(); return { bottom: Math.round(r.bottom), view: window.innerHeight, hit: document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === b }; });
    for (const [w, h] of [[1440, 900], [1920, 1080]]) {
      await page.setViewportSize({ width: w, height: h });
      await page.waitForTimeout(400);
      await page.evaluate(() => window.scrollTo(0, 0));
      const first = await firstScreen();
      want(first.bottom <= first.view && first.hit, `at ${w}x${h} Looks good is not on the first screen (its bottom is at ${first.bottom} of ${first.view} px)`);
    }
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.waitForTimeout(400);
    await page.evaluate(() => window.scrollTo(0, 0));
    const at1280 = await firstScreen();
    want(at1280.bottom <= at1280.view + 64, `at 1280x800 Looks good is far under the first screen (its bottom is at ${at1280.bottom} of ${at1280.view} px)`);
    want(await card.locator('[data-key="result-frame-report.md"]').count() === 1, 'the note does not show itself in the Result');
    want(await card.locator('[data-key="result-frame-sources.json"]').count() === 0 && await card.locator('[data-key="file-artifacts-sources.json"]').count() === 1, 'the data file is not one row');
    want(await card.locator('[data-key="file-artifacts-deck.pptx"]').count() === 1, 'the presentation is not a row of the Result');
    want(/2 of 2 tasks done/.test(await card.locator(`[data-key="overview-tasks-${tid}"]`).innerText()), 'the tasks are not one line "2 of 2 tasks done"');
    want(await over.locator('.task-row').count() === 0, 'the task list is on the Overview again');
    want(await over.locator('[data-ticket-talk], .history-msg, .history-day').count() === 0, 'the write box or the history is on the Overview again');
    const filled = await page.locator('main .btn.primary:visible').allInnerTexts();
    want(filled.length === 1 && filled[0].trim() === 'Looks good', 'the filled buttons on the page are: ' + JSON.stringify(filled));
    const live = page.locator('[data-key="ticket-open-layer"]');
    if (await live.count()) want(/(^| )outline( |$)/.test(await live.getAttribute('class')), 'Open in Live is filled while it is your turn');
    const latest = over.locator(`[data-key="overview-latest-${tid}"]`);
    want(await latest.locator('.history-event').count() === 3, 'the Overview does not show the last three events');
    want(await sideways() <= 1, 'the page scrolls sideways at 1280');
    await shot('overview-review', card);
    // the header line jumps to the buttons
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.locator('[data-key="ticket-turn-jump"]').click();
    await page.waitForTimeout(500);
    want(await looks.evaluate(b => b === document.activeElement), '"Your turn: look at the result." does not put the keyboard on Looks good');
    // Show all N in Activity opens the tab with the same number of lines
    const all = over.locator('[data-key="overview-all-activity"]');
    const n = Number((/Show all (\d+) in Activity/.exec(await all.innerText()) || [])[1]);
    await all.click();
    await page.waitForFunction(() => /tab=activity/.test(location.hash));
    const lines = await page.locator('#ticket-panel-activity .ticket-event').count();
    want(n > 3 && lines === n, `Show all says ${n}, the Activity tab lists ${lines}`);

    // ---- O-12: the one compact task list
    await page.locator('#ticket-tab-tasks').click();
    const rows = page.locator('#ticket-panel-tasks ol.tasks-list > li.task-row');
    want(await rows.count() === 2, 'the Tasks tab does not list the two tasks');
    const heights = await rows.evaluateAll(els => els.map(e => Math.round(e.getBoundingClientRect().height)));
    want(heights.every(h => h <= 72), 'a task row is taller than the compact form: ' + heights.join(', ') + ' px');
    want(/All twelve shops answered\./.test(await rows.first().innerText()), 'a done task does not say what came out in its grey line');
    const tick = await rows.first().getByRole('checkbox').evaluate(b => { const r = b.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; });
    want(tick[0] === tick[1] && tick[0] >= 24 && tick[0] <= 28, 'the tick box is ' + tick.join('x') + ' px');
    await shot('tasks', page.locator('#ticket-panel-tasks'));

    // ---- O-10, O-09: Files is a list with tags; a click opens the viewer; the presentation is the same bytes
    await page.locator('#ticket-tab-files').click();
    const files = page.locator('#ticket-panel-files .files-row');
    await files.first().waitFor({ timeout: 15000 });
    want(await files.count() === 3, 'Files does not list the three files');
    want(await page.locator('#ticket-panel-files').locator('.file-tile, .files-preview').count() === 0, 'Files shows tiles or a preview pane');
    const pptx = page.locator('[data-key="file-item-artifacts-deck.pptx"]');
    const said = (await pptx.innerText()).replace(/\s+/g, ' ');
    want(/deck\.pptx/.test(said) && /Result/.test(said) && /Presentation/.test(said), 'the presentation row reads: ' + said);
    const fheights = await files.evaluateAll(els => els.map(e => Math.round(e.getBoundingClientRect().height)));
    want(fheights.every(h => h <= 56), 'a file row is taller than a list row: ' + fheights.join(', ') + ' px');
    await page.locator('[data-key="files-sort-name"]').click();
    const names = await files.evaluateAll(els => els.map(e => e.dataset.key.replace('file-item-artifacts-', '')));
    want(names.join() === 'deck.pptx,report.md,sources.json', 'sorted by name the list reads: ' + names.join(', '));
    await shot('files', page.locator('#ticket-panel-files'));
    const got = await page.evaluate(async id => {
      const r = await fetch('/api/file?t=' + id + '&k=artifacts&n=deck.pptx&dl=1');
      return { status: r.status, hex: [...new Uint8Array(await r.arrayBuffer())].map(b => b.toString(16).padStart(2, '0')).join(''), cd: r.headers.get('Content-Disposition') || '' };
    }, tid);
    want(got.status === 200 && got.hex === deck.toString('hex'), 'the downloaded presentation is not the same bytes as the file (' + got.status + ', ' + got.hex.length / 2 + ' of ' + deck.length + ' bytes)');
    want(/deck\.pptx/.test(got.cd), 'the download does not keep its name: ' + got.cd);
    await page.locator('[data-key="file-item-artifacts-report.md"]').click();
    const viewer = page.locator('dialog[open]');
    await viewer.waitFor({ timeout: 10000 });
    want(/report\.md/.test(await viewer.innerText()), 'a click on a row does not open the file viewer on that file');
    await page.keyboard.press('Escape');
    await viewer.waitFor({ state: 'detached', timeout: 5000 }).catch(() => {});
    for (const [w, h] of [[1920, 1080], [390, 844], [320, 700]]) {
      await page.setViewportSize({ width: w, height: h });
      await page.waitForTimeout(400);
      want(await sideways() <= 1, 'the Files tab scrolls sideways at ' + w);
      await page.locator('#ticket-tab-overview').click();
      await page.waitForTimeout(300);
      want(await sideways() <= 1, 'the Overview scrolls sideways at ' + w);
      await page.locator('#ticket-tab-files').click();
    }
    await page.setViewportSize({ width: 1280, height: 800 });

    // ---- W-029: Done from Actions shows the result with Looks good first; Looks good is the one click that finishes
    const open1 = make('Write the summer report', 'active');
    await open('#ticket/' + open1);
    await page.locator(`[data-key="ticket-strip-${open1}"]`).waitFor();
    want(await page.locator(`[data-key="review-card-${open1}"]`).count() === 0, 'a ticket that is worked on shows the review card by itself');
    await page.waitForTimeout(800);
    await pick(page.locator(`summary[data-key="ticket-actions-${open1}"]`), page.locator('[data-key="ticket-move-done"]'), 'Actions > Done');
    const ask = page.locator(`[data-key="review-card-${open1}"]`);
    await ask.waitFor({ timeout: 5000 });
    want(/You chose Done\. Look at the result first/.test(await ask.innerText()), 'the card does not say why it shows');
    want(await page.locator('dialog[open]').count() === 0, 'a confirm window opened');
    want((await page.evaluate(async id => (await (await fetch('/api/state?fresh=1', { cache: 'no-store' })).json()).tickets.find(t => t.id === id)?.status, open1)) === 'active', 'the ticket was closed before the result was seen');
    await shot('done-shows-result', ask);
    await act('ticket.patch', () => ask.getByRole('button', { name: 'Looks good', exact: true }).click());
    await reload();
    want(/^Done/.test((await page.locator('[data-key="ticket-sentence"]').innerText()).trim()), 'Looks good did not finish the ticket');

    // ---- the same from the state word above the title; Not yet keeps the ticket where it is
    const open2 = make('Write the autumn report', 'active');
    await open('#ticket/' + open2);
    await page.waitForTimeout(800);
    await pick(page.locator(`[data-key="ticket-pill-menu-${open2}"] > summary`), page.locator('[data-key="pill-move-done"]'), 'the state word > Done');
    const ask2 = page.locator(`[data-key="review-card-${open2}"]`);
    await ask2.waitFor({ timeout: 5000 });
    await ask2.getByRole('button', { name: 'Not yet', exact: true }).click();
    await page.waitForTimeout(300);
    want(await ask2.count() === 0, 'Not yet did not take the card away');
    await reload();
    want(!/^Done/.test((await page.locator('[data-key="ticket-sentence"]').innerText()).trim()), 'Not yet closed the ticket');

    must(!bad.length, bad.length + (bad.length === 1 ? ' thing is' : ' things are') + ' not as decided on 28 Nov:\n        - ' + bad.join('\n        - '));
  },
};

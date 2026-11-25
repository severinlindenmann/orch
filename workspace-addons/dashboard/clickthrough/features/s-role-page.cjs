// Role page (ORCH-827, draft A2): a ticket that repeats by itself shows "Runs by itself", Run now and Pause, and the
// tabs Overview · Runs · Schedule · Chat · Files. Seeded like a real role: a harmless script repeat (echo, once a
// month so no planned run lands in the test), one run done with Start now, its result and one finding written the
// way a role's helper writes them. The person reads the last run, opens it on Runs (the finding links its ticket),
// sets a time limit on Schedule, writes a note for the next run in Chat, pauses and turns it on again; after each
// reload the page and `orch automation role` agree.
module.exports = {
  name: 'Role page: runs, schedule, chat and pause on a ticket that runs by itself',
  covers: ['addon.act', 'log'],
  async run({ page, open, reload, act, must, text, orchAsPerson, addonOn, addonOff, until, shot }) {
    addonOn('automation');
    const title = 'Check the wine cellar';
    const tid = JSON.parse(orchAsPerson('ticket', 'new', title, '--json')).id;
    orchAsPerson('ticket', 'edit', tid, '--note', 'Every month it counts the bottles in the cellar and compares them with the list. What is missing becomes a ticket for you. It changes nothing itself.');
    orchAsPerson('automation', 'script', 'add', 'count-cellar', '--', 'echo', 'cellar counted');
    orchAsPerson('automation', 'repeat', tid, 'monthly 1 03:00', '--script', 'count-cellar');
    orchAsPerson('automation', 'act', 'run', tid);
    let role = {};
    for (let i = 0; i < 30 && !(role.runs || []).length; i++) {
      await page.waitForTimeout(500);
      role = JSON.parse(orchAsPerson('automation', 'role', tid, '--json'));
    }
    must((role.runs || []).length === 1, 'Start now made no run: ' + JSON.stringify(role).slice(0, 300));
    orchAsPerson('automation', 'result', tid, 'Counted 214 bottles; 3 are missing from the list.', '--outcome', 'problems', '--run', '1',
      '--checked', 'Shelves A to D: counted', '--checked', 'List of last month: compared');
    orchAsPerson('automation', 'finding', tid, 'Three bottles of the 2019 red are missing', '--run', '1');

    await open('#home');
    await until(s => (s.addons || []).some(a => a.name === 'automation'), 'Automation on');
    await open('#ticket/' + tid);
    const strip = page.locator('[data-key="ticket-strip-' + tid + '"]');
    await strip.getByText('Runs by itself').waitFor({ timeout: 30000 });
    for (const name of ['Run now', 'Pause']) must(await strip.getByRole('button', { name }).isVisible(), 'the header has no ' + name);
    const tabs = await page.getByRole('tab').allInnerTexts();
    must(['Overview', 'Runs', 'Schedule', 'Chat', 'Files'].every((w, i) => (tabs[i] || '').startsWith(w)), 'the tabs are not Overview Runs Schedule Chat Files: ' + tabs.join(' | '));
    must(!tabs.some(x => /^Tasks/.test(x)), 'a role still shows the growing Tasks tab');
    const last = page.locator('[data-key="role-last"]');
    await last.getByText('Run 1').waitFor({ timeout: 20000 });
    must(/1 problem reported/.test(await last.innerText()) && /214 bottles/.test(await last.innerText()), 'Overview does not show the last run: ' + await last.innerText());
    must(/Its job/.test(await text()) && /counts the bottles/.test(await text()), 'Overview does not show its job');
    await shot('overview');

    // Runs: the run opens in place with what it checked and the finding's ticket
    await page.getByRole('tab', { name: /^Runs/ }).click();
    const run1 = page.locator('[data-key="role-run-1"]');
    must(/Shelves A to D/.test(await run1.innerText()), 'the run does not show what it checked: ' + await run1.innerText());
    must(await run1.getByRole('link').count() > 0, 'the finding has no link to its ticket');
    await shot('runs');

    // the runs do not load (a broken answer): an error with one Try again, never "Loading the runs…" for ever (R7.2)
    const broken = /\/api\/role\//;
    await page.route(broken, route => route.fulfill({ status: 200, contentType: 'text/html', body: '<html>Bad gateway</html>' }));
    await open('#ticket/' + tid);
    await reload();
    const failed = page.locator('[data-key="role-last"]');
    await failed.getByText('The runs did not load').waitFor({ timeout: 20000 });
    must(!/Bad gateway|<html>/.test(await text()), 'the page shows the raw answer');
    await page.unroute(broken);
    await failed.getByRole('button', { name: 'Try again' }).click();
    await last.getByText('Run 1').waitFor({ timeout: 20000 });

    // Schedule: in words; a script repeat ends by itself, so it has no time limit
    await page.getByRole('tab', { name: 'Schedule' }).click();
    must(/Monthly|month/i.test(await page.locator('[data-key="role-schedule"]').innerText()), 'Schedule does not say how it repeats in words');
    must(await page.locator('[data-key="role-setting-limit"]').count() === 0, 'a script repeat shows a time limit');

    // a helper repeat: the time limit is saved by one choice; the command line agrees and it stays after a reload
    const helperTid = JSON.parse(orchAsPerson('ticket', 'new', 'Tidy the shared drive', '--json')).id;
    orchAsPerson('automation', 'repeat', helperTid, 'monthly 1 04:00');
    await open('#ticket/' + helperTid);
    await page.locator('[data-key="ticket-strip-' + helperTid + '"]').getByText('Runs by itself').waitFor({ timeout: 30000 });
    await page.getByRole('tab', { name: 'Schedule' }).click();
    await page.locator('[data-key^="role-limit-"]').waitFor({ timeout: 20000 });
    await act('addon.act', () => page.locator('[data-key^="role-limit-"]').selectOption('90'));
    const saved = JSON.parse(orchAsPerson('automation', 'role', helperTid, '--json')).schedule;
    must(saved.time_limit === 90, 'orch automation role does not show the time limit: ' + JSON.stringify(saved));
    await reload();
    await page.getByRole('tab', { name: 'Schedule' }).click();
    let limit = '';
    for (let i = 0; i < 20 && limit !== '90'; i++) { await page.waitForTimeout(500); limit = await page.locator('[data-key^="role-limit-"]').inputValue().catch(() => ''); }
    must(limit === '90', 'the time limit is not kept after a reload: ' + limit);
    await page.locator('[data-key^="role-repeats-0 4"]').waitFor({ state: 'attached', timeout: 20000 });
    await shot('schedule');

    orchAsPerson('automation', 'repeat', helperTid, '--off');
    await open('#ticket/' + tid);

    // Chat: the run as a run card, a note for the next run saved as the person's message
    await page.getByRole('tab', { name: 'Chat' }).click();
    await page.locator('[data-key="role-chat-run-1"]').waitFor({ timeout: 20000 }).catch(() => {});
    must(await page.locator('[data-key="role-chat-run-1"]').count() === 1, 'the chat has no run card for run 1');
    await page.getByLabel('Tell it something for the next run').fill('Count the white wine first next time.');
    await act('log', () => page.locator('[data-key="role-say"]').getByRole('button', { name: 'Send' }).click());
    await reload();
    await page.getByRole('tab', { name: 'Chat' }).click();
    await page.locator('[data-key="role-chat-run-1"]').waitFor({ timeout: 20000 });
    const thread = page.locator('[data-key="role-thread"]');
    await thread.getByText('Count the white wine first next time.').waitFor({ timeout: 20000 });
    must(/Saved for the next run/.test(await thread.innerText()), 'the note does not say it is saved for the next run');
    await shot('chat');

    // Pause and Turn on, each kept after a reload
    await act('addon.act', () => strip.getByRole('button', { name: 'Pause' }).click());
    await reload();
    await strip.getByRole('button', { name: 'Turn on' }).waitFor({ timeout: 20000 });
    must(/Paused/.test(await strip.innerText()), 'the header does not say Paused');
    await act('addon.act', () => strip.getByRole('button', { name: 'Turn on' }).click());
    await reload();
    await strip.getByRole('button', { name: 'Pause' }).waitFor({ timeout: 20000 });

    // the same totals on the Automation page
    await open('#addon/automation');
    const found = page.locator('tr', { hasText: title }).filter({ hasText: 'open' });
    await found.first().waitFor({ timeout: 30000 }).catch(async () => { throw new Error('What the roles found has no row:\n' + (await text()).slice(0, 800)); });
    must(/0 fixed · 1 open · 0 dropped/.test(await found.first().innerText()), 'the Automation page totals differ: ' + await found.first().innerText());
    await shot('automation', found.first());

    orchAsPerson('automation', 'repeat', tid, '--off');
    await addonOff('automation');
  },
};

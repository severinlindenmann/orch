// Automation (ORCH-896): a ticket repeats a harmless script once a month (so no planned run lands in the test).
// The person opens Automation, sees the repeat in the table, presses Start now (the script runs and Recent starts
// says Done), then switches the repeat off; after a reload it says Off and `orch automation list` agrees. Then on
// again, and the add-on goes off for the next click-through. The script is `echo` in this throw-away home (CI runs
// on Linux, where echo is a program): no helper, no network.
module.exports = {
  name: 'Automation: a repeat shows, Start now runs it, the Repeats switch stays off after a reload',
  covers: ['addon.act'],
  async run({ page, open, reload, act, must, text, orchAsPerson, addonOn, addonOff, until }) {
    addonOn('automation');
    const title = 'Count the stock in the cellar';
    const tid = JSON.parse(orchAsPerson('ticket', 'new', title, '--json')).id;
    orchAsPerson('automation', 'script', 'add', 'say-stock', '--', 'echo', 'stock counted');
    orchAsPerson('automation', 'repeat', tid, 'monthly 1 03:00', '--script', 'say-stock');
    await open('#home');
    await until(s => (s.addons || []).some(a => a.name === 'automation'), 'Automation on');
    await open('#addon/automation');
    const row = () => page.locator('tr', { hasText: title });
    await row().waitFor({ timeout: 30000 }).catch(async () => { throw new Error('the repeat is not in the table:\n' + (await text()).slice(0, 500)); });
    must(/Runs say-stock/.test(await row().innerText()), 'the row does not say which script it runs');
    must(/Monthly|month/i.test(await row().innerText()), 'the row does not show the plan: ' + (await row().innerText()));
    must(/Not yet/.test(await row().innerText()), 'the repeat ran before Start now: ' + (await row().innerText()));

    // Start now: the script runs right away and the row and Recent starts say so
    await act('addon.act', () => row().getByRole('button', { name: 'Start now' }).click());
    let shown = '';
    for (let i = 0; i < 30 && !/Done/.test(shown); i++) { await page.waitForTimeout(1000); await reload(); shown = await row().innerText(); }
    must(/Done/.test(shown), 'Start now did not end in Done: ' + shown);
    const recent = (await text()).split('Recent starts')[1] || '';
    must(new RegExp(title + '[\\s\\S]{0,80}Done').test(recent), 'Recent starts does not list the run as Done:\n' + recent.slice(0, 300));

    // the Repeats switch: off, reload, still off (page and command line)
    const sw = () => row().locator('input[type=checkbox], [role=switch]').first();
    must(await sw().isChecked(), 'the repeat should start switched on');
    await act('addon.act', () => sw().click({ force: true }));
    await reload();
    must(!(await sw().isChecked()), 'the repeat is on again after a reload');
    const line = orchAsPerson('automation', 'list').split('\n').find(l => l.includes(title)) || '';
    must(/switched off/.test(line), '`orch automation list` does not say switched off: ' + line);
    await act('addon.act', () => sw().click({ force: true }));
    await reload();
    must(await sw().isChecked(), 'the repeat did not switch back on');

    orchAsPerson('automation', 'repeat', tid, '--off');
    await addonOff('automation');
  },
};

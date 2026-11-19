// Ticket page tabs and kinds (ORCH-891): Overview, Tasks, Files and Activity by click and by arrow keys; a task's
// evidence summary and file on Tasks; an epic lists its tickets, a sub-ticket says it is part of the epic; a release.
const idOf = out => (/\[(t_[A-Za-z0-9]+)\]/.exec(out) || [])[1];
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Ticket page: tabs, tasks with evidence, epic, sub-ticket and release',
  covers: ['page:ticket'],
  async run({ page, open, reload, must, text, orch, workspace }) {
    const links = idOf(orch('ticket', 'new', 'Check the website links'));
    orch('check', 'add', links, 'Run the link checker');
    orch('check', 'add', links, 'Fix the broken ones');
    fs.writeFileSync(path.join(workspace, 'links-report.md'), '# Links\nThree broken\n');
    orch('check', 'done', links, 'c1', '--file', 'links-report.md', '--title', 'Link report', '--summary', 'Three broken links found');
    const epic = idOf(orch('ticket', 'new', 'Spring newsletter', '--epic'));
    const sub = idOf(orch('ticket', 'new', 'Write the newsletter text', '--parent', epic));
    orch('ticket', 'new', 'Pick the photos', '--parent', epic);
    const release = idOf(orch('ticket', 'new', 'Release 2.0', '--release'));

    // tabs by click: each shows its panel
    await open('#ticket/' + links);
    const tabs = page.getByRole('tab');
    const names = (await tabs.allInnerTexts()).map(x => x.replace(/\s+/g, ' ').trim());
    must(names.length === 4 && /^Overview/.test(names[0]) && /^Tasks 2/.test(names[1]) && /^Files/.test(names[2]) && /^Activity/.test(names[3]), 'the tabs are ' + names.join(', '));
    await page.getByRole('tab', { name: /Tasks/ }).click();
    must((await page.getByRole('tab', { name: /Tasks/ }).getAttribute('aria-selected')) === 'true', 'Tasks is not selected after a click');
    const tasks = await text();
    must(tasks.includes('Run the link checker') && tasks.includes('Three broken links found') && tasks.includes('Link report'), 'Tasks does not show the done task with its evidence');
    must(tasks.includes('Fix the broken ones'), 'Tasks does not show the open task');
    await page.getByRole('tab', { name: /Activity/ }).click();
    must((await page.getByRole('tab', { name: /Activity/ }).getAttribute('aria-selected')) === 'true', 'Activity is not selected after a click');

    // tabs by keyboard: the arrow key moves to the next tab
    await page.getByRole('tab', { name: /Overview/ }).click();
    await page.getByRole('tab', { name: /Overview/ }).focus();
    await page.keyboard.press('ArrowRight');
    must(/^Tasks/.test((await page.evaluate(() => document.activeElement?.innerText || '')).trim()), 'the right arrow does not move to Tasks');

    // an epic lists its tickets; a sub-ticket says what it is part of
    await open('#ticket/' + epic);
    const e = await text();
    must(e.includes('Tickets in this epic') && e.includes('Write the newsletter text') && e.includes('Pick the photos'), 'the epic page does not list its tickets');
    await open('#ticket/' + sub);
    must((await text()).includes('Part of the epic'), 'a sub-ticket does not say it is part of the epic');
    await page.getByText(/Part of the epic/).click();
    await page.waitForFunction(id => location.hash.includes(id), epic, { timeout: 10000 });

    // a release says so in its properties after a reload
    await open('#ticket/' + release);
    await reload();
    must((await text()).includes('Release'), 'the release page does not say Release');
  },
};

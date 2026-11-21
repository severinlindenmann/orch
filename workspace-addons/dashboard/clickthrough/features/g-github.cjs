// GitHub with a stand-in `gh` (server.py; only the made-up repository standin/lunch answers, nothing is reached):
// a ticket in Review has a pull request whose checks passed but nobody merged it. Home shows it with a Merge button;
// the person presses Merge, reloads, and the row is gone and the ticket's pull request is merged. Then the person
// turns the Pull requests add-on on and sets the ticket's "Merge when green" field to On on the ticket page.
const fs = require('node:fs');
const path = require('node:path');

const PULL = 'https://github.com/standin/lunch/pull/7';

module.exports = {
  name: 'GitHub: merge a green pull request from Home, set Merge when green',
  covers: ['pull.merge', 'ticket.field', 'page:ticket'],
  async run({ page, open, reload, act, must, text, orch, addonOn, workspace, standins, home, until, addonOff }) {
    const tid = JSON.parse(orch('ticket', 'new', 'Add the lunch poll to the team page', '--json')).id;
    orch('check', 'add', tid, 'Build the poll');
    orch('check', 'done', tid, 'c1', '--summary', 'Poll built.', '--note', 'Pull request 7.', '--pr', PULL);
    orch('ref', 'add', tid, PULL);
    orch('ticket', 'summary', tid, 'The poll is built; its pull request passed every check.');
    orch('ticket', 'status', tid, 'done');
    // what orch last saw of the pull request (the stand-in gh answers the same when orch looks again)
    const now = Date.now() / 1000;
    fs.writeFileSync(path.join(workspace, '.orch', 'run', 'pull-checks.json'), JSON.stringify({
      pulls: { [PULL]: { state: 'OPEN', head: standins.head, green: true, at: now, green_since: now } }, asked_at: now }));

    await open('#home');
    await until(s => (s.needs || []).some(r => r.kind === 'helper:unmerged' && r.ticket === tid), 'the pull request waiting to be merged');
    await reload();
    const merge = page.locator(`[data-key$="-act-Merge"]`).first();
    await merge.waitFor({ timeout: 20000 }).catch(async () => { throw new Error('no Merge button on Home:\n' + (await text()).slice(0, 600)); });
    await act('pull.merge', () => merge.click());
    must(fs.existsSync(path.join(home, 'standin-merged')), 'the stand-in gh was never asked to merge');
    await until(s => !(s.needs || []).some(r => r.kind === 'helper:unmerged' && r.ticket === tid), 'the merged pull request leaving Home');
    await reload();
    must(await page.locator(`[data-key$="-act-Merge"]`).count() === 0, 'the Merge row is still on Home after a reload');
    const refs = JSON.parse(orch('ticket', 'show', tid, '--json')).refs || [];
    must(refs.some(r => r.url === PULL && /merged/.test(JSON.stringify(r))), 'the ticket does not say its pull request is merged');

    addonOn('pull-requests');
    await until(s => (s.addons || []).some(a => a.name === 'pull-requests' && a.ticket_fields), 'the Pull requests add-on turned on');
    await open('#ticket/' + tid);
    // ORCH-581: an add-on the ticket has not used waits in + Add; picking it shows its group and opens the field
    const pick = page.locator(`[data-key="prop-add-addon:pull-requests-${tid}"]`);
    await page.locator(`[data-key="props-add-${tid}"] > summary`).waitFor({ timeout: 20000 }).catch(async () => { throw new Error('no + Add menu:\n' + (await text()).slice(0, 600)); });
    await page.locator(`[data-key="props-add-${tid}"] > summary`).click();
    await pick.click();
    const field = page.locator(`button[data-action="field"][data-field="merge_when_green"]`);
    await act('ticket.field', () => page.getByRole('menuitemradio', { name: 'On' }).click());
    await reload();
    must((await field.innerText()).trim() === 'On', 'Merge when green is not On after a reload');
    must(JSON.parse(orch('ticket', 'show', tid, '--json')).ext?.['pull-requests']?.merge_when_green === 'on', 'the ticket file does not say on');
    await addonOff('pull-requests');   // off again for the next click-through
  },
};

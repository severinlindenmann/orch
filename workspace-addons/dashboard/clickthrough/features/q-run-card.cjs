// Run it now (ORCH-848): a helper asks the person to turn a setting on with a run card. On the ticket page the
// person clicks Run it now: the setting is on, the card answered "I ran it", and it stays so after a reload. A card
// whose command orch does not run shows Copy only and no Run it now.
const idOf = out => (/\[(t_[A-Za-z0-9]+)\]/.exec(out) || [])[1];

module.exports = {
  name: 'Run it now on a run card',
  covers: ['card.run'],
  async run({ page, open, reload, act, must, text, seen, orch, orchAsPerson }) {
    const tid = idOf(orch('ticket', 'new', 'Turn on the second look'));
    must(tid, 'no ticket was made');
    orch('ask', tid, 'Turn on the second look?', '--run', 'orch config set workflow.reviewer_look on',
      '--option', 'Leave it off for now');
    orch('ask', tid, 'Check the disk?', '--run', 'df -h');

    await open('#ticket/' + tid);
    const runCard = page.locator('.run-card').filter({ hasText: 'orch config set workflow.reviewer_look on' }).first();
    await runCard.waitFor();
    must((await runCard.innerText()).includes('second look'), 'the card does not say in orch\'s words what it changes');
    const copyOnly = page.locator('.run-card').filter({ hasText: 'df -h' }).first();
    must(!(await copyOnly.getByRole('button', { name: /Run it now/ }).count()), 'a command orch does not run has Run it now');
    must(/did not check this command/.test(await copyOnly.innerText()), 'a Copy-only card does not say orch did not check it');

    await act('card.run', () => runCard.getByRole('button', { name: /Run it now/ }).click());
    await reload();
    // a reloaded page draws its last copy first and fills in the newer state after (ORCH-1652, #2589)
    must(/I ran it/.test(await seen([/I ran it/])), '"I ran it" is not on the ticket after a reload');
    const got = JSON.parse(orchAsPerson('config', 'get', 'workflow.reviewer_look', '--json'));
    const on = typeof got === 'object' && got !== null ? got['workflow.reviewer_look'] : got;
    must(on === true || on === 'on', 'the setting is not on after Run it now');
    orchAsPerson('config', 'set', 'workflow.reviewer_look', 'off');  // leave the workspace as it was
  },
};

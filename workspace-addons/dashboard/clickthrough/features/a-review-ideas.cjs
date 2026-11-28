// ORCH-2186 (Focused review E): with workflow.decision_first on, a question asked with `orch ask --idea` is an ideas
// card on Review: one row per idea with Keep / Later / No, and Save in the bar. Saving part of it is fine: what is not
// sorted comes back as a smaller card that does not hold up the ticket. The switch is turned back off at the end.
module.exports = {
  name: 'Review: the ideas card saves part of it and asks the rest again',
  covers: ['page:review'],
  async run({ page, open, reload, must, orch, orchAsPerson, shot }) {
    const IDEAS = ['Customer story, 3 posts', 'Advent calendar', 'Video with an installer', 'Podcast guest spot'];
    const tid = JSON.parse(orchAsPerson('ticket', 'new', 'December content', '--json')).id;
    orch('ask', tid, 'Which content ideas should the helper work out?', ...IDEAS.flatMap((i) => ['--idea', i]),
      '--fact', 'Three ideas need no budget.');
    const card = () => page.locator('.swipe-card:not(.under):not(.under2)', { hasText: 'content ideas' }).first();
    const shown = async () => {  // the first load may still show another card
      await page.locator('.swipe-card:not(.under):not(.under2)').first().waitFor();
      if (!(await card().count())) await page.locator('.review-side').getByText(/content ideas/).first().click();
      await card().locator('.swipe-ideas').waitFor();
    };
    const questions = () => JSON.parse(orch('ticket', 'show', tid, '--json')).questions;
    orchAsPerson('config', 'set', 'workflow.decision_first', 'on');
    try {
      await open('#review?card=' + encodeURIComponent('core:q:' + tid + ':q1'));
      await shown();
      const c = card();
      const rows = await c.locator('.swipe-idea-t').allInnerTexts();
      must(JSON.stringify(rows) === JSON.stringify(IDEAS), `the ideas on the card are ${JSON.stringify(rows)}`);
      const save = page.locator('.swipe-act.ok .act-word');
      must((await save.innerText()).trim().startsWith('Save'), `the main button says "${await save.innerText()}"`);

      // Save with nothing sorted asks to sort one first and saves nothing
      await save.click();
      await page.getByText('Sort at least one idea, then save.').first().waitFor();
      must(questions()[0].answer == null, 'Save with nothing sorted answered the card');

      await c.getByRole('button', { name: 'Keep: ' + IDEAS[0] }).click();
      await c.getByRole('button', { name: 'No: ' + IDEAS[3] }).click();
      await c.getByRole('button', { name: 'No: ' + IDEAS[1] }).click();
      await c.getByRole('button', { name: 'No: ' + IDEAS[1] }).click();  // a second tap takes it back
      must((await c.getByRole('button', { name: 'No: ' + IDEAS[1] }).getAttribute('aria-pressed')) === 'false', 'a second tap did not take the No back');
      must((await save.innerText()).includes('Save, 2 left for later'), `after sorting two the button says "${await save.innerText()}"`);
      await shot('sorted', c);

      await save.click();
      await page.waitForFunction(() => !document.querySelector('.swipe-card:not(.under):not(.under2) .swipe-idea-t')
        || document.querySelectorAll('.swipe-card:not(.under):not(.under2) .swipe-idea-t').length === 2, null, { timeout: 20000 })
        .catch(() => must(false, 'the card stayed after Save'));
      // the answer is held a few seconds (Undo); then it is on the ticket
      let qs = [];
      for (let i = 0; i < 40 && !(qs = questions())[0].answer; i++) await page.waitForTimeout(500);
      must(/^Keep: Customer story, 3 posts\. No: Podcast guest spot\. Later: /.test(String(qs[0].answer)), `the saved answer is ${JSON.stringify(qs[0].answer)}`);
      must(qs.length === 2 && JSON.stringify(qs[1].ideas) === JSON.stringify([IDEAS[1], IDEAS[2]]) && qs[1].left_from === 'q1',
        `the rest was not asked again: ${JSON.stringify(qs.slice(1))}`);

      // after a reload the smaller card is there with the two ideas that were left
      await open('#review?card=' + encodeURIComponent('core:q:' + tid + ':q2'));
      await reload();
      await shown();
      const left = await card().locator('.swipe-idea-t').allInnerTexts();
      must(JSON.stringify(left) === JSON.stringify([IDEAS[1], IDEAS[2]]), `the smaller card shows ${JSON.stringify(left)}`);
      await shot('left', card());
    } finally {
      orchAsPerson('config', 'set', 'workflow.decision_first', 'off');
    }
    // switch off: the same card is a plain list again
    await reload();
    await page.waitForFunction(() => !document.querySelector('.swipe-ideas'), null, { timeout: 15000 })
      .catch(() => must(false, 'the ideas rows stayed after the switch went off'));
  },
};

// ORCH-547: the manager answers a question FOR the person (orch answer --for). On Review, Answered → "Answered for
// me" shows it as "Manager for Severin"; the person clicks Undo and the question waits for them again, after a reload.
module.exports = {
  name: 'Review: answered for me, and Undo',
  covers: ['review.undo'],
  async run({ page, open, reload, act, must, text, orchAsPerson }) {
    const tid = JSON.parse(orchAsPerson('ticket', 'new', 'Undo walk: pick the cake', '--json')).id;
    orchAsPerson('ask', tid, 'Which cake?', '--option', 'Carrot', '--option', 'Lemon', '--recommend', 'Lemon');
    orchAsPerson('answer', tid, 'q1', 'Lemon', '--by', 'agent:manager', '--for', 'Severin');

    await open('#review');
    await page.locator('[data-show="answered"]').click();
    await page.getByRole('button', { name: 'Answered for me' }).click();
    const rec = page.locator('article.decision', { hasText: 'Which cake?' }).first();
    await rec.waitFor();
    must(/Manager for Severin/.test(await rec.innerText()), 'the answer does not say the manager gave it for Severin');
    await act('review.undo', () => rec.getByRole('button', { name: 'Undo' }).click());

    await open('#ticket/' + tid);
    await reload();
    must((await page.locator('[data-question]').count()) > 0, 'the question does not wait again after Undo and a reload');
    must((await text()).includes('Which cake?'), 'the asked-again question is not on the ticket');
  },
};

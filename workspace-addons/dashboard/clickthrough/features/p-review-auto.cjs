// Review > Auto Reviewer (ORCH-425): turn "Check finished work" on from the page, let the Reviewer's pass accept a
// finished data ticket without Human review needed, then press Undo on "What the Reviewer did": the ticket is back in
// Review after a reload. "Away for the night" is flipped on and off again; both switches end where they started.
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Review: Auto Reviewer switches and Undo of a verdict',
  covers: ['auto_reviewer.set', 'away.set', 'review.undo'],
  async run({ page, open, reload, act, must, orchAsPerson, workspace }) {
    const sw = key => page.locator(`[data-key="review-switch-${key}"]`);
    const checked = async key => (await sw(key).getAttribute('aria-checked')) === 'true';

    // a finished data ticket in Review, Human review needed off
    const tid = JSON.parse(orchAsPerson('ticket', 'new', 'Export the lunch figures', '--json')).id;
    orchAsPerson('ticket', 'tidy', tid, 'Export the lunch figures', '--description', 'For the team',
      '--done-when', 'the lunch figures are exported');
    orchAsPerson('check', 'add', tid, 'Export the figures', '--covers', 'the lunch figures are exported');
    fs.writeFileSync(path.join(workspace, 'lunch.csv'), 'day,people\nMon,12\nTue,9\n');
    orchAsPerson('check', 'done', tid, 'c1', '--file', 'lunch.csv', '--summary', 'Two days exported.');
    orchAsPerson('ticket', 'edit', tid, '--human-review', 'no');
    orchAsPerson('ticket', 'status', tid, 'review');

    await open('#review');
    const autoWas = await checked('auto');
    if (!autoWas) {
      await act('auto_reviewer.set', () => sw('auto').click());
      await reload();
      must(await checked('auto'), 'Check finished work did not stay on after a reload');
    }
    orchAsPerson('review', 'tend');
    await reload();
    const row = page.locator(`[data-key^="review-accepted-${tid}"]`).first();
    await row.waitFor();
    must((await row.innerText()).includes('Auto Reviewer · Accepted'), 'the accept is not marked as the Auto Reviewer\'s');
    await act('review.undo', () => row.getByRole('button', { name: 'Undo' }).click());
    await reload();
    const shown = JSON.parse(orchAsPerson('ticket', 'show', tid, '--json'));
    must(shown.status === 'review', 'the ticket is not back in Review after Undo');
    must((await page.locator(`[data-key^="review-accepted-${tid}"]`).first().innerText()).includes('Undone'),
      'the row does not say Undone after a reload');

    const awayWas = await checked('away');
    await act('away.set', () => sw('away').click());
    await reload();
    must((await checked('away')) === !awayWas, 'Away for the night did not stay flipped after a reload');
    await act('away.set', () => sw('away').click());
    await reload();
    must((await checked('away')) === awayWas, 'Away for the night did not go back');

    if (!autoWas) {
      await act('auto_reviewer.set', () => sw('auto').click());
      await reload();
      must(!(await checked('auto')), 'Check finished work did not go back off');
    }
  },
};

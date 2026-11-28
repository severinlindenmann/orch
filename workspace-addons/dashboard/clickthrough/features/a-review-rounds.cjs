// ORCH-2184 (Focused review C): with workflow.decision_first on and more than 5 cards, three tiles sit over the Review
// deck (Quick look, Short decision, Take your time); a card that costs money is in Take your time. A tile starts a
// round of up to 5 cards of its group; Esc (or Back to the start) goes back to the tiles. Nothing is answered by
// starting a round. The switch is turned back off at the end.
module.exports = {
  name: 'Review: attention tiles start a round of up to 5',
  covers: ['page:review'],
  async run({ page, open, reload, must, orch, orchAsPerson, shot }) {
    const tid = JSON.parse(orchAsPerson('ticket', 'new', 'Autumn tidy-up', '--json')).id;
    for (const [i, room] of ['kitchen', 'hall', 'garden', 'cellar', 'attic', 'garage'].entries()) {
      orch('ask', tid, `Move the old boxes from the ${room} to the shed this week?`, '--option', 'Move them',
        '--option', 'Leave them');
      if (i === 0) orch('ask', tid, 'Buy a new shelf for the shed for 80 EUR?', '--option', 'Buy it', '--option', 'Not now');
    }
    orchAsPerson('config', 'set', 'workflow.decision_first', 'on');
    try {
      await open('#review');
      await page.locator('.attn-tile').first().waitFor();
      const names = await page.locator('.attn-tile .stat-label').allInnerTexts();
      must(JSON.stringify(names) === JSON.stringify(['Quick look', 'Short decision', 'Take your time']), `the tiles are ${JSON.stringify(names)}`);
      const time = page.locator('.attn-tile[data-group="time"] .stat-value');
      must(Number(await time.innerText()) >= 1, 'the card that costs money is not in Take your time');
      await shot('tiles');
      const before = JSON.parse(orch('review', 'list', '--json')).cards.length;

      // six plain questions with two answers each are one tap (you can undo it): Quick look, a round of 5
      const quick = page.locator('.attn-tile[data-group="quick"]');
      must(Number(await quick.locator('.stat-value').innerText()) >= 6, 'the one-tap questions are not in Quick look');
      await quick.click();
      await page.locator('.attn-round').waitFor();
      must((await page.locator('.attn-round-h').innerText()) === 'Quick look', 'the round does not name its group');
      // W-038: the progress row shows with the first answer; its words are in the page from the start
      const top = await page.locator('.swipe-top span').first().textContent();
      must(/^0 answered · 5 waiting/.test(top), `the round is not 5 cards: ${top}`);
      must(!(await page.locator('.swipe-top span').first().isVisible()), 'the progress row shows before the first answer');
      await shot('round');
      must(JSON.parse(orch('review', 'list', '--json')).cards.length === before, 'starting a round answered a card');

      await page.locator('#deck').focus();
      await page.keyboard.press('Escape');
      await page.locator('.attn-tiles').waitFor();
      must((await page.locator('.attn-round').count()) === 0, 'Esc did not go back to the tiles');
    } finally {
      orchAsPerson('config', 'set', 'workflow.decision_first', 'off');
    }
    await reload();
    await page.waitForFunction(() => !document.querySelector('.attn-tiles'), null, { timeout: 15000 })
      .catch(() => must(false, 'the tiles stayed after the switch went off'));
  },
};

// ORCH-2182 (Focused review A): with workflow.decision_first on, a Review card leads with "You decide:", "If you wait:"
// and one "What matters" box (orch ask --if-wait / --fact), the answers stay in the bar and the card's links sit in one
// More menu. Off (the default), the same card looks as before. The switch is turned back off at the end.
module.exports = {
  name: 'Review: the decision-first card behind its switch',
  covers: ['page:review'],
  async run({ page, open, reload, must, orch, orchAsPerson, shot }) {
    const tid = JSON.parse(orchAsPerson('ticket', 'new', 'Spring newsletter', '--json')).id;
    orch('ask', tid, 'Send the spring newsletter to all 2,400 customers today?', '--option', 'Send today',
      '--option', 'Wait for Tuesday', '--recommend', 'Wait for Tuesday',
      '--if-wait', 'It goes out next Tuesday with the old prices.',
      '--fact', 'The new prices start on 1 March', '--fact', 'Anna checked every link',
      '--fact', 'It cannot be called back once sent');
    const id = 'core:q:' + tid + ':q1';
    const card = () => page.locator('.swipe-card:not(.under):not(.under2)').first();
    const shown = async () => {
      await card().waitFor();
      if (!(await card().innerText()).includes('spring newsletter')) {  // the first load may still show another card
        await page.locator('.review-side').getByText(/spring newsletter/).first().click();
        await page.locator('.swipe-card:not(.under):not(.under2)', { hasText: 'spring newsletter' }).first().waitFor();
      }
    };

    await open('#review?card=' + encodeURIComponent(id));
    await shown();
    must((await card().locator('.swipe-decide, .swipe-fact, .swipe-more').count()) === 0, 'the decision-first parts show while the switch is off');
    await shot('before');

    orchAsPerson('config', 'set', 'workflow.decision_first', 'on');
    await reload();
    await shown();
    const c = card();
    await c.locator('.swipe-decide').waitFor();
    must((await c.locator('.swipe-decide').innerText()).startsWith('You decide:'), 'no "You decide:" first');
    must((await c.locator('.swipe-wait').innerText()).includes('If you wait: It goes out next Tuesday'), 'no "If you wait:" line');
    const facts = await c.locator('.swipe-fact li').allInnerTexts();
    must(facts.length === 3 && facts[0] === 'The new prices start on 1 March', `the What matters box shows ${JSON.stringify(facts)}`);
    must(await page.getByRole('button', { name: /^Wait for Tuesday|^Use/ }).first().isVisible(), 'the answers are not in view');
    await c.locator('.swipe-more > summary').click();
    must(await c.getByRole('menuitem', { name: /Open ticket/ }).isVisible(), 'Open ticket is not in the More menu');
    await page.keyboard.press('Escape');
    await shot('after', c);

    orchAsPerson('config', 'set', 'workflow.decision_first', 'off');
    await reload();
    await shown();
    await page.waitForFunction(() => !document.querySelector('.swipe-card:not(.under):not(.under2) .swipe-decide'), null, { timeout: 15000 })
      .catch(() => must(false, 'the card did not go back to how it was'));
  },
};

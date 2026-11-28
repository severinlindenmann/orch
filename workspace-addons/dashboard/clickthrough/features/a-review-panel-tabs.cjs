// ORCH-2185 (Focused review D): with workflow.decision_first on, the panel beside a Review card has Ticket, Chat and
// "What the helper does". "Ask about this" in the card's More opens Chat with "About: <the decision>" in the box, the
// card stays on screen, a reload keeps the tab, and a sent line shows in the panel's chat. The switch goes back off.
module.exports = {
  name: 'Review: the panel beside the card has Ticket, Chat and What the helper does',
  covers: ['page:review'],
  async run({ page, open, reload, must, orch, orchAsPerson, shot }) {
    const tid = JSON.parse(orchAsPerson('ticket', 'new', 'Autumn price list', '--json')).id;
    orch('ask', tid, 'Send the autumn price list to the shops today?', '--option', 'Send today',
      '--option', 'Wait for Monday', '--recommend', 'Send today',
      '--if-wait', 'The shops keep the summer prices until Monday.', '--fact', 'All 14 prices were checked');
    orchAsPerson('config', 'set', 'workflow.decision_first', 'on');
    const id = 'core:q:' + tid + ':q1';
    const card = () => page.locator('.swipe-card:not(.under):not(.under2)', { hasText: 'autumn price list' }).first();
    await open('#review?card=' + encodeURIComponent(id));
    await page.locator('.swipe-card:not(.under):not(.under2)').first().waitFor();
    if (!(await card().isVisible())) {  // the first load may show another card; the list shows five rows at a time (O-05): All shows the rest
      if (await page.locator('.review-side [data-review-more="all"]').count()) await page.locator('.review-side [data-review-more="all"]').click();
      await page.locator('.review-side').getByText(/autumn price list/).first().click();
    }
    await card().waitFor();
    const host = await page.locator('[data-review-host]').elementHandle();

    await card().locator('.swipe-more > summary').click();
    await card().getByRole('menuitem', { name: 'Ask about this' }).click();
    const panel = page.locator('.review-ticket');
    await panel.locator('[data-review-chat-box] textarea').waitFor();
    must(page.url().includes('ticket=' + tid) && page.url().includes('tab=chat'), 'the address names the ticket and Chat: ' + page.url());
    const box = panel.locator('[data-review-chat-box] textarea');
    must((await box.inputValue()).startsWith('About: Send the autumn price list to the shops today?'), 'the box is not prefilled: ' + await box.inputValue());
    must(await host.evaluate(n => n.isConnected), 'the deck was drawn again');
    must(await card().isVisible(), 'the card stays beside the panel');
    const tabs = await panel.locator('.review-ticket-tabs a').allInnerTexts();
    must(JSON.stringify(tabs.map(s => s.trim())) === JSON.stringify(['Ticket', 'Chat', 'What the helper does']), 'the tabs read ' + JSON.stringify(tabs));
    must(!(await panel.innerText()).match(/session/i), 'the panel says "session"');
    await shot('chat');

    await panel.getByRole('link', { name: 'What the helper does' }).click();
    await panel.getByText('No helper works on this now').waitFor();
    await panel.getByRole('link', { name: 'Ticket', exact: true }).click();
    await panel.locator('.ticket-page').first().waitFor();

    await panel.getByRole('link', { name: 'Chat', exact: true }).click();
    await box.waitFor();
    await box.fill('Is the delivery cost in the list too?');
    await panel.locator('[data-key="review-chat-send"]').click();
    await panel.locator('.review-panel-log').getByText('Is the delivery cost in the list too?').waitFor({ timeout: 15000 });
    await reload();
    await page.locator('.review-ticket .review-panel-log').getByText('Is the delivery cost in the list too?').waitFor({ timeout: 15000 });
    must(page.url().includes('tab=chat'), 'a reload keeps the Chat tab');

    orchAsPerson('config', 'set', 'workflow.decision_first', 'off');
    await reload();
    await page.locator('.review-ticket .review-ticket-h h2').waitFor();
    must((await page.locator('.review-ticket-tabs').count()) === 0, 'the tabs show while the switch is off');
  },
};

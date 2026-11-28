// Chats page, Ticket chats (team chat step 1, ORCH-1168): a ticket of its own gets a helper's line and a question
// (written with orch as the stand-in helper). The person opens Chats, sees the ticket under Ticket chats with its
// unread count, opens the chat (it is marked read), writes to the helper, answers the question in the chat and sees
// the answer under Decided in the ticket beside the chat. At phone width the list comes first, then the chat with a
// back button. The ticket page's Ticket chat leads to the same chat. Everything survives a reload.
module.exports = {
  name: 'Chats page: ticket chats, answer a question, Decided',
  covers: ['page:chat', 'chat.read', 'chat.say', 'answer'],
  async run({ page, open, reload, act, must, text, orch, until, shot }) {
    await open('#chat');
    const tid = JSON.parse(orch('ticket', 'new', 'Launch the trail shoe', '--json')).id;
    orch('ticket', 'tidy', tid, 'Launch the trail shoe', '--description', 'New trail shoe in shops on 3 March.', '--done-when', 'Shoe in shops, campaign live');
    orch('chat', 'reply', 'The poster draft is ready. One choice before the print:', '--ticket', tid);
    orch('ask', tid, 'Which colour leads the campaign?', '--option', 'Glacier blue', '--option', 'Moss', '--recommend', 'Glacier blue');
    await until(s => (s.ticket_chats || []).some(r => r.id === tid && r.unread >= 2), 'the ticket chat with 2 unread');

    // the list: the ticket under Ticket chats, with its unread count
    await reload();
    const row = page.locator(`.chat-list-row[data-id="${tid}"]`);
    await row.waitFor();
    must(/^tickets$/i.test((await page.locator('[data-key="ticket-chats-heading"]').innerText()).trim()), 'there is no Tickets heading in the list');
    must(/2/.test(await row.locator('.count').innerText()), 'the row does not show 2 unread');

    // open it: the helper's line, the question card, the ticket beside the chat; it is marked read
    await act('chat.read', () => row.click());
    must(/#chat\/t_/.test(await page.evaluate(() => location.hash)), 'the address is not the ticket chat');
    const main = await text();
    must(main.includes('The poster draft is ready.'), "the helper's line is not in the chat");
    must(main.includes('Which colour leads the campaign?'), 'the question is not in the chat');
    const panel = page.locator('[data-key="ticket-chat-panel"]');
    must(/Shoe in shops, campaign live/.test(await panel.innerText()), 'the ticket panel has no Done when');
    must(/Nothing decided yet/.test(await panel.innerText()), 'the ticket panel lists a decision before any answer');
    await shot('open-chat', page.locator('.chat-page'));

    // write to the helper: a chat line on the ticket, still there after a reload
    await page.locator('.chat-page textarea[data-thread]').fill('Please keep the logo small');
    await act('chat.say', () => page.locator('.chat-page [data-key="send"]').click());
    await reload();
    must((await text()).includes('Please keep the logo small'), 'the message is gone after a reload');
    must(!(await row.locator('.count').count()), 'the opened chat still shows unread after a reload');

    // answer the question in the chat: it shows under Decided
    const q = page.locator('.chat-log [data-question]').first();
    await act('answer', () => q.getByRole('button', { name: /Glacier blue/ }).first().click());  // one tap answers
    await reload();
    must(!(await page.locator('.chat-log [data-question]').count()), 'the question is still open after a reload');
    const decided = await page.locator('[data-key="ticket-chat-decided"]').innerText();
    must(/Glacier blue/.test(decided) && /Which colour leads the campaign\?/.test(decided), 'the answer is not under Decided after a reload');
    await shot('decided', page.locator('[data-key="ticket-chat-decided"]'));

    // phone width: the list first, then the chat with a back button
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: '‹ Chats' }).first().click();
    must(await row.isVisible(), 'at 390 the back button does not show the list');
    must(!(await panel.isVisible()), 'at 390 the ticket panel stays over the list');
    await row.click();  // nothing new now: no read mark is written
    must(await page.locator('[data-key="ticket-chat-' + tid + '"]').isVisible(), 'at 390 the chat does not open from the list');
    await page.setViewportSize({ width: 1280, height: 800 });

    // the ticket page's Ticket chat leads to the same chat
    await open('#ticket/' + tid);
    await page.getByRole('link', { name: 'Ticket chat' }).first().click();
    await page.waitForFunction(id => location.hash === '#chat/' + id, tid);
    await page.locator('[data-key="ticket-chat-' + tid + '"]').waitFor();
    must((await text()).includes('Please keep the logo small'), 'Ticket chat on the ticket page does not open its chat');
  },
};

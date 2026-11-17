// Chat: a person opens Chat, writes to the helper, and the message is still there after a reload. The helper then
// proposes a ticket and the person presses "Make ticket". The demo has no relay and no automation host, so no helper
// starts; the helper's proposal is written with `orch chat reply` as the stand-in helper (ORCH_AGENT), in the
// click-through's own throw-away workspace.
module.exports = {
  name: 'Chat: write a message, make a ticket from a proposal',
  covers: ['page:chat', 'chat.say', 'chat.make_ticket'],
  async run({ page, open, reload, act, must, text, orch }) {
    await open('#chat');
    await page.locator('.chat-page .chat-draft').fill('Please plan the Friday lunch menu');
    await act('chat.say', () => page.locator('.chat-compose [type="submit"]').click());
    await reload();
    must((await text()).includes('Please plan the Friday lunch menu'), 'the Chat message is gone after a reload');

    orch('chat', 'reply', 'I can make that a ticket.', '--ref', 'proposal:Plan the Friday lunch menu');
    await reload();
    await act('chat.make_ticket', () => page.getByRole('button', { name: /Make ticket: Plan the Friday lunch menu/ }).click());
    await reload();
    must(!(await page.getByRole('button', { name: /Make ticket: Plan the Friday lunch menu/ }).count()), 'the Make ticket button is back after a reload');
    await open('#tickets');
    must((await text()).includes('Plan the Friday lunch menu'), 'the new ticket is not in the list');
  },
};

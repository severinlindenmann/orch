// Messages and group chats with the stand-in relay (server.py; the workspace "Kitchen" may receive text and files):
// - Contacts: the person presses "Send a message" for Kitchen, writes in the chat with Kitchen and sends it; it is
//   delivered and still there after a reload.
// - A group chat on a ticket (made here as a helper would): the person writes to the group, finds it again as the
//   ticket's chat, and shares a ticket file with the group from the ticket page.
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Relay: message a workspace, write to a group, share a file',
  covers: ['chat.send_ws', 'group.say', 'group.share', 'page:chat'],
  async run({ page, open, reload, act, must, text, orch, orchAsPerson, python, workspace, standins, until, addonOff, shot }) {
    const r = standins.relay;
    if (!fs.existsSync(path.join(workspace, '.orch', 'secrets', 'relay.json'))) {
      orchAsPerson('addon', 'add', 'relay', '--yes');
      orchAsPerson('relay', 'connect', r.url, '--workspace', r.workspace, '--token', r.token);
    }
    await open('#home');
    await until(s => (s.addons || []).some(a => a.dashboard?.panel === 'phone'), 'the relay turned on');

    // a message to Kitchen, started from Contacts
    await open('#addon/relay');
    const send = page.getByRole('button', { name: 'Send a message' }).first();
    await send.waitFor({ timeout: 30000 }).catch(async () => { throw new Error('no Send a message button on Contacts:\n' + (await text()).slice(0, 500)); });
    await send.click();
    const box = page.getByRole('textbox', { name: 'Message Kitchen' });
    await box.waitFor({ timeout: 20000 });
    await box.fill('Can you cook for twelve on Friday?');
    await act('chat.send_ws', () => page.getByRole('button', { name: 'Send' }).click());
    await page.getByText('Delivered').first().waitFor({ timeout: 20000 }).catch(async () => { throw new Error('the message was not delivered:\n' + (await text()).slice(0, 500)); });
    await reload();
    await page.locator('text=Can you cook for twelve on Friday? >> visible=true').first().waitFor({ timeout: 20000 })
      .catch(() => { throw new Error('the message to Kitchen is gone after a reload'); });

    // a group chat on a ticket, with Kitchen in it
    const tid = JSON.parse(orch('ticket', 'new', 'Plan the summer party', '--json')).id;
    orchAsPerson('relay', 'group', 'add', tid, 'ws_kitchen001');
    python('import sys; from pathlib import Path; from orch import tickets\n' +   // a ticket file, as orch ticket attach makes it
      'tickets.attach(Path(sys.argv[1]), sys.argv[2], "guest-list.txt", b"Anna\\nBen\\nChiara\\n", "agent:standin")', workspace, tid);
    const inGroup = s => (s.groups?.hosted || []).find(g => g.ticket === tid);
    const members = s => (inGroup(s)?.members || []).filter(m => !m.left_at).map(m => m.ws);
    await until(s => members(s).includes('ws_kitchen001'), 'the group with Kitchen');
    await open('#chat');
    await page.locator('[data-chat-action="select"]').filter({ hasText: 'Plan the summer party' }).first().click();
    const draft = page.locator('.chat-page .chat-draft');
    await draft.waitFor({ timeout: 20000 });
    await draft.fill('Kitchen, can you bring the dessert?');
    await act('group.say', () => draft.press('Enter'));
    // once it has a chat line the group is the ticket's chat (one row under Ticket chats, team chat step 2); adding
    // and removing a member there is e-ticket-chat-workspaces.cjs
    await until(s => (s.ticket_chats || []).some(x => x.id === tid), 'the group as a ticket chat');
    await reload();
    await page.locator(`.chat-list-row[data-id="${tid}"]`).first().click();
    await page.getByText('Kitchen, can you bring the dessert?').first().waitFor({ timeout: 20000 })
      .catch(() => { throw new Error('the group message is gone after a reload'); });

    await open('#ticket/' + tid);
    const share = page.getByRole('button', { name: 'Share with group' }).first();
    await share.waitFor({ timeout: 20000 }).catch(async () => { throw new Error('no Share with group button on the ticket:\n' + (await text()).slice(0, 600)); });
    await shot('share-with-group', share);
    await act('group.share', () => share.click());
    await page.getByText('Shared with the group.').first().waitFor({ timeout: 20000 });
    await addonOff('relay');   // off again
  },
};

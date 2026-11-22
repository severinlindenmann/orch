// Another workspace in a ticket chat (team chat step 2, ORCH-1174; draft picked in ORCH-1098), with the stand-in relay
// (server.py; the workspace "Kitchen"): the person opens a ticket chat, presses + Add, reads the one line on what an
// added workspace sees, ticks Kitchen in the Workspaces list and adds it. The header then shows the member chips and
// "You and one other workspace"; Kitchen's helper writes (as orch does when a member's message arrives) and the line
// carries its name and workspace; the person writes to everyone; "In this chat" beside the chat says Kitchen was added
// by you and removes it after one question. At 390 the chips, + Add and the dialog fit. Everything survives a reload.
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Ticket chat: add a workspace, member chips, names on messages, chat info and remove',
  covers: ['group.add', 'group.remove', 'group.say', 'page:chat'],
  async run({ page, open, reload, act, must, text, orch, orchAsPerson, python, workspace, standins, until, addonOff, shot }) {
    const r = standins.relay;
    if (!fs.existsSync(path.join(workspace, '.orch', 'secrets', 'relay.json'))) {
      orchAsPerson('addon', 'add', 'relay', '--yes');
      orchAsPerson('relay', 'connect', r.url, '--workspace', r.workspace, '--token', r.token);
    }
    await open('#home');
    await until(s => (s.addons || []).some(a => a.dashboard?.panel === 'phone'), 'the relay turned on');

    const tid = JSON.parse(orch('ticket', 'new', 'Dealer price list', '--json')).id;
    orch('ticket', 'tidy', tid, 'Dealer price list', '--description', 'One-page price list for the dealers.', '--done-when', 'Price list sent to the dealers');
    orch('chat', 'reply', 'The draft price list is ready. Kitchen knows the order numbers.', '--ticket', tid);
    await until(s => (s.ticket_chats || []).some(x => x.id === tid), 'the ticket chat');
    const inGroup = s => (s.groups?.hosted || []).find(g => g.ticket === tid);
    const members = s => (inGroup(s)?.members || []).filter(m => !m.left_at).map(m => m.ws);

    // open the ticket chat: only you and your helper, + Add is there because a workspace is connected
    await open('#chat/' + tid);
    const chat = page.locator('[data-key="ticket-chat-' + tid + '"]');
    await chat.waitFor({ timeout: 20000 });
    const head = chat.locator('[data-key="thread-head"]');
    must(/You and your helper/.test(await head.textContent()), 'the ticket chat does not start with you and your helper');
    const addButton = page.getByRole('button', { name: 'Add a workspace to this chat' });
    await addButton.waitFor({ timeout: 20000 }).catch(async () => { throw new Error('no + Add in the ticket chat:\n' + (await text()).slice(0, 500)); });

    // + Add: the one-line notice, the Workspaces list, Add stays off until a pick
    await addButton.click();
    const dlg = page.locator('dialog[open][data-key="ticket-chat-add-dialog"]');
    await dlg.waitFor();
    must(/They see this ticket and the earlier messages in this chat, including places, voice notes and file names\./.test(await dlg.locator('[data-key="ticket-chat-share-notice"]').innerText()), 'the Add dialog does not say what they see');
    must(/Workspaces/.test(await dlg.innerText()), 'the Add dialog has no Workspaces list');
    const confirm = dlg.locator('[data-key="ticket-chat-add-confirm"]');
    must(await confirm.isDisabled(), 'Add is on before a workspace is picked');
    await dlg.getByRole('checkbox').first().waitFor();
    await dlg.locator('label', { hasText: 'Kitchen' }).click();
    must(!(await confirm.isDisabled()), 'Add stays off after Kitchen is picked');
    await shot('add-dialog', dlg);
    await act('group.add', () => confirm.click());
    await until(s => members(s).includes('ws_kitchen001'), 'Kitchen in the ticket chat');

    // the header: chips and "one other workspace"; the join line in the chat
    await reload();
    await chat.waitFor({ timeout: 20000 });
    must(/You and one other workspace/.test(await head.textContent()), 'the header does not say one other workspace');
    const chips = chat.locator('[data-key="ticket-chat-chips"]');
    must(/Kitchen helper/.test(await chips.innerText()), 'there is no Kitchen chip in the header');
    must(/You added Kitchen\. They see this ticket and the whole chat\./.test(await chat.innerText()), 'the chat does not say you added Kitchen');
    must(!(await page.locator('.chat-list-row[data-chat-action="select"]', { hasText: 'Dealer price list' }).count()), 'the group is listed a second time under Groups');

    // Kitchen's helper writes (as orch does when a member's message arrives): its name and workspace are on the line
    python('import sys; from pathlib import Path; from orch import chat_groups as cg\n' +
      'cg._history(Path(sys.argv[1]), sys.argv[2], "agent:Kitchen", "Group: Order numbers are on the list now.", chat=True)', workspace, tid);
    await until(s => (s.tickets || []).some(t => t.id === tid && (t.history || []).some(e => /Order numbers are on the list now/.test(e.text || ''))), 'the line from Kitchen');
    await reload();
    const line = chat.locator('.thread-line', { hasText: 'Order numbers are on the list now.' }).first();
    await line.waitFor({ timeout: 20000 });
    const who = await line.locator('.thread-line-head').innerText();
    must(/Kitchen helper/.test(who) && /Kitchen/.test(await line.locator('.chat-ws-label').innerText()), 'the line from Kitchen does not name its helper and workspace: ' + who);
    must(!/Group: /.test(await line.innerText()), 'the line still shows the Group: mark');
    must(/helper/.test(await chat.locator('.thread-line', { hasText: 'The draft price list is ready.' }).locator('.thread-line-head').innerText()), "your own helper's line has no name");

    // the person writes to everyone in the chat
    const draft = chat.locator('.chat-draft');
    must(/everyone/.test(await draft.getAttribute('placeholder')), 'the chat box does not say it goes to everyone');
    await draft.fill('Thanks, Kitchen. I send it on Friday.');
    await act('group.say', () => chat.locator('[data-key="ticket-chat-send"]').click());
    await reload();
    must((await chat.innerText()).includes('Thanks, Kitchen. I send it on Friday.'), 'your message is gone after a reload');

    // chat info: added by you, then Remove after one question
    const info = page.locator('[data-key="ticket-chat-info"]');
    await info.waitFor();
    const infoText = await info.innerText();
    must(/In this chat/.test(infoText) && /Kitchen helper/.test(infoText) && /added by you/.test(infoText), 'chat info does not say Kitchen was added by you:\n' + infoText);
    await chips.click();  // the chips lead to chat info
    await shot('chat-info', info);
    await shot('member-chips', head);
    await info.getByRole('button', { name: 'Remove Kitchen from this chat' }).click();
    const sure = page.locator('dialog[open][data-key="ticket-chat-remove-dialog"]');
    await sure.waitFor();
    must(/What it already got stays with it/.test(await sure.innerText()), 'the remove question does not say what stays with Kitchen');
    await act('group.remove', () => sure.getByRole('button', { name: 'Remove' }).click());
    await until(s => !members(s).includes('ws_kitchen001'), 'Kitchen out of the ticket chat');
    await reload();
    must(/You and your helper/.test(await head.textContent()), 'the header still counts Kitchen after it was removed');
    must(/You removed Kitchen\. What it already got stays with it\./.test(await chat.innerText()), 'the chat does not say you removed Kitchen');
    must(/Earlier: Kitchen removed/.test(await info.innerText()), 'chat info does not list Kitchen under Earlier');

    // phone width: add it back from the dialog; the chips and + Add fit, the page does not scroll sideways
    await page.setViewportSize({ width: 390, height: 844 });
    await addButton.click();
    await dlg.waitFor();
    await dlg.locator('label', { hasText: 'Kitchen' }).click();
    await act('group.add', () => confirm.click());
    await until(s => members(s).includes('ws_kitchen001'), 'Kitchen back in the ticket chat');
    await reload();
    await chips.waitFor({ timeout: 20000 });
    must(await chips.isVisible() && await addButton.isVisible(), 'at 390 the chips or + Add are not visible');
    must(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'at 390 the page scrolls sideways');
    await page.setViewportSize({ width: 1280, height: 800 });
    await addonOff('relay');   // off again
  },
};

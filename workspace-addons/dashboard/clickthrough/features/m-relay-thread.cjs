// Relay conversations (RP5, ORCH-2169): on the Relay page the person picks the thread with the stand-in workspace
// "Kitchen" (server.py), writes in its box and presses Send. The message is in Kitchen's thread, and still there
// after a reload.
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Relay: write in a workspace thread on the Relay page',
  covers: ['message.send'],
  async run({ page, open, reload, act, text, orchAsPerson, workspace, standins, until }) {
    const r = standins.relay, ws = 'ws_kitchen001', words = 'Thread test: are you open on Saturday?';
    orchAsPerson('addon', 'add', 'relay', '--yes');   // always: an earlier click-through may have turned it off
    if (!fs.existsSync(path.join(workspace, '.orch', 'secrets', 'relay.json'))) {
      orchAsPerson('relay', 'connect', r.url, '--workspace', r.workspace, '--token', r.token);
    }
    orchAsPerson('relay', 'refresh');
    await open('#home');
    await until(s => (s.addons || []).some(a => a.dashboard?.panel === 'phone'), 'the relay turned on');

    await open('#addon/relay?chat=' + ws);
    const box = page.locator(`input[data-conv-input="${ws}"]`);
    await box.waitFor({ timeout: 30000 }).catch(async () => { throw new Error('no thread with Kitchen on Relay:\n' + (await text()).slice(0, 800)); });
    await box.fill(words);
    await act('message.send', () => page.locator(`button[data-conv-send="${ws}"]`).click());
    await reload();
    const panel = page.locator(`[data-split-panel="${ws}"]`);
    await panel.getByText(words).first().waitFor({ timeout: 20000 })
      .catch(async () => { throw new Error('the message is not in the Kitchen thread after a reload:\n' + (await text()).slice(0, 800)); });
    // the relay stays on (as in m-contacts-trust)
  },
};

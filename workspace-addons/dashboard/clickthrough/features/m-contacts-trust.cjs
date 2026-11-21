// Contacts with fingerprint and state (message keys, ORCH-1203; owner picked look B). The stand-in relay lists three
// workspaces with a message key (server.py KEYED). Seeded here as earlier days would leave them: Home Mac was accepted
// with an older key (so now: New key without the old one), Marketing is accepted but sent a forged message (Not valid).
// fernscout is new (Not accepted yet). The person:
// - sees every contact with its fingerprint and state, this workspace's own fingerprint, and the careful Accept for
//   Home Mac (Accept as new contact, empty name, one warning line);
// - types their own name for fernscout and presses Accept: after a reload it is Accepted under that name;
// - presses Stop trusting for it and confirms: after a reload it is Withdrawn.
const fs = require('node:fs');
const path = require('node:path');

const SEED = `
import sys
from pathlib import Path
from orch import msgtrust
root = Path(sys.argv[1])
with msgtrust._state(root) as st:
    old = msgtrust._contact(st, "ws_homemac001")
    old["keys"] = [{"pub": "44" * 32, "accepted_at": "2026-11-10T09:00:00Z", "by": "human:standin", "via": "cli"}]
    mk = msgtrust._contact(st, "ws_market0001")
    pub = msgtrust._hint_key(root, "ws_market0001").hex()
    mk["keys"] = [{"pub": pub, "accepted_at": "2026-11-12T09:00:00Z", "by": "human:standin", "via": "cli"}]
    mk["not_valid"] = 3
`;

module.exports = {
  name: 'Contacts: every contact with its fingerprint and state; accept one under your own name, then stop trusting it',
  covers: ['contact.accept', 'contact.withdraw'],
  async run({ page, open, reload, act, text, orchAsPerson, python, workspace, standins, until, shot }) {
    const r = standins.relay;
    orchAsPerson('addon', 'add', 'relay', '--yes');   // always: an earlier click-through may have turned it off
    if (!fs.existsSync(path.join(workspace, '.orch', 'secrets', 'relay.json'))) {
      orchAsPerson('relay', 'connect', r.url, '--workspace', r.workspace, '--token', r.token);
    }
    orchAsPerson('relay', 'refresh');
    orchAsPerson('relay', 'key');   // this workspace's own key (made at the first relay use)
    python(SEED, workspace);
    await open('#home');
    await until(s => (s.addons || []).some(a => a.dashboard?.panel === 'phone'), 'the relay turned on');

    await open('#addon/relay');
    const asks = page.locator('.trust-asks');
    await asks.waitFor({ timeout: 30000 }).catch(async () => { throw new Error('no Needs your Accept on Contacts:\n' + (await text()).slice(0, 800)); });
    const card = id => page.locator(`article[data-contact="${id}"]`);
    const row = id => page.locator(`tr[data-contact="${id}"]`);
    // every state the page can show today, each with its fingerprint (8 groups of 4)
    await card('ws_homemac001').locator('.trust-pill', { hasText: 'New key without the old one' }).waitFor();
    await card('ws_homemac001').getByText('Only accept if they set up a new computer.').waitFor();
    const careful = card('ws_homemac001').getByRole('button', { name: 'Accept as new contact Home Mac' });
    await careful.waitFor();
    if (await card('ws_homemac001').locator('input[name=name]').inputValue() !== '') throw new Error('the name field of a new key must start empty');
    await card('ws_fernscout1').locator('.trust-pill', { hasText: 'Not accepted yet' }).waitFor();
    await card('ws_fernscout1').getByText('Check that it matches the fingerprint fernscout shows on its own Settings page.').waitFor();
    await row('ws_market0001').locator('.trust-pill', { hasText: 'Not valid' }).waitFor();
    await row('ws_market0001').getByText('3 messages refused as forged or changed.').waitFor();
    for (const id of ['ws_homemac001', 'ws_fernscout1']) {
      const groups = await card(id).locator('.fingerprint.lg > span').allTextContents();
      if (groups.length !== 8 || !groups.every(g => /^[0-9A-Z]{4}$/.test(g))) throw new Error(`${id}: the fingerprint is not 8 groups of 4: ${groups}`);
    }
    await page.locator('aside.trust-own .fingerprint').waitFor();   // this workspace's own, to read out
    await shot('contacts-states', asks);

    // accept fernscout under the person's own name
    const fern = card('ws_fernscout1');
    await fern.locator('input[name=name]').fill('Fernscout team');
    await act('contact.accept', () => fern.getByRole('button', { name: 'Accept fernscout' }).click());
    await reload();
    await row('ws_fernscout1').locator('.trust-pill', { hasText: 'Accepted' }).waitFor({ timeout: 20000 })
      .catch(async () => { throw new Error('fernscout is not Accepted after a reload:\n' + (await text()).slice(0, 800)); });
    await row('ws_fernscout1').getByText('Fernscout team').waitFor();
    await row('ws_fernscout1').getByText('Name on the relay: fernscout').waitFor();
    await shot('contacts-accepted', row('ws_fernscout1'));

    // stop trusting it: one confirm with the action's own word, no typed word
    await row('ws_fernscout1').getByRole('button', { name: 'Stop trusting Fernscout team' }).click();
    await act('contact.withdraw', () => page.getByRole('button', { name: 'Stop trusting', exact: true }).click());
    await reload();
    await row('ws_fernscout1').locator('.trust-pill', { hasText: 'Withdrawn' }).waitFor({ timeout: 20000 })
      .catch(async () => { throw new Error('fernscout is not Withdrawn after a reload:\n' + (await text()).slice(0, 800)); });
    await shot('contacts-withdrawn', row('ws_fernscout1'));
    // the relay stays on (as in l-phone): turned off and on again, its contact list is empty until the next refresh
  },
};

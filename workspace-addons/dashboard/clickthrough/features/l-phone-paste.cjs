// The phone link from Settings, no terminal (ORCH-1693): with the relay on but not connected, Settings > Relay
// says "Not set up" and asks for the line from the phone link's admin page; the person pastes it, presses Connect,
// reloads and sees Connected. A line that is not that line is refused with a plain next step.
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Phone link: paste the line from its admin page and Connect',
  covers: ['relay.connect'],
  async run({ page, open, reload, act, must, text, orchAsPerson, workspace, standins, until }) {
    const r = standins.relay;
    orchAsPerson('addon', 'add', 'relay', '--yes');
    fs.rmSync(path.join(workspace, '.orch', 'secrets', 'relay.json'), { force: true });  // an earlier one may have connected it
    await open('#home');
    await until(s => (s.addons || []).some(a => a.dashboard?.panel === 'phone'), 'the relay turned on');
    await open('#settings/phone');
    const line = page.locator('[data-key="phone-relay-line"]');
    await line.waitFor({ timeout: 20000 }).catch(async () => { throw new Error('no paste field for the phone link line:\n' + (await text()).slice(0, 600)); });
    must(!/terminal/i.test(await text()), 'Settings still sends the person to a terminal');

    await line.fill('not the line');
    await act('relay.connect', () => page.locator('[data-key="phone-relay-connect"]').click(), { refused: true });
    await page.getByText('That is not the line from your phone link').first().waitFor({ timeout: 10000 });

    await line.fill(`orch relay connect ${r.url} --workspace ${r.workspace} --token ${r.token}`);
    await act('relay.connect', () => page.locator('[data-key="phone-relay-connect"]').click());
    await reload();
    await page.locator('[data-key="phone-relay-status"]', { hasText: 'Connected' }).waitFor({ timeout: 20000 });
    must(fs.existsSync(path.join(workspace, '.orch', 'secrets', 'relay.json')), 'the connection was not saved');
    must(!(await text()).includes(r.token), 'the token is shown on the page');
  },
};

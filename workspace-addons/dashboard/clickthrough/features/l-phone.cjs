// Contacts and the phone, with a stand-in relay (server.py, on 127.0.0.1; one paired phone, one workspace "Kitchen"):
// the person turns the relay on and connects it here, opens Settings > Relay, turns on "Send questions to my
// phone" (confirms), picks "switch off after 8 h", reloads and sees both kept. When the time runs out (made to run
// out here), the page says so once and marks the notice seen; after a reload it is not shown again.
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Phone: connect the relay, send questions to the phone, switch-off time, the end notice',
  covers: ['page:settings/phone', 'mobile.set', 'mobile.hours', 'mobile.ack'],
  async run({ page, open, reload, act, must, text, orchAsPerson, workspace, standins, until }) {
    const r = standins.relay;
    orchAsPerson('addon', 'add', 'relay', '--yes');
    orchAsPerson('relay', 'connect', r.url, '--workspace', r.workspace, '--token', r.token);
    await open('#home');
    await until(s => (s.addons || []).some(a => a.dashboard?.panel === 'phone') && s.mobile_mode, 'the relay turned on and connected');
    await open('#settings/phone');
    must((await text()).includes('Connected'), 'Settings > Relay does not say Connected:\n' + (await text()).slice(0, 500));

    const sw = page.getByTestId('mobile-mode-switch');
    await sw.waitFor({ timeout: 20000 }).catch(async () => { throw new Error('no "Send questions to my phone" switch:\n' + (await text()).slice(0, 600)); });
    must((await sw.innerText()).trim() === 'Off', 'the phone switch should start off');
    await sw.click();
    await act('mobile.set', () => page.getByTestId('mobile-mode-confirm').click());
    await act('mobile.hours', () => page.getByTestId('mobile-mode-hours-8').click());
    await reload();
    await sw.waitFor({ timeout: 20000 });
    must((await sw.innerText()).trim() === 'On', 'the phone switch is not on after a reload');
    must(await page.getByTestId('mobile-mode-hours-8').getAttribute('aria-checked') === 'true', '8 h is not picked after a reload');

    // the time runs out: the page says so once (a toast) and marks it seen
    const f = path.join(workspace, '.orch', 'run', 'mobile-mode.json');
    await act('mobile.ack', async () => {
      const d = JSON.parse(fs.readFileSync(f, 'utf8'));
      d.ends_at = new Date(Date.now() - 60000).toISOString().replace(/\.\d+Z$/, 'Z');
      fs.writeFileSync(f, JSON.stringify(d));
      await until(s => s.mobile_mode && !s.mobile_mode.on, 'the phone mode ended');
    });
    await reload();
    await sw.waitFor({ timeout: 20000 });
    must((await sw.innerText()).trim() === 'Off', 'the phone switch is not off after the time ran out');
    must(!JSON.parse(fs.readFileSync(f, 'utf8')).ended, 'the end notice was not marked seen');
  },
};

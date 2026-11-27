// Publish from its own page, no terminal (ORCH-2170, RP2): with Publish on but not connected, the Publish page shows
// a box for the admin's whole text; a text without the connect line is refused with one plain sentence, the real
// text connects, and "Share a file" appears. The token never shows on the page.
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Publish: paste the admin text on the Publish page and Connect',
  covers: ['link.connect'],
  async run({ page, open, reload, act, must, text, orch, standins, workspace, until, addonOff }) {
    const p = standins.publish;
    orch('addon', 'add', 'publish', '--yes');
    fs.rmSync(path.join(workspace, '.orch', 'secrets', 'publish.json'), { force: true });  // an earlier one may have connected it
    await open('#home');
    await until(s => (s.addons || []).some(a => a.name === 'publish'), 'Publish turned on');
    await open('#addon/publish');
    const box = page.locator('[data-key="link-connect-text"]');
    await box.waitFor({ timeout: 30000 }).catch(async () => { throw new Error('no paste box on the Publish page:\n' + (await text()).slice(0, 600)); });
    must(!/terminal/i.test(await text()), 'the Publish page still sends the person to a terminal');

    await box.fill('Hello, here is nothing useful');
    await act('link.connect', () => page.locator('[data-key="link-connect-button"]').click(), { refused: true });
    await page.locator('[data-key="link-connect-error"]').waitFor({ timeout: 10000 });

    await box.fill(`Connect this workspace:\n\n  orch publish connect ${p.url} --workspace ${p.workspace} --token ${p.token}\n`);
    await act('link.connect', () => page.locator('[data-key="link-connect-button"]').click());
    await reload();
    await page.getByRole('button', { name: 'Share a file' }).waitFor({ timeout: 30000 });
    must(fs.existsSync(path.join(workspace, '.orch', 'secrets', 'publish.json')), 'the connection was not saved');
    must(!(await text()).includes(p.token), 'the token is shown on the page');
    await addonOff('publish');   // off again, as the next click-through expects
  },
};

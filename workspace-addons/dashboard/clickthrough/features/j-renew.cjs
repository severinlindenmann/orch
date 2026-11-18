// Renew a helper login, with the stand-in agent program of server.py (its login check says signed out; its sign-in
// prints a link and waits for one code). The person presses Renew, the window shows the sign-in link, the person
// "opens" it (the page is never really loaded: the click-through blocks it), pastes the code, and the login is
// renewed. After a reload the login no longer says it needs renewing.
module.exports = {
  name: 'Logins: renew a helper login with a code',
  covers: ['logins.status', 'logins.code', 'page:settings/agent'],
  async run({ page, base, open, reload, act, must, text, orch, until }) {
    // nothing may leave this computer: the sign-in page of the stand-in link is never loaded
    await page.context().route(u => !u.href.startsWith(base + '/'), r => r.abort());
    orch('logins');   // the checks once; the page shows their result
    await open('#settings/agent');
    const needsRenew = s => (s.logins?.items || []).find(x => x.renew && /renew|soon|unreachable/.test(x.state || ''));
    const item = needsRenew(await until(needsRenew, 'a helper login that needs renewing'));
    await reload();
    const renew = page.getByRole('button', { name: `Renew the ${item.label} login` }).first();
    await renew.waitFor({ timeout: 20000 }).catch(async () => { throw new Error('no Renew button:\n' + (await text()).slice(0, 600)); });
    must(/Needs renewing/.test(await text()), 'the login does not say Needs renewing before Renew');
    await act('logins.renew', () => renew.click());
    const dlg = page.locator('dialog[open]');
    const link = dlg.getByRole('link', { name: 'Open the sign-in page' });
    await act('logins.status', () => link.waitFor({ timeout: 30000 }));
    must(/standin-sign-in/.test(await link.getAttribute('href')), 'the link is not the stand-in sign-in link');
    await page.evaluate(() => document.addEventListener('click', e => { if (e.target.closest('a[target=_blank]')) e.preventDefault(); }, true));
    await link.click();
    await dlg.getByText('Does the page show a code? Paste it here.').waitFor({ timeout: 10000 });
    await dlg.locator('input').fill('standin-code-4711');
    await act('logins.code', () => dlg.getByRole('button', { name: 'Continue' }).click());
    await dlg.getByText(/login renewed/).waitFor({ timeout: 60000 }).catch(async () => { throw new Error('the login was not renewed:\n' + (await dlg.innerText()).slice(0, 400)); });
    await dlg.getByRole('button', { name: 'Done' }).click();
    orch('logins');
    await until(s => !(s.logins?.items || []).some(x => x.name === item.name && /renew|unreachable/.test(x.state || '')), 'the login renewed');
    await reload();
    must(!/Needs renewing/.test(await text()), 'the login still says Needs renewing after a reload');
  },
};

// Log in with a token (ORCH-1035): the person makes a token in their terminal, a browser that is not signed in gets
// the login screen, pastes it, picks a profile ("Who is using orch?"), acts as that profile, stays logged in after a
// reload, and logs out from the "You:" menu. On the demo's own address (127.0.0.1) the page itself loads without a
// sign-in, so the click-through opens the login screen the way a refused click does (window.orchLogin.showLogin).
module.exports = {
  name: 'Log in with a token and pick a profile',
  covers: ['session:login', 'session:me', 'session:profile', 'session:logout'],
  async run({ page, open, reload, python, workspace, must, until, signedOut }) {
    // what `orch dashboard token new|list|revoke` runs (the demo runs the dashboard from source, not as an add-on command)
    const tokens = (what, arg = '') => JSON.parse(python(
      'import json, sys\nfrom pathlib import Path\nfrom orch import dashlogin\nroot = Path(sys.argv[1])\nwhat = sys.argv[2]\n' +
      'if what == "new":\n    t, e = dashlogin.new_token(root, "click-through")\n    print(json.dumps({"token": t, **e}))\n' +
      'elif what == "list":\n    print(json.dumps(dashlogin.list_tokens(root)))\n' +
      'else:\n    print(json.dumps(dashlogin.revoke_token(root, sys.argv[3])))\n', workspace, what, arg));
    const made = tokens('new');
    must(/^odt_/.test(made.token) && made.state === 'active', 'no working token was made');
    // a browser that never signed in: no cookie, no page key
    await open('#home');
    // the click-throughs share one signed-in browser: keep its sign-in and put it back at the end
    const ctx = page.context(), cookies = await ctx.cookies();
    const secret = await page.evaluate(() => localStorage.getItem('orch_page_secret'));
    await ctx.clearCookies();
    signedOut(true);
    try {
      await page.evaluate(() => { localStorage.removeItem('orch_page_secret'); sessionStorage.removeItem('orch_page_secret'); });
      await reload();
      await page.evaluate(() => window.orchLogin.showLogin());
      await page.locator('[data-testid="login-door"]').waitFor();
      must(/Log in with your token/.test(await page.locator('[data-testid="login-door"]').innerText()), 'the login screen does not ask for the token');
      await page.locator('#door-token').fill(made.token);
      await Promise.all([page.waitForNavigation(), page.locator('[data-testid="login-door"] button[type=submit]').click()]);
      signedOut(false);
      // first time: the profile picker; add a profile (the demo list may be empty)
      await page.locator('[data-testid="profile-picker"]').waitFor();
      const add = page.locator('[data-testid="profile-picker"] .profile.add');
      if (await add.count()) await add.click();
      await page.locator('[data-testid="profile-picker"] input[name=name]').fill('Clara');
      await page.locator('[data-testid="profile-picker"] .profiles-add button[type=submit]').click();
      await page.locator('[data-testid="profile-picker"]').waitFor({ state: 'detached' });
      await until(async () => /Clara/.test(await page.locator('[data-testid="person-switch"]').innerText()), 'the sidebar says You: Clara', 20);
      await reload();
      must(!(await page.locator('[data-testid="login-door"]').count()), 'after a reload the browser is not logged in any more');
      must(/Clara/.test(await page.locator('[data-testid="person-switch"]').innerText()), 'after a reload the profile is not Clara');
      const listed = tokens('list');
      must(listed.some(t => t.id === made.id && t.state === 'active'), 'the token list does not show the token');
      // log out from the You menu
      await page.locator('[data-testid="person-switch"]').click();
      signedOut(true);
      await Promise.all([page.waitForNavigation(), page.locator('[data-testid="logout"]').click()]);
      await page.waitForLoadState('load');
      // asked outside the page: with every read behind the sign-in (ORCH-481) the logged-out page may load again meanwhile
      const res = await ctx.request.get(new URL('/session/me', page.url()).href, { headers: { 'Cache-Control': 'no-store' } });
      const me = await res.json().catch(() => ({}));
      must(res.status() === 401 || (res.ok() && me.login && me.login !== 'token'), 'after Log out the browser still has its token login');
    } finally {
      // put the shared sign-in back even when a step failed, so later click-throughs are not logged out
      tokens('revoke', made.id);
      await ctx.clearCookies();
      await ctx.addCookies(cookies);
      await page.evaluate(v => localStorage.setItem('orch_page_secret', v || ''), secret).catch(() => {});
      signedOut(false);
    }
  },
};

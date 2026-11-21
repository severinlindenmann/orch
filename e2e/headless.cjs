// The one way a script in this repository starts a browser (ORCH-615, AGENTS.md section 4).
//
// Every browser gets '--use-mock-keychain' and '--password-store=basic'. Without them macOS shows the person at the
// computer a keychain password window ("headless_shell wants to use ... Chromium Safe Storage"). The CI check
// scripts/check_headless_launch.py fails any file that calls launch() itself.
//
// Never a profile folder (launchPersistentContext, userDataDir, --user-data-dir; ORCH-1101): the headless shell
// ignores '--use-mock-keychain' once it keeps a profile on disk, fetches the cookie key from the login keychain and
// macOS asks the owner for his password. A context from launch() + newContext() keeps cookies in memory and never
// asks. A sign-in that must survive between runs goes in a storageState file: newContext({ storageState: file }).
//
//   const { launch } = require('./headless.cjs');               // CommonJS
//   import headless from './headless.cjs';                      // ES module: headless.launch(chromium, {...})
//   const browser = await launch(chromium, { headless: true });
//   const ctx = await browser.newContext({ viewport, acceptDownloads: true });
//
// Python twin: e2e/headless.py.

'use strict';

const ARGS = Object.freeze(['--use-mock-keychain', '--password-store=basic']);

// The launch options with the two keychain options first; the caller's own args follow (no duplicates).
function withArgs(opts = {}) {
  const own = Array.isArray(opts.args) ? opts.args.filter(a => !ARGS.includes(a)) : [];
  return { ...opts, args: [...ARGS, ...own] };
}

function launch(browserType, opts) {
  return browserType.launch(withArgs(opts));
}

module.exports = { ARGS, withArgs, launch };

// The one way a script in this repository starts a browser (ORCH-615, AGENTS.md section 4).
//
// Every browser gets '--use-mock-keychain' and '--password-store=basic'. Without them macOS shows the person at the
// computer a keychain password window ("headless_shell wants to use ... Chromium Safe Storage"). The CI check
// scripts/check_headless_launch.py fails any file that calls launch() / launchPersistentContext() itself.
//
//   const { launch } = require('./headless.cjs');               // CommonJS
//   import headless from './headless.cjs';                      // ES module: headless.launch(chromium, {...})
//   const browser = await launch(chromium, { headless: true });
//   const ctx = await headless.launchPersistent(chromium, profileDir, { viewport });
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

function launchPersistent(browserType, userDataDir, opts) {
  return browserType.launchPersistentContext(userDataDir, withArgs(opts));
}

module.exports = { ARGS, withArgs, launch, launchPersistent };

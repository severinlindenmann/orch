# TestFlight upload (orch mobile)

Scripts: `testflight.sh` (archive + upload + wait + group + notes), `testflight_asc.py` (App Store Connect part),
`tf-next-build.py` (next build number `YYMMDD.HHMMSS`, always above the latest in ASC).

## Prerequisites
- Xcode, `xcodegen`, `uv`.
- An App Store Connect API key `.p8`. It lives outside the repo (default `~/.appstoreconnect/private_keys/AuthKey_<KEYID>.p8`).
  Never commit or paste the key. The key id, issuer id, app id and team id are not secret; the defaults in the scripts
  are the orch ones and can be overridden by env: `ASC_KEY_PATH`, `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_APP_ID`,
  `ASC_TEAM_ID`, `ASC_BETA_GROUP` (default `Owner`).
- Python deps (`pyjwt`, `cryptography`) come from `uv run --with`, nothing to install.

## Steps
1. Write the "What to test" text to a file, e.g. `notes.txt` (plain text, a few lines).
2. Run `mobile/scripts/testflight.sh <git-sha> notes.txt`.
   - It checks out `<git-sha>` in a separate detached worktree (`TF_WORKTREE`, default `<repo>/../.worktrees/tf`), picks the
     next build number, archives the `OrchMobile` scheme and exports with `destination: upload` (this uploads to ASC).
   - Set `TF_HEAVY` to a wrapper (for example a job limiter) if the machine needs one.
3. `testflight_asc.py` then polls ASC (up to ~40 min) until the build is `VALID`, adds it to the beta group `Owner` and sets
   "What to test". It exits non-zero if the build turns `FAILED`/`INVALID` or is not `VALID` in time.
4. The build appears in TestFlight for the group; testers get it after Apple's automatic processing.

Logs of the archive and export are in the work dir printed at the start (`archive.log`, `export.log`).

Re-running only the ASC part (build already uploaded):
`uv run --with pyjwt --with cryptography python mobile/scripts/testflight_asc.py <build-number> notes.txt`

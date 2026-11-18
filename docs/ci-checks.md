# Required checks per place

The one written list of which checks run where and which of them can stop a merge (ORCH-453, from the CI review of
the night 17/18 Nov, ORCH-446). Change it in the same pull request as the workflow it describes.

Words: **required** = a red result stops the merge. **Shown** = it runs and shows its result, but cannot stop
anything. **Known red** = a system that is red today and has an owner and an end date (table at the end); its
steps are marked `continue-on-error`, so its check stays green and only a warning names the failure.

## How a red check stops a merge

- GitHub (rule on `develop`) requires two checks: the **final ci check** (the last job of `ci.yml`, green only when
  every called job passed or was skipped) and **banned-words** (the `rules` workflow).
- The orch merge queue (pull-requests add-on) reads **every** check of a queue group: one failed, cancelled or
  timed-out check drops the group. So a known-red part must never report a failed check: known red sits on the
  steps, never on the job (`brand/tests/test_ci_known_red.py` keeps it so), and since PR 1473 queue groups run
  no Windows or macOS part at all. Night 17/18 Nov, before both, a known-red Windows check stopped the queue for
  75 minutes.
- `main` has no required check on GitHub; the owner merges a release after its pull request into `main` is green.

## The list

| Check | Pull request into develop | Queue group (`orch-queue/…`) | Push to develop | Nightly | Release (pull request into main + release check) |
|---|---|---|---|---|---|
| final ci check (last job of `ci.yml`) | required | required | runs | runs | required |
| banned-words (rules) | required | required | | | skipped for `release/*` (already checked) |
| workspace, Linux (2 parts) | required | required | runs | runs | required |
| workspace, macOS (5 parts) | | | runs | runs | required |
| workspace, Windows (10 parts) | not while known red ¹ | | shown (known red) | shown (known red) | shown (known red), in the release check |
| Windows install as a standard user | not while Windows is known red ¹ | | runs | runs | required, in the release check |
| CLI smoke, Windows + macOS | required | required | | | required |
| e2e smoke (5 minutes) | required | required | | | required |
| add-on suites, page smoke, click-throughs | required | required | runs | | required |
| clock (suites at 22:30 and 23:59:40 UTC) | required | required | runs | runs | required |
| contracts, publish, relay | required | required | runs | | required |
| mobile | required | required | runs | runs, with phone UI tests | required |
| brand (words, tokens, CI time limits) | required | required | runs | runs | required |
| full e2e (`e2e` workflow, 03:17 UTC) | | | | runs | |

On a pull request, a queue group and a release, a check runs only when the change touches files it reads (paths
filter in `ci.yml`); a skipped check counts as passed. Queue groups run Linux only (ORCH-315, PR 1473): macOS and
Windows run on develop itself, on every push (never cancelled), at night and in the release check (the release
keeper's manual `ci` run with `windows=true`). On a push to develop and at night there is no merge left to stop: a
red part there (known red aside) opens the release keeper's red-develop ticket, to be fixed by a pull request first
in the queue.

¹ While Windows is known red, `scripts/touches_os_code.py --pr` answers `false` on every pull request, so the
Windows parts run only on develop pushes, nightly and the release check (or a manual run with `windows=true`).
Once Windows is green (KNOWN_RED empty), a pull request that changes file, process or path code runs them again.

A draft pull request gets no CI run; marking it ready starts one.

## Known red

The systems in `KNOWN_RED` (`.github/workflows/workspace.yml`). Every row needs an owner and an end date;
`scripts/ci_known_red.py --warn` writes a warning on every `ci` run when one is missing or the end date has passed,
and `brand/tests/test_ci_known_red.py` fails when this table and `KNOWN_RED` disagree.

| System | Owner | End date | Ticket | Why |
|---|---|---|---|---|
| windows-latest | owner (worked on in ORCH-32) | 2026-11-30 | ORCH-32 | full workspace suite fails and runs past its time limit on Windows |

When a system turns green: empty `KNOWN_RED` (or remove the system) and remove its row here in the same pull request.

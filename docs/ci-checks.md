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

## Light on a pull request, full once per queue group (ORCH-545)

A pull request into develop on its own runs one **light** job (`scripts/ci_light.py`, about 5 minutes): words and
style, ruff, the workspace tests that import the modules it changed (or a quarter of the suite as a sample when it
changes what all tests share, a module no test imports, or more than a quarter of the suite), the rule tests that
read the whole tree (`RULE_TESTS`: tool names, CLI seams, skills and history lint, next-step hints; about 15 s; they
made most red queue groups on 18-19 Nov) and the suites of the add-ons it changed. The full set runs **once per merge queue group** (`orch-queue/…`) on top of develop, whatever
files the group touches. A push to develop whose files equal a green queue group (`scripts/ci_proven.py`: a merge
commit with the tree of its second parent, and a green `ci` run of that parent on an `orch-queue/` branch) runs no
suite again. Contracts, publish, relay, mobile and the dashboard pictures still follow their paths on a pull request.

Why: 18 Nov, nearly every pull request ran the full set: 365 `ci` runs for 62 merges (5.9 per merge), GitHub ran
about two full runs at once, pull requests waited up to two hours and the queue merged about one an hour.

## The list

| Check | Pull request into develop | Queue group (`orch-queue/…`) | Push to develop | Nightly | Release (pull request into main + release check) |
|---|---|---|---|---|---|
| final ci check (last job of `ci.yml`) | required | required | runs | runs | required |
| light (words, style, ruff, tests of the changed code and add-ons) | required | | | | |
| banned-words (rules) | required | required | | | skipped for `release/*` (already checked) |
| headless-launch (rules): every browser start goes through `e2e/headless.cjs` / `.py` (ORCH-615) | runs (the queue stops on it) | required | | | runs |
| workspace, Linux (2 parts) | only with Windows ² | required, always | runs unless proven | runs | required |
| workspace, macOS (5 parts) | | | runs | runs | required |
| workspace, Windows (10 parts) | not while known red ¹ | | shown (known red) | shown (known red) | shown (known red), in the release check |
| Windows install as a standard user | not while Windows is known red ¹ | | runs | runs | required, in the release check |
| CLI smoke, Windows + macOS | | required, always | | | required |
| e2e smoke (5 minutes) | | required, always | | | required |
| add-on suites, page smoke, click-throughs | in light (changed add-ons only) | required, always | runs unless proven | | required |
| clock (suites at 22:30 and 23:59:40 UTC) | | required, always | runs unless proven | runs | required |
| contracts, publish, relay | required | required (contracts always) | runs unless proven | | required |
| mobile | required | required | runs unless proven | runs, with phone UI tests | required |
| brand (words, tokens, CI time limits, Windows-safe paths: ORCH-872) | in light | required, always | runs unless proven | runs | required |
| full e2e (`e2e` workflow, 03:17 UTC) | | | | runs | |

On a pull request and a release, a check runs only when the change touches files it reads (paths filter in
`ci.yml`); a skipped check counts as passed. "Always" = a queue group runs it whatever files it touches. Queue groups run Linux only (ORCH-315, PR 1473): macOS and
Windows run on develop itself, on every push (never cancelled), at night and in the release check (the release
keeper's manual `ci` run with `windows=true`). On a push to develop and at night there is no merge left to stop: a
red part there (known red aside) opens the release keeper's red-develop ticket, to be fixed by a pull request first
in the queue.

¹ While Windows is known red, `scripts/touches_os_code.py --pr` answers `false` on every pull request, so the
Windows parts run only on develop pushes, nightly and the release check (or a manual run with `windows=true`).
Once Windows is green (KNOWN_RED empty), a pull request that changes file, process or path code runs them again.

² A light pull request that changes file, process or path code while Windows is green runs the workspace job
with its Windows parts (`scripts/touches_os_code.py --pr`); while Windows is known red that never happens.

A draft pull request gets no CI run; marking it ready starts one.

## Known red

The systems in `KNOWN_RED` (`.github/workflows/workspace.yml`). Every row needs an owner and an end date;
`scripts/ci_known_red.py --warn` writes a warning on every `ci` run when one is missing or the end date has passed,
and `brand/tests/test_ci_known_red.py` fails when this table and `KNOWN_RED` disagree.

| System | Owner | End date | Ticket | Why |
|---|---|---|---|---|

When a system turns green: empty `KNOWN_RED` (or remove the system) and remove its row here in the same pull request.

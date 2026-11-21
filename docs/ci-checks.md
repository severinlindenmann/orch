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
read the whole tree (`RULE_TESTS` plus every file named `test_no_*`, `test_*_lint`, `test_*_seams`, `test_*_scan_doors`,
`test_*names*` or `test_spawn_argv`, and the node ids in `RULE_NODES`; about 25 s; they made most red queue groups on
18-19 Nov), the suites of the add-ons it changed, the click-throughs it changed and the Focus/Insights page smoke
when those add-ons change. A new rule test runs on every pull request by its file name alone.

Before a group is pushed the merge queue runs `python scripts/ci_light.py --rules` (the whole-tree checks above that
take seconds) on the group's merged tree on this computer (setting `[pull_requests] precheck = "uv run --project
workspace python scripts/ci_light.py --rules"`, about 35 s). Red: the base alone first (red there too = a broken
setting, nobody blamed), then each member on its own; a member red alone leaves the queue at once with the failing
lines, instead of after a 16 minute group run. The full set runs **once per merge queue group** (`orch-queue/…`) on top of develop, whatever
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
| workspace, Windows (20 parts, split by measured time, 20-minute limit) | not while known red ¹ | not run ³ | shown (known red), also when proven ³ | shown (known red) | shown (known red), in the release check |
| Windows install as a standard user | not while Windows is known red ¹ | | runs | runs | required, in the release check |
| CLI smoke, Windows + macOS | | required, always | | | required |
| e2e smoke (5 minutes) | | required, always | | | required |
| add-on suites, page smoke | in light (changed add-ons only) | required, always | runs unless proven | | required |
| dashboard click-throughs | in light (changed add-ons only) | not run, for now ³ | runs, also when proven ³ | | required |
| clock (suites at 22:30 and 23:59:40 UTC, 4 parts each: ORCH-1118) | | required, always | runs unless proven | runs | required |
| contracts, publish, relay | required | required (contracts always) | runs unless proven | | required |
| mobile | required (smoke set) | not run (owner, 20 Nov: ORCH-1118) | runs, full suite, also when proven | runs, with phone UI tests | required |
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

³ For now (ORCH-1106, owner 20 Nov): queue groups skip the click-throughs and the Windows parts, so a flaky
click-through or a Windows part at its time limit no longer drops a group (17 green and 81 red groups on 20 Nov).
Both still run on every push to develop, also one a green group proved (then only they run), and on a release
pull request; a red one on develop opens the red-develop ticket as before. Switch back when ORCH-555 and ORCH-1050
are done and 20 groups in a row were green with them: the note at the top of `ci.yml`,
`brand/tests/test_ci_queue_skip.py`.

## Windows on our own Windows VM (ORCH-1127)

The repository variable `WINDOWS_RUNNER=winvm` moves the Windows parts of develop pushes and of the nightly run
off GitHub's machines. On this Mac, `e2e/winvm/dispatch.py` (an orch service) then runs the Windows test parts,
the Windows CLI smoke (with the junction check) and the standard-user install in a fresh winvm clone of the golden image (4 CPUs, 8 GB) and removes the clone
afterwards, even after a failed or stopped run. It runs one clone at a time, in this order: the head of every open
release pull request, the develop head once a night after 01:00 UTC, then the newest develop commit. Commits
pushed while the clone was busy are skipped. A failed run is run once more before it counts. The result goes on
the commit as the status `windows (winvm)`, and a failed one on develop opens the red-develop ticket
(`releasekeeper.winvm_red`).
The VM is ARM64, so release checks and pull requests keep GitHub's x86-64 Windows run.
**Switch back:** delete the variable or set it to `github`. GitHub runs the Windows parts again on the next push,
and the dispatcher stays idle. Logs: `~/.orch-test/winvm-runs/` on the Mac.

A draft pull request gets no CI run; marking it ready starts one.

Time limits (ORCH-1050): every workspace part has a limit (15 minutes, Windows 20) and a "Time used" step that writes
a warning once a part passes 70 percent of it. Windows parts are split by measured time
(`workspace/tests/ci_times_windows.json`, `--part-times`); every Windows part uploads its test times as the
`ci-times-windows-<K>` artifact. When a part nears its limit, refresh the file from one run's artifacts:
`python tests/ci_parts.py merge tests/ci_times_windows.json <downloaded ci-times.json files>`. The release keeper runs
a develop job that hit its time limit with no failed test once more before it blocks a release; a red release check
already gets one more try (ORCH-1023).

## Known red

The systems in `KNOWN_RED` (`.github/workflows/workspace.yml`). Every row needs an owner and an end date;
`scripts/ci_known_red.py --warn` writes a warning on every `ci` run when one is missing or the end date has passed,
and `brand/tests/test_ci_known_red.py` fails when this table and `KNOWN_RED` disagree.

| System | Owner | End date | Ticket | Why |
|---|---|---|---|---|

When a system turns green: empty `KNOWN_RED` (or remove the system) and remove its row here in the same pull request.

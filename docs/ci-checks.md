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
18-19 Nov), the suites of the add-ons it changed, the click-throughs it changed. When it changes the Focus or Insights
add-on, their page smoke runs next to it as its own job `page-smoke` (about 6 minutes, ORCH-1333). A new rule test runs on every pull request by its file name alone.

Before a group is pushed the merge queue runs `python scripts/ci_light.py --rules` (the whole-tree checks above that
take seconds) on the group's merged tree on this computer (setting `[pull_requests] precheck = "uv run --project
workspace python scripts/ci_light.py --rules"`, about 35 s). Red: the base alone first (red there too = a broken
setting, nobody blamed), then each member on its own; a member red alone leaves the queue at once with the failing
lines, instead of after a 16 minute group run. The full set runs **once per merge queue group** (`orch-queue/…`) on top of develop, whatever
files the group touches. A push to develop whose files equal a green queue group (`scripts/ci_proven.py`: a merge
commit with the tree of its second parent, and a green `ci` run of that parent on an `orch-queue/` branch) runs no
suite again. Contracts, publish, relay, mobile and the dashboard pictures still follow their paths on a pull request.
With the queue setting `group_check = local` (ORCH-1124) the queue checks a group with the local check on this Mac
instead: its group pull request carries `orch-group-check: local`, ci.yml and rules.yml skip it, and the push to
develop runs the full set because a skipped group run proves nothing.

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
| add-on suites | in light (changed add-ons only) | required, always | runs unless proven | | required |
| page smoke (Focus and Insights pages, Focus click-through) | in light (changed add-ons only), as its own job `page-smoke` when Focus or Insights changed (ORCH-1333) | required, always | runs, also when proven (ORCH-1457) | | required |
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

## Mac jobs on this Mac's own runner (ORCH-1125)

The phone build and UI tests, the macOS workspace part, the dashboard click-throughs, the page smoke, the dashboard
pictures and the Python 3.11 checks can run on a GitHub runner on the development Mac instead of GitHub's machines.
ci.yml's `route` job (`scripts/mac_route.py`) decides once per run:

- **Only trusted runs**: a push to develop, the nightly run, a manual run and a release pull request (into main, from
  a branch of this repository). Pull requests into develop, merge queue groups and every pull request from a fork
  stay on GitHub's machines. The runner's job hook refuses the same again on the Mac.
- **One setting moves them back**: repository variable `MAC_RUNNER`. `this-mac` = this Mac; anything else or unset
  = GitHub's machines (the default). It only steers orch's own workflows: it does not close the runner. The off
  switch in an emergency is `sudo bash scripts/mac-runner/uninstall.sh` plus removing the runner on GitHub.
- **Offline = GitHub by itself**: the route reads the runner list with the repository secret
  `MAC_RUNNER_STATUS_TOKEN` (a fine-grained token for this repository only, "Administration: read"; it lives in
  GitHub, never on the Mac). No secret, no answer or no online runner with the label `orch-mac`: GitHub's machines.
- **Busy**: a develop push while the runner is busy goes to GitHub's machines; set `MAC_RUNNER_WHEN_BUSY=wait` to
  queue it on the Mac instead. The nightly run, manual runs and release pull requests always wait for the Mac.
- **Clean run per job**: own hidden macOS user `orch-ci` (cannot read the owner's home or `~/.orch-tool`). A loop
  owned by root (`scripts/mac-runner/runner-loop.sh`) starts the runner for ONE job at a time and, before each job,
  stops everything of `orch-ci`, makes a fresh runner folder from a read-only copy owned by root and empties
  `orch-ci`'s home (only the Simulators stay). Each job also gets a throwaway home with its own download caches
  (`.github/actions/mac-job-home`). Nothing a job changes or leaves reaches the next job. No owner secrets on the Mac.
- **No private network**: a pf rule (`scripts/mac-runner/pf-orch-ci.conf`) closes the private network and the local
  network to `orch-ci`; the internet stays open. The loop starts no runner while the rule is not in place.
- **A refused job never runs a step**: the job-started hook stops the job's worker process at once (a failed hook
  alone would still run later `if: always()` steps).
- **No job setting runs before the hook**: the runner starts its hooks with `bash` from its own PATH, and that is
  `scripts/mac-runner/bash`: privileged bash with an empty environment, so `BASH_ENV`, `SHELLOPTS` or functions a
  job sets (a fork's workflow file can name any runner) never run before the hook refuses the job.
- **What stays open** (owner's choice, no admin key on the Mac): a job can read the runner's own registration and could
  take jobs with it elsewhere until it is removed; after anything suspicious run `uninstall.sh`, remove the runner
  on GitHub and run `setup.sh` again. pf covers TCP and UDP only (ping still works) and not a LAN host with a public
  IPv6 address; services on this Mac's own 127.0.0.1 stay reachable, so they must ask for a login. Each round
  ends after 4 hours at the latest, so a job cannot keep the runner for itself.
- **GitHub's own lock**: every outside contributor's run waits until the owner clicks (step 1 below; `setup.sh`
  checks it). Helper accounts never approve a workflow run from a fork; only the owner does, after reading it.
- **Shares the Mac with helpers**: each job holds the shared `heavy` lock, xcodebuild the `xcode` lock
  (`scripts/mac-runner/lock.sh`, folder `/Users/Shared/orch-locks`, group `orch-locks`); the macOS workspace suite
  is one part at `-n 6` there.

Turn it on (owner, admin rights):
1. Settings > Actions > General > "Fork pull request workflows from outside collaborators": pick the strictest
   choice, the one for all external contributors (a fork's workflow file can name any runner; nothing runs until
   you click).
2. On the Mac: `sudo bash scripts/mac-runner/setup.sh` (asks for the runner registration token from
   Settings > Actions > Runners > New self-hosted runner; used once, never stored). Run it again to take a new
   runner version: the runner does not update itself.
3. A fine-grained token for this repository only, permission "Administration: read", as the Actions secret
   `MAC_RUNNER_STATUS_TOKEN`.
4. The Actions variable `MAC_RUNNER` = `this-mac`. Back to GitHub's machines: change or delete it.

Off and undo on the Mac: `sudo bash scripts/mac-runner/uninstall.sh`, then remove the runner under Settings >
Actions > Runners.

## Linux jobs on the orch edge test server (ORCH-1126)

The clock tests (fake wall clock), relay, publish, the short e2e set and the Services add-on with its real Linux run
can run on a GitHub runner on the orch edge test server (Debian, ARM64, 8 cores, 8 GB) instead of GitHub's machines.
Never on a production server. There the jobs use uv's own Python builds (`UV_PYTHON_PREFERENCE=only-managed`), and
the clock tests keep real file times as on GitHub (`NO_FAKE_STAT=1`: libfaketime would shift the file times a
program reads but not the ones it sets).
The same `route` job decides (`scripts/edge_route.py`), with the Mac's rules:

- **Only trusted runs**: a push to develop, the nightly run, a manual run and a release pull request. Pull requests
  into develop, queue groups and forks stay on GitHub's machines; the runner's job hook refuses them again.
- **One setting moves them back**: repository variable `EDGE_RUNNER`. `orch-edge` = orch edge; anything else or
  unset = GitHub's machines (the default), with every job exactly as before.
- **Offline = GitHub by itself**: the route reads the runner list with the same secret `MAC_RUNNER_STATUS_TOKEN`.
  No secret, no answer or no online runner with the label `orch-edge`: GitHub's machines.
- **Busy**: a develop push while the runner is busy goes to GitHub's machines (`EDGE_RUNNER_WHEN_BUSY=wait` queues
  it instead). The nightly run, manual runs and release pull requests always wait for orch edge.
- **All of them after every merge**: when the jobs go to orch edge they all run, whatever files changed (a queue
  group no longer has to have run them).
- **x86-64 before every release**: orch edge is ARM64, so a release pull request runs the Linux jobs on orch edge
  AND on GitHub's x86-64 machines. Binaries are named by their machine (`orch-relay-linux-aarch64` / `-x86_64`).
- **Clean run per job** (the Mac's security review ORCH-1233, same fixes): own user `orch-ci` (cannot read the other
  homes). A loop owned by root (`scripts/edge-runner/runner-loop.sh`) starts the runner for ONE job at a time and,
  before each job, stops everything of `orch-ci` and its user services, makes a fresh runner folder (with a fresh
  work folder) from a read-only copy owned by root, empties `orch-ci`'s home and its files in `/tmp`, `/var/tmp` and
  `/dev/shm` (and every other file of `orch-ci` anywhere). Each job gets a throwaway home with its own download caches, Rust included
  (`.github/actions/edge-job-home`; on disk, Debian keeps `/tmp` in memory), 4 test workers and 4 build jobs, the
  runner capped at 5 GB and its user services at 1.5 GB so the test copies of relay, publish and hub keep running.
  Nothing a job changes or leaves reaches the next job. No owner secrets on orch edge.
- **No private network**: an nftables rule (`scripts/edge-runner/nft-orch-ci.nft`) closes the private network, the
  local network and orch edge's own private addresses to `orch-ci` (every protocol); the internet and 127.0.0.1 stay
  open. The loop starts no runner while the rule is not in place.
- **No job setting runs before the hook**: the runner starts its hooks with `bash` from its own PATH, and that is
  `scripts/edge-runner/bash`: privileged bash with an empty environment, so `BASH_ENV`, `SHELLOPTS` or functions a
  job sets (a fork's workflow file can name any runner) never run before the hook refuses the job. A refused job
  never runs a step: the hook stops the job's worker process at once.
- **What stays open**: a job can read the runner's own registration and could take jobs with it elsewhere until it
  is removed; after anything suspicious run `uninstall.sh`, remove the runner on GitHub and register again. Services
  on orch edge's own 127.0.0.1 stay reachable for a job. A round ends 60 minutes after its job started (4 hours with
  no job), so a job cannot keep the runner for itself for long; before the next job the loop removes every file of
  `orch-ci` on every writable filesystem, so nothing a job planted (a library for `LD_PRELOAD`) waits for the next.
- **GitHub's own lock**: every outside contributor's run waits until the owner clicks (below). Helper accounts never
  approve a workflow run from a fork; only the owner does, after reading it.

Set up (done; `sudo bash scripts/edge-runner/setup.sh` again is safe): packages (faketime, build tools, tmux,
Chromium's libraries, nftables), the user, the runner copy, its hooks, the clean bash, the network rule and the loop.
Register (manager, with the owner's login; the token is used once and never stored). First make sure Settings >
Actions > General > "Fork pull request workflows from outside collaborators" is the strictest choice (the same
setting `scripts/mac-runner/setup.sh` checks in its step 5; the manager's command on ticket ORCH-1126 checks it and
stops otherwise). Then:

    gh api -X POST repos/severinlindenmann/orch/actions/runners/registration-token --jq .token \
      | ssh orch-edge 'sudo bash /opt/orch-edge-runner-src/setup.sh register'

Then the Actions variable `EDGE_RUNNER` = `orch-edge` (the secret `MAC_RUNNER_STATUS_TOKEN` from the Mac step serves
both):

    gh variable set EDGE_RUNNER --repo severinlindenmann/orch --body orch-edge

Back to GitHub's machines: change or delete the variable (the runner stays registered). Off and undo on orch edge:
`sudo bash scripts/edge-runner/uninstall.sh`, then remove the runner under Settings > Actions > Runners.

"""The release keeper (`orch github release`, ORCH-225): takes a release from green develop to installed on
this computer, for a repeating automation (no AI call; a pass with nothing to do costs no tokens and writes
nothing).

One pass moves the release one phase on (state: .orch/run/release-keeper.json):
  idle     develop has unreleased pull requests and the last release is MIN_GAP_H (3) hours ago or more, or
           one of them carries the GitHub label urgent: the candidate is the newest fully green develop
           commit (ORCH-314). Covered already when the nightly runs of the release workflows on that very
           commit are green; else the keeper dispatches them itself on a branch release-test/<N>-<sha> at
           that commit, so they run on it and not on a newer develop head (ORCH-1475) -> testing. Runs are
           judged job by job: the roll-up job (ROLLUP_JOBS) and known-red jobs (--known-red <job>=<ticket>,
           while that ticket is open) neither block nor wait; they are named in the highlights.
  testing  every run on the candidate green -> cut: branch release/part<N>-<MMDD> from the candidate in
           its own worktree, merge main with -s ours (tree equals develop), push, open the pull request
           into main -> its checks. A red run -> one top ticket (a helper starts at once) and the candidate is
           skipped until develop moves.
  gate     the release pull request's checks: green -> the Merge card on the role ticket (orch ask
           --merge --release) -> card. Red -> its failed jobs run once more (a flaky test, ORCH-1023); red
           again -> one top ticket; when develop moves past it the old pull
           request is closed and the release is cut again from scratch.
  card     `orch review tend-releases` merges it when the owner allowed it (workflow.release_merge), also
           when its only red checks have a named exception (ORCH-178);
           otherwise the owner clicks Merge. Merged -> installed.
  merged   `orch update` here; when a server folder (github.release_servers) changed the deploy is prepared
           (the CI-built program fetched and checked, production's program read over ssh, read only, new
           settings and data changes listed) and a deploy card asked (production: the owner's go; on "Deploy
           now" a helper ticket gets the prepared program), the highlights as a short note on the role ticket,
           the release worktree removed -> idle.
Release proof (ORCH-456): a red check holds the release unless a person recorded a named exception for it
(`orch github release-exception "<check>" --ticket <key> --until <date>`, shown on the Merge card and in the
note; the keeper records one itself, for FIX_DAYS, when its "Release N checks are red" ticket links a fix pull
request, ORCH-178); and the walks named in github.release_walks (install walk, services test, click-through
pass) each get a helper ticket when the release is cut; the Merge card waits until every walk recorded a pass
(`orch github release-walk <N> <walk> pass|fail "<line>"`). A release that reached main without that proof
is written on the role ticket.
A red after-merge run on develop (ORCH-1128; the workflows of github.release_after_merge, default the first
release workflow): its failed jobs run once more (GitHub's attempt counter, so never twice); still red opens
the red-develop fix ticket, whose pull request goes first in the merge queue (pull-requests add-on); when no
pull request of that ticket is in the queue REVERT_AFTER_H (2) hours after it opened, the pull request that
broke develop is undone by a revert pull request through the queue (never a push), only when one suspect is
clear (the only merge since the last green commit, or the only one that touched what the failed tests name).
A release is cut only from a develop commit where every after-merge workflow finished green.
Every pass also runs the security check (secreview.py, ORCH-317): pull requests touching the servers, sign-in,
secrets or what leaves this computer get a security review helper by themselves, and the idle phase cuts
nothing until each of them in the release has an OK.
A run or release check that is red only because jobs hit their time limit with no failed test in their log is
run once more (per run and release) before the release is blocked or closed (ORCH-1050).
A release pull request the keeper did not cut is only watched. `orch github release-hold "<why>"` stops
cutting (a running release goes on); `orch github release-hold off` lifts it.

Off until the owner names the role ticket, the repository and the local clone (`orch config set
github.release_keeper <ticket>`, `github.release_repo <owner/name>`, `github.release_clone <folder>`). Nothing
happens while automation is paused. The keeper's own GitHub and git writes (push, release pull request,
dispatch, close) run with the login of github.release_env (a shell file sourced first) and are checked to be
github.release_bot before the first write; the merge into main is never the keeper's: it is the owner's
click or `orch review tend-releases` with the owner's own gh login.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orch import brake, config, runs, secdelta, secreview, tickets
from orch.errors import Refused

BY = "agent:release-keeper"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
LOGIN_RE = re.compile(r"^[A-Za-z0-9-]{1,39}$")
HOST_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}@[A-Za-z0-9_.:-]{1,253}$")
SERVER_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
WALK_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}(=[A-Za-z0-9:_-]{1,60})?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WORKFLOW_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}\.ya?ml(:[A-Za-z0-9_-]{1,40}=[A-Za-z0-9_.-]{0,80})*$")
TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")

MIN_GAP_H = 3  # at most one release this often while pull requests wait (manager, 17 Nov) ...
URGENT_LABEL = "urgent"  # ... at once for a merged pull request with this GitHub label
# A pull request labelled "fix for release 33" is checked alone in the merge queue and, once merged into
# develop, shipped at once as release 33.1 (main + only that change), without pace or other work (ORCH-552).
FIX_LABEL_RE = re.compile(r"^fix[ -]for[ -]release[ -]([1-9][0-9]{0,5})$", re.IGNORECASE)


def fix_target(labels) -> int | None:
    """The release a pull request fixes, from its GitHub labels ("fix for release 33" -> 33), else None."""
    for lb in labels or []:
        name = lb.get("name") if isinstance(lb, dict) else lb
        hit = FIX_LABEL_RE.match(name) if isinstance(name, str) else None
        if hit:
            return int(hit[1])
    return None


ROLLUP_JOBS = {"gate"}  # a roll-up of the other jobs: the jobs themselves are judged
# The checks a release pull request must REPORT before it is judged: the required checks of the branch it goes
# INTO (main). main has none of its own today, so the roll-up. Never develop's: develop's banned-words is
# skipped on release/* into main by design.
REQUIRED_FALLBACK = ["gate"]
# Flaky checks out of the merge queue run in this workflow (ORCH-2363): nightly on develop and on every push
# to a release branch, never required. Its checks never count for a release pull request; a red nightly run
# opens one "later" ticket (quarantine_red).
QUARANTINE_WORKFLOW = "quarantine"
QUARANTINE_FILE = "quarantine.yml"
QUARANTINE_WORDS = "Quarantined CI checks are red (later)"
# A job GitHub stopped at its timeout-minutes (the check run's annotation) whose log has no failed test runs
# once more per release before the release is blocked or closed (ORCH-1050).
TIME_LIMIT_RE = re.compile(r"exceeded the maximum execution time", re.I)
FAILED_TEST_RE = re.compile(r"\bFAILED\s+\S+::|\b\d+ (?:failed|errors?)\b")
PASSED_RE = re.compile(r"\b\d+ passed\b[^\n]* in [\d.]+s\b")  # pytest's closing line
REVERT_AFTER_H = 2  # a red develop with no fix in the merge queue this long: revert the suspect (ORCH-1128)
QUEUE_ADDON = "pull-requests"  # the merge queue add-on: its queue file is read, its add command run
TAKE_IN = re.compile(r"^Merge queue: take in #(\d+)$")  # a member of a merge queue group
TEST_TIMEOUT_H = 4  # dispatched runs that have not finished after this: say it once, dispatch again next pass
# The full-signal runs are dispatched on a branch of their own that points at the picked commit (ORCH-1475,
# #1508): `gh workflow run --ref develop` runs on develop's HEAD, which is often newer than the green commit a
# release is cut from, so the keeper waited for runs that were never started. Removed when testing ends.
TEST_BRANCH = "release-test/"
KEEP_STAGED = 2  # newest prepared programs kept per server (rollback)
PASSED = ("SUCCESS", "SKIPPED", "NEUTRAL")
DONE = {"done", "dropped", "wontdo", "archived"}
STATE_MAX = 512 * 1024
NOTE_MAX = 1900
TITLE_MAX = 90
MERGE_LINE = re.compile(r"^Merge pull request #(\d+) from \S")  # GitHub's own merge commit subject
RELEASE_MERGE = re.compile(r"Release \d+: merge main")
DEPLOY_ASK = "changed the"  # words of the deploy card, found again in the answer

# ---------------------------------------------------------------- settings

SETTINGS = {
    "github.release_keeper": "the role ticket (questions, notes, parent of red tickets)",
    "github.release_repo": "owner/name of the repository",
    "github.release_clone": "the local git clone the release worktrees come from",
    "github.release_worktrees": "the folder for release worktrees (default: beside the clone)",
    "github.release_workflows": "the full-signal workflows, e.g. ci.yml:windows=true,e2e.yml",
    "github.release_env": "a shell file that sets the bot's GitHub login for the keeper's writes",
    "github.release_bot": "the GitHub login the keeper's writes must use",
    "github.release_servers": "folders whose change needs a production deploy, e.g. relay,publish",
    "github.release_deploy_host": "user@host of production, read only over ssh (program checksum)",
    "github.release_deploy_key": "the ssh key for that read",
    "github.release_deploy_script": "the install command the deploy helper runs after the owner's go",
    "github.release_security_paths": "files whose change needs a security review before a release "
    "(default: servers, sign-in, secrets, what leaves this computer, CI)",
    "github.security_reviews_per_day": "security review helpers the keeper starts for one release "
    f"(default {secreview.PER_DAY}; counts again after each release)",
    "github.security_review_call": "commands that give each security review a first look as one call, tried "
    "in order, comma separated, each a full path and its words; {prompt} is the prompt file (also on stdin). "
    "A helper runs only when the call finds High or Medium or fails (default: none, a helper every time)",
    "github.release_walks": "walks every release needs before its Merge card, each a name or name=skill, "
    "e.g. install=release-walk,services,clickthrough",
    "github.release_after_merge": "the workflows every develop commit must pass after the merge, e.g. "
    "ci.yml,after-merge.yml (default: the first release workflow)",
    "github.release_revert_hours": f"hours a red develop waits for a fix in the merge queue before the "
    f"keeper opens a revert pull request (default {REVERT_AFTER_H}; never: no revert)",
}
SETTING_KEYS = tuple(SETTINGS)


def _raw(root: Path | None, name: str) -> str | None:
    if root is None:
        return None
    try:
        v = (config.read(root).get("github") or {}).get(name)
    except (Refused, OSError):
        return None
    return v.strip() if isinstance(v, str) and v.strip() else None


def get(root: Path | None, key: str) -> str | None:
    """The value of one github.release_* setting, or None."""
    return _raw(root, key.split(".", 1)[1])


def _path_ok(v: str) -> str:
    p = Path(v).expanduser()
    if not p.is_absolute():
        raise Refused("Give the full path of the folder or file.")
    return str(p)


def set_setting(root: Path, key: str, value: str) -> str | None:
    """`orch config set github.release_* <value>`; off clears it. Refused with a plain reason when wrong."""
    if key not in SETTINGS:
        raise Refused(f"Unknown setting {key}.")
    name = key.split(".", 1)[1]
    v = (value or "").strip()
    if v.lower() in ("off", "none", ""):
        config.set_key(root, "github", name, None)
        return None
    if name == "release_keeper":
        t = tickets.load(root, tickets.resolve(root, v))  # an unknown ticket is refused here
        v = str(t.get("key") or t["id"])
    elif name == "release_repo" and not REPO_RE.match(v):
        raise Refused("Name the repository as owner/name, for example acme/app.")
    elif name in ("release_clone", "release_worktrees", "release_env", "release_deploy_key"):
        v = _path_ok(v)
        if name == "release_clone" and not (Path(v) / ".git").exists():
            raise Refused(f"{v} is not a git clone.")
    elif name == "release_bot" and not LOGIN_RE.match(v):
        raise Refused("Give the GitHub login, for example acme-bot.")
    elif name == "release_deploy_host" and not HOST_RE.match(v):
        raise Refused("Give production as user@host.")
    elif name == "release_servers":
        parts = [x.strip() for x in v.split(",") if x.strip()]
        if not parts or any(not SERVER_RE.match(x) for x in parts):
            raise Refused("Give the server folders separated by commas, for example relay,publish.")
        v = ",".join(parts)
    elif name == "release_workflows":
        parts = [x.strip() for x in v.split(",") if x.strip()]
        if not parts or any(not WORKFLOW_RE.match(x) for x in parts):
            raise Refused(
                "Give workflow files separated by commas, inputs after a colon: ci.yml:windows=true,e2e.yml"
            )
        v = ",".join(parts)
    elif name == "release_deploy_script":
        v = _path_ok(v)
    elif name == "release_security_paths":
        v = secreview.check_patterns(v)
    elif name == "security_reviews_per_day":
        v = secreview.check_limit(v)
    elif name == "security_review_call":
        from orch import seccall, worktrees

        if worktrees._agent_ticket(root) is not None:  # a helper must not pick who reviews (ORCH-1591)
            raise Refused("Only a person sets who gives security reviews their first look.")
        v = seccall.check_commands(v)
    elif name == "release_after_merge":
        parts = [x.strip() for x in v.split(",") if x.strip()]
        if not parts or any(not WORKFLOW_RE.match(x) or ":" in x for x in parts):
            raise Refused("Give workflow files separated by commas: ci.yml,after-merge.yml")
        v = ",".join(parts)
    elif name == "release_revert_hours":
        v = v.lower()
        if v != "never":
            try:
                ok = 0 < float(v) <= 72
            except ValueError:
                ok = False
            if not ok:
                raise Refused("Give the hours as a number from 0.5 to 72, or never.")
    elif name == "release_walks":
        parts = [x.strip() for x in v.split(",") if x.strip()]
        if not parts or any(not WALK_RE.match(x) for x in parts):
            raise Refused(
                "Give the walks separated by commas, each a short name or name=skill: "
                "install=release-walk,services,clickthrough"
            )
        v = ",".join(parts)
    config.set_key(root, "github", name, v)
    return v


def workflows(spec: str | None) -> list[tuple[str, list[str]]]:
    """[(file, dispatch inputs as gh flags)] from "ci.yml:windows=true,e2e.yml"."""
    out = []
    for item in [x.strip() for x in (spec or "ci.yml").split(",") if x.strip()]:
        name, *inputs = item.split(":")
        flags: list[str] = []
        for kv in inputs:
            flags += ["-f", kv]
        out.append((name, flags))
    return out


def walks(spec: str | None) -> list[tuple[str, str | None]]:
    """[(walk name, skill or None)] from "install=release-walk,services"."""
    out = []
    for item in [x.strip() for x in (spec or "").split(",") if x.strip()]:
        name, _, skill = item.partition("=")
        out.append((name, skill or None))
    return out


class Cfg:
    """The keeper's settings for one pass."""

    def __init__(self, root: Path | None = None, **over):
        g = lambda n: over.get(n, _raw(root, f"release_{n}"))  # noqa: E731
        self.role = g("keeper")
        self.repo = g("repo") or "owner/repo"
        clone = g("clone")
        self.clone = Path(clone) if clone else None
        wts = g("worktrees")
        self.worktrees = (
            Path(wts) if wts else (self.clone.parent / f"{self.clone.name}-releases" if self.clone else None)
        )
        self.workflows = workflows(g("workflows"))
        self.env = Path(g("env")) if g("env") else None
        self.bot = g("bot")
        self.servers = tuple(x for x in (g("servers") or "").split(",") if x)
        self.deploy_host = g("deploy_host")
        self.deploy_key = Path(g("deploy_key")) if g("deploy_key") else None
        self.deploy_script = g("deploy_script")
        self.security_paths = g("security_paths")
        self.security_limit = over.get("security_limit", _raw(root, "security_reviews_per_day"))
        self.security_call = over.get("security_call", _raw(root, "security_review_call"))
        self.walks = walks(g("walks"))
        am = [x.strip() for x in str(g("after_merge") or "").split(",") if x.strip()]
        self.after_merge = am or [self.workflows[0][0] if self.workflows else "ci.yml"]
        rh = str(g("revert_hours") or REVERT_AFTER_H).strip().lower()
        try:
            self.revert_hours: float | None = None if rh == "never" else float(rh)
        except ValueError:
            self.revert_hours = float(REVERT_AFTER_H)
        self.run_dir = runs.run_dir(root) if root is not None else Path(over.get("run_dir") or ".")

    @property
    def state_path(self) -> Path:
        return self.run_dir / "release-keeper.json"

    @property
    def deployed_path(self) -> Path:
        return self.run_dir / "release-deployed.json"

    @property
    def hold_path(self) -> Path:
        return self.run_dir / "release-hold.txt"

    @property
    def exceptions_path(self) -> Path:
        return self.run_dir / "release-exceptions.json"

    @property
    def walks_path(self) -> Path:
        return self.run_dir / "release-walks.json"

    @property
    def stage_dir(self) -> Path:
        return self.run_dir / "release-staged"


# ---------------------------------------------------------------- time and checks (pure)


def now() -> datetime:
    return datetime.now(UTC)


def ts(s) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00")) if s else None
    except ValueError:
        return None
    return d if d is None or d.tzinfo else d.replace(tzinfo=UTC)


SHARD = re.compile(r", [0-9]{1,3}/[0-9]{1,3}\)")


def known_name(name: str, names) -> str | None:
    """The entry of `names` that covers job `name`: the same name, or the job without its part. A job split
    into parts (ORCH-315, "workspace / test (windows-latest, 3/6)") is covered by "workspace / test
    (windows-latest)", so a known-red entry keeps working when CI splits the job."""
    if name in names:
        return name
    for n in names:  # only a part number ("3/6") is added; another matrix axis is another job
        if n.endswith(")") and name.startswith(n[:-1] + ", ") and SHARD.fullmatch(name[len(n) - 1 :]):
            return n
    return None


def _ignored(c: dict, ignore) -> bool:
    """A check that does not count: named in `ignore` (known red, roll-ups) or of the quarantine workflow."""
    return (
        c.get("workflowName") == QUARANTINE_WORKFLOW
        or known_name(c.get("name") or c.get("context") or "", ignore) is not None
    )


def checks_green(rollup, ignore=frozenset()) -> str:
    """green, red or pending for a pull request's statusCheckRollup (newest run of each check counts); checks
    named in `ignore` (known red, roll-ups) and those of the quarantine workflow do not count."""
    rollup = [c for c in rollup or [] if not _ignored(c, ignore)]
    if not rollup:
        return "pending"
    last: dict = {}
    for n, c in enumerate(rollup):
        key = (c.get("workflowName"), c.get("name") or c.get("context") or n)
        when = str(c.get("startedAt") or "")
        if key not in last or when >= last[key][0]:
            last[key] = (when, c)
    state, good = "green", 0
    for _, c in last.values():
        if "state" in c and "status" not in c:
            word = c.get("state")
            if word == "PENDING":
                state = "pending" if state == "green" else state
                continue
        elif c.get("status") != "COMPLETED":
            state = "pending" if state == "green" else state
            continue
        else:
            word = c.get("conclusion")
        if word not in PASSED:
            return "red"
        good += word == "SUCCESS"
    return state if good or state != "green" else "pending"


RUN_URL = re.compile(r"/actions/runs/(\d+)")


def _newest_failed(rollup, ignore=frozenset()) -> list[dict]:
    """The failed checks, the newest try of each (not ignored)."""
    last: dict = {}
    for n, c in enumerate(rollup or []):
        name = c.get("name") or c.get("context") or ""
        if _ignored(c, ignore):
            continue
        key, when = (c.get("workflowName"), name or n), str(c.get("startedAt") or "")
        if key not in last or when >= last[key][0]:
            last[key] = (when, c)
    out = []
    for _, c in last.values():
        word = c.get("conclusion") if "status" in c else c.get("state")
        if c.get("status") in (None, "COMPLETED") and word not in PASSED and word not in (None, "PENDING"):
            out.append(c)
    return out


def failed_runs(rollup, ignore=frozenset()) -> list[str]:
    """The Actions run ids of the failed checks (newest try of each check counts), for one more try."""
    out = []
    for c in _newest_failed(rollup, ignore):
        m = RUN_URL.search(str(c.get("detailsUrl") or c.get("targetUrl") or ""))
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def failed_before(rollup, since: datetime, ignore=frozenset()) -> bool:
    """A failed check whose newest try started before `since`: the run again has not reported it yet."""
    for c in _newest_failed(rollup, ignore):
        started = ts(c.get("startedAt"))
        if started is None or started < since:
            return True
    return False


def not_reported(rollup, names) -> list[str]:
    """The checks in `names` the pull request has not reported as finished yet (newest run of each counts)."""
    last: dict = {}
    for c in rollup or []:
        name = c.get("name") or c.get("context")
        when = str(c.get("startedAt") or "")
        if name in names and (name not in last or when >= last[name][0]):
            last[name] = (when, c)
    out = []
    for name in names:
        c = last.get(name, ("", None))[1]
        done = c is not None and (
            c.get("state") not in (None, "PENDING", "EXPECTED")
            if "state" in c and "status" not in c
            else c.get("status") == "COMPLETED"
        )
        if not done:
            out.append(name)
    return out


def failed_checks(rollup, ignore=frozenset()) -> list[str]:
    out = []
    for c in rollup or []:
        if _ignored(c, ignore):
            continue
        word = c.get("conclusion") if "status" in c else c.get("state")
        if (c.get("status") in (None, "COMPLETED")) and word not in PASSED and word not in (None, "PENDING"):
            out.append(str(c.get("name") or c.get("context") or "?"))
    return sorted(set(out))


# a failure line of a failed job's log (pytest -rfE, node --test, the click-throughs);
# `gh run view --log-failed` puts "<job>\t<step>\t<time> " in front of each line
_FAILED_LINE = re.compile(r"^(?:[^\t\n]*\t[^\t\n]*\t\S+ )?\s*(?:FAILED|ERROR|not ok|✖)\s.*$", re.MULTILINE)
_TEST_FILE = re.compile(r"[\w./-]*?([\w-]+\.(?:py|cjs|mjs|js|ts|swift|rs))\b")
_WORD = re.compile(r"[a-z0-9]+")
_NOISE = frozenset(
    {"test", "tests", "spec", "src", "py", "js", "cjs", "mjs", "ts", "rs", "swift", "the", "and"}
)


def failed_test_files(log: str, most: int = 20) -> list[str]:
    """The test file names a failed job's log names on its failure lines, in order, each once."""
    out: list[str] = []
    for line in _FAILED_LINE.findall(log or ""):
        for name in _TEST_FILE.findall(line):
            if name not in out:
                out.append(name)
    return out[:most]


def queue_merge(subject: str, repo: str) -> bool:
    """The merge commit of a merge queue group: GitHub's merge line for a branch orch-queue/... of the
    repository itself (a fork's branch of the same name is not the queue's)."""
    owner = repo.split("/", 1)[0]
    return (
        re.fullmatch(rf"Merge pull request #\d+ from {re.escape(owner)}/orch-queue/\S+", subject) is not None
    )


def _words(text: str) -> frozenset[str]:
    return frozenset(w for w in _WORD.findall(text.lower()) if len(w) >= 3 and w not in _NOISE)


def suspect(members: list[dict], tests: list[str]) -> dict | None:
    """The one pull request that broke develop, or None when that is not clear (no guessing: a wrong revert
    costs more than the wait). The only one merged since the last green commit; else the only one that changed
    a failed test file; else the only one whose changed paths share the most words with the failed tests'
    names (test_sessions.py -> sessions)."""
    if len(members) == 1:
        return members[0]
    if not members or not tests:
        return None
    names = set(tests)
    touched = [m for m in members if names & {Path(f).name for f in m.get("files") or []}]
    if len(touched) == 1:
        return touched[0]
    want = frozenset().union(*(_words(t) for t in tests))
    got = [(len(want & frozenset().union(*(_words(f) for f in m.get("files") or []))), m) for m in members]
    top = max(n for n, _ in got)
    best = [m for n, m in got if n == top]
    return best[0] if top and len(best) == 1 else None


def parse_known(items: list[str] | None) -> dict[str, str]:
    """--known-red "<job>=<ticket>": a job that is red for a known reason while that ticket is open."""
    out = {}
    for item in items or []:
        job, sep, tid = str(item).rpartition("=")
        if not sep or not job.strip() or not tid.strip() or len(job) > 120:
            raise Refused(
                '--known-red needs "<job name>=<ticket>", for example "workspace / test (windows)=ORCH-32".'
            )
        out[job.strip()] = tid.strip()
    return out


# ---------------------------------------------------------------- the world (every read and write outside)


class World:
    """Every read and write outside the keeper. `sim` (a recorded dict) replaces it in tests."""

    def __init__(self, root: Path | None, cfg: Cfg, sim: dict | None = None, dry: bool = False, known=None):
        self.root, self.cfg, self.sim, self.dry, self.did = root, cfg, sim, dry, []
        self.dispatched: list[tuple[str, str]] = []  # (workflow, ref) of every dispatch this pass
        self.left_branches: list[str] = []  # test branches whose deletion failed this pass (ORCH-1475)
        self.known_table = dict(known or {})
        self._bot_checked = False
        self.gh = shutil.which("gh") or "gh"
        self.secret_hit: dict | None = None  # the line the release text's secret check stopped at

    # ---- processes (gh and git with the bot's login when github.release_env is set)
    def _run(self, argv, cwd=None, timeout=120) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k not in TOKEN_VARS}
        if self.cfg.env is not None:
            if not self.cfg.env.is_file():
                raise Refused(
                    f"the bot login file is missing ({self.cfg.env}): the keeper does not write as you"
                )
            argv = ["/bin/sh", "-c", '. "$0" && exec "$@"', str(self.cfg.env), *argv]
            env = dict(os.environ)
        try:
            return subprocess.run(
                argv,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
                stdin=subprocess.DEVNULL,
            )
        except OSError as e:
            raise Refused(f"{Path(str(argv[0])).name} could not start: {e}") from None

    def _git(self, *args, timeout=120) -> subprocess.CompletedProcess:
        return self._run(["git", "-C", str(self.cfg.clone), *args], timeout=timeout)

    def bot_ok(self) -> None:
        """Before the first write: gh must act as the bot (github.release_bot), never as the owner."""
        if self._bot_checked or not self.cfg.bot:
            return
        who = self._run([self.gh, "api", "user", "--jq", ".login"]).stdout.strip()
        if who != self.cfg.bot:
            raise Refused(f"gh does not act as the bot {self.cfg.bot} (it is {who or 'nobody'}): no write")
        self._bot_checked = True

    def _gh_json(self, args):
        r = self._run([self.gh, *args])
        if r.returncode != 0:
            raise Refused(f"gh {' '.join(args[:3])}: {(r.stderr or r.stdout).strip()[:200]}")
        try:
            return json.loads(r.stdout or "null")
        except ValueError:
            raise Refused("gh gave an answer that is not JSON") from None

    def orch(self, args: list[str], inp: str | None = None) -> subprocess.CompletedProcess:
        """`orch <args>` in this workspace with gh's own login (the owner's: token variables dropped)."""
        env = {k: v for k, v in os.environ.items() if k not in TOKEN_VARS}
        return subprocess.run(
            [sys.executable, "-I", "-P", "-m", "orch", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            input=inp,
            env=env,
        )

    # ---- reads
    def green_develop(self) -> str | None:
        """The newest develop commit whose own push runs finished green (ORCH-314), judged job by job like any
        other run (known-red jobs and the roll-up do not count): every workflow of the after-merge set
        (github.release_after_merge, ORCH-1128), so a commit with one of them red, running or missing is never
        a release candidate. develop's push runs are never cancelled, so every commit has an answer. None when
        none of the last ten push runs is green."""
        first, *rest = self.cfg.after_merge
        known = self.known_red()
        seen: set[str] = set()
        for r in sorted(self.runs(first, "push"), key=lambda x: str(x.get("createdAt")), reverse=True):
            sha = r.get("headSha")
            if not sha or sha in seen:
                continue
            seen.add(sha)
            if all(run_state(self, wf, sha, None, ("push",), known)[0] == "green" for wf in (first, *rest)):
                return sha
        return None

    def heads(self) -> dict:
        """{"develop": sha, "green": sha|None, "main": sha, "unreleased": [{sha, at, subject, title}]} after a
        fetch. green = the last fully green develop commit; unreleased = the merges main does not have, up to
        green (a release is cut from green only). title is the pull request's own title: GitHub writes it as
        the first line of the merge commit's body."""
        if self.sim is not None:
            return {"green": self.sim["heads"]["develop"], **self.sim["heads"]}
        self._git("fetch", "-q", "origin", timeout=180)
        dev = self._git("rev-parse", "origin/develop").stdout.strip()
        main = self._git("rev-parse", "origin/main").stdout.strip()
        green = self.green_develop()
        if green and self._git("merge-base", "--is-ancestor", green, dev).returncode != 0:
            green = None  # not on develop's history any more
        lg = (
            self._git(
                "log",
                "--first-parent",
                "--merges",
                "--format=%H%x1f%cI%x1f%s%x1f%b%x1e",
                f"origin/main..{green}",
            ).stdout
            if green
            else ""
        )
        rows = []
        for rec in lg.split("\x1e"):
            p = rec.strip("\n").split("\x1f")
            if len(p) == 4:
                title = next((ln.strip() for ln in p[3].splitlines() if ln.strip()), "")
                rows.append({"sha": p[0], "at": p[1], "subject": p[2], "title": title})
        return {"develop": dev, "green": green, "main": main, "unreleased": rows}

    def open_release(self) -> dict | None:
        if self.sim is not None:
            return self.sim.get("open_release")
        rows = self._gh_json(
            [
                "pr",
                "list",
                "--repo",
                self.cfg.repo,
                "--base",
                "main",
                "--state",
                "open",
                "--json",
                "number,url,title,headRefName,headRefOid",
            ]
        )
        return rows[0] if rows else None

    def pr(self, num: int) -> dict:
        if self.sim is not None:
            return self.sim["prs"][str(num)]
        return self._gh_json(
            [
                "pr",
                "view",
                str(num),
                "--repo",
                self.cfg.repo,
                "--json",
                "number,url,state,isDraft,headRefOid,statusCheckRollup,mergedAt,body,title",
            ]
        )

    _PR_FIELDS = "number,title,url,headRefOid,isDraft,files"  # open pull requests (security check)

    def changes(self) -> list[dict]:
        """Every first-parent change on develop since main (after heads() fetched): {sha, files, pr, head,
        title, url}. files is git's full list with renames as both names; pr and head come from GitHub's merge
        line ("Merge pull request #N from ...", head = the second parent), else None. Only a hint: the
        security check confirms them with GitHub (pr_for_commit)."""
        if self.sim is not None:
            return list(self.sim.get("changes") or [])
        lg = self._git("log", "--first-parent", "--format=%H%x1f%P%x1f%s", "origin/main..origin/develop")
        if lg.returncode != 0:
            raise Refused("git log could not read what develop has since main")
        out = []
        for ln in lg.stdout.splitlines():
            p = ln.split("\x1f", 2)
            if len(p) != 3 or not re.fullmatch(r"[0-9a-f]{40}", p[0]) or not p[1].split():
                raise Refused("git log gave a change it could not read: the release waits")
            sha, parents, subject = p[0], p[1].split(), p[2]
            d = self._git("diff", "--no-renames", "--name-only", "-z", parents[0], sha)
            if d.returncode != 0:
                raise Refused(f"git diff could not read the change {sha[:8]}")
            m = MERGE_LINE.match(subject)
            pr = int(m[1]) if m and len(parents) == 2 else None
            out.append(
                {
                    "sha": sha,
                    "files": [x for x in d.stdout.split("\0") if x],
                    "pr": pr,
                    "head": parents[1] if pr else None,
                    "title": subject[:120],
                    "url": f"https://github.com/{self.cfg.repo}/pull/{pr}" if pr else None,
                }
            )
        return out

    def pr_for_commit(self, sha: str) -> dict:
        """The pull request GitHub merged as this very commit (a squash or rebase merge): {pr, head, title,
        url}, or {} when there is none."""
        if self.sim is not None:
            return dict((self.sim.get("pr_for_commit") or {}).get(sha) or {})
        rows = self._gh_json(["api", f"repos/{self.cfg.repo}/commits/{sha}/pulls"]) or []
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict) and r.get("merge_commit_sha") == sha and r.get("number"):
                return {
                    "pr": int(r["number"]),
                    "head": ((r.get("head") or {}).get("sha")),
                    "title": str(r.get("title") or "")[:120],
                    "url": r.get("html_url"),
                }
        return {}

    OPEN_PR_LIMIT = 1000

    def open_prs(self) -> list[dict]:
        """The open pull requests into develop, with their files (security check)."""
        if self.sim is not None:
            return list(self.sim.get("open_prs") or [])
        args = ["pr", "list", "--repo", self.cfg.repo, "--state", "open", "--base", "develop"]
        # gh pages through the list up to --limit; 60 skipped every open pull request beyond the newest 60
        return self._gh_json([*args, "--limit", str(self.OPEN_PR_LIMIT), "--json", self._PR_FIELDS]) or []

    def security_verdicts(self) -> dict:
        if self.sim is not None:
            return dict(self.sim.get("security_verdicts") or {})
        return secreview.read_verdicts(self.root)

    # ---- ORCH-1591: what a new head changed since its reviewed head (secdelta.py), in the keeper's clone
    def _secgit(self, *args) -> tuple[int, str]:
        r = self._run(
            ["env", "GIT_NO_REPLACE_OBJECTS=1", "git", "-C", str(self.cfg.clone), *args], timeout=120
        )
        return r.returncode, r.stdout

    def _dev_tips(self) -> set[str] | None:
        if not hasattr(self, "_tips"):
            self._tips = secdelta.develop_tips(self._secgit) if self.cfg.clone else None
        return self._tips

    def _fetch_head(self, n: int, head: str) -> bool:
        """The commit in the clone (fetched from the pull request when missing); False when git has none."""
        if not secdelta.SHA.fullmatch(str(head or "")):
            return False
        if self._secgit("cat-file", "-e", f"{head}^{{commit}}")[0] == 0:
            return True
        self._secgit("fetch", "-q", "origin", f"+refs/pull/{int(n)}/head:refs/orch-security/{int(n)}")
        return self._secgit("cat-file", "-e", f"{head}^{{commit}}")[0] == 0

    def keep_check(self, n: int, reviewed: str, head: str, pats: tuple[str, ...]) -> dict:
        if self.sim is not None:
            return dict((self.sim.get("keep") or {}).get(f"{n}:{reviewed}:{head}") or {"kind": "full"})
        if not self.cfg.clone or not self._fetch_head(n, head) or not self._fetch_head(n, reviewed):
            return {"kind": "full", "why": "git could not get both commits"}
        return secdelta.keep_check(self._secgit, reviewed, head, pats, self._dev_tips())

    def group_steps(self, n: int, head: str, pats: tuple[str, ...]) -> list | None:
        if self.sim is not None:
            g = (self.sim.get("groups") or {}).get(str(n))
            return [tuple(x) for x in g] if g is not None else None
        if not self.cfg.clone or not self._fetch_head(n, head):
            return None
        return secdelta.group_steps(self._secgit, head, pats, self._dev_tips())

    def keep_verdict(self, n: int, rec: dict, expect: str | None) -> bool:
        """A kept OK for #n, only while #n's verdict is still the OK for `expect` (None: none needed)."""
        self.did.append(f"security-keep:#{n}")
        if self.sim is not None:
            self.sim.setdefault("security_verdicts", {})[str(n)] = rec
            return True
        if self.dry or self.root is None:
            return False
        return secreview.keep(self.root, n, rec, expect)

    def withdraw_kept(self, n: int, sha: str) -> None:
        self.did.append(f"security-withdraw:#{n}")
        if self.sim is not None:
            v = (self.sim.get("security_verdicts") or {}).get(str(n))
            if v and v.get("sha") == sha and v.get("kept_from"):
                self.sim["security_verdicts"].pop(str(n), None)
        elif not self.dry and self.root is not None:
            secreview.withdraw(self.root, n, sha)

    def call_state(self, n: int) -> dict:
        """The first-look call's own record for #n (seccall.py): {sha, pid, state, alive}."""
        if self.sim is not None:
            return dict((self.sim.get("calls") or {}).get(str(n)) or {})
        from orch import seccall

        return seccall.state(self.root, n) if self.root is not None else {}

    def start_call(self, root, tid: str, n: int, sha: str, since: str | None) -> str:
        from orch import seccall

        return seccall.spawn(root, tid, n, sha, since)

    def start_review_helper(self, tid: str) -> str:
        self.did.append(f"security-helper:{tid}")
        if self.sim is not None:
            return "helper started"
        if self.dry:
            return "would start the helper"
        try:
            runs.start(self.root, tid, secreview.BY, priority="high")
        except Exception as ex:  # noqa: BLE001 - busy, paused or no agent: the ticket waits in line
            return f"helper not started yet ({' '.join(str(ex).split())[:100]})"
        return "helper started"

    def required(self, branch: str) -> list[str] | None:
        """The required checks of `branch`'s rules ([] when it has none), None when GitHub did not say."""
        if self.sim is not None:
            return list(self.sim.get("required", {}).get(branch, []))
        try:
            rules = self._gh_json(["api", f"repos/{self.cfg.repo}/rules/branches/{branch}"])
        except Refused:
            return None
        if not isinstance(rules, list):
            return None
        return sorted(
            {
                c["context"]
                for r in rules
                if isinstance(r, dict) and r.get("type") == "required_status_checks"
                for c in (r.get("parameters") or {}).get("required_status_checks") or []
                if c.get("context")
            }
        )

    def last_release(self) -> int:
        if self.sim is not None:
            return int(self.sim.get("last_release", 0))
        rows = self._gh_json(
            [
                "pr",
                "list",
                "--repo",
                self.cfg.repo,
                "--base",
                "main",
                "--state",
                "all",
                "--limit",
                "30",
                "--json",
                "title",
            ]
        )
        nums = [int(m[1]) for r in rows or [] if (m := re.match(r"Release (\d+)", r.get("title") or ""))]
        return max(nums, default=0)

    def jobs(self, run_id) -> list[dict] | None:
        if self.sim is not None:
            return self.sim.get("jobs", {}).get(str(run_id))
        try:
            d = self._gh_json(["run", "view", str(run_id), "--repo", self.cfg.repo, "--json", "jobs"])
        except Refused:
            return None
        return d.get("jobs") if isinstance(d, dict) else None

    def urgent(self) -> set[int]:
        """Numbers of merged pull requests with the urgent label (recent ones)."""
        if self.sim is not None:
            return set(self.sim.get("urgent", []))
        rows = self._gh_json(
            [
                "pr",
                "list",
                "--repo",
                self.cfg.repo,
                "--state",
                "merged",
                "--base",
                "develop",
                "--label",
                URGENT_LABEL,
                "--limit",
                "30",
                "--json",
                "number",
            ]
        )
        return {int(r["number"]) for r in rows or []}

    def fixes(self) -> list[dict]:
        """Recently merged pull requests into develop labelled "fix for release N": {number, release, sha,
        head, title, url}. sha = the commit GitHub says merged it: a merge-queue group's merge commit
        when it was merged inside a group, so never shipped as a whole; head = the pull request's own last
        commit, the one that was reviewed (ORCH-786)."""
        if self.sim is not None:
            return list(self.sim.get("fixes") or [])
        rows = self._gh_json(
            [
                "pr",
                "list",
                "--repo",
                self.cfg.repo,
                "--state",
                "merged",
                "--base",
                "develop",
                "--limit",
                "30",
                "--json",
                "number,title,url,labels,mergeCommit,headRefOid",
            ]
        )
        out = []
        for r in rows or []:
            n = fix_target(r.get("labels"))
            sha = str((r.get("mergeCommit") or {}).get("oid") or "")
            head = str(r.get("headRefOid") or "")
            if n is not None and re.fullmatch(r"[0-9a-f]{40}", sha) and re.fullmatch(r"[0-9a-f]{40}", head):
                out.append(
                    {
                        "number": int(r["number"]),
                        "release": n,
                        "sha": sha,
                        "head": head,
                        "title": r.get("title") or "",
                        "url": r.get("url") or "",
                    }  # fmt: skip
                )
        return out

    def fix_count(self, n: int) -> int:
        """How many fix releases of release n exist already (Release 33.1, 33.2 ... into main)."""
        if self.sim is not None:
            return int((self.sim.get("fix_count") or {}).get(str(n), 0))
        rows = self._gh_json(
            [
                "pr",
                "list",
                "--repo",
                self.cfg.repo,
                "--base",
                "main",
                "--state",
                "all",
                "--limit",
                "30",
                "--json",
                "title",
            ]  # fmt: skip
        )
        got = [
            int(m[1]) for r in rows or [] if (m := re.match(rf"Release {n}\.(\d+)\b", r.get("title") or ""))
        ]
        return max(got, default=0)

    def last_release_at(self) -> datetime | None:
        if self.sim is not None:
            return ts(self.sim.get("last_release_at"))
        rows = self._gh_json(
            [
                "pr",
                "list",
                "--repo",
                self.cfg.repo,
                "--base",
                "main",
                "--state",
                "merged",
                "--limit",
                "1",
                "--json",
                "mergedAt",
            ]
        )
        return ts(rows[0]["mergedAt"]) if rows else None

    def exceptions(self) -> dict[str, dict]:
        """The named exceptions a person recorded: {check: {ticket, until, why, by, at}}."""
        if self.sim is not None:
            return dict(self.sim.get("exceptions") or {})
        return _read_json(self.cfg.exceptions_path)

    def record_exception(self, check: str, entry: dict) -> None:
        """A named exception the keeper records itself for a fix ticket (ORCH-178, owner 20 Nov)."""
        self.did.append(f"exception:{check}")
        if self.sim is not None:
            self.sim.setdefault("exceptions", {})[check] = entry
            return
        if self.dry:
            return
        data = _read_json(self.cfg.exceptions_path)
        data[check] = entry
        self.cfg.run_dir.mkdir(parents=True, exist_ok=True)
        runs._atomic(self.cfg.exceptions_path, json.dumps(data, indent=1) + "\n")

    def walk_results(self) -> dict[str, dict]:
        """{release number: {walk: {verdict, line, at, by}}} as the walk helpers recorded them."""
        if self.sim is not None:
            return dict(self.sim.get("walk_results") or {})
        return _read_json(self.cfg.walks_path)

    def known_red(self) -> dict[str, str]:
        """{check name: "<ticket>[, until <date>]"} of checks that may be red: a recorded exception until its
        end date, or a --known-red job, each only while its ticket is not done yet."""
        table = self.sim.get("known_red", self.known_table) if self.sim is not None else self.known_table
        rows: dict[str, tuple[str, str | None]] = {job: (key, None) for job, key in table.items()}
        for check, e in self.exceptions().items():
            if isinstance(e, dict) and e.get("ticket"):
                rows[check] = (str(e["ticket"]), e.get("until"))
        status = {t.get("key"): t.get("status") for t in self.tickets()}
        status.update({t.get("id"): t.get("status") for t in self.tickets()})
        today = now().date().isoformat()
        return {
            job: key + (f", until {until}" if until else "")
            for job, (key, until) in rows.items()
            if (status.get(key) or "open") not in DONE and not (until and str(until) < today)
        }

    def winvm_results(self) -> list[tuple[str, str]]:
        """[(sha, state)] of the status 'windows (winvm)' on the newest develop commits, newest first, only
        the commits that have one (ORCH-1127: e2e/winvm/dispatch.py posts it). One GraphQL call."""
        if self.sim is not None:
            return [tuple(x) for x in self.sim.get("winvm", [])]
        owner, name = self.cfg.repo.split("/", 1)
        q = (
            'query($o:String!,$n:String!){repository(owner:$o,name:$n){ref(qualifiedName:"refs/heads/develop")'
            "{target{... on Commit{commits:history(first:60){nodes{oid status{context(name:"
            + json.dumps(WINVM_CONTEXT)
            + "){state}}}}}}}}}"
        )
        d = self._gh_json(["api", "graphql", "-f", f"query={q}", "-F", f"o={owner}", "-F", f"n={name}"])
        nodes = ((((d or {}).get("data") or {}).get("repository") or {}).get("ref") or {}).get("target") or {}
        out = []
        for n in (nodes.get("commits") or {}).get("nodes") or []:  # alias: GitHub's commit list
            c = (n.get("status") or {}).get("context") if n.get("status") else None
            if c and c.get("state"):
                out.append((n["oid"], str(c["state"]).lower()))
        return out

    def runs(self, workflow: str, event: str, branch: str = "develop") -> list[dict]:
        """Runs of one event only: merge bursts push the nightly run far down an unfiltered list. `branch` is
        develop, or the release's test branch for the runs the keeper dispatched (ORCH-1475)."""
        if self.sim is not None:
            return [
                r for r in self.sim.get("runs", {}).get(workflow, []) if r.get("headBranch", branch) == branch
            ]
        return (
            self._gh_json(
                [
                    "run",
                    "list",
                    "--repo",
                    self.cfg.repo,
                    "--workflow",
                    workflow,
                    "--branch",
                    branch,
                    "--event",
                    event,
                    "--limit",
                    "10",
                    "--json",
                    "databaseId,headSha,event,status,conclusion,createdAt,url,attempt",
                ]
            )
            or []
        )

    def hit_time_limit(self, job_id) -> bool:
        """GitHub stopped the job at its timeout-minutes (its annotation on the job's check run says so)."""
        if self.sim is not None:
            return str(job_id) in {str(x) for x in self.sim.get("time_limit", [])}
        try:
            notes = self._gh_json(["api", f"repos/{self.cfg.repo}/check-runs/{int(job_id)}/annotations"])
        except (Refused, ValueError, TypeError):
            return False
        return any(TIME_LIMIT_RE.search(str(a.get("message") or "")) for a in notes or [])

    def all_passed(self, job_id) -> bool:
        """The job's log holds pytest's closing line with passed tests and none failed (ORCH-1050: Windows
        part 12 printed '438 passed, 62 skipped in 876.38s' and was still killed at 15m0s). A part stopped
        before that line proves nothing: -q shows a failure only as an F until the end. GitHub gives the log
        once the whole run finished."""
        if self.sim is not None:
            return str(job_id) in {str(x) for x in self.sim.get("passed_log", [])}
        r = self._run([self.gh, "run", "view", "--repo", self.cfg.repo, "--job", str(int(job_id)), "--log"])
        log = r.stdout or ""
        return r.returncode == 0 and bool(PASSED_RE.search(log)) and not FAILED_TEST_RE.search(log)

    def run_done(self, run_id) -> bool:
        if self.sim is not None:
            return str(run_id) not in {str(x) for x in self.sim.get("running_runs", [])}
        try:
            d = self._gh_json(["run", "view", str(int(run_id)), "--repo", self.cfg.repo, "--json", "status"])
        except (Refused, ValueError, TypeError):
            return False
        return isinstance(d, dict) and d.get("status") == "completed"

    def rerun(self, run_id) -> None:
        """Runs the failed (and time-limit cancelled) jobs of one run again: a new attempt of the same run."""

        def go():
            self.bot_ok()
            r = self._run([self.gh, "run", "rerun", str(int(run_id)), "--failed", "--repo", self.cfg.repo])
            if r.returncode != 0:
                raise Refused(f"rerun {run_id}: {(r.stderr or r.stdout).strip()[:200]}")

        self.act(f"rerun:{run_id}", go)

    def tickets(self) -> list[dict]:
        if self.sim is not None:
            return self.sim.get("tickets", [])
        keep = ("id", "key", "title", "status", "refs")
        return [{k: t.get(k) for k in keep} for t in tickets.list_all(self.root)]

    def ticket(self, ref: str) -> dict:
        if self.sim is not None:
            return self.sim.get("ticket", {}).get(ref, {})
        try:
            return tickets.load(self.root, tickets.resolve(self.root, ref))
        except (Refused, OSError, ValueError):
            return {}

    def changed(self, old: str, new: str, paths: list[str]) -> list[str]:
        if self.sim is not None:
            return self.sim.get("changed", [])
        if not paths:
            return []
        r = self._git("diff", "--name-only", old, new, "--", *paths)
        return [x for x in r.stdout.splitlines() if x.strip()]

    def deployed(self) -> dict:
        """{"relay": {"sha", "at", "by"}, ...}: the commit each server last went to production from.
        Written by `orch github release-deployed` (the deploy helper and a hand deploy) and by the owner's
        "Already deployed" answer. A server that does not report its own version is known only by this
        record."""
        if self.sim is not None:
            return self.sim.get("deployed", {})
        try:
            p = self.cfg.deployed_path
            data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def running(self, part: str, release_sha: str) -> dict | None:
        """The deploy record of `part` when production already runs the same `part/` tree as the release."""
        rec = self.deployed().get(part)
        if not isinstance(rec, dict) or not rec.get("sha"):
            return None
        if self.sim is not None:
            same = rec["sha"] in self.sim.get("same_tree", {}).get(part, [])
        else:
            same = self._git("diff", "--quiet", rec["sha"], release_sha, "--", f"{part}/").returncode == 0
        return rec if same else None

    def built_run(self, part: str, sha: str) -> dict | None:
        """The newest ci run whose `part/` folder and `part`.yml equal the release's, with a green "<part> /
        test" job and its artifact still kept: that artifact is the program of this release (no local build).
        The run as a whole may be cancelled or red in another part."""
        if self.sim is not None:
            return self.sim.get("built", {}).get(part)
        rows = self._gh_json(
            [
                "run",
                "list",
                "--repo",
                self.cfg.repo,
                "--workflow",
                "ci.yml",
                "--status",
                "completed",
                "--limit",
                "100",
                "--json",
                "databaseId,headSha,createdAt,url",
            ]
        )
        tried = 0
        for r in sorted(rows or [], key=lambda x: str(x.get("createdAt") or ""), reverse=True):
            d = self._git(
                "diff", "--quiet", r["headSha"], sha, "--", f"{part}/", f".github/workflows/{part}.yml"
            )
            if d.returncode != 0:  # 1 = differs, 128 = commit not here (a fork's branch): skip both
                continue
            tried += 1
            if tried > 10:
                break
            if not any(
                j.get("name") == f"{part} / test" and j.get("conclusion") == "success"
                for j in self.jobs(r["databaseId"]) or []
            ):
                continue
            try:
                arts = self._gh_json(
                    ["api", f"repos/{self.cfg.repo}/actions/runs/{r['databaseId']}/artifacts"]
                )
            except Refused:
                continue
            if any(
                a.get("name") == f"orch-{part}-linux-x86_64" and not a.get("expired")
                for a in (arts or {}).get("artifacts") or []
            ):
                return r
        return None

    def fetch_built(self, part: str, run_id, dest: Path) -> dict:
        """Download the artifact into `dest` (only the keeper's own folder): {"path", "sha256", "linux"}."""
        if self.sim is not None:
            return self.sim.get("fetched", {}).get(part, {})
        if dest.exists():
            shutil.rmtree(dest)  # our own staging folder of this very release: a fresh copy
        dest.mkdir(parents=True)
        r = self._run(
            [
                self.gh,
                "run",
                "download",
                str(run_id),
                "--repo",
                self.cfg.repo,
                "-n",
                f"orch-{part}-linux-x86_64",
                "-D",
                str(dest),
            ],
            timeout=600,
        )
        if r.returncode != 0:
            raise Refused(f"download: {(r.stderr or r.stdout).strip()[:200]}")
        binp = dest / f"orch-{part}"
        if not binp.is_file():
            raise Refused(f"the artifact has no orch-{part} program")
        binp.chmod(0o755)
        data = binp.read_bytes()
        return {
            "path": str(binp),
            "sha256": hashlib.sha256(data).hexdigest(),
            "linux": is_linux_x86_64(data[:20]),
        }

    def prod_sha(self, part: str) -> str | None:
        """sha256 of the program production runs now (read only, over ssh); None when it cannot be read."""
        if self.sim is not None:
            return self.sim.get("prod_sha", {}).get(part)
        key, host = self.cfg.deploy_key, self.cfg.deploy_host
        if not host or key is None or not key.is_file():
            return None
        try:
            r = subprocess.run(
                [
                    "ssh",
                    "-i",
                    str(key),
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "ConnectTimeout=10",
                    host,
                    f"sha256sum /opt/orch/bin/orch-{part}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                stdin=subprocess.DEVNULL,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        m = re.match(r"([0-9a-f]{64})\s", r.stdout or "")
        return m[1] if r.returncode == 0 and m else None

    def needs_person(self, old: str, new: str, part: str) -> list[str]:
        """What in `part/` between two commits a deploy must look at: new ORCH_ settings, data (schema,
        migration, sql) and service files. Plain lines; [] when nothing."""
        if self.sim is not None:
            return list(self.sim.get("needs_person", {}).get(part, []))
        names = [
            x
            for x in self._git("diff", "--name-only", old, new, "--", f"{part}/").stdout.splitlines()
            if x.strip()
        ]
        return needs_lines(part, names, self._git("diff", "-U0", old, new, "--", f"{part}/src").stdout)

    def drop_old_stages(self, part: str) -> None:
        d0 = self.cfg.stage_dir
        if self.sim is not None or self.dry or not d0.is_dir():
            return
        mine = sorted(
            (d for d in d0.iterdir() if d.is_dir() and re.fullmatch(rf"{re.escape(part)}-r(\d+)", d.name)),
            key=lambda d: int(d.name.rsplit("-r", 1)[1]),
            reverse=True,
        )
        for d in mine[KEEP_STAGED:]:
            shutil.rmtree(d)  # a folder the keeper made itself, by its own name

    # ---- writes (recorded; skipped on dry run and in a simulation)
    def act(self, what: str, fn=None):
        self.did.append(what)
        if self.sim is not None:
            return self.sim.get("results", {}).get(what.split(":")[0])
        if self.dry or fn is None:
            return None
        return fn()

    def test_branch(self, n, sha: str) -> str:
        """Pushes branch release-test/<n>-<sha8> at `sha` (the commit the release is cut from) and returns its
        name: the full-signal runs are dispatched on it, so they run on exactly that commit (ORCH-1475). A
        plain push of a new branch (never a force push); the same name at the same commit is a no-op."""
        br = f"{TEST_BRANCH}{n}-{sha[:8]}"

        def go():
            self.bot_ok()
            r = self._git("push", "-q", "origin", f"{sha}:refs/heads/{br}", timeout=180)
            if r.returncode != 0:
                raise Refused(f"push {br}: {(r.stderr or r.stdout).strip()[:200]}")

        self.act(f"test-branch:{br}", go)
        return br

    def drop_test_branch(self, br: str | None) -> None:
        """Deletes the release's test branch once its runs were judged. A deletion that fails is kept in
        `left_branches`; pass_once stores them and tries again on the next pass. Gone already counts as
        done."""
        if not br or not br.startswith(TEST_BRANCH):
            return

        def go():
            self.bot_ok()
            r = self._git("push", "-q", "origin", "--delete", br, timeout=180)
            if r.returncode != 0 and "remote ref does not exist" not in (r.stderr or ""):
                raise Refused(f"delete {br}: {(r.stderr or r.stdout).strip()[:200]}")

        try:
            self.act(f"drop-test-branch:{br}", go)
        except (Refused, subprocess.TimeoutExpired, OSError):
            self.left_branches.append(br)

    def dispatch(self, workflow: str, extra: list[str], ref: str = "develop") -> None:
        """Starts one full-signal workflow on `ref`: the release's test branch, so the run is on the very
        commit the keeper then waits for (ORCH-1475)."""
        self.dispatched.append((workflow, ref))

        def go():
            self.bot_ok()
            r = self._run(
                [self.gh, "workflow", "run", workflow, "--repo", self.cfg.repo, "--ref", ref, *extra]
            )
            if r.returncode != 0:
                raise Refused(f"dispatch {workflow}: {(r.stderr or r.stdout).strip()[:200]}")

        self.act(f"dispatch:{workflow}", go)

    def new_ticket(
        self,
        parent: str,
        title: str,
        note: str,
        done_when: str,
        priority: str = "high",
        over_limit: bool = False,
        start: bool = True,
    ) -> str | None:
        def go():
            try:
                pid = tickets.resolve(self.root, parent)
                t = tickets.create(
                    self.root,
                    title[:200],
                    BY,
                    parent=pid,
                    fields={"note": note[:4000], "done_when": done_when},
                )
            except Refused as e:
                return f"not opened ({e})"
            if start:
                with contextlib.suppress(Exception):  # busy, paused or no agent: the ticket waits in line
                    runs.start(self.root, t["id"], BY, priority=priority, over_limit=over_limit)
            return str(t.get("key") or t["id"])

        got = self.act(f"ticket:{title}", go)
        if isinstance(got, str) and got.startswith("not opened"):
            self.did[-1] += " failed"  # act lists a step before it runs: no "opened" for a refusal
        return got or (None if self.sim is None else "t_sim")

    def record_deployed(self, parts: list[str], sha: str, by: str) -> None:
        def go():
            data = self.deployed()
            for part in parts:
                data[part] = {"sha": sha, "at": now().isoformat(timespec="seconds"), "by": by}
            self.cfg.run_dir.mkdir(parents=True, exist_ok=True)
            runs._atomic(self.cfg.deployed_path, json.dumps(data, indent=1) + "\n")

        self.act(f"deployed:{' and '.join(parts)} {sha[:8]}", go)

    def note(self, ref: str, text: str) -> None:
        def go():
            with contextlib.suppress(Refused, OSError):
                tickets.log(self.root, tickets.resolve(self.root, ref), text[:NOTE_MAX], BY)

        self.act(f"note:{text[:80]}", go)

    def ask(self, args: list[str]):
        """A question on the role ticket through `orch ask` (the same card a helper makes)."""
        return self.orch(["ask", *args, "--by", BY])

    def secret_free(self, text: str) -> bool:
        return not secret_lines(text, self.root)

    def cut(self, n: int, sha: str, body: str) -> dict | None:
        """Branch + worktree + merge main (ours) + push + pull request. Returns {"number", "url", "wt"}."""
        br = f"release/part{n}-{now().astimezone().strftime('%m%d')}"
        wt = (self.cfg.worktrees or Path(".")) / f"release-{n}"

        made: dict[str, bool] = {}  # what this cut made, so a refused cut removes only that (ORCH-1000)

        def go():
            self.bot_ok()
            if wt.exists():
                raise Refused(f"{wt} exists already: look at it, remove it by its path")
            try:
                return attempt()
            except (Refused, subprocess.TimeoutExpired, OSError):
                self._undo_cut(wt, br, made)
                raise

        def attempt():
            self.secret_hit = None
            wt.parent.mkdir(parents=True, exist_ok=True)
            had_branch = self._git("rev-parse", "-q", "--verify", f"refs/heads/{br}").returncode == 0
            for argv in (
                ["-C", str(self.cfg.clone), "worktree", "add", "-q", str(wt), "-b", br, sha],
                [
                    "-C",
                    str(wt),
                    "merge",
                    "-q",
                    "-s",
                    "ours",
                    "--no-edit",
                    "-m",
                    f"Release {n}: merge main (ours) - tree equals develop",
                    "origin/main",
                ],
            ):
                r = self._run(["git", *argv])
                if (
                    argv[2] == "worktree"
                ):  # git can make both and still fail (a hook): count what is there now
                    made["wt"] = wt.exists()
                    made["branch"] = not had_branch and (
                        self._git("rev-parse", "-q", "--verify", f"refs/heads/{br}").returncode == 0
                    )
                if r.returncode != 0:
                    raise Refused(f"git {argv[2]}: {(r.stderr or r.stdout).strip()[:200]}")
            if self._run(["git", "-C", str(wt), "diff", "--quiet", sha, "HEAD"]).returncode != 0:
                raise Refused("release tree differs from develop: stop")
            hits = secret_lines(body, self.root)
            if hits:
                self.secret_hit = hits[0]
                more = f" (and {len(hits) - 1} more)" if len(hits) > 1 else ""
                h0 = hits[0]
                raise Refused(
                    f"line {h0['line']} of the release text looks like it holds {h0['words']}{more}: "
                    f"{h0['shown']}"
                )
            seen = self._run(["git", "-C", str(wt), "ls-remote", "--heads", "origin", br], timeout=120)
            if seen.returncode != 0 or seen.stdout.strip():
                raise Refused(
                    f"the branch {br} is on GitHub already (or GitHub could not be read): look at it"
                )
            r = self._run(["git", "-C", str(wt), "push", "-q", "-u", "origin", br], timeout=300)
            if r.returncode != 0:
                raise Refused(f"push: {(r.stderr or r.stdout).strip()[:200]}")
            made["pushed"] = True  # only a branch this cut put there (checked just before)
            r = self._run(
                [
                    self.gh,
                    "pr",
                    "create",
                    "--repo",
                    self.cfg.repo,
                    "--base",
                    "main",
                    "--head",
                    br,
                    "--title",
                    f"Release {n}: develop {sha[:8]} -> main",
                    "--body",
                    body,
                ]
            )
            if r.returncode != 0:
                raise Refused(f"pr create: {(r.stderr or r.stdout).strip()[:200]}")
            url = r.stdout.strip().splitlines()[-1]
            return {"number": int(url.rsplit("/", 1)[1]), "url": url, "wt": str(wt), "branch": br}

        got = self.act(f"cut:release {n} from {sha[:8]}", go)
        if got is None and self.sim is not None:
            got = {
                "number": 9000 + n,
                "url": f"https://github.com/{self.cfg.repo}/pull/{9000 + n}",
                "wt": str(wt),
                "branch": br,
            }
        return got

    def _undo_cut(self, wt: Path, br: str, made: dict) -> None:
        """A refused cut removes what it made itself (its worktree, its local branch, the branch it pushed),
        so the next pass does not stop at "exists already" and shows the real cause (ORCH-1000)."""
        for what, args in (
            ("pushed", ["push", "-q", "origin", "--delete", br]),
            ("wt", ["worktree", "remove", "--force", str(wt)]),
            ("branch", ["branch", "-q", "-D", br]),
        ):
            if made.get(what):
                with contextlib.suppress(subprocess.TimeoutExpired, OSError, Refused):
                    self._git(*args)

    def fix_range(self, fix: dict, cwd: str | Path) -> tuple[str, str]:
        """(base, head): the fix pull request's own change is `git diff base head`, nothing else (ORCH-786):
        from where its reviewed head meets develop as it was before the merge, to that head. The same for a
        merge commit (alone or a merge-queue group's) and a squash: never the merged commit's own content.
        Refused when the head is not known or was not what got merged."""
        sha, head = str(fix.get("sha") or ""), str(fix.get("head") or "")
        num = fix.get("number")
        if not (re.fullmatch(r"[0-9a-f]{40}", sha) and re.fullmatch(r"[0-9a-f]{40}", head)):
            raise Refused(f"the fix #{num} has no known merged commit and head")

        def git(*a: str, timeout: int = 120) -> subprocess.CompletedProcess:
            return self._run(["git", "-C", str(cwd), *a], timeout=timeout)

        parents = git("rev-list", "--parents", "-n", "1", sha).stdout.split()[1:]
        if not parents:
            raise Refused(f"the fix #{num}'s merged commit {sha[:8]} is not known here")
        if git("cat-file", "-e", f"{head}^{{commit}}").returncode != 0 and isinstance(num, int):
            git("fetch", "-q", "origin", f"refs/pull/{num}/head", timeout=180)  # a squashed branch is gone
        if git("cat-file", "-e", f"{head}^{{commit}}").returncode != 0:
            raise Refused(f"the fix #{num}'s reviewed head {head[:8]} is not known here")
        before = parents[0]
        if git("merge-base", "--is-ancestor", head, sha).returncode != 0 and len(parents) != 1:
            raise Refused(
                f"the fix #{num}'s own commits cannot be told apart in {sha[:8]} (its head is not in it)"
            )
        if git("merge-base", "--is-ancestor", head, before).returncode == 0:
            raise Refused(f"the fix #{num} was in develop before {sha[:8]}: nothing of its own")
        base = git("merge-base", head, before).stdout.strip()
        if not base:
            raise Refused(f"the fix #{num} shares no history with develop")
        return base, head

    def fix_files(self, fix: dict) -> list[str] | None:
        """Every path the fix's own change touches (a rename as both names), from git; None when unknown."""
        if self.sim is not None:
            got = fix.get("files")
            return None if got is None else [str(f.get("path") if isinstance(f, dict) else f) for f in got]
        try:
            base, top = self.fix_range(fix, self.cfg.clone)
        except Refused:
            return None
        r = self._run(
            ["git", "-C", str(self.cfg.clone), "diff", "-z", "--name-only", "--no-renames", base, top]
        )
        return [x for x in r.stdout.split("\0") if x] if r.returncode == 0 else None

    def cut_fix(self, n: int, k: int, fix: dict, body: str) -> dict | None:
        """Release n.k: a branch from main with ONLY the fix pull request's own change on top, pushed, and a
        pull request into main. Returns {number, url, wt, branch, sha}.

        Its own change is what the pull request itself shows: from where its last commit (head, the one that
        was reviewed) meets develop as it was before the merge, to that head. Never the merge commit as a
        whole: a merge-queue group merge commit holds the other pull requests of the group too (ORCH-786)."""
        br = f"release/part{n}.{k}-{now().astimezone().strftime('%m%d')}"
        wt = (self.cfg.worktrees or Path(".")) / f"release-{n}.{k}"

        def git(*a: str) -> subprocess.CompletedProcess:
            return self._run(["git", "-C", str(wt), *a])

        made: dict[str, bool] = {}  # what this cut made, so a refused cut removes only that (ORCH-1000)

        def go():
            self.bot_ok()
            if wt.exists():
                raise Refused(f"{wt} exists already: look at it, remove it by its path")
            try:
                return attempt()
            except (Refused, subprocess.TimeoutExpired, OSError):
                self._undo_cut(wt, br, made)
                raise

        def attempt():
            self.secret_hit = None
            wt.parent.mkdir(parents=True, exist_ok=True)
            had_branch = self._git("rev-parse", "-q", "--verify", f"refs/heads/{br}").returncode == 0
            r = self._run(
                ["git", "-C", str(self.cfg.clone), "worktree", "add", "-q", str(wt), "-b", br, "origin/main"]
            )
            made["wt"] = wt.exists()
            made["branch"] = not had_branch and (
                self._git("rev-parse", "-q", "--verify", f"refs/heads/{br}").returncode == 0
            )
            if r.returncode != 0:
                raise Refused(f"git worktree: {(r.stderr or r.stdout).strip()[:200]}")
            base, tip = self.fix_range(fix, wt)
            patch = (wt.parent / f".release-{n}.{k}.patch").resolve()
            try:
                r = git("diff", "--binary", "--no-color", "--no-ext-diff", f"--output={patch}", base, tip)
                if r.returncode != 0 or not patch.is_file() or not patch.stat().st_size:
                    raise Refused(f"the fix #{fix['number']} has no change of its own")
                r = git("apply", "--3way", "--index", str(patch))
            finally:
                patch.unlink(missing_ok=True)
            if r.returncode != 0:
                git("reset", "-q", "--hard", "origin/main")
                raise Refused(
                    f"the fix #{fix['number']} does not apply on main as it is: "
                    f"{(r.stderr or r.stdout).strip()[:160]}"
                )
            msg = (
                f"Fix #{fix['number']}: {_short(fix.get('title') or 'fix', TITLE_MAX)}\n\n"
                f"Only the change of pull request #{fix['number']} ({base[:12]}..{tip[:12]}), "
                f"taken by the release keeper for fix release {n}.{k}."
            )
            r = git("commit", "-q", "--no-verify", "-m", msg)
            if r.returncode != 0:
                raise Refused(f"commit: {(r.stderr or r.stdout).strip()[:200]}")
            hits = secret_lines(body, self.root)
            if hits:
                self.secret_hit = hits[0]
                more = f" (and {len(hits) - 1} more)" if len(hits) > 1 else ""
                h0 = hits[0]
                raise Refused(
                    f"line {h0['line']} of the release text looks like it holds {h0['words']}{more}: "
                    f"{h0['shown']}"
                )
            top = git("rev-parse", "HEAD").stdout.strip()
            r = self._run(["git", "-C", str(wt), "push", "-q", "-u", "origin", br], timeout=300)
            if r.returncode != 0:
                raise Refused(f"push: {(r.stderr or r.stdout).strip()[:200]}")
            made["pushed"] = True
            r = self._run(
                [
                    self.gh,
                    "pr",
                    "create",
                    "--repo",
                    self.cfg.repo,
                    "--base",
                    "main",
                    "--head",
                    br,
                    "--title",
                    _short(f"Release {n}.{k}: {fix.get('title') or 'fix'}", TITLE_MAX),
                    "--body",
                    body,
                ]  # fmt: skip
            )
            if r.returncode != 0:
                raise Refused(f"pr create: {(r.stderr or r.stdout).strip()[:200]}")
            url = r.stdout.strip().splitlines()[-1]
            return {
                "number": int(url.rsplit("/", 1)[1]),
                "url": url,
                "wt": str(wt),
                "branch": br,
                "sha": top,
            }

        got = self.act(f"cut:release {n}.{k} with #{fix['number']}", go)
        if got is None and self.sim is not None:
            num = 9500 + int(fix["number"]) % 400
            got = {"number": num, "url": f"https://github.com/{self.cfg.repo}/pull/{num}", "wt": str(wt),
                   "branch": br, "sha": "f" * 40}  # fmt: skip
        return got

    def close_release(self, rel: dict) -> None:
        def go():
            self.bot_ok()
            self._run(
                [
                    self.gh,
                    "pr",
                    "close",
                    str(rel["pr"]),
                    "--repo",
                    self.cfg.repo,
                    "--delete-branch",
                    "--comment",
                    "Closed by the release keeper: develop moved past its red checks; the release is cut "
                    "again.",
                ]
            )
            if rel.get("wt") and Path(rel["wt"]).exists():
                self._git("worktree", "remove", "--force", rel["wt"])

        self.act(f"close:release {rel['n']} PR {rel['pr']}", go)

    def rerun_failed(self, run_id: str):
        """Run the failed jobs of one Actions run once more (a red release check gets one more try).
        Raises Refused when GitHub refused it."""

        def go():
            self.bot_ok()
            r = self._run([self.gh, "run", "rerun", str(run_id), "--failed", "--repo", self.cfg.repo])
            if r.returncode != 0:
                raise Refused(f"rerun {run_id}: {(r.stderr or r.stdout).strip()[:200]}")
            return True

        return self.act(f"rerun:{run_id}", go)

    def remove_wt(self, wt: str | None) -> None:
        if wt and (self.sim is not None or Path(wt).exists()):
            self.act(f"rmwt:{wt}", lambda: self._git("worktree", "remove", "--force", wt))

    # ---- a red after-merge run on develop (ORCH-1128)
    def rerun_once(self, run_id) -> bool:
        """rerun_failed, as yes/no: False when GitHub refused it (the refusal stays in the log)."""
        try:
            got = self.rerun_failed(run_id)
        except Refused:
            self.did[-1] += " failed"
            return False
        return got is not False

    def failed_tests(self, run_id) -> list[str]:
        """The test file names the failed jobs' log names on its failure lines (reads only)."""
        if self.sim is not None:
            return list(self.sim.get("failed_tests", {}).get(str(run_id), []))
        r = self._run(
            [self.gh, "run", "view", str(run_id), "--repo", self.cfg.repo, "--log-failed"], timeout=120
        )
        return failed_test_files(r.stdout[-400_000:] if r.returncode == 0 else "")

    def merged_between(self, good: str, bad: str) -> list[dict] | None:
        """The pull requests that reached develop after `good` up to `bad`, each {pr, sha, files}: a merge
        queue group counts as its members (the queue's "take in #N" commits), any other merge as itself. sha
        is the commit whose first-parent diff is that pull request's change (git revert -m 1). None when git
        cannot tell (good is not before bad)."""
        if self.sim is not None:
            got = self.sim.get("merged_between")
            return None if got is None else list(got)
        if self._git("merge-base", "--is-ancestor", good, bad).returncode != 0:
            return None
        lg = self._git("log", "--first-parent", "--merges", "--format=%H%x1f%s", f"{good}..{bad}").stdout
        out: list[dict] = []
        for line in lg.splitlines():
            sha, _, subject = line.partition("\x1f")
            group = queue_merge(subject, self.cfg.repo)  # only the queue's own group merges
            members = [
                (m[1], x.split("\x1f", 1)[0])
                for x in self._git(
                    "log", "--first-parent", "--format=%H\x1f%s", f"{sha}^1..{sha}^2"
                ).stdout.splitlines()
                if group and (m := TAKE_IN.match(x.partition("\x1f")[2]))
            ]
            if not members and (m := MERGE_LINE.match(subject)):
                members = [(m[1], sha)]
            if not members:
                return None  # a merge the keeper cannot name: no guessing
            for pr, c in members:
                files = self._git("diff", "--name-only", f"{c}^1", c).stdout.split()
                out.append({"pr": int(pr), "sha": c, "files": files})
        return out

    def queue_entries(self) -> list[dict] | None:
        """The merge queue's entries (the pull-requests add-on's file, read only); None: no queue here."""
        if self.sim is not None:
            got = self.sim.get("queue")
            return None if got is None else list(got)
        if self.root is None:
            return None
        try:
            data = json.loads(
                (self.root / ".orch" / "addons" / QUEUE_ADDON / "queue.json").read_text("utf-8")
            )
        except (OSError, ValueError):
            return None
        rows = data.get("entries") if isinstance(data, dict) else None
        return [r for r in rows or [] if isinstance(r, dict)]

    def revert(self, pr: int, sha: str, title: str, body: str, ticket: str) -> str | None:
        """A revert pull request into develop for one merged pull request, put first in the merge queue on the
        red-develop ticket (never a push to develop). The pull request's url, or None."""
        br = f"revert/pr-{pr}-{sha[:8]}"
        wt = (self.cfg.worktrees or Path(".")) / f"revert-{pr}"

        def go():
            self.bot_ok()
            if wt.exists():
                raise Refused(f"{wt} exists already: look at it, remove it by its path")
            if not self.secret_free(body):
                raise Refused("the revert text looks like it holds a secret: stop")
            wt.parent.mkdir(parents=True, exist_ok=True)
            try:
                for argv in (
                    ["-C", str(self.cfg.clone), "worktree", "add", "-q", str(wt), "-b", br, "origin/develop"],
                    ["-C", str(wt), "revert", "--no-edit", "-m", "1", sha],
                    ["-C", str(wt), "push", "-q", "-u", "origin", br],
                ):
                    r = self._run(["git", *argv], timeout=300)
                    if r.returncode != 0:
                        raise Refused(f"git {argv[2]}: {(r.stderr or r.stdout).strip()[:200]}")
                r = self._run(
                    [
                        self.gh,
                        "pr",
                        "create",
                        "--repo",
                        self.cfg.repo,
                        "--base",
                        "develop",
                        "--head",
                        br,
                        "--title",
                        title,
                        "--body",
                        body,
                    ]
                )
                if r.returncode != 0:
                    raise Refused(f"pr create: {(r.stderr or r.stdout).strip()[:200]}")
                url = r.stdout.strip().splitlines()[-1]
            finally:
                if wt.exists():
                    self._git("worktree", "remove", "--force", str(wt))
            q = self.orch([QUEUE_ADDON, "queue", "add", url, "--ticket", ticket, "--first"])
            if q.returncode != 0:
                self.note(
                    ticket,
                    f"Release keeper: the revert {url} could not join the merge queue: "
                    f"{(q.stderr or q.stdout).strip()[:300]}",
                )
            return url

        got = self.act(f"revert:#{pr}", go)
        if got is None and self.sim is not None:
            got = f"https://github.com/{self.cfg.repo}/pull/{8000 + pr}"
        return got


def secret_lines(text: str, root: Path | None) -> list[dict]:
    """Every line of `text` the secret check stops at: {line, kind, words, shown}. `shown` is the line with
    the value hidden, so a person can find the title it came from. Masked per line: a line that also holds a
    stored key, or a hider that cannot run, shows no text at all (fail closed)."""
    from orch import phone_results, phone_view, secretscan

    found = secretscan.find(text, root)
    stored = {f["line"] for f in found if f["kind"] == "stored-key"}
    hider = phone_results.value_hider(root) if root is not None else None
    rows = text.split("\n")

    def shown(n: int) -> str:
        if n in stored or not 0 < n <= len(rows) or (root is not None and hider is None):
            return "(not shown)"
        try:
            masked = phone_view.redact(rows[n - 1])
            masked = hider.hide_text(masked) if hider is not None else masked
        except Exception:  # noqa: BLE001 - never show a line that could not be masked
            return "(not shown)"
        return masked.strip()[:200]

    words = secretscan.WORDS
    return [{**f, "words": words.get(f["kind"], "a secret"), "shown": shown(f["line"])} for f in found]


def is_linux_x86_64(head: bytes) -> bool:
    return (
        len(head) >= 20
        and head[:4] == b"\x7fELF"
        and head[4] == 2
        and int.from_bytes(head[18:20], "little") == 0x3E
    )


def needs_lines(part: str, names: list[str], diff: str) -> list[str]:
    out = []
    data = [x for x in names if re.search(r"migrat|schema|\.sql$", x, re.I)]
    svc = [x for x in names if x.startswith(f"{part}/deploy/")]
    plus = "\n".join(ln for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    minus = "\n".join(ln for ln in diff.splitlines() if ln.startswith("-") and not ln.startswith("---"))
    new_env = sorted(
        set(re.findall(r"\bORCH_[A-Z0-9_]+", plus)) - set(re.findall(r"\bORCH_[A-Z0-9_]+", minus))
    )
    if new_env:
        out.append("new settings: " + ", ".join(new_env[:6]))
    if data:
        out.append("data changes: " + ", ".join(x.split("/")[-1] for x in data[:4]))
    if svc:
        out.append("service files: " + ", ".join(x.split("/")[-1] for x in svc[:4]))
    return out


# ---------------------------------------------------------------- words


def _short(text: str, n: int = TITLE_MAX) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def pr_number(u: dict) -> int | None:
    m = re.search(r"#(\d+)", u.get("subject") or "")
    return int(m[1]) if m else None


def pr_title(u: dict) -> str:
    """The pull request's own title; a bare merge subject only when the commit carried none."""
    if (u.get("title") or "").strip():
        return u["title"].strip()
    subj = u.get("subject") or ""
    return "" if re.match(r"Merge pull request #\d+", subj) else subj


def ticket_for_prs(rows: list[dict], repo: str) -> dict[int, dict]:
    """{pull request number: ticket} from the tickets' GitHub links (orch ref add <ticket> <PR url>)."""
    out: dict[int, dict] = {}
    for t in rows:
        for r in t.get("refs") or []:
            m = re.search(rf"github\.com/{re.escape(repo)}/pull/(\d+)", (r or {}).get("url") or "")
            if m and t.get("key"):
                out.setdefault(int(m[1]), t)
    return out


def highlights(unreleased: list[dict], rows: list[dict], repo: str) -> list[str]:
    """One line per piece of work that went to main: the ticket key and title when a ticket links the pull
    request (one line per ticket, however many pull requests it had), else the pull request's title and
    number."""
    by_pr = ticket_for_prs(rows, repo)
    lines, seen = [], set()
    for u in unreleased:
        num = pr_number(u)
        if num is None and RELEASE_MERGE.match(u.get("subject") or ""):
            continue  # the keeper's own "merge main (ours)" commit, not work
        t = by_pr.get(num) if num is not None else None
        if t is not None:
            if t["key"] in seen:
                continue
            seen.add(t["key"])
            lines.append(f"{t['key']} {_short(t.get('title') or pr_title(u))}")
        else:
            title = _short(pr_title(u)) or "pull request"
            lines.append(f"{title} (#{num})" if num is not None else title)
    return lines


def release_body(n: int, sha: str, unreleased: list[dict], rows: list[dict], repo: str, signal: str) -> str:
    lines = [
        f"Release {n}: develop {sha[:8]} -> main (tree equals develop; main merged with -s ours).",
        "",
        "What goes to main:",
    ]
    by_pr = ticket_for_prs(rows or [], repo)
    for u in unreleased:
        num = pr_number(u)
        t = by_pr.get(num) if num is not None else None
        title = _short(t.get("title") if t else pr_title(u)) or "pull request"
        tk = f"{t['key']} " if t else ""
        lines.append(f"- {tk}{title}" + (f" (#{num})" if num is not None else ""))
    lines += [
        "",
        f"Cut by the orch release keeper after green {signal} on this commit. Release merge, no new code.",
    ]
    return "\n".join(lines)


def _when(rec: dict) -> str:
    t = ts(rec.get("at"))
    return t.astimezone().strftime("%d %b %H:%M") if t else "earlier"


def highlight_block(items: list[str], budget: int) -> str:
    """The highlights, one per line, as many as fit the note (the rest counted)."""
    if not items:
        return " Highlights: see the release."
    text = " In it:"
    for i, it in enumerate(items):
        line = f"\n- {it}"
        rest = f"\n- and {len(items) - i} more (see the release)"
        if len(text) + len(line) + (len(rest) if i < len(items) - 1 else 0) > budget:
            return text + rest
        text += line
    return text


# ---------------------------------------------------------------- the pass


def run_state(
    w: World,
    workflow: str,
    sha: str,
    since: datetime | None,
    events: tuple[str, ...],
    known: dict[str, str],
    branch: str = "develop",
) -> tuple[str, dict | None, list[str]]:
    """(green / red / pending / none, the run, known-red jobs that failed) for the newest run on `sha` of the
    given events (created after `since`). Judged job by job: a known-red job and the roll-up job do not count,
    so the run's own conclusion (red through them) is not the signal."""
    mine = [
        r
        for e in events
        for r in w.runs(workflow, e, branch)
        if r.get("headSha") == sha
        and r.get("event") in events
        and (since is None or (ts(r.get("createdAt")) or since) >= since)
    ]
    if not mine:
        return "none", None, []
    r = max(mine, key=lambda x: str(x.get("createdAt")))
    jobs = w.jobs(r.get("databaseId"))
    if not jobs:  # no job list: the run as a whole
        if r.get("status") != "completed":
            return "pending", r, []
        return ("green" if r.get("conclusion") == "success" else "red"), r, []
    noted, state = [], "green"
    for j in jobs:
        name = j.get("name") or ""
        if name in ROLLUP_JOBS:
            continue
        entry = known_name(name, known)
        if entry is not None:
            if j.get("status") == "completed" and j.get("conclusion") not in ("success", "skipped"):
                noted.append(f"{name} ({known[entry]})")
            continue  # neither waited for nor a blocker
        if j.get("status") != "completed":
            state = "pending" if state == "green" else state
        elif j.get("conclusion") not in ("success", "skipped", "neutral"):
            state = "red"
    return state, r, noted


def red_jobs(w: World, r: dict | None, known: dict[str, str]) -> list[tuple[str, str, str]]:
    """(run id, job id, name) of every job that makes run `r` red (judged like run_state)."""
    if not r or not r.get("databaseId"):
        return []
    out = []
    for j in w.jobs(r.get("databaseId")) or []:
        name = j.get("name") or ""
        if name in ROLLUP_JOBS or known_name(name, known) is not None:
            continue
        if j.get("status") == "completed" and j.get("conclusion") not in ("success", "skipped", "neutral"):
            out.append((str(r["databaseId"]), str(j.get("databaseId") or ""), name))
    return out


def retry_time_limit(w: World, rel: dict, red: list[tuple[str, str, str]]) -> list[str] | None:
    """A release red ONLY through jobs that hit their time limit with every test passed: run those jobs again,
    once per run and release (ORCH-1050). None when the red is anything else or already had its retry."""
    if not red or any(not r or not j for r, j, _ in red):
        return None
    runs_ = sorted({r for r, _, _ in red})
    done = set(rel.get("retried") or [])
    if done & set(runs_):
        return None  # the second time it is a real red
    if not all(w.hit_time_limit(j) for _, j, _ in red):
        return None
    names = ", ".join(sorted({n for _, _, n in red}))
    if not all(w.run_done(r) for r in runs_):  # the logs come only once the whole run finished
        return [f"release {rel['n']}: {names} hit the time limit; waits for the rest of the run to judge it"]
    if not all(w.all_passed(j) for _, j, _ in red):
        return None
    for r in runs_:
        w.rerun(r)
    rel["retried"] = sorted(done | set(runs_))
    return [f"release {rel['n']}: {names} only hit the time limit with every test passed: started once more"]


def _wf_name(f: str) -> str:
    return f.rsplit(".", 1)[0]


def open_red_ticket(rows: list[dict], words: str) -> dict | None:
    return next(
        (t for t in rows if (t.get("status") or "") not in DONE and words in (t.get("title") or "")), None
    )


FIX_DAYS = 2  # how long an exception the keeper records for a fix ticket lasts (owner 20 Nov, ORCH-178)


def fix_exceptions(w: World, rel: dict, bad: list[str]) -> list[str]:
    """Owner 20 Nov (ORCH-178, from ORCH-431): once the keeper's own "Release N checks are red" ticket links a
    fix pull request (orch ref add), the keeper records the named exception itself for each red check it put
    on that ticket: that ticket, ending FIX_DAYS later or when the ticket is done. The ticket and its checks
    come from the keeper's own record (rel["red_checks"], written when it opened or noted the ticket), never
    from a title or note anyone can edit. It shows on the Merge card and in the release note like one a person
    recorded; it is never renewed for the same ticket. Returns the lines when it recorded any (the release is
    judged again next pass)."""
    mine = rel.get("red_checks") or {}
    if not bad or not mine.get("ticket"):
        return []
    t = next(
        (
            x
            for x in w.tickets()
            if mine["ticket"] in (x.get("key"), x.get("id")) and (x.get("status") or "") not in DONE
        ),
        None,
    )
    if t is None:
        return []
    fix = next(
        (
            u
            for r in t.get("refs") or []
            if (
                m := re.search(
                    rf"github\.com/{re.escape(w.cfg.repo)}/pull/(\d+)", u := (r or {}).get("url") or ""
                )
            )
            and int(m[1]) != rel.get("pr")
        ),
        None,
    )
    if fix is None:
        return []
    key = str(t.get("key") or t["id"])
    have = w.exceptions()
    names = [
        c
        for c in bad
        if c in (mine.get("checks") or [])
        and not ((have.get(c) or {}).get("by") == BY and (have.get(c) or {}).get("ticket") == key)
    ]
    if not names:
        return []
    until = (now().date() + timedelta(days=FIX_DAYS)).isoformat()
    for c in names:
        w.record_exception(
            c,
            {"ticket": key, "until": until, "why": f"fix pull request {fix} linked to {key}"[:300], "by": BY,
             "at": now().isoformat(timespec="seconds")},
        )  # fmt: skip
    w.note(
        key, f"Release keeper: recorded a named exception until {until} for {', '.join(names)} (fix {fix})."
    )
    return [
        f"release {rel['n']}: {key} links the fix {fix}: recorded named exceptions until {until} for "
        f"{', '.join(names)}; judged again next pass"
    ]


def recut(w: World, st: dict, rel: dict, h: dict, what: str) -> bool:
    """A release held by red `what` (checks, walks) whose fix ticket is closed while develop moved on: close
    its pull request so the next pass cuts it again from the new develop. True when it did."""
    if (
        rel.get("fix")
        or h.get("green") == rel["sha"]
        or open_red_ticket(w.tickets(), f"Release {rel['n']} {what}")
    ):
        return False  # a fix release is never cut again from develop: its own fix makes it green
    w.close_release(rel)
    st["release"] = None
    st["skip_sha"] = None
    return True


def start_walks(w: World, rel: dict) -> list[str]:
    """One helper ticket per walk in github.release_walks that this release has not started yet. A fix release
    has none: it is one change on top of a release that was walked, and must ship within 30 minutes."""
    if rel.get("fix"):
        return []
    started = rel.setdefault("walks", {})
    out = []
    for name, skill in w.cfg.walks:
        if name in started:
            continue
        how = (
            f"Use the skill {skill}."
            if skill
            else f"Run this workspace's {name} walk as its skill or brief says."
        )
        tid = w.new_ticket(
            w.cfg.role or "",
            f"Release {rel['n']}: {name} walk",
            f"Release {rel['n']} waits for this walk before its Merge card: pull request "
            f"{rel.get('url') or ''} "
            f"(commit {rel['sha'][:12]}). {how} Walk exactly this commit in a test home or on a throwaway "
            "server, never on production or the real home. Open one ticket per bug you find. Then record the "
            f'result: orch github release-walk {rel["n"]} {name} pass "<what was walked, one line>" '
            f'--commit {rel["sha"][:12]} (or fail "<the worst problem>"), and finish this ticket.',
            f"The {name} walk of release {rel['n']} is recorded as passed or failed",
            priority="normal",
        )
        started[name] = {"ticket": tid, "at": now().isoformat()}
        out.append(f"release {rel['n']}: started the {name} walk ({tid})")
    return out


WALK_TITLE = re.compile(r"^Release (\d+): ([a-z][a-z0-9-]{0,30}) walk$")


def walk_of(root: Path, ticket: dict) -> dict | None:
    """ORCH-1835: the release walk this ticket is, with the result its helper recorded:
    {"n", "name", "commit", "result": {verdict, line, commit, by, at} | None}; None for any other ticket.
    The keeper's open release names its walk tickets and the commit to walk (a result for another cut of the
    same number is no result, as in walk_verdicts); an earlier release's walk is known by the title
    start_walks gave it, its commit is no longer known ("")."""
    ids = {str(ticket.get("id") or ""), str(ticket.get("key") or "")} - {""}
    cfg = Cfg(root)
    found, sha = None, ""
    rel = _read_json(cfg.state_path).get("release")
    if isinstance(rel, dict) and isinstance(rel.get("walks"), dict):
        for name, s in rel["walks"].items():
            if isinstance(s, dict) and str(s.get("ticket") or "") in ids:
                found, sha = (str(rel.get("n") or ""), str(name)), str(rel.get("sha") or "").lower()
    if found is None:
        m = WALK_TITLE.match(" ".join(str(ticket.get("title") or "").split()))
        if m is None:
            return None
        found = (m.group(1), m.group(2))
        if isinstance(rel, dict) and str(rel.get("n") or "") == found[0]:
            sha = str(rel.get("sha") or "").lower()  # the open release of that number: its commit counts
    n, name = found
    got = _read_json(cfg.walks_path).get(n)
    r = got.get(name) if isinstance(got, dict) else None
    ok = isinstance(r, dict) and r.get("verdict") in ("pass", "fail")
    c = str(r.get("commit") or "") if ok else ""
    if ok and sha and not (len(c) >= 7 and sha.startswith(c)):
        ok = False
    return {"n": int(n) if n.isdigit() else n, "name": name, "commit": sha[:12], "result": r if ok else None}


def walk_verdicts(w: World, rel: dict) -> dict:
    """{"passed", "failed", "waiting"} lines for the walks of github.release_walks; only a result for this
    release's own commit counts (an earlier cut of the same number walked another one)."""
    res: dict[str, list[str]] = {"passed": [], "failed": [], "waiting": []}
    if rel.get("fix"):
        return res
    got = (w.walk_results() or {}).get(str(rel["n"])) or {}
    started = rel.get("walks") or {}
    status = {t.get(k): t.get("status") for t in w.tickets() for k in ("key", "id")}
    for name, _ in w.cfg.walks:
        s = started.get(name) or {}
        r = got.get(name) or {}
        tk = s.get("ticket") or "no ticket"
        c = str(r.get("commit") or "")
        fresh = bool(r) and len(c) >= 7 and rel["sha"].startswith(c)
        if fresh and r.get("verdict") == "pass":
            res["passed"].append(f"{name} ({tk})")
        elif fresh and r.get("verdict") == "fail":
            res["failed"].append(f"{name} ({tk}): {r.get('line') or 'failed'}")
        elif (status.get(tk) or "") in DONE:
            res["waiting"].append(
                f"{name} ({tk} finished without a result: "
                f"orch github release-walk {rel['n']} {name} pass|fail ... --commit {rel['sha'][:12]})"
            )
        else:
            res["waiting"].append(f"{name} ({tk})")
    return res


def proof_gaps(w: World, rel: dict, p: dict) -> list[str]:
    """What a release merged before its Merge card was missing: red checks with no recorded exception,
    unfinished checks, walks without a pass."""
    rollup = p.get("statusCheckRollup")
    ignore = frozenset(w.known_red()) | ROLLUP_JOBS
    gaps = []
    bad = failed_checks(rollup, ignore)
    if bad:
        gaps.append(f"red checks with no recorded exception: {', '.join(bad)}")
    elif checks_green(rollup, ignore) == "pending":
        gaps.append("its checks had not finished")
    wv = walk_verdicts(w, rel)
    if wv["failed"] or wv["waiting"]:
        gaps.append(f"walks without a pass: {'; '.join(wv['failed'] + wv['waiting'])}")
    return gaps


def red(w: World, st: dict, role: str, title: str, words: str, note: str, done_when: str) -> list[str]:
    """One top ticket per red thing: never a second while one with the same words is open."""
    cur = open_red_ticket(w.tickets(), words)
    if cur:
        st["red_ticket"] = str(cur.get("key") or cur["id"])
        if st.get("red_logged") != title:
            w.note(cur.get("key") or cur["id"], f"Release keeper: still red. {note[:600]}")
            st["red_logged"] = title
        return [f"red, ticket {cur.get('key') or cur['id']} is open"]
    tid = w.new_ticket(role, title, note, done_when, over_limit=True)  # a red base starts at once (ORCH-699)
    st["red_ticket"] = tid if tid and not str(tid).startswith("not opened") else None
    st["red_logged"] = title
    return [f"red: opened top ticket {tid} ({title})"]


def develop_red(w: World, st: dict, role: str) -> list[str]:
    """The after-merge runs on develop (every push, at night; the workflows of github.release_after_merge):
    macOS and Windows run only there, not in the merge queue (ORCH-315), with ORCH-1120 the heavy checks too.
    For the newest FINISHED push or nightly run of each workflow that is red (judged job by job, ORCH-1128):
      1. its failed jobs run once more (GitHub's attempt counter: a run already tried again is not);
      2. still red: the red-develop ticket opens (one per workflow; the same words as a red release run, so
         one ticket), and its pull request goes first in the merge queue (the add-on knows the keeper's
         red-run tickets);
      3. no pull request of that ticket in the queue github.release_revert_hours (2) after it opened: the one
         suspect pull request is undone by a revert pull request, first in the queue on that ticket."""
    known = w.known_red()
    out: list[str] = []
    mem = st.setdefault("after_merge", {})
    for wf in w.cfg.after_merge:
        rows = [r for e in ("push", "schedule") for r in w.runs(wf, e) if r.get("event") == e]
        rows.sort(key=lambda x: str(x.get("createdAt")), reverse=True)
        seen: set[str] = set()
        for r in rows:
            sha = r.get("headSha")
            if not sha or sha in seen:
                continue
            seen.add(sha)
            state, run_, _ = run_state(w, wf, sha, None, ("push", "schedule"), known)
            if state in ("pending", "none"):
                continue
            if state == "green":
                mem.pop(wf, None)
            else:
                out += _red_after_merge(w, st, role, wf, sha, run_ or r, rows, known)
            break
    return out


def _red_after_merge(
    w: World, st: dict, role: str, wf: str, sha: str, run_: dict, rows: list[dict], known: dict
) -> list[str]:
    mem = st["after_merge"]
    rec = mem.get(wf) or {}
    name = _wf_name(wf)
    words = f"{name} run is red on develop"
    cur = open_red_ticket(w.tickets(), words)
    if rec.get("ticket") and (w.ticket(rec["ticket"]).get("status") or "") in DONE:
        # its ticket was closed while develop is still red: a fresh round
        rec = {k: rec[k] for k in ("first_red", "rid") if k in rec}
    rid = run_.get("databaseId")
    # 1. one more try, only for the first red run (a ticket already open: develop is known red, no reruns)
    if not cur and not rec.get("ticket") and rid is not None and int(run_.get("attempt") or 1) < 2:
        asked = ts(rec.get("rerun_at"))
        if rec.get("rerun") == rid and asked and (now() - asked).total_seconds() < TEST_TIMEOUT_H * 3600:
            return [f"{name} on develop {sha[:8]} is red; waits for its failed jobs to run once more"]
        if rec.get("rerun") != rid and w.rerun_once(rid):
            mem[wf] = {**rec, "rerun": rid, "rerun_at": now().isoformat(timespec="seconds")}
            return [f"{name} on develop {sha[:8]} is red: ran its failed jobs once more"]
    # 2. still red: the red-develop ticket (once per commit; the fix goes first in the merge queue)
    lines: list[str] = []
    if rec.get("red_sha") != sha:
        st["develop_red_sha"] = sha
        lines = red(
            w,
            st,
            role,
            f"{words} ({sha[:8]})",
            words,
            f"The {name} run on develop {sha[:8]} failed (and once more): {run_.get('url')}. It runs only on "
            "develop (after the merge), so fix it on develop with a normal pull request linked to this "
            "ticket: it goes first in the merge queue (orch pull-requests queue add --first). With no pull "
            f"request of this ticket in the queue {_hours(w.cfg.revert_hours)} after it opened, the release "
            "keeper opens a revert pull request for the pull request that broke it.",
            f"The next {name} run on develop is green",
        )
        if not (rec.get("ticket") or st.get("red_ticket")):
            return lines  # the ticket was not opened: no record, so the next pass tries again
        rec = {
            **rec,
            "red_sha": sha,
            "first_red": rec.get("first_red") or sha,
            "rid": rec.get("rid") or rid,
            "ticket": rec.get("ticket") or st.get("red_ticket"),
            "opened_at": rec.get("opened_at") or now().isoformat(timespec="seconds"),
        }
        rec.pop("rerun", None)
        rec.pop("rerun_at", None)
        mem[wf] = rec
    return lines + _revert_if_due(w, role, wf, rec, rows, known, str(run_.get("createdAt") or ""))


def last_green_before(w: World, wf: str, rows: list[dict], sha: str, known: dict) -> str | None:
    """The newest commit before `sha` whose run of wf finished green (from the runs listed, newest first)."""
    at = [str(r.get("createdAt")) for r in rows if r.get("headSha") == sha]
    if not at:
        return None
    for r in rows:
        c = r.get("headSha")
        if c and c != sha and str(r.get("createdAt")) < min(at):
            if run_state(w, wf, c, None, ("push", "schedule"), known)[0] == "green":
                return c
    return None


def _hours(h: float | None) -> str:
    return "never" if h is None else (f"{h:g} hours" if h != 1 else "1 hour")


def _revert_if_due(
    w: World, role: str, wf: str, rec: dict, rows: list[dict], known: dict, red_at: str
) -> list[str]:
    """3. The revert rule: the ticket open for revert_hours and none of its pull requests in the queue."""
    name = _wf_name(wf)
    key, opened = rec.get("ticket"), ts(rec.get("opened_at"))
    if w.cfg.revert_hours is None or not key or not opened or rec.get("revert"):
        return []
    if (now() - opened).total_seconds() < w.cfg.revert_hours * 3600:
        return []
    t = w.ticket(key)
    if (t.get("status") or "") in DONE:
        return []
    ids = {str(x) for x in (key, t.get("id"), t.get("key")) if x}
    queue = w.queue_entries()
    if queue is None:
        return [f"{name} red on develop: no merge queue here, so no revert pull request"]
    for e in queue:
        if str(e.get("ticket") or "") not in ids or e.get("state") == "out":
            continue
        # a fix waits or runs; a merged one counts until a red run started after its merge (it did not fix it)
        if e.get("state") != "merged" or (ts(e.get("ended")) or now()) > (ts(red_at) or now()):
            return []
    rec["revert"] = "looked"  # one look per red streak: never a second revert, never a retry loop
    good = last_green_before(w, wf, rows, rec["first_red"], known)
    members = w.merged_between(good, rec["first_red"]) if good else None
    if not members:
        why = "the last green commit is too far back" if not good else "git could not name the merges"
        w.note(
            key,
            f"Release keeper: no fix in the merge queue after {_hours(w.cfg.revert_hours)}, but no "
            f"revert: {why}. Fix it on develop.",
        )
        return [f"{name} red on develop: no revert ({why})"]
    tests = w.failed_tests(rec.get("rid") or "") if len(members) > 1 else []
    bad = suspect(members, tests)
    if bad is None:
        nums = ", ".join(f"#{m['pr']}" for m in members)
        w.note(
            key,
            f"Release keeper: no fix in the merge queue after {_hours(w.cfg.revert_hours)}; the merges "
            f"since the last green commit ({nums}) do not point at one pull request, so no revert. Fix it "
            "on develop or revert the right one by a pull request.",
        )
        return [f"{name} red on develop: no revert (not one clear suspect among {nums})"]
    pr = int(bad["pr"])
    body = (
        f"Reverts #{pr}: the {name} run on develop has been red since {rec['first_red'][:8]} and no fix "
        f"reached the merge queue within {_hours(w.cfg.revert_hours)} (release keeper, ticket {key}). "
        f"Failed tests: {', '.join(tests) or 'see the run'}. Bring the change back in a new pull request "
        "with the fix.\n\nOpened by the orch release keeper (no AI call)."
    )
    try:
        url = w.revert(pr, bad["sha"], f"Revert #{pr}: {name} red on develop", body, str(key))
    except Refused as e:
        w.note(key, f"Release keeper: the revert of #{pr} could not be opened: {e}")
        return [f"{name} red on develop: the revert of #{pr} failed ({e})"]
    rec["revert"] = url or "asked"
    w.note(
        key,
        f"Release keeper: no fix in the merge queue after {_hours(w.cfg.revert_hours)}: opened {url}, "
        f"which reverts #{pr}; it goes first in the merge queue.",
    )
    return [f"{name} red on develop: opened revert pull request {url} for #{pr}"]


WINVM_CONTEXT = "windows (winvm)"


def winvm_red(w: World, st: dict, role: str) -> list[str]:
    """The Windows checks on our own Windows VM (ORCH-1127) report as a commit status, not a workflow run:
    the newest develop commit with a FINISHED result that failed (after the dispatcher's one re-run) opens
    the same red-develop ticket as a red run, once per commit."""
    for sha, state in w.winvm_results():
        if state == "pending":
            continue
        if state == "success" or st.get("winvm_red_sha") == sha:
            return []
        st["winvm_red_sha"] = sha
        return red(
            w,
            st,
            role,
            f"windows (winvm) is red on develop ({sha[:8]})",
            "windows (winvm) is red on develop",
            f"The Windows checks on our own Windows VM failed on develop {sha[:8]} (status "
            f"'{WINVM_CONTEXT}', after one re-run; logs on the Mac under ~/.orch-test/winvm-runs). Fix it on "
            "develop with a normal pull request (orch pull-requests queue add --first).",
            "The next windows (winvm) result on develop is green",
        )
    return []


def quarantine_red(w: World, st: dict, role: str) -> list[str]:
    """The quarantined checks (ORCH-2363, quarantine.yml) are never required: the newest finished nightly run
    that is red opens one Backlog ticket with "later" in its title (not started, no revert, no rerun); while
    that ticket is open each further red run adds a note to it. Once per run."""
    try:  # a repository without the quarantine workflow has nothing to say here
        rows = [r for r in w.runs(QUARANTINE_FILE, "schedule") if r.get("status") == "completed"]
    except Refused:
        return []
    if not rows:
        return []
    r = max(rows, key=lambda x: str(x.get("createdAt")))
    if r.get("conclusion") in ("success", "skipped", "cancelled"):
        return []
    rid = str(r.get("databaseId") or r.get("url") or r.get("createdAt"))
    if st.get("quarantine_red_run") == rid:
        return []
    st["quarantine_red_run"] = rid
    sha = str(r.get("headSha") or "")[:8]
    note = (
        f"The nightly quarantine run on develop {sha} is red: {r.get('url')}. These checks are out of the "
        "merge queue because they are flaky (docs/ci-checks.md, Quarantine). Fix one, see it green in the "
        "quarantine run, then move it back into ci.yml / addons.yml in the same pull request."
    )
    cur = open_red_ticket(w.tickets(), QUARANTINE_WORDS)
    if cur:
        key = str(cur.get("key") or cur["id"])
        w.note(key, f"Release keeper: still red. {note}")
        return [f"quarantine run red on develop {sha}: noted on {key}"]
    tid = w.new_ticket(
        role,
        QUARANTINE_WORDS,
        note,
        "Every quarantined check is green and back in the merge queue",
        start=False,
    )
    if not tid or str(tid).startswith("not opened"):
        st.pop("quarantine_red_run", None)  # tried again next pass
        return [f"quarantine run red on develop {sha}: the later ticket was {tid or 'not opened'}"]
    return [f"quarantine run red on develop {sha}: opened later ticket {tid}"]


def pass_once(w: World, st: dict, role: str, hold: str | None) -> list[str]:
    """One pass (see the module text). Test branches whose deletion failed are tried again first and kept in
    the state while they still fail (ORCH-1475)."""
    for br in st.pop("test_branches_left", None) or []:
        w.drop_test_branch(br)
    try:
        return _pass(w, st, role, hold)
    finally:
        if w.left_branches:
            st["test_branches_left"] = sorted(set(w.left_branches))[-20:]


def _pass(w: World, st: dict, role: str, hold: str | None) -> list[str]:
    out: list[str] = []
    h = w.heads()
    try:
        out += develop_red(w, st, role)
    except (Refused, subprocess.TimeoutExpired, OSError, KeyError, ValueError, TypeError) as e:
        out.append(f"the develop check could not run: {e}")
    try:
        out += winvm_red(w, st, role)
    except (Refused, subprocess.TimeoutExpired, OSError, KeyError, ValueError, TypeError) as e:
        out.append(f"the Windows VM check could not run: {e}")
    try:
        out += quarantine_red(w, st, role)
    except (Refused, subprocess.TimeoutExpired, OSError, KeyError, ValueError, TypeError) as e:
        out.append(f"the quarantine check could not run: {e}")
    try:  # every pass, so a review starts while a pull request is still open
        sec_lines, sec_holds = secreview.tend(w, st, role)
    except (Refused, subprocess.TimeoutExpired, OSError, KeyError, ValueError, TypeError) as e:
        sec_lines, sec_holds = [f"security check could not run: {e}"], ["the security check could not run"]
    out += sec_lines
    rel = st.get("release")
    foreign = w.open_release()
    if foreign and not (rel and rel.get("pr") == foreign.get("number")):
        return out + [f"release PR {foreign['number']} is open and was not cut by the keeper: watching only"]

    if not rel or rel.get("phase") == "testing":  # a fix for the newest release goes before anything else
        lane = fix_lane(w, st, hold, sec_holds)
        if st.get("release") is not rel:
            return out + lane
        out += lane
        rel = st.get("release")

    if rel and rel.get("phase") in ("gate", "card"):
        p = w.pr(rel["pr"])
        if p.get("state") == "MERGED":
            if rel["phase"] == "gate":  # merged before the keeper put its Merge card: what proof was missing
                rel["unproven"] = proof_gaps(w, rel, p)
            rel["phase"] = "merged"
        elif p.get("state") == "CLOSED":
            out.append(f"release {rel['n']} PR {rel['pr']} was closed by someone: back to idle")
            w.remove_wt(rel.get("wt"))
            st["release"] = None
            return out
        elif rel["phase"] == "gate":
            out += start_walks(w, rel)
            req = w.required("main")  # the branch the release goes INTO; never develop's
            if req is None:
                return out + [f"release {rel['n']}: could not read the rules of main; asked again next pass"]
            waiting = not_reported(p.get("statusCheckRollup"), req or REQUIRED_FALLBACK)
            if waiting:
                return out + [
                    f"release {rel['n']}: release checks still running "
                    f"(not reported yet: {', '.join(waiting)})"
                ]
            ignore = frozenset(w.known_red()) | ROLLUP_JOBS
            g = checks_green(p.get("statusCheckRollup"), ignore)
            if g == "pending":
                return out + [f"release {rel['n']}: release checks still running"]
            if g == "red":
                bad = ", ".join(failed_checks(p.get("statusCheckRollup"), ignore)) or "see the pull request"
                runs = failed_runs(p.get("statusCheckRollup"), ignore)
                again = rel.get("reran") or {}
                if runs and not again:  # one more try: a flaky test must not close it (ORCH-1023)
                    # written before the call: the new try starts after this time at GitHub
                    rel["reran"] = {"runs": runs, "at": now().isoformat()}
                    asked = []
                    for run_id in runs:
                        try:
                            w.rerun_failed(run_id)
                            asked.append(run_id)
                        except Refused as e:  # refused: no endless retries, the red path below goes on
                            out.append(f"release {rel['n']}: could not run {run_id} again: {e}")
                    if asked:
                        return out + [
                            f"release {rel['n']}: checks red on {bad}; ran the failed jobs once more"
                        ]
                elif again:
                    since = ts(again.get("at"))
                    if (
                        since
                        and now() - since < timedelta(hours=TEST_TIMEOUT_H)
                        and failed_before(p.get("statusCheckRollup"), since, ignore)
                    ):
                        return out + [f"release {rel['n']}: waits for the failed jobs to finish once more"]
                if recut(w, st, rel, h, "checks"):
                    return out + [
                        f"release {rel['n']}: checks were red, develop moved and the fix ticket is closed: "
                        "closed the pull request; cut again next pass"
                    ]
                names = failed_checks(p.get("statusCheckRollup"), ignore)
                if fixed := fix_exceptions(w, rel, names):
                    return out + fixed
                lines = red(
                    w,
                    st,
                    role,
                    f"Release {rel['n']} checks are red: {bad}"[:120],
                    f"Release {rel['n']} checks",
                    f"The release pull request {p.get('url')} into main is red on: {bad}. Fix it on "
                    "develop (a normal pull request); the release keeper closes this release and cuts it "
                    "again once develop "
                    "has the fix and this ticket is done. A red check ships only with a named exception: "
                    "link the fix pull request to this ticket (orch ref add) and the release keeper records "
                    f"one for the checks named here until {FIX_DAYS} days later, so the release goes without "
                    'a new cut; or a person records one: orch github release-exception "<check>" --ticket '
                    "<key> --until <YYYY-MM-DD>.",
                    f"Release {rel['n']}'s checks are green (after a fix on develop)",
                )
                mine = rel.get("red_checks") or {}  # which checks the keeper put on which ticket (ORCH-178)
                if st.get("red_ticket") and mine.get("ticket") != st["red_ticket"]:
                    mine = {"ticket": st["red_ticket"], "checks": []}
                if mine:
                    mine["checks"] = sorted(set(mine.get("checks") or []) | set(names))
                    rel["red_checks"] = mine
                return out + lines
            wv = walk_verdicts(w, rel)
            if wv["failed"]:
                bad = "; ".join(wv["failed"])
                if recut(w, st, rel, h, "walks"):
                    return out + [
                        f"release {rel['n']}: a walk failed, develop moved and the fix ticket is closed: "
                        "closed the pull request; cut again next pass"
                    ]
                return out + red(
                    w,
                    st,
                    role,
                    f"Release {rel['n']} walks failed: {bad}"[:120],
                    f"Release {rel['n']} walks",
                    f"A walk of release {rel['n']} ({p.get('url')}) failed: {bad}. Fix what it found on "
                    "develop (one ticket per bug); the release keeper closes this release and cuts it again "
                    "once develop has the fixes and this ticket is done.",
                    f"Every walk of release {rel['n']} passes (after the fixes on develop)",
                )
            if wv["waiting"]:
                return out + [
                    f"release {rel['n']}: checks green; waits for the walks: {'; '.join(wv['waiting'])}"
                ]
            allowed = w.known_red()
            excused = [
                f"{c} ({allowed[e]})"
                for c in failed_checks(p.get("statusCheckRollup"), ROLLUP_JOBS)
                if (e := known_name(c, allowed)) is not None
            ]
            rel["known_red"] = sorted(set((rel.get("known_red") or []) + excused))
            proof = (f" Red by a named exception: {', '.join(excused)}." if excused else "") + (
                f" Walks passed: {', '.join(wv['passed'])}." if wv["passed"] else ""
            )
            ask = [
                role,
                f"Merge release {rel['n']} into main?{proof}",
                "--link",
                f"Release {rel['n']}",
                "--open",
                p["url"],
                "--merge",
                "--release",
                "--then",
                f"Release {rel['n']} goes to main; then this workspace updates to it and you get the "
                "highlights.",
            ]
            r = w.ask(ask) if not (w.dry or w.sim is not None) else None
            w.did.append(f"card:release {rel['n']}")
            if r is not None and r.returncode != 0:
                return out + [
                    f"release {rel['n']}: the Merge card was refused: {(r.stderr or r.stdout).strip()[:200]}"
                ]
            rel["phase"] = "card"
            out.append(f"release {rel['n']}: checks green, Merge card on the role ticket")
        if rel["phase"] == "card":
            r = w.act("tend-releases", lambda: tend_releases(w))
            p = w.pr(rel["pr"]) if r is not None or w.sim is not None else p
            if p.get("state") == "MERGED":
                rel["phase"] = "merged"
            else:
                return out + [
                    f"release {rel['n']}: waits for the Merge (the owner's click, or by itself when "
                    "Settings allow it)"
                ]

    if rel and rel.get("phase") == "merged":
        return out + installed(w, st, role, rel, h)

    dep = st.get("deploy")
    if dep:
        out += deploy_answered(w, st, role, dep)

    if rel and rel.get("phase") == "testing":
        since = ts(rel.get("dispatched_at"))
        known = w.known_red()
        states, noted = [], []
        tbr = rel.get("test_branch") or "develop"  # develop: a release dispatched before ORCH-1475
        for wf, _ in w.cfg.workflows:
            s_, r_, n_ = run_state(w, wf, rel["sha"], since, ("workflow_dispatch",), known, tbr)
            states.append((_wf_name(wf), s_, r_))
            noted += n_
        rel["known_red"] = noted
        per_run = [red_jobs(w, r_, known) for _, s_, r_ in states if s_ == "red"]
        # a red run without a job list (red as a whole) is never retried, nor are the others with it
        reds = [x for jobs_ in per_run for x in jobs_] if per_run and all(per_run) else []
        again = retry_time_limit(w, rel, reds) if reds else None
        if again:
            return out + again
        for name, s_, r_ in states:
            if s_ == "red":
                st["release"] = None
                st["skip_sha"] = rel["sha"]
                w.drop_test_branch(rel.get("test_branch"))
                return out + red(
                    w,
                    st,
                    role,
                    f"{name} run is red on develop (release {rel['n']} blocked)",
                    f"{name} run is red on develop",
                    f"The full {name} run on develop {rel['sha'][:8]} failed: {(r_ or {}).get('url')}. "
                    f"Release {rel['n']} waits until develop has the fix; the release keeper tests the new "
                    "head by "
                    "itself.",
                    f"The next {name} run on develop is green",
                )
        if all(s_ == "green" for _, s_, _ in states):
            rel["phase"] = "cut"
            w.drop_test_branch(rel.pop("test_branch", None))
        else:
            if since and (now() - since).total_seconds() > TEST_TIMEOUT_H * 3600:
                st["release"] = None
                w.drop_test_branch(rel.get("test_branch"))
                return out + [
                    f"release {rel['n']}: test runs did not finish in {TEST_TIMEOUT_H} h; again next pass"
                ]
            return out + [
                f"release {rel['n']}: "
                + ", ".join(f"{n_} {s_}" for n_, s_, _ in states)
                + f" on {rel['sha'][:8]}"
            ]

    if rel and rel.get("phase") == "cut":
        return out + cut_now(w, st, h, role)

    if rel:
        return out
    # idle
    un = h["unreleased"]
    if not h.get("green"):
        return out + ["no develop commit is fully green yet: nothing is cut"]
    if not un:
        return out + ["green develop has nothing main does not have"]
    if hold:
        return out + [f"on hold: {hold}"]
    if sec_holds:
        return out + ["waits for every security OK: " + ", ".join(sec_holds)]
    nums = {int(m[1]) for u in un if (m := re.search(r"#(\d+)", u["subject"]))}
    urgent = sorted(nums & w.urgent())
    last = w.last_release_at()  # only a merged release moves the pace; a blocked or red try does not
    gap_h = (now() - last).total_seconds() / 3600 if last else 999
    if not urgent and gap_h < MIN_GAP_H:
        return out + [
            f"{len(un)} unreleased pull request(s); last release {gap_h:.1f} h ago, next after "
            f"{MIN_GAP_H} h (or at once for an {URGENT_LABEL} one)"
        ]
    sha = h["green"]  # never develop's head: only a commit whose own push run finished green (ORCH-314)
    if st.get("skip_sha") == sha:
        return out + [f"develop {sha[:8]} was red; waiting for develop to move"]
    n = w.last_release() + 1
    rel = {"n": n, "sha": sha, "unreleased": un, "phase": "testing", "dispatched_at": now().isoformat()}
    if urgent:
        out.append(f"urgent pull request(s) {', '.join('#' + str(x) for x in urgent)}: release now")
    known = w.known_red()
    nightly = [run_state(w, wf, sha, None, ("schedule",), known) for wf, _ in w.cfg.workflows]
    if all(s_ == "green" for s_, _, _ in nightly):
        rel["known_red"] = [x for _, _, n_ in nightly for x in n_]
        rel["phase"] = "cut"
        st["release"] = rel
        out.append(f"release {n}: the nightly runs on {sha[:8]} are green")
        return out + cut_now(w, st, h, role)
    try:
        rel["test_branch"] = w.test_branch(n, sha)
    except (Refused, subprocess.TimeoutExpired, OSError) as e:
        return out + [f"release {n}: could not make the test branch for {sha[:8]}: {e}; again next pass"]
    try:
        for wf, extra in w.cfg.workflows:
            w.dispatch(wf, extra, rel["test_branch"])
    except (Refused, subprocess.TimeoutExpired, OSError):
        w.drop_test_branch(rel["test_branch"])  # not tracked by any release: never left behind
        raise
    st["release"] = rel
    names = " and ".join(_wf_name(wf) for wf, _ in w.cfg.workflows)
    return out + [f"release {n}: {len(un)} pull requests waiting; started {names} on {sha[:8]}"]


def _other_change(hold: str, fix: dict) -> bool:
    """A security hold that names another pull request or another commit than the fix: the fix release ships
    only the fix pull request's own change (cut_fix), so those cannot hold it. A hold on a merge-queue group
    names the group, and the group's other pull requests are not shipped. Any other hold (the check could not
    run, a commit of the fix itself or its merge commit ...) counts."""
    m = re.match(r"^#(\d+) \(", hold) or re.match(r"^([0-9a-f]{7,40}) \(", hold)
    if not m:
        return False
    v = m[1]
    if hold.startswith("#"):
        return v != str(fix["number"])
    return not any(str(fix.get(k) or "").startswith(v) for k in ("sha", "head"))


def _own_review_hold(w: World, st: dict, fix: dict) -> tuple[str | None, list[str]]:
    """(hold, lines) for the fix pull request's own security review, for the head it was merged with. A fix
    merged inside a merge-queue group has no hold of its own in the release's list (that names the group), so
    it is checked here, over exactly the files the fix release ships: when one is a watched path, only an OK
    for that head lets it ship. A missing review is started here (ORCH-786)."""
    n, head = str(fix["number"]), str(fix.get("head") or "")
    files = w.fix_files(fix)
    if files is None:
        return f"#{n} (its own changed files are not known)", []
    hits = secreview.matched(files, secreview.patterns(w.cfg.security_paths))
    if not hits:
        return None, []
    sec = st.get("security") if isinstance(st.get("security"), dict) else {}
    sec.setdefault("prs", {})
    st["security"] = sec
    e = sec["prs"].get(n)
    lines: list[str] = []
    if not isinstance(e, dict) or (e.get("sha") != head and not secreview._open(w, e.get("tid"))):
        pr = {"number": int(n), "title": fix.get("title"), "url": fix.get("url"), "headRefOid": head}
        lines.append(secreview._start(w, sec, w.cfg.role or "", pr, hits, secreview._window(w)))
        e = sec["prs"].get(n)
    if not isinstance(e, dict) or not head or e.get("sha") != head:
        return f"#{n} (no security review of its merged head yet)", lines
    got = secreview._effective(e, (w.security_verdicts() or {}).get(n))
    if got in secreview.OK:
        return None, lines
    return f"#{n} (security review " + ("found problems)" if got == "problems" else "has no OK yet)"), lines


def fix_lane(w: World, st: dict, hold: str | None, sec_holds: list[str] | None = None) -> list[str]:
    """A merged pull request labelled "fix for release N", N the newest release on main, not shipped yet: cut
    release N.k from main with only that change, at once (no pace, no other work, no walks). Its checks, Merge
    card and update then go the normal way. A release that was being tested waits; it is tested after."""
    try:
        fixes = w.fixes()
    except (Refused, subprocess.TimeoutExpired, OSError, KeyError, ValueError, TypeError) as e:
        return [f"the fix lane could not read merged fixes: {e}"]
    done = set(st.get("fixes_shipped") or [])
    try:
        newest = w.last_release()
    except (Refused, subprocess.TimeoutExpired, OSError, KeyError, ValueError, TypeError) as e:
        return [f"the fix lane could not read the newest release: {e}"]
    todo = [f for f in fixes if f["number"] not in done and f["release"] == newest]
    stale = [f for f in fixes if f["number"] not in done and f["release"] != newest]
    out = [
        f"#{f['number']} is labelled a fix for release {f['release']}, but the newest release is {newest}: "
        "it ships with the next release"
        for f in stale
    ]
    st["fixes_shipped"] = sorted(done | {f["number"] for f in stale})[-100:]
    if not todo:
        return out
    if hold:
        return out + [f"fix #{todo[0]['number']} for release {newest} waits: on hold: {hold}"]
    fix = sorted(todo, key=lambda f: f["number"])[0]
    mine = [x for x in sec_holds or [] if not _other_change(x, fix)]  # fail closed: unknown holds count
    own, started = _own_review_hold(w, st, fix)
    out += started
    if own and own not in mine:
        mine.append(own)
    if mine:  # the same rule as every release: no cut before the security OK of what it ships
        return out + [
            f"fix #{fix['number']} for release {newest} waits for its security OK: " + ", ".join(mine)
        ]
    k = w.fix_count(newest) + 1
    label = f"{newest}.{k}"
    rel = st.get("release")
    if rel:  # a normal release was being tested: it starts again after the fix release
        out.append(f"release {rel['n']}: testing stopped for fix release {label}; tested again after it")
        w.drop_test_branch(rel.get("test_branch"))
        st["release"] = None
    body = (
        f"Fix release {label}: release {newest} plus only #{fix['number']} "
        f"({_short(fix.get('title') or '')}).\n\n"
        f"Cut by the release keeper from main: the change of {fix.get('url') or '#' + str(fix['number'])} "
        "and nothing else. No walks: it is one change on top of a walked release."
    )
    try:
        got = w.cut_fix(newest, k, fix, body)
    except Refused as e:
        st["fixes_shipped"] = sorted(set(st["fixes_shipped"]) | {fix["number"]})[-100:]
        return out + red(
            w,
            st,
            w.cfg.role or "",
            f"Fix release {label} could not be cut: #{fix['number']}"[:120],
            f"Fix release {label}",
            f"The fix {fix.get('url')} for release {newest} could not be shipped as {label}: {e}. Ship it "
            "with the next release, or make a pull request that applies on main and label it again.",
            f"Fix release {label} is out, or the fix ships with the next release",
        )
    if not got:
        return out + [f"fix release {label}: cut failed (see the log); tried again next pass"]
    st["fixes_shipped"] = sorted(set(st["fixes_shipped"]) | {fix["number"]})[-100:]
    st["release"] = {
        "n": label,
        "fix": fix["number"],
        "sha": got.get("sha") or "",
        "unreleased": [],
        "phase": "gate",
        "pr": got["number"],
        "url": got["url"],
        "wt": got["wt"],
        "main_before": w.heads()["main"] if w.sim is None else (w.sim.get("heads") or {}).get("main"),
    }
    return out + [
        f"fix release {label}: cut with only #{fix['number']}, pull request {got['url']}; its checks next"
    ]


def tend_releases(w: World) -> dict:
    """`orch review tend-releases` in this process: merges the release when the owner allowed it."""
    from orch import review

    try:
        return review.tend_releases(w.root, known_red=w.known_red())
    except Refused as e:  # inside a helper, or GitHub said no: the owner's click still works
        return {"refused": str(e)}


def cut_now(w: World, st: dict, h: dict, role: str | None = None) -> list[str]:
    rel = st["release"]
    signal = " and ".join(_wf_name(wf) for wf, _ in w.cfg.workflows)
    body = release_body(rel["n"], rel["sha"], rel.get("unreleased") or [], w.tickets(), w.cfg.repo, signal)
    w.secret_hit = None
    try:
        got = w.cut(rel["n"], rel["sha"], body)
    except Refused as e:
        out = [f"release {rel['n']}: cut failed: {e}"]
        hit = w.secret_hit
        if hit and role and rel.get("secret_card") != hit["shown"]:
            out.append(secret_card(w, rel, role, hit))
        return out
    if not got:
        return [f"release {rel['n']}: cut failed (see the log)"]
    rel.update(phase="gate", pr=got["number"], url=got["url"], wt=got["wt"], main_before=h["main"])
    return [f"release {rel['n']}: cut, pull request {got['url']}; its checks next", *start_walks(w, rel)]


def secret_card(w: World, rel: dict, role: str, hit: dict) -> str:
    """One card per release and line: which line of the release text the secret check stopped at (masked).
    The keeper tries again every pass; the card only says what to change."""
    q = (
        f"Release {rel['n']} is not cut: line {hit['line']} of its release text looks like it holds "
        f'{hit["words"]}: "{hit["shown"]}". The line comes from a ticket title, or for a pull request '
        "without a ticket from its merge commit: change the ticket's title (or link that pull request to a "
        "ticket with a plain title), and the next pass cuts the release by itself."
    )
    args = [role, q, "--option", "I changed the title", "--option", "Leave it for now"]
    r = w.ask([*args, "--recommend", "I changed the title"]) if not (w.dry or w.sim is not None) else None
    w.did.append(f"card:release {rel['n']} secret line {hit['line']}")
    if r is not None and r.returncode != 0:
        return f"release {rel['n']}: the card was refused: {(r.stderr or r.stdout).strip()[:200]}"
    rel["secret_card"] = hit["shown"]
    return f"release {rel['n']}: card on the role ticket names line {hit['line']} of the release text"


def installed(w: World, st: dict, role: str, rel: dict, h: dict) -> list[str]:
    """Merged: update here, prepare the deploy, note the highlights, remove the worktree."""
    n = rel["n"]
    u = w.act("update", lambda: w.orch(["update", "--json"]))
    upd = (
        "updated"
        if (u is None or getattr(u, "returncode", 0) == 0)
        else "update refused: " + ((u.stderr or u.stdout).strip()[:200])
    )
    servers = w.cfg.servers
    base = rel.get("main_before") or h["main"]
    deploy = w.changed(base, rel["sha"], [f"{x}/" for x in servers])
    changed = sorted({x.split("/")[0] for x in deploy} & set(servers))
    running = {x: w.running(x, rel["sha"]) for x in changed}
    parts = [x for x in changed if not running[x]]
    prep = {x: prepare(w, x, n, rel["sha"], base) for x in parts}
    for x in [x for x in parts if prep[x].get("live")]:  # production already runs this very program
        w.record_deployed([x], rel["sha"], "release keeper (same program on the server)")
        running[x] = {"at": now().isoformat()}
    parts = [x for x in changed if not running[x]]
    done = [x for x in changed if running[x]]
    if parts:
        what = " and ".join(parts)
        ready = "; ".join(prep_line(x, prep[x]) for x in parts)
        r = w.act(
            f"deploy-card:{what}",
            lambda: w.ask(
                [
                    role,
                    f"Release {n} {DEPLOY_ASK} {what} server. Deploy it to production now? {ready}",
                    "--option",
                    "Deploy now",
                    "--option",
                    "Already deployed",
                    "--option",
                    "Later",
                    "--recommend",
                    "Deploy now",
                    "--json",
                ]
            ),
        )
        st["deploy"] = {"n": n, "what": what, "sha": rel["sha"], "prep": {x: prep[x] for x in parts}}
        qid = _asked_id(r)
        if qid:
            st["deploy"]["qid"] = qid
    un = rel.get("unreleased") or []
    if un:
        items = highlights(un, w.tickets(), w.cfg.repo)
    else:  # a release from before the keeper kept its list: the lines of its pull request
        items = [ln[2:] for ln in (w.pr(rel["pr"]).get("body") or "").splitlines() if ln.startswith("- ")]
    kr = rel.get("known_red") or []
    gaps = rel.get("unproven") or []
    head = f"Release {n} is on main and installed here ({upd})." + (
        f" It reached main without its proof: {'; '.join(gaps)}." if gaps else ""
    )
    tail = (
        (f"\nRed by a named exception: {', '.join(kr)}." if kr else "")
        + "".join(
            f"\nThe {x} server already runs this release (deployed {_when(running[x])}): nothing to deploy."
            for x in done
        )
        + (f"\nThe {' and '.join(parts)} server changed: a deploy card waits." if parts else "")
    )
    w.note(role, head + highlight_block(items, NOTE_MAX - len(head) - len(tail)) + tail)
    w.remove_wt(rel.get("wt"))
    st["release"] = None
    st["last_installed"] = n
    return [
        f"release {n}: merged, {upd}, highlights noted"
        + (f", WITHOUT PROOF ({'; '.join(gaps)})" if gaps else "")
        + (", deploy card asked" if parts else "")
        + (f", {' and '.join(done)} already deployed" if done else "")
    ]


def _asked_id(r) -> str | None:
    """The question id `orch ask --json` printed, or None."""
    try:
        qid = json.loads(getattr(r, "stdout", "") or "{}").get("id")
    except (ValueError, AttributeError):
        return None
    return qid if isinstance(qid, str) and qid else None


def deploy_answered(w: World, st: dict, role: str, dep: dict) -> list[str]:
    ans = deploy_answer(w.ticket(role), dep["n"], dep.get("qid"), w.root if w.sim is None else None)
    parts = dep["what"].split(" and ")
    if ans == "Deploy now" and dep.get("sha") and all(w.running(x, dep["sha"]) for x in parts):
        st["deploy"] = None  # deployed by hand between the card and the answer: no second production deploy
        w.note(role, f"Release {dep['n']}: the {dep['what']} server already runs it; no deploy ticket.")
        return [f"deploy: {dep['what']} already runs release {dep['n']}"]
    if ans == "Already deployed":
        if dep.get("sha"):
            w.record_deployed(parts, dep["sha"], "owner (Already deployed)")
        st["deploy"] = None
        return [f"deploy: the owner said {dep['what']} is already deployed"]
    if ans == "Deploy now":
        tid = w.new_ticket(
            role,
            f"Deploy release {dep['n']} {dep['what']} to production",
            f"The owner said Deploy now. Deploy the {dep['what']} server of release {dep['n']} to "
            "production with the usual procedure (CI artifact, backup, health checks). No tests on "
            "production. When the health "
            f"checks answer, write down what runs there: orch github release-deployed "
            f"{dep['what'].replace(' and ', ',')}={dep.get('sha') or '<release commit>'}"
            + helper_steps(dep.get("prep") or {}, w.cfg.deploy_script),
            "The production health checks answer with the new version",
            priority="high",
        )
        st["deploy"] = None
        return [f"deploy go: ticket {tid}"]
    if ans:
        st["deploy"] = None
        return [f"deploy: the owner said {ans}"]
    return []


def prepare(w: World, part: str, n: int, sha: str, base: str) -> dict:
    """Deploy preparation of one server, no production change: {"ready", "run", "path", "sha256", "prod",
    "live", "needs", "why"}. A step that cannot be done says why; the deploy helper then does it by hand."""
    out: dict = {"ready": False}
    rec = w.deployed().get(part)
    try:
        out["needs"] = w.needs_person(
            rec["sha"] if isinstance(rec, dict) and rec.get("sha") else base, sha, part
        )
    except (Refused, OSError, subprocess.TimeoutExpired) as e:
        out["needs"] = [f"could not compare: {str(e)[:80]}"]
    try:
        run = w.built_run(part, sha)
        if not run:
            out["why"] = f"no green {part} build of this tree yet"
            return out
        out["run"] = run.get("databaseId")
        dest = w.cfg.stage_dir / f"{part}-r{n}"
        got = w.act(f"fetch:{part} run {out['run']}", lambda: w.fetch_built(part, out["run"], dest))
        if got is None and w.sim is not None:
            got = w.fetch_built(part, out["run"], dest)
        if got is None:  # dry run
            out["why"] = "dry run: not fetched"
            return out
        if not got.get("linux"):
            out["why"] = "the built program is not for Linux x86_64"
            return out
        out.update(path=got.get("path"), sha256=got.get("sha256"), ready=True)
        w.drop_old_stages(part)
    except (Refused, OSError, subprocess.TimeoutExpired, ValueError) as e:
        out["why"] = f"fetch failed: {str(e)[:120]}"
        return out
    out["prod"] = w.prod_sha(part)
    out["live"] = bool(out["prod"] and out["prod"] == out.get("sha256"))
    return out


def prep_line(part: str, p: dict) -> str:
    """One plain sentence for the deploy card."""
    if not p.get("ready"):
        return f"The {part} server is not prepared ({p.get('why') or 'unknown'}); the helper fetches it."
    needs = "; ".join(p.get("needs") or []) or "no new settings or data changes"
    line = f"The {part} server is fetched and checked ({needs})."
    if not p.get(
        "prod"
    ):  # after the 19 Nov server move the deploy host pointed at the stopped server, unnoticed
        line += (
            f" Production's {part} program could not be read over ssh: check that the deploy host and key "
            "settings (github.release_deploy_host, github.release_deploy_key) point at the server that runs "
            "it now."
        )
    return line


def helper_steps(prep: dict, script: str | None = None) -> str:
    """The prepared facts for the deploy helper, so the go costs a short run."""
    lines = []
    for part, p in prep.items():
        if p.get("ready"):
            how = f"install with {script} {part} {p['path']}" if script else "install it"
            lines.append(
                f"\n{part}: prepared program {p['path']} (sha256 {p['sha256']}, CI run {p.get('run')}); "
                f"production runs sha256 {p.get('prod') or 'unknown'}. Back up the program and the "
                f"database first, then {how}."
            )
        else:
            lines.append(
                f"\n{part}: not prepared ({p.get('why') or 'unknown'}): fetch the CI artifact yourself."
            )
        if p.get("needs"):
            lines.append(f" Look at: {'; '.join(p['needs'])}.")
    return "".join(lines)


def deploy_answer(ticket: dict, n: int, qid: str | None = None, root: Path | None = None) -> str | None:
    """A person's answer to the deploy card: the very question the keeper asked (its id; the words only for a
    card asked before ids were kept), answered by a human:. Anything else is no answer: "Deploy now" leads to
    production, so an agent's answer never counts, and with `root` the ticket is read through
    history.shown_ticket, where an answer this computer cannot prove (a synced one) is not a human: one."""
    if root is not None:
        from orch import history

        ticket = history.shown_ticket(root, ticket)
    for q in ticket.get("questions") or []:
        if qid is not None and q.get("id") != qid:
            continue
        if qid is None and f"Release {n} {DEPLOY_ASK}" not in (q.get("text") or ""):
            continue
        if not q.get("answer") or not str(q.get("answered_by") or "").startswith("human:"):
            continue
        return q["answer"]
    return None


# ---------------------------------------------------------------- state and entry points


def read_state(cfg: Cfg) -> dict:
    try:
        p = cfg.state_path
        if p.stat().st_size > STATE_MAX:
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(cfg: Cfg, st: dict) -> None:
    cfg.run_dir.mkdir(parents=True, exist_ok=True)
    runs._atomic(cfg.state_path, json.dumps(st, indent=1, default=str) + "\n")


def hold_text(cfg: Cfg) -> str | None:
    try:
        return cfg.hold_path.read_text(encoding="utf-8").strip() or "hold set"
    except OSError:
        return None


def set_hold(root: Path, why: str) -> str | None:
    """`orch github release-hold "<why>"` stops cutting; off lifts it. Returns the hold text or None."""
    cfg = Cfg(root)
    v = " ".join((why or "").split())[:300]
    if v.lower() in ("off", "none", ""):
        with contextlib.suppress(FileNotFoundError):
            cfg.hold_path.unlink()
        return None
    cfg.run_dir.mkdir(parents=True, exist_ok=True)
    runs._atomic(cfg.hold_path, v + "\n")
    return v


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def set_exception(
    root: Path, check: str, ticket: str | None, until: str | None, why: str | None, by: str
) -> dict | None:
    """`orch github release-exception "<check>" --ticket <key> --until <YYYY-MM-DD> [--why ...]`: a named
    exception that lets this one check be red in a release until the date or until the ticket is done.
    `off` as the ticket removes it. Returns the entry, or None when removed."""
    cfg = Cfg(root)
    check = " ".join((check or "").split())
    if not check or len(check) > 120:
        raise Refused(
            'Name the check as the pull request shows it, e.g. "workspace / test (windows-latest)".'
        )
    data = _read_json(cfg.exceptions_path)
    if (ticket or "").strip().lower() == "off":
        if data.pop(check, None) is None:
            raise Refused(f"No exception is recorded for {check}.")
        runs._atomic(cfg.exceptions_path, json.dumps(data, indent=1) + "\n")
        return None
    if not ticket or not until:
        raise Refused("An exception needs its ticket and an end date: --ticket <key> --until <YYYY-MM-DD>.")
    t = tickets.load(root, tickets.resolve(root, ticket.strip()))  # an unknown ticket is refused here
    if not DATE_RE.match(until.strip()) or ts(until.strip()) is None:
        raise Refused("Give the end date as YYYY-MM-DD.")
    if until.strip() < now().date().isoformat():
        raise Refused("The end date is in the past.")
    e = {
        "ticket": str(t.get("key") or t["id"]),
        "until": until.strip(),
        "why": " ".join((why or "").split())[:300],
        "by": by,
        "at": now().isoformat(timespec="seconds"),
    }
    data[check] = e
    cfg.run_dir.mkdir(parents=True, exist_ok=True)
    runs._atomic(cfg.exceptions_path, json.dumps(data, indent=1) + "\n")
    return e


def list_exceptions(root: Path) -> dict[str, dict]:
    return _read_json(Cfg(root).exceptions_path)


def record_walk(root: Path, n: int, name: str, verdict: str, line: str, by: str, commit: str = "") -> dict:
    """`orch github release-walk <N> <walk> pass|fail "<line>" --commit <sha>`: a walk helper's result for
    release N, for the commit it walked."""
    cfg = Cfg(root)
    names = [x for x, _ in cfg.walks]
    if name not in names:
        raise Refused(
            f"{name} is not a release walk here "
            f"({', '.join(names) or 'none: orch config set github.release_walks'})."
        )
    if verdict not in ("pass", "fail"):
        raise Refused("The result is pass or fail.")
    text = " ".join((line or "").split())[:300]
    if not text:
        raise Refused("Say in one line what was walked (pass) or the worst problem (fail).")
    if n < 1:
        raise Refused("Give the release number.")
    commit = (commit or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{7,40}", commit):
        raise Refused("Give the commit you walked: --commit <sha> (its ticket names it).")
    data = _read_json(cfg.walks_path)
    for k in sorted(data, key=lambda x: int(x) if str(x).isdigit() else 0)[:-20]:  # keep the last 20 releases
        data.pop(k, None)
    e = {
        "verdict": verdict,
        "line": text,
        "commit": commit,
        "by": by,
        "at": now().isoformat(timespec="seconds"),
    }
    data.setdefault(str(n), {})[name] = e
    cfg.run_dir.mkdir(parents=True, exist_ok=True)
    runs._atomic(cfg.walks_path, json.dumps(data, indent=1) + "\n")
    return e


def missing(cfg: Cfg) -> list[str]:
    return [
        k
        for k, v in (
            ("github.release_keeper", cfg.role),
            ("github.release_repo", cfg.repo != "owner/repo" and cfg.repo),
            ("github.release_clone", cfg.clone),
        )
        if not v
    ]


def run(
    root: Path, *, dry_run: bool = False, known: dict[str, str] | None = None, world: World | None = None
) -> dict:
    """One pass: {"off"|"paused", "lines", "did", "state"}. dry_run writes nothing."""
    cfg = Cfg(root)
    if missing(cfg):
        return {"off": True, "missing": missing(cfg)}
    if brake.paused(root) is not None:
        return {"off": False, "paused": True}
    t = tickets.load(
        root, tickets.resolve(root, cfg.role)
    )  # the role ticket was removed: Refused, plain words
    role = str(t.get("key") or t["id"])
    reopened = None
    if t.get("status") == "done" and not dry_run:
        # A person moved the role ticket to Done but its repeat goes on (a repeat survives Done): every
        # card of this pass would be refused ("This ticket is closed") and nothing reaches Home.
        # Open it again.
        tickets.set_status(root, t["id"], "open", tickets.SYSTEM)
        tickets.log(
            root,
            t["id"],
            "The role ticket was Done but its repeat still runs: opened it again so the cards reach you.",
            tickets.SYSTEM,
        )
        reopened = f"{role} was Done while its repeat runs: opened it again"
    st = read_state(cfg)
    w = world or World(root, cfg, dry=dry_run, known=known)
    try:
        lines = pass_once(w, st, role, hold_text(cfg))
    except (Refused, subprocess.TimeoutExpired, OSError, KeyError, ValueError) as e:
        lines = [f"pass stopped: {e}"]
    if reopened:
        lines.insert(0, reopened)
    if not dry_run:
        _write_state(cfg, st)
    return {"off": False, "paused": False, "role": role, "lines": lines, "did": w.did, "state": st}


def record_deployed(root: Path, spec: str, by: str) -> dict:
    """`orch github release-deployed relay,publish=<commit>`: what production runs after a deploy."""
    cfg = Cfg(root)
    names, _, ref = spec.partition("=")
    parts = [x.strip() for x in names.split(",") if x.strip()]
    if not ref.strip() or not parts or any(x not in cfg.servers for x in parts):
        known = ", ".join(cfg.servers) or "none (orch config set github.release_servers relay,publish)"
        raise Refused(f"Give SERVER=COMMIT with SERVER one of {known}.")
    if cfg.clone is None:
        raise Refused("Set the local clone first: orch config set github.release_clone <folder>")
    w = World(root, cfg)
    r = w._git("rev-parse", "--verify", "-q", f"{ref.strip()}^{{commit}}")
    if r.returncode != 0:
        raise Refused(f"{ref.strip()} is not a commit in {cfg.clone} (fetch first?)")
    sha = r.stdout.strip()
    w.record_deployed(parts, sha, by)
    return {"parts": parts, "sha": sha}


def green_status(root: Path) -> dict:
    """`orch github develop-green`: the last fully green develop commit and how far develop is ahead of it."""
    cfg = Cfg(root)
    if cfg.clone is None:
        raise Refused("Set the local clone first: orch config set github.release_clone <folder>")
    w = World(root, cfg)
    h = w.heads()
    ahead = 0
    if h.get("green"):
        r = w._git("rev-list", "--count", f"{h['green']}..{h['develop']}")
        ahead = int(r.stdout.strip() or 0) if r.returncode == 0 else 0
    return {
        "green": h.get("green"),
        "develop": h["develop"],
        "ahead": ahead,
        "unreleased": len(h["unreleased"]),
    }


def green_text(res: dict) -> str:
    if not res.get("green"):
        return f"No develop commit is fully green yet (develop is at {res['develop'][:8]})."
    if res["green"] == res["develop"]:
        return f"Develop is green: {res['green'][:8]} is the newest commit and its checks all passed."
    return (
        f"Last green develop commit: {res['green'][:8]}; develop is {res['ahead']} commit(s) ahead, "
        "still being checked. Releases are cut from the green one."
    )


def text(res: dict, dry_run: bool = False) -> str:
    if res.get("off"):
        return (
            "The release keeper is off here. Turn it on: orch config set "
            + ", ".join(res.get("missing") or [])
            + " (see orch github release --help)"
        )
    if res.get("paused"):
        return "Automation is paused here: the release keeper did nothing. Turn it back on: orch resume."
    head = ["Dry run, nothing written."] if dry_run else []
    verb = "would" if dry_run else "did"  # act() lists a step before it skips it on a dry run
    return "\n".join(head + list(res.get("lines") or []) + [f"  {verb}: {d}" for d in res.get("did") or []])

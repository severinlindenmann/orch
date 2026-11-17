"""The release keeper (`orch github release`, ORCH-225): takes a release from green develop to installed on
this computer, for a repeating automation (no AI call; a pass with nothing to do costs no tokens and writes
nothing).

One pass moves the release one phase on (state: .orch/run/release-keeper.json):
  idle     develop has unreleased pull requests and the last release is MIN_GAP_H (3) hours ago or more, or
           one of them carries the GitHub label urgent: the candidate is develop's head. Covered already
           when the nightly runs of the release workflows on that very commit are green; else the keeper
           dispatches them itself -> testing. Runs are judged job by job: the roll-up job (ROLLUP_JOBS) and
           known-red jobs (--known-red <job>=<ticket>, while that ticket is open) neither block nor wait;
           they are named in the highlights.
  testing  every run on the candidate green -> cut: branch release/part<N>-<MMDD> from the candidate in
           its own worktree, merge main with -s ours (tree equals develop), push, open the pull request
           into main -> its checks. A red run -> one top ticket (a helper starts at once) and the candidate is
           skipped until develop moves.
  gate     the release pull request's checks: green -> the Merge card on the role ticket (orch ask
           --merge --release) -> card. Red -> one top ticket; when develop moves past it the old pull
           request is closed and the release is cut again from scratch.
  card     `orch review tend-releases` merges it when the owner allowed it (workflow.release_merge);
           otherwise the owner clicks Merge. Merged -> installed.
  merged   `orch update` here; when a server folder (github.release_servers) changed the deploy is prepared
           (the CI-built program fetched and checked, production's program read over ssh, read only, new
           settings and data changes listed) and a deploy card asked (production: the owner's go; on "Deploy
           now" a helper ticket gets the prepared program), the highlights as a short note on the role ticket,
           the release worktree removed -> idle.
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
from datetime import UTC, datetime
from pathlib import Path

from orch import brake, config, runs, tickets
from orch.errors import Refused

BY = "agent:release-keeper"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
LOGIN_RE = re.compile(r"^[A-Za-z0-9-]{1,39}$")
HOST_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}@[A-Za-z0-9_.:-]{1,253}$")
SERVER_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
WORKFLOW_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}\.ya?ml(:[A-Za-z0-9_-]{1,40}=[A-Za-z0-9_.-]{0,80})*$")
TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")

MIN_GAP_H = 3  # at most one release this often while pull requests wait (manager, 17 Nov) ...
URGENT_LABEL = "urgent"  # ... at once for a merged pull request with this GitHub label
ROLLUP_JOBS = {"gate"}  # a roll-up of the other jobs: the jobs themselves are judged
# The checks a release pull request must REPORT before it is judged: the required checks of the branch it goes
# INTO (main). main has none of its own today, so the roll-up. Never develop's: develop's banned-words is
# skipped on release/* into main by design.
REQUIRED_FALLBACK = ["gate"]
TEST_TIMEOUT_H = 4  # dispatched runs that have not finished after this: say it once, dispatch again next pass
KEEP_STAGED = 2  # newest prepared programs kept per server (rollback)
PASSED = ("SUCCESS", "SKIPPED", "NEUTRAL")
DONE = {"done", "dropped", "wontdo", "archived"}
STATE_MAX = 512 * 1024
NOTE_MAX = 1900
TITLE_MAX = 90
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


def checks_green(rollup, ignore=frozenset()) -> str:
    """green, red or pending for a pull request's statusCheckRollup (newest run of each check counts); checks
    named in `ignore` (known red, roll-ups) do not count."""
    rollup = [c for c in rollup or [] if (c.get("name") or c.get("context")) not in ignore]
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
        if (c.get("name") or c.get("context")) in ignore:
            continue
        word = c.get("conclusion") if "status" in c else c.get("state")
        if (c.get("status") in (None, "COMPLETED")) and word not in PASSED and word not in (None, "PENDING"):
            out.append(str(c.get("name") or c.get("context") or "?"))
    return sorted(set(out))


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
        self.known_table = dict(known or {})
        self._bot_checked = False
        self.gh = shutil.which("gh") or "gh"

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
        """The newest develop commit whose own push run finished green (ORCH-314), judged job by job like any
        other run (known-red jobs and the roll-up do not count). develop's push runs are never cancelled, so
        every commit has an answer. None when none of the last ten push runs is green."""
        wf = self.cfg.workflows[0][0] if self.cfg.workflows else "ci.yml"
        known = self.known_red()
        seen: set[str] = set()
        for r in sorted(self.runs(wf, "push"), key=lambda x: str(x.get("createdAt")), reverse=True):
            sha = r.get("headSha")
            if not sha or sha in seen:
                continue
            seen.add(sha)
            if run_state(self, wf, sha, None, ("push",), known)[0] == "green":
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

    def known_red(self) -> dict[str, str]:
        """{job name: ticket key} of known-red jobs whose ticket is not done yet."""
        table = self.sim.get("known_red", self.known_table) if self.sim is not None else self.known_table
        status = {t.get("key"): t.get("status") for t in self.tickets()}
        status.update({t.get("id"): t.get("status") for t in self.tickets()})
        return {job: key for job, key in table.items() if (status.get(key) or "open") not in DONE}

    def runs(self, workflow: str, event: str) -> list[dict]:
        """Runs of one event only: merge bursts push the nightly run far down an unfiltered list."""
        if self.sim is not None:
            return self.sim.get("runs", {}).get(workflow, [])
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
                    "develop",
                    "--event",
                    event,
                    "--limit",
                    "10",
                    "--json",
                    "databaseId,headSha,event,status,conclusion,createdAt,url",
                ]
            )
            or []
        )

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

    def dispatch(self, workflow: str, extra: list[str]) -> None:
        def go():
            self.bot_ok()
            r = self._run(
                [self.gh, "workflow", "run", workflow, "--repo", self.cfg.repo, "--ref", "develop", *extra]
            )
            if r.returncode != 0:
                raise Refused(f"dispatch {workflow}: {(r.stderr or r.stdout).strip()[:200]}")

        self.act(f"dispatch:{workflow}", go)

    def new_ticket(
        self, parent: str, title: str, note: str, done_when: str, priority: str = "high"
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
            with contextlib.suppress(Exception):  # busy, paused or no agent: the ticket waits in line
                runs.start(self.root, t["id"], BY, priority=priority)
            return str(t.get("key") or t["id"])

        return self.act(f"ticket:{title}", go) or (None if self.sim is None else "t_sim")

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
        from orch import secretscan

        return not secretscan.find(text, self.root)

    def cut(self, n: int, sha: str, body: str) -> dict | None:
        """Branch + worktree + merge main (ours) + push + pull request. Returns {"number", "url", "wt"}."""
        br = f"release/part{n}-{now().astimezone().strftime('%m%d')}"
        wt = (self.cfg.worktrees or Path(".")) / f"release-{n}"

        def go():
            self.bot_ok()
            if wt.exists():
                raise Refused(f"{wt} exists already: look at it, remove it by its path")
            wt.parent.mkdir(parents=True, exist_ok=True)
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
                if r.returncode != 0:
                    raise Refused(f"git {argv[2]}: {(r.stderr or r.stdout).strip()[:200]}")
            if self._run(["git", "-C", str(wt), "diff", "--quiet", sha, "HEAD"]).returncode != 0:
                raise Refused("release tree differs from develop: stop")
            if not self.secret_free(body):
                raise Refused("the release text looks like it holds a secret: stop")
            r = self._run(["git", "-C", str(wt), "push", "-q", "-u", "origin", br], timeout=300)
            if r.returncode != 0:
                raise Refused(f"push: {(r.stderr or r.stdout).strip()[:200]}")
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

    def remove_wt(self, wt: str | None) -> None:
        if wt and (self.sim is not None or Path(wt).exists()):
            self.act(f"rmwt:{wt}", lambda: self._git("worktree", "remove", "--force", wt))


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
    w: World, workflow: str, sha: str, since: datetime | None, events: tuple[str, ...], known: dict[str, str]
) -> tuple[str, dict | None, list[str]]:
    """(green / red / pending / none, the run, known-red jobs that failed) for the newest run on `sha` of the
    given events (created after `since`). Judged job by job: a known-red job and the roll-up job do not count,
    so the run's own conclusion (red through them) is not the signal."""
    mine = [
        r
        for e in events
        for r in w.runs(workflow, e)
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
        if name in known:
            if j.get("status") == "completed" and j.get("conclusion") not in ("success", "skipped"):
                noted.append(f"{name} ({known[name]})")
            continue  # neither waited for nor a blocker
        if j.get("status") != "completed":
            state = "pending" if state == "green" else state
        elif j.get("conclusion") not in ("success", "skipped", "neutral"):
            state = "red"
    return state, r, noted


def _wf_name(f: str) -> str:
    return f.rsplit(".", 1)[0]


def open_red_ticket(rows: list[dict], words: str) -> dict | None:
    return next(
        (t for t in rows if (t.get("status") or "") not in DONE and words in (t.get("title") or "")), None
    )


def red(w: World, st: dict, role: str, title: str, words: str, note: str, done_when: str) -> list[str]:
    """One top ticket per red thing: never a second while one with the same words is open."""
    cur = open_red_ticket(w.tickets(), words)
    if cur:
        if st.get("red_logged") != title:
            w.note(cur.get("key") or cur["id"], f"Release keeper: still red. {note[:600]}")
            st["red_logged"] = title
        return [f"red, ticket {cur.get('key') or cur['id']} is open"]
    tid = w.new_ticket(role, title, note, done_when)
    st["red_logged"] = title
    return [f"red: opened top ticket {tid} ({title})"]


def pass_once(w: World, st: dict, role: str, hold: str | None) -> list[str]:
    out: list[str] = []
    h = w.heads()
    rel = st.get("release")
    foreign = w.open_release()
    if foreign and not (rel and rel.get("pr") == foreign.get("number")):
        return [f"release PR {foreign['number']} is open and was not cut by the keeper: watching only"]

    if rel and rel.get("phase") in ("gate", "card"):
        p = w.pr(rel["pr"])
        if p.get("state") == "MERGED":
            rel["phase"] = "merged"
        elif p.get("state") == "CLOSED":
            out.append(f"release {rel['n']} PR {rel['pr']} was closed by someone: back to idle")
            w.remove_wt(rel.get("wt"))
            st["release"] = None
            return out
        elif rel["phase"] == "gate":
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
                if h.get("green") != rel["sha"] and not open_red_ticket(
                    w.tickets(), f"Release {rel['n']} checks"
                ):
                    w.close_release(rel)
                    st["release"] = None
                    st["skip_sha"] = None
                    return out + [
                        f"release {rel['n']}: checks were red, develop moved and the fix ticket is closed: "
                        "closed the pull request; cut again next pass"
                    ]
                return out + red(
                    w,
                    st,
                    role,
                    f"Release {rel['n']} checks are red: {bad}"[:120],
                    f"Release {rel['n']} checks",
                    f"The release pull request {p.get('url')} into main is red on: {bad}. Fix it on "
                    "develop (a normal pull request); the release keeper closes this release and cuts it "
                    "again once develop "
                    "has the fix and this ticket is done.",
                    f"Release {rel['n']}'s checks are green (after a fix on develop)",
                )
            ask = [
                role,
                f"Merge release {rel['n']} into main?",
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
        for wf, _ in w.cfg.workflows:
            s_, r_, n_ = run_state(w, wf, rel["sha"], since, ("workflow_dispatch",), known)
            states.append((_wf_name(wf), s_, r_))
            noted += n_
        rel["known_red"] = noted
        for name, s_, r_ in states:
            if s_ == "red":
                st["release"] = None
                st["skip_sha"] = rel["sha"]
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
        else:
            if since and (now() - since).total_seconds() > TEST_TIMEOUT_H * 3600:
                st["release"] = None
                return out + [
                    f"release {rel['n']}: test runs did not finish in {TEST_TIMEOUT_H} h; again next pass"
                ]
            return out + [
                f"release {rel['n']}: "
                + ", ".join(f"{n_} {s_}" for n_, s_, _ in states)
                + f" on {rel['sha'][:8]}"
            ]

    if rel and rel.get("phase") == "cut":
        return out + cut_now(w, st, h)

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
    nums = {int(m[1]) for u in un if (m := re.search(r"#(\d+)", u["subject"]))}
    urgent = sorted(nums & w.urgent())
    last = max([x for x in (w.last_release_at(), ts(st.get("last_cut_at"))) if x], default=None)
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
    st["last_cut_at"] = now().isoformat()  # the pace counts from the start of a try, so a red one waits too
    if urgent:
        out.append(f"urgent pull request(s) {', '.join('#' + str(x) for x in urgent)}: release now")
    known = w.known_red()
    nightly = [run_state(w, wf, sha, None, ("schedule",), known) for wf, _ in w.cfg.workflows]
    if all(s_ == "green" for s_, _, _ in nightly):
        rel["known_red"] = [x for _, _, n_ in nightly for x in n_]
        rel["phase"] = "cut"
        st["release"] = rel
        out.append(f"release {n}: the nightly runs on {sha[:8]} are green")
        return out + cut_now(w, st, h)
    for wf, extra in w.cfg.workflows:
        w.dispatch(wf, extra)
    st["release"] = rel
    names = " and ".join(_wf_name(wf) for wf, _ in w.cfg.workflows)
    return out + [f"release {n}: {len(un)} pull requests waiting; started {names} on {sha[:8]}"]


def tend_releases(w: World) -> dict:
    """`orch review tend-releases` in this process: merges the release when the owner allowed it."""
    from orch import review

    try:
        return review.tend_releases(w.root)
    except Refused as e:  # inside a helper, or GitHub said no: the owner's click still works
        return {"refused": str(e)}


def cut_now(w: World, st: dict, h: dict) -> list[str]:
    rel = st["release"]
    signal = " and ".join(_wf_name(wf) for wf, _ in w.cfg.workflows)
    body = release_body(rel["n"], rel["sha"], rel.get("unreleased") or [], w.tickets(), w.cfg.repo, signal)
    try:
        got = w.cut(rel["n"], rel["sha"], body)
    except Refused as e:
        return [f"release {rel['n']}: cut failed: {e}"]
    if not got:
        return [f"release {rel['n']}: cut failed (see the log)"]
    rel.update(phase="gate", pr=got["number"], url=got["url"], wt=got["wt"], main_before=h["main"])
    return [f"release {rel['n']}: cut, pull request {got['url']}; its checks next"]


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
    head = f"Release {n} is on main and installed here ({upd})."
    tail = (
        (f"\nKnown red, not a blocker: {', '.join(kr)}." if kr else "")
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
    return f"The {part} server is fetched and checked ({needs})."


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
    st = read_state(cfg)
    w = world or World(root, cfg, dry=dry_run, known=known)
    try:
        lines = pass_once(w, st, role, hold_text(cfg))
    except (Refused, subprocess.TimeoutExpired, OSError, KeyError, ValueError) as e:
        lines = [f"pass stopped: {e}"]
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
    return "\n".join(head + list(res.get("lines") or []) + [f"  did: {d}" for d in res.get("did") or []])

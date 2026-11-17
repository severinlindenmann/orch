"""Wait for a pull request's checks and merge it on green, without an AI call (`orch ref wait`).

The verdict follows the rules the helpers' hand-made pr-green script learned the hard way (its recorded cases
are the tests in tests/fixtures/prwait/):

- a draft is never green (a draft runs only the light CI, so all its checks can pass without the full run);
- wait until at least one check exists, none is pending, every required check of the base branch exists, and
  no pull-request workflow run of the head is still queued or running (a second workflow can register its
  checks after the first one finished: PR 978, 16 Nov);
- green ONLY when every check is SUCCESS; when the base branch has required checks, a SKIPPED (path-filtered)
  job is accepted only while no check failed and every required check is present and SUCCESS;
- FAILURE, CANCELLED, TIMED_OUT, NEUTRAL, ACTION_REQUIRED, no checks in time, or still pending at the timeout:
  never green. Anything unreadable keeps waiting or reads as not green, never as green.

Merging (`--merge`) takes only the commit that was checked (`--match-head-commit`) and runs with the helper's
own GitHub login; GitHub's branch rules decide the rest. When the base branch got commits since the branch
last took it in and they touch a file the pull request changes (or a test file of the same module), the
base branch is taken in and the checks are waited for once more, so two green pull requests on the same
code cannot break it together. A pull request a person merges with a Merge card is never merged here.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field

from orch import ghlimit
from orch.errors import Refused
from orch.ghmerge import is_pr_url  # noqa: F401  (orch ref wait checks addresses with it)

NO_CHECKS_SECS = 900  # a fresh push reports no checks for a while; after this long that is an answer
TIMEOUT_SECS = 3600
POLL_SECS = 60
FIRST_NAP = 30
NET_TRIES = 7
NET_SLEEP = 20
# errors where the request never reached GitHub: a retry can never make a second merge or comment
NET_ERROR = re.compile(
    r"connection refused|connect: |could not resolve host|failed to connect|no route to host"
    r"|network is unreachable",
    re.I,
)
UNEXPANDED = "${{"  # a draft-time matrix job whose name was never expanded


@dataclass
class Verdict:
    green: bool
    why: str
    checks: list = field(default_factory=list)  # [(name, state)] as seen last, green first

    def line(self) -> str:
        return f"GREEN: {self.why}" if self.green else f"NOT green: {self.why}"


class Replay:
    """Plays a recorded case: {"repo", "isDraft", "required", "polls": [<checks list> | {"checks", "runs"}]}.
    Each poll counts as POLL_SECS; the last poll repeats. No GitHub, no waiting."""

    def __init__(self, data: dict):
        polls = data.get("polls") if isinstance(data, dict) else None
        if not isinstance(polls, list) or not polls:
            raise Refused("The recorded case has no polls.")
        self.data, self.polls, self.n, self.t = data, polls, 0, 0.0
        self.repo = str(data.get("repo") or "severinlindenmann/orch")

    def is_draft(self):
        v = self.data.get("isDraft")
        return False if v is None else v

    def required(self) -> list[str]:
        req = self.data.get("required")
        self.fallback = self.data.get("requiredFrom") == "default branch"
        return list(req) if isinstance(req, list) else []  # a recorded case lists its base branch's

    def look(self) -> tuple[list, str]:
        p = self.polls[min(self.n, len(self.polls) - 1)]
        self.n += 1
        p = {"checks": p} if isinstance(p, list) else p
        runs = p.get("runs") or []
        open_ = sorted({r["name"] for r in runs if r.get("status") != "completed"})
        return list(p.get("checks") or []), ", ".join(open_)

    def sleep(self, secs: float) -> None:
        self.t += secs

    def elapsed(self) -> float:
        return self.t

    def take(self, kind: str, what: str) -> bool:
        return True  # a recorded case writes nothing to GitHub


def _run(argv: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """One gh call with the helper's own environment; a connection-level failure is retried (the request
    never reached GitHub), anything else comes back at once."""
    for i in range(NET_TRIES):
        try:
            got = subprocess.run(
                argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout, stdin=subprocess.DEVNULL,
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            got = subprocess.CompletedProcess(argv, 124, "", "connect: timed out")
        except OSError:
            raise Refused("This needs the GitHub command line (gh), signed in.") from None
        if got.returncode == 0 or not NET_ERROR.search(got.stderr or "") or i == NET_TRIES - 1:
            return got
        time.sleep(NET_SLEEP)
    return got  # pragma: no cover


class Live:
    """Reads one pull request at GitHub through gh."""

    def __init__(self, url: str):
        m = re.fullmatch(r"https://github\.com/([^/]+/[^/]+)/pull/([0-9]+)", url)
        if m is None:
            raise Refused("That is not a GitHub pull request address.")
        gh = shutil.which("gh")
        if gh is None:
            raise Refused("This needs the GitHub command line (gh), signed in.")
        self.gh, self.url, self.repo, self.num = gh, url, m[1], m[2]
        self.start = time.monotonic()
        self.base = ""

    def take(self, kind: str, what: str) -> bool:
        """Wait for room in this computer's hourly GitHub write limit (orch github writes), then count it."""
        return ghlimit.take(kind, what)

    def gh_json(self, *args: str):
        got = _run([self.gh, *args])
        if got.returncode != 0:
            return None
        try:
            return json.loads(got.stdout)
        except ValueError:
            return None

    def view(self) -> dict | None:
        """{state, isDraft, baseRefName, headRefOid} or None when GitHub did not answer."""
        v = self.gh_json("pr", "view", self.url, "--json", "state,isDraft,baseRefName,headRefOid")
        if not isinstance(v, dict) or not isinstance(v.get("headRefOid"), str):
            return None
        self.base = v.get("baseRefName") or self.base
        return v

    def is_draft(self):
        v = self.view()
        return None if v is None else v.get("isDraft")

    def _rules(self, branch: str) -> list[str]:
        """The required checks of `branch`'s rules; Refused when GitHub did not say."""
        rules = self.gh_json("api", f"repos/{self.repo}/rules/branches/{branch}") if branch else None
        if not isinstance(rules, list):
            raise Refused(f"could not read the rules of the branch {branch or '(unknown)'}")
        out: list[str] = []
        for r in rules:
            if isinstance(r, dict) and r.get("type") == "required_status_checks":
                for c in (r.get("parameters") or {}).get("required_status_checks") or []:
                    if isinstance(c, dict) and c.get("context") and c["context"] not in out:
                        out.append(c["context"])
        return out

    def required(self) -> list[str]:
        """The required checks of the branch the pull request goes INTO. A branch without any of its own (a
        release into main) falls back to the repository's default branch's (self.fallback): the pull
        request must report each of them, a skipped one counts as GitHub counts it, and one must pass."""
        self.fallback = False
        base = self.base or (self.view() or {}).get("baseRefName") or ""
        own = self._rules(base)
        if own:
            return own
        repo = self.gh_json("api", f"repos/{self.repo}")
        default = repo.get("default_branch") if isinstance(repo, dict) else None
        if not isinstance(default, str) or not default or default == base:
            return []
        self.fallback = True
        return self._rules(default)

    def look(self) -> tuple[list, str]:
        v = self.view()
        got = _run([self.gh, "pr", "checks", self.url, "--json", "name,state,bucket"])
        try:  # gh pr checks exits non-zero while checks are pending or failed: read the list anyway
            checks = json.loads(got.stdout) if got.stdout.strip() else []
        except ValueError:
            checks = []
        if v is None:
            return checks if isinstance(checks, list) else [], "(pull request unreadable)"
        runs = self.gh_json("api", f"repos/{self.repo}/actions/runs?head_sha={v['headRefOid']}&per_page=100")
        if not isinstance(runs, dict) or not isinstance(runs.get("workflow_runs"), list):
            return checks if isinstance(checks, list) else [], "(workflow runs unreadable)"
        open_ = sorted(
            {
                r.get("name") or "?"
                for r in runs["workflow_runs"]
                if str(r.get("event") or "").startswith("pull_request") and r.get("status") != "completed"
            }
        )
        return checks if isinstance(checks, list) else [], ", ".join(open_)

    def landed(self, head: str, base: str) -> list[str] | None:
        """Files changed on the base branch since the branch last took it in ([] when nothing landed)."""
        got = self.gh_json("api", f"repos/{self.repo}/compare/{head}...{base}")
        if not isinstance(got, dict) or not isinstance(got.get("ahead_by"), int):
            return None
        if got["ahead_by"] == 0:
            return []
        files = [f.get("filename") for f in got.get("files") or [] if isinstance(f, dict)]
        return [f for f in files if isinstance(f, str)] or None  # commits but no files listed: unknown

    def changed_files(self) -> list[str] | None:
        got = _run([self.gh, "pr", "diff", self.url, "--name-only"], 60)
        names = [x.strip() for x in got.stdout.splitlines() if x.strip()] if got.returncode == 0 else []
        return names or None

    def update_branch(self, head: str) -> str | None:
        """Take the base branch in on GitHub (a merge commit, as a person's Update branch button); the new
        newest commit, or None when GitHub could not (a conflict)."""
        got = _run(
            [self.gh, "api", "-X", "PUT", f"repos/{self.repo}/pulls/{self.num}/update-branch",
             "-f", f"expected_head_sha={head}"],
            60,
        )  # fmt: skip
        if got.returncode != 0:
            return None
        for _ in range(20):  # GitHub makes the merge commit a moment later
            time.sleep(15)
            v = self.view()
            if v and v.get("headRefOid") != head:
                new = v["headRefOid"]
                # only GitHub's own merge of the checked commit and the base branch: any other new commit
                # (someone pushed meanwhile) is never taken for it
                if not self.merge_of(new, head):
                    return None
                self.start = time.monotonic()  # the wait for the new checks starts now
                return new
        return None

    def merge_of(self, sha: str, head: str) -> bool:
        """True when `sha` is a merge commit whose first parent is `head` and whose second parent is on the
        base branch."""
        got = self.gh_json("api", f"repos/{self.repo}/commits/{sha}")
        parents = [p.get("sha") for p in (got or {}).get("parents") or [] if isinstance(p, dict)]
        if len(parents) != 2 or parents[0] != head:
            return False
        on_base = self.gh_json("api", f"repos/{self.repo}/compare/{self.base}...{parents[1]}")
        return isinstance(on_base, dict) and on_base.get("ahead_by") == 0

    def sleep(self, secs: float) -> None:
        time.sleep(secs)

    def elapsed(self) -> float:
        return time.monotonic() - self.start


def _sorted(checks: list) -> list[tuple[str, str]]:
    rank = {"SUCCESS": 0, "SKIPPED": 1}
    rows = [(str(c.get("name")), str(c.get("state"))) for c in checks]
    return sorted(rows, key=lambda r: rank.get(r[1], 2))


def wait(src, no_checks: float = NO_CHECKS_SECS, timeout: float = TIMEOUT_SECS) -> Verdict:
    """Wait until the checks have finished, then say GREEN or NOT green. Never raises for GitHub trouble:
    what cannot be read keeps the wait going or ends NOT green."""
    if src.is_draft() is not False:
        return Verdict(False, "the pull request is a draft (or unreadable)")
    try:
        required = src.required()
    except Refused as e:
        return Verdict(False, str(e))
    src.sleep(FIRST_NAP)  # a fresh push reports "no checks" for a moment
    while True:
        raw, open_runs = src.look()
        checks = [
            c
            for c in raw
            if isinstance(c, dict) and not (c.get("state") == "SKIPPED" and UNEXPANDED in str(c.get("name")))
        ]
        names = {c.get("name") for c in checks}
        pending = sum(1 for c in checks if c.get("bucket") == "pending")
        have_required = all(r in names for r in required)
        if checks and not pending and have_required and not open_runs:
            break
        el = src.elapsed()
        if not checks and el >= no_checks:
            return Verdict(False, f"no checks after {int(el)}s")
        if el >= timeout:
            why = f"still waiting after {int(el)}s (pending checks: {pending}"
            if not have_required:
                why += "; required not reported yet: " + ", ".join(r for r in required if r not in names)
            if open_runs:
                why += f"; unfinished workflow runs: {open_runs}"
            return Verdict(False, why + ")", _sorted(checks))
        src.sleep(POLL_SECS)
    rows = _sorted(checks)
    bad = [f"{n} {s}" for n, s in rows if s != "SUCCESS"]
    if not required:
        if bad:
            return Verdict(False, ", ".join(bad), rows)
        return Verdict(True, f"all {len(rows)} checks SUCCESS", rows)
    hard = [f"{n} {s}" for n, s in rows if s not in ("SUCCESS", "SKIPPED")]
    if hard:
        return Verdict(False, ", ".join(hard), rows)
    fallback = getattr(src, "fallback", False)  # the base branch has none: the default branch's count
    passing = ("SUCCESS", "SKIPPED") if fallback else ("SUCCESS",)
    missing = [r for r in required if not any(n == r and s in passing for n, s in rows)]
    if missing:
        return Verdict(False, "required check(s) not SUCCESS: " + ", ".join(missing), rows)
    if fallback and not any(n in required and s == "SUCCESS" for n, s in rows):
        return Verdict(False, "none of the required checks ran (all skipped)", rows)
    if src.is_draft() is not False:
        return Verdict(False, "the pull request is a draft (or unreadable)", rows)
    ok = sum(1 for _, s in rows if s == "SUCCESS")
    skipped = sum(1 for _, s in rows if s == "SKIPPED")
    return Verdict(
        True,
        f"{ok} checks SUCCESS, {skipped} path-filtered job(s) SKIPPED; "
        + (
            f"the base branch has no required checks: the default branch's passed ({', '.join(required)})"
            if fallback
            else f"all required checks SUCCESS ({', '.join(required)})"
        ),
        rows,
    )


TEST_PREFIX, TEST_SUFFIXES = "test_", ("_test", ".test", ".spec")
UPDATE_ROUNDS = 2  # times develop is taken in for an overlap before it is left to the helper
MANY_FILES = 300  # GitHub's compare lists at most this many: more than that counts as an overlap


def _module(path: str) -> tuple[str, bool]:
    """(module name, is a test file): tests/test_prwait.py and src/orch/prwait.py are both prwait."""
    full = path.rsplit("/", 1)[-1]
    stem = full.split(".", 1)[0]
    test = (
        stem.startswith(TEST_PREFIX) or stem.endswith("_test") or any(f"{x}." in full for x in TEST_SUFFIXES)
    )
    return stem.removeprefix(TEST_PREFIX).removesuffix("_test"), test


def overlap(changed: list[str], landed: list[str]) -> list[str]:
    """The files that landed on the base branch and touch the pull request: the same file, a test file of a
    module the pull request changes, or a module whose test file the pull request changes."""
    mine = set(changed)
    mods: dict[str, set[bool]] = {}
    for f in changed:
        name, test = _module(f)
        if name:
            mods.setdefault(name, set()).add(test)
    hits = []
    for f in landed:
        name, test = _module(f)
        if f in mine or (name in mods and (test or True in mods[name])):
            hits.append(f)
    return hits


@dataclass
class Outcome:
    url: str
    ok: bool  # green (and merged, when asked)
    status: str  # what the ticket's reference shows: checks passed | checks failed | merged | ...
    line: str  # the one line written on the ticket
    verdict: Verdict | None = None


def _no_room(url: str, kind: str) -> str:
    return (
        f"Checks of {url} passed, but this computer's GitHub limit for {ghlimit.WHAT[kind]} had no room "
        "within an hour (orch github writes); not merged. Run it again later."
    )


def run_one(url: str, merge: bool, timeout: float = TIMEOUT_SECS, src: Live | None = None) -> Outcome:
    """Wait for one pull request's checks; with merge, merge it on green as GitHub's branch rules allow, only
    its checked commit. When the base branch got commits since the branch last took it in, and they touch a
    file the pull request changes (or a test file of the same module), the base branch is taken in first and
    the checks are waited for once more: two green pull requests on the same code must not break it
    together."""
    src = src or Live(url)
    v = src.view()
    if v is None:
        return Outcome(url, False, "", f"GitHub did not show {url}; nothing was done.")
    if v.get("state") == "MERGED":
        return Outcome(url, True, "merged", f"{url} is merged already.")
    if v.get("state") != "OPEN":
        return Outcome(url, False, "closed", f"{url} is closed; nothing was done.")
    head, base = v["headRefOid"], v.get("baseRefName") or ""
    verdict = wait(src, timeout=timeout)
    if not verdict.green:
        return Outcome(url, False, "checks failed", f"Checks of {url}: {verdict.line()}", verdict)
    if not merge:
        return Outcome(url, True, "checks passed", f"Checks of {url}: {verdict.line()}", verdict)
    rounds = 0
    while True:
        now = src.view()
        if now is None or now.get("headRefOid") != head:
            line = f"{url} got a new commit while its checks ran; not merged."
            return Outcome(url, False, "changed", line, verdict)
        base = now.get("baseRefName") or base
        landed, changed = src.landed(head, base), src.changed_files()
        if landed is None or changed is None:
            line = f"GitHub did not say what changed on {base} or in {url}; not merged. Run it again."
            return Outcome(url, False, "checks passed", line, verdict)
        hits = overlap(changed, landed) if len(landed) < MANY_FILES else landed[:3]
        if not landed:
            case = f"{base} had nothing new since the branch took it in"
            break
        if not hits:
            case = f"{base} moved ({len(landed)} files changed there), none of them touch this pull request"
            break
        shown = ", ".join(hits[:3]) + (" ..." if len(hits) > 3 else "")
        if rounds >= UPDATE_ROUNDS:
            line = (
                f"{base} keeps changing files of {url} ({shown}); not merged. Take {base} in, push, "
                "then run this again."
            )
            return Outcome(url, False, "behind", line, verdict)
        rounds += 1
        note = f"{base} changed files of this pull request since it took {base} in ({shown}): "
        print(note + f"taking {base} in and waiting for the checks once more.", file=sys.stderr, flush=True)
        if not src.take("other", f"{url} take {base} in"):
            return Outcome(url, False, "checks passed", _no_room(url, "other"), verdict)
        new = src.update_branch(head)
        if new is None:
            line = (
                f"{base} changed files of {url} ({shown}) and was not taken in (a conflict, or a push "
                f"meanwhile); not merged. Merge {base} into the branch by hand and push, then run this again."
            )
            return Outcome(url, False, "behind", line, verdict)
        head = new
        verdict = wait(src, timeout=timeout)
        if not verdict.green:
            line = f"Checks of {url} after taking {base} in: {verdict.line()}"
            return Outcome(url, False, "checks failed", line, verdict)
    if not src.take("merge", url):
        return Outcome(url, False, "checks passed", _no_room(url, "merge"), verdict)
    done = _run([src.gh, "pr", "merge", url, "--merge", "--match-head-commit", head], 60)
    if done.returncode != 0:
        why = next((x.strip() for x in (done.stderr or done.stdout).splitlines() if x.strip()), "no reason")
        ghlimit.give_back("merge", url)  # no merge happened: the place goes back
        line = f"Checks of {url} passed but GitHub did not merge it ({case}): {why[:200]}"
        return Outcome(url, False, "checks passed", line, verdict)
    took = f"; {base} taken in {rounds}x first" if rounds else ""
    return Outcome(
        url, True, "merged", f"Merged {url} on green checks ({verdict.why}); {case}{took}.", verdict
    )

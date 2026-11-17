"""Merge a GitHub pull request when a person approves a merge card (orch ask --link --open PR --merge).

The merge runs with the person's OWN GitHub login: the one the GitHub command line (gh) is signed in with
on this computer. Token variables a helper's environment may carry (GH_TOKEN, GITHUB_TOKEN, ...) are
dropped, so a helper's account never does the merge. GitHub itself decides who may merge (branch rules);
a refusal comes back to the person in plain words. Only review.decide/change and `orch ref merge` call
merge(), after the person check. checks() only reads (orch needs uses it for a finished ticket whose pull
request is still open).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from orch import ghlimit
from orch.errors import Refused

PR_URL = re.compile(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[0-9]{1,9}")
# gh reads these before its own sign-in; a helper's environment may set them for a helper account
TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
OPEN_IT = "Open the pull request and merge it there."
JQ_VIEW = '[.state, (.reviewDecision // ""), .headRefOid] | @tsv'
SHA = re.compile(r"[0-9a-f]{40}")
CHANGED = "The pull request changed after the card was made. Ask the helper for a new card."
REVIEW_BODY = "Merge clicked on the orch card."
NO_GH = "The merge needs the GitHub command line (gh) signed in with your own account. " + OPEN_IT


def is_pr_url(url) -> bool:
    return isinstance(url, str) and PR_URL.fullmatch(url) is not None


def own_env() -> dict:
    """This process's environment without any GitHub token variable: gh then uses its own sign-in."""
    return {k: v for k, v in os.environ.items() if k not in TOKEN_VARS}


def _gh(gh: str, args: list[str], timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [gh, *args],
            env=own_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        raise Refused("GitHub did not answer in time. Try again in a minute, or " + OPEN_IT.lower()) from None
    except OSError:
        raise Refused(NO_GH) from None


def _first_line(text: str) -> str:
    line = next((x.strip() for x in (text or "").splitlines() if x.strip()), "no reason given")
    return line.removeprefix("X ").removeprefix("! ")[:200]


def _parts(url: str) -> tuple[str, str]:
    """(owner/repo, number) of a pull request address."""
    m = re.fullmatch(r"https://github\.com/([^/]+/[^/]+)/pull/([0-9]+)", url)
    if m is None:
        raise Refused("A merge card needs a GitHub pull request address.")
    return m[1], m[2]


def _view(gh: str, url: str, env_own: bool) -> tuple[str, str, str]:
    """(state, review decision, head commit) of the pull request."""
    args = ["pr", "view", url, "--json", "state,reviewDecision,headRefOid", "--jq", JQ_VIEW]
    v = _gh(gh, args, 15) if env_own else _gh_plain(gh, args, 15)
    if v.returncode != 0:
        raise Refused(f"GitHub did not show the pull request: {_first_line(v.stderr)}. {OPEN_IT}")
    state, review, head = ([*v.stdout.rstrip("\r\n").split("\t"), "", ""])[:3]
    if not SHA.fullmatch(head):
        raise Refused(f"GitHub did not show the pull request's newest commit. {OPEN_IT}")
    return state, review, head


def _gh_plain(gh: str, args: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Reading only, with whatever login this process has (a helper's is fine to read)."""
    try:
        return subprocess.run(
            [gh, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, stdin=subprocess.DEVNULL,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        raise Refused("GitHub did not answer in time. Try again in a minute.") from None
    except OSError:
        raise Refused("--merge needs the GitHub command line (gh) to read the pull request.") from None


JSON_CHECKS = "state,isDraft,headRefOid,statusCheckRollup"
PASSED = ("SUCCESS", "SKIPPED", "NEUTRAL")


def _newest(rollup: list) -> list:
    """One entry per check: GitHub lists every run of a workflow on the commit (a first run made while the
    pull request was a draft, the full run after), and only the newest run of a check counts."""
    last: dict = {}
    for n, c in enumerate(rollup):
        if not isinstance(c, dict):
            return rollup
        key = (c.get("workflowName"), c.get("name") or c.get("context") or n)
        when = str(c.get("startedAt") or "")
        if key not in last or when >= last[key][0]:
            last[key] = (when, c)
    return [c for _, c in last.values()]


def passed(rollup) -> bool:
    """True when every check of a pull request has finished, none failed and at least one succeeded."""
    if not isinstance(rollup, list) or not rollup:
        return False
    good = 0
    for c in _newest(rollup):
        if not isinstance(c, dict):
            return False
        if "state" in c and "status" not in c:  # a commit status (no run): SUCCESS or not
            word = c.get("state")
        elif c.get("status") != "COMPLETED":
            return False
        else:
            word = c.get("conclusion")
        if word not in PASSED:
            return False
        good += word == "SUCCESS"
    return good > 0


def checks(url: str) -> dict | None:
    """What GitHub says about a pull request now, read-only, with whatever login this process has:
    {"state": OPEN|MERGED|CLOSED, "head": <newest commit>, "green": <open, not a draft, checks passed>}.
    None when it cannot be read (no gh, not signed in, no network): the caller then shows nothing."""
    gh = shutil.which("gh")
    if gh is None or not is_pr_url(url):
        return None
    try:
        v = _gh_plain(gh, ["pr", "view", url, "--json", JSON_CHECKS], 15)
        data = json.loads(v.stdout) if v.returncode == 0 else None
    except (Refused, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("state"), str):
        return None
    head = data.get("headRefOid")
    if not isinstance(head, str) or not SHA.fullmatch(head):
        return None
    green = data["state"] == "OPEN" and data.get("isDraft") is False and passed(data.get("statusCheckRollup"))
    return {"state": data["state"], "head": head, "green": green}


MERGE_COMMIT = re.compile(r"Merge pull request #([0-9]{1,9}) from ")
MAX_ITEMS = 40


def checks_words(rollup) -> str:
    """The checks of a pull request in plain words (ORCH-183): "all 18 passed", "3 of 18 still running",
    "1 failed: gate". The newest run of each check counts, as in passed()."""
    if not isinstance(rollup, list) or not rollup:
        return "no checks ran"
    runs = [c for c in _newest(rollup) if isinstance(c, dict)]
    failed, running = [], 0
    for c in runs:
        if "state" in c and "status" not in c:
            word = c.get("state")
            if word == "PENDING":
                running += 1
                continue
        elif c.get("status") != "COMPLETED":
            running += 1
            continue
        else:
            word = c.get("conclusion")
        if word not in PASSED:
            failed.append(str(c.get("name") or c.get("context") or "a check")[:60])
    if failed:
        return f"{len(failed)} failed: " + ", ".join(failed[:3]) + (" …" if len(failed) > 3 else "")
    if running:
        return f"{running} of {len(runs)} still running"
    return f"all {len(runs)} passed"


def summary(url: str, head: str) -> dict | None:
    """What a merge card shows (ORCH-183, owner 17 Nov: "the address is a link, not the content"), read
    once when the card is made, with whatever login this process has: {"title", "base", "checks" (plain
    words), "items": [{"pr": n, "title"}], "other": commits that are no pull request merge}. Items come from
    merge commit headlines, which a commit author writes: GitHub's own titles, never a ticket alone, and the
    count of other commits is always shown. None when GitHub cannot be read or the newest commit is no longer
    `head` (the commit the click merges): the card then shows only that commit."""
    gh = shutil.which("gh")
    if gh is None or not is_pr_url(url):
        return None
    try:
        v = _gh_plain(
            gh, ["pr", "view", url, "--json", "title,baseRefName,headRefOid,commits,statusCheckRollup"], 20
        )
        data = json.loads(v.stdout) if v.returncode == 0 else None
    except (Refused, ValueError):
        return None
    if not isinstance(data, dict) or data.get("headRefOid") != head:
        return None
    items, seen, other = [], set(), 0
    for c in data.get("commits") or []:
        if not isinstance(c, dict):
            continue
        m = MERGE_COMMIT.match(str(c.get("messageHeadline") or ""))
        if not m or m[1] in seen:
            other += 1
            continue
        seen.add(m[1])
        title = next((x.strip() for x in str(c.get("messageBody") or "").splitlines() if x.strip()), "")
        items.append({"pr": int(m[1]), "title": title[:200]})
    return {
        "title": str(data.get("title") or "")[:200],
        "base": str(data.get("baseRefName") or "")[:100],
        "checks": checks_words(data.get("statusCheckRollup")),
        "items": items[:MAX_ITEMS],
        "more": max(0, len(items) - MAX_ITEMS),
        "other": other,
    }


RELEASE_PREFIX = "release/"
RELEASE_FROM = "develop"  # a release only carries what is on this branch already (reviewed there)


def release_problem(url: str, head: str) -> str | None:
    """Why a pull request is not a release that may merge without a click (None = it is one): it must
    come from a release/... branch into the repository's default branch, and change nothing that is not on
    develop already (GitHub's compare develop...<commit> lists no file). Read-only, with any login."""
    repo, _ = _parts(url)
    gh = shutil.which("gh")
    if gh is None or not SHA.fullmatch(str(head or "")):
        return "GitHub could not be read"
    try:
        v = _gh_plain(gh, ["pr", "view", url, "--json", "baseRefName,headRefName,isCrossRepository"], 15)
        pr = json.loads(v.stdout) if v.returncode == 0 else None
        d = _gh_plain(gh, ["api", f"repos/{repo}", "--jq", ".default_branch"], 15)
        # the branch's own commit (a tag of that name cannot stand in), then compare commit to commit
        b = _gh_plain(gh, ["api", f"repos/{repo}/branches/{RELEASE_FROM}", "--jq", ".commit.sha"], 15)
        base = b.stdout.strip() if b.returncode == 0 else ""
        if not SHA.fullmatch(base):
            return "GitHub could not be read"
        c = _gh_plain(gh, ["api", f"repos/{repo}/compare/{base}...{head}", "--jq", ".files | length"], 20)
    except (Refused, ValueError):
        return "GitHub could not be read"
    if not isinstance(pr, dict) or v.returncode != 0 or d.returncode != 0:
        return "GitHub could not be read"
    if pr.get("isCrossRepository") is not False:
        return "it comes from another repository"
    if not str(pr.get("headRefName") or "").startswith(RELEASE_PREFIX):
        return f"it does not come from a {RELEASE_PREFIX}... branch"
    if pr.get("baseRefName") != d.stdout.strip():
        return "it does not go into the default branch"
    if c.returncode != 0 or c.stdout.strip() != "0":
        return f"it changes files that are not on {RELEASE_FROM}"
    return None


def head_of(url: str) -> str:
    """The newest commit of an open pull request, read when the card is made: the click merges exactly it."""
    _parts(url)
    gh = shutil.which("gh")
    if gh is None:
        raise Refused("--merge needs the GitHub command line (gh) to read the pull request.")
    state, _, head = _view(gh, url, env_own=False)
    if state != "OPEN":
        raise Refused("That pull request is not open on GitHub, so there is nothing to merge.")
    return head


def merge(url: str, head: str, add_review: bool = True) -> dict:
    """Merge the pull request at `url` as the person signed in to gh, only while its newest commit is still
    `head` (what the card showed). Returns {"login", "already"}: already is True when it was merged before (a
    second click, or a retry after a crash), which is not an error. add_review False (`orch ref merge`): the
    person's review is never added; where the branch rules want one, GitHub refuses and says so."""
    repo, num = _parts(url)
    if not isinstance(head, str) or not SHA.fullmatch(head):
        raise Refused("This merge card has no commit to merge. Ask the helper for a new card.")
    gh = shutil.which("gh")
    if gh is None:
        raise Refused(NO_GH)
    who = _gh(gh, ["api", "user", "--jq", ".login"], 15)
    login = who.stdout.strip()
    if who.returncode != 0 or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login):
        raise Refused(NO_GH)
    state, review, now = _view(gh, url, env_own=True)
    if state == "MERGED":
        return {"login": login, "already": True}
    if state != "OPEN":
        raise Refused("The pull request is closed on GitHub, so it cannot be merged. Open it to see why.")
    if now != head:
        raise Refused(CHANGED)
    if (
        add_review and review == "REVIEW_REQUIRED"
    ):  # the branch rules want a review: the click is the person's, on THIS commit
        _gh(  # the person's own pull request: GitHub says no, and the merge below tells what is missing
            gh,
            ["api", "-X", "POST", f"repos/{repo}/pulls/{num}/reviews", "-f", f"commit_id={head}",
             "-f", "event=APPROVE", "-f", f"body={REVIEW_BODY}"],
            15,
        )  # fmt: skip
    done = _gh(gh, ["pr", "merge", url, "--merge", "--match-head-commit", head], 25)
    if done.returncode != 0:
        raise Refused(f"GitHub did not merge it: {_first_line(done.stderr or done.stdout)}. {OPEN_IT}")
    ghlimit.count("merge", url)  # the person's own click never waits, but it uses up the hour too
    return {"login": login, "already": False}

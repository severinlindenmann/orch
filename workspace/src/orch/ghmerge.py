"""Merge a GitHub pull request when a person approves a merge card (orch ask --link --open PR --merge).

The merge runs with the person's OWN GitHub login: the one the GitHub command line (gh) is signed in with
on this computer. Token variables a helper's environment may carry (GH_TOKEN, GITHUB_TOKEN, ...) are
dropped, so a helper's account never does the merge. GitHub itself decides who may merge (branch rules);
a refusal comes back to the person in plain words. Only review.decide/change call this, after the person
check.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

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


def merge(url: str, head: str) -> dict:
    """Merge the pull request at `url` as the person signed in to gh, only while its newest commit is still
    `head` (what the card showed). Returns {"login", "already"}: already is True when it was merged before (a
    second click, or a retry after a crash), which is not an error."""
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
        review == "REVIEW_REQUIRED"
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
    return {"login": login, "already": False}

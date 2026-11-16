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


def merge(url: str) -> dict:
    """Merge the pull request at `url` as the person signed in to gh. Returns {"login", "already"}: already is
    True when it was merged before (a second click, or a retry after a crash), which is not an error."""
    if not is_pr_url(url):
        raise Refused("A merge card needs a GitHub pull request address.")
    gh = shutil.which("gh")
    if gh is None:
        raise Refused(NO_GH)
    who = _gh(gh, ["api", "user", "--jq", ".login"], 15)
    login = who.stdout.strip()
    if who.returncode != 0 or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login):
        raise Refused(NO_GH)
    view = _gh(gh, ["pr", "view", url, "--json", "state", "--jq", ".state"], 15)
    state = view.stdout.strip()
    if view.returncode != 0:
        raise Refused(f"GitHub did not show the pull request: {_first_line(view.stderr)}. {OPEN_IT}")
    if state == "MERGED":
        return {"login": login, "already": True}
    if state != "OPEN":
        raise Refused("The pull request is closed on GitHub, so it cannot be merged. Open it to see why.")
    done = _gh(gh, ["pr", "merge", url, "--merge"], 25)
    if done.returncode != 0:
        raise Refused(f"GitHub did not merge it: {_first_line(done.stderr or done.stdout)}. {OPEN_IT}")
    return {"login": login, "already": False}

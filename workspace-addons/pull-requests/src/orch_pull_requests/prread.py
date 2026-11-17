"""Read pull requests from GitHub with the person's own `gh` (read-only: one GraphQL query per repository).

One call answers the repository's open pull requests (newest first, up to OPEN_MAX) with their checks and merge
state, plus every linked pull request that is not open any more (by number, aliased into the same query). Nothing
is ever written to GitHub here, so the hourly write limit (orch.ghlimit) is not touched.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

from . import prstate

OPEN_MAX = 50
LINKED_MAX = 40  # linked pull requests looked up by number in one query
TIMEOUT = 30
REPO_RE = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
NO_GH = "GitHub isn't set up on this computer: install gh and run gh auth login once."
NOT_SIGNED_IN = "GitHub isn't signed in on this computer: run gh auth login once."

FIELDS = """number title url state isDraft mergeable mergeStateStatus baseRefName headRefName updatedAt
author { login }
commits(last: 1) { nodes { commit { statusCheckRollup { contexts(first: 100) { nodes {
  __typename
  ... on CheckRun { name status conclusion }
  ... on StatusContext { context state }
} } } } } }"""


class GhError(Exception):
    """GitHub could not be read; the text is one plain sentence for the person."""


def query(numbers: list[int]) -> str:
    linked = " ".join(f"p{n}: pullRequest(number: {n}) {{ {FIELDS} }}" for n in numbers[:LINKED_MAX])
    return (
        "query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) { "
        f"open: pullRequests(states: OPEN, first: {OPEN_MAX}, orderBy: {{field: UPDATED_AT, direction: DESC}}) "
        f"{{ nodes {{ {FIELDS} }} }} {linked} }} }}"
    )


def _gh(args: list[str]) -> subprocess.CompletedProcess:
    gh = shutil.which("gh")
    if gh is None:
        raise GhError(NO_GH)
    try:
        return subprocess.run(
            [gh, *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        raise GhError("GitHub did not answer in time; orch tries again in a minute.") from None
    except OSError:
        raise GhError(NO_GH) from None


def _why(stderr: str) -> str:
    low = (stderr or "").lower()
    if "auth login" in low or "not logged" in low or "authentication" in low:
        return NOT_SIGNED_IN
    if "could not resolve to a repository" in low or "not found" in low:
        return "GitHub says this repository does not exist or this login cannot see it."
    if "rate limit" in low:
        return "GitHub's read limit is used up for now; orch tries again later."
    return "GitHub could not be read just now; orch tries again in a minute."


def fetch(repo: str, numbers: list[int] | None = None, run=_gh) -> dict:
    """{"open": [row], "linked": {number: row}} for one repository. Raises GhError."""
    if not REPO_RE.fullmatch(repo or ""):
        raise GhError("That is not a GitHub repository name.")
    owner, name = repo.split("/", 1)
    nums = sorted({int(n) for n in numbers or [] if isinstance(n, int) and 0 < n < 10**9})
    got = run(["api", "graphql", "-f", f"query={query(nums)}", "-F", f"owner={owner}", "-F", f"name={name}"])
    if got.returncode != 0:
        raise GhError(_why(got.stderr))
    try:
        data = json.loads(got.stdout)
    except ValueError:
        raise GhError("GitHub answered something orch cannot read.") from None
    repo_data = ((data or {}).get("data") or {}).get("repository") if isinstance(data, dict) else None
    if not isinstance(repo_data, dict):
        errs = data.get("errors") if isinstance(data, dict) else None
        raise GhError(_why(json.dumps(errs) if errs else ""))
    rows = [prstate.row(repo, pr) for pr in ((repo_data.get("open") or {}).get("nodes") or [])]
    linked = {}
    for n in nums[:LINKED_MAX]:
        r = prstate.row(repo, repo_data.get(f"p{n}"))
        if r is not None:
            linked[n] = r
    return {"open": [r for r in rows if r is not None], "linked": linked}

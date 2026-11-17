"""The few GitHub calls the merge queue makes besides the core waiter (orch.prwait), through gh."""

from __future__ import annotations

import json
import shutil
from urllib.parse import quote

from .store import Refused

VIEW = "state,isDraft,baseRefName,headRefOid,number,title,closingIssuesReferences,isCrossRepository"


class GitHub:
    def __init__(self):
        gh = shutil.which("gh")
        if gh is None:
            raise Refused("The merge queue needs the GitHub command line (gh), signed in.")
        self.gh = gh

    def _run(self, *args: str, timeout: int = 60):
        from orch import prwait

        return prwait._run([self.gh, *args], timeout)

    def _json(self, *args: str):
        got = self._run(*args)
        if got.returncode != 0:
            return None
        try:
            return json.loads(got.stdout)
        except ValueError:
            return None

    def pr(self, url: str) -> dict | None:
        """{state, isDraft, baseRefName, headRefOid, number, title, closingIssuesReferences} or None."""
        v = self._json("pr", "view", url, "--json", VIEW)
        return v if isinstance(v, dict) and isinstance(v.get("headRefOid"), str) else None

    def own_checks_failed(self, url: str) -> bool:
        """True when one of the pull request's own checks has already failed (gh exits 8 while some run)."""
        got = self._run("pr", "checks", url, "--json", "name,bucket")
        try:
            rows = json.loads(got.stdout or "[]")
        except ValueError:
            return False
        return any(isinstance(r, dict) and r.get("bucket") == "fail" for r in rows)

    def create_pr(self, repo: str, base: str, branch: str, title: str, body: str) -> str | None:
        got = self._run(
            "pr", "create", "--repo", repo, "--base", base, "--head", branch, "--title", title, "--body", body
        )
        lines = [
            x.strip() for x in (got.stdout or "").splitlines() if x.strip().startswith("https://github.com/")
        ]
        return lines[-1] if got.returncode == 0 and lines else None

    def close(self, url: str) -> bool:
        """Close a group pull request and delete its branch."""
        return self._run("pr", "close", url, "--delete-branch").returncode == 0

    def delete_branch(self, repo: str, branch: str) -> bool:
        return (
            self._run(
                "api", "-X", "DELETE", f"repos/{repo}/git/refs/heads/{quote(branch, safe='/')}"
            ).returncode
            == 0
        )

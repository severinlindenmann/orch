"""The few GitHub calls the merge queue makes besides the core waiter (orch.prwait), through gh."""

from __future__ import annotations

import json
import shutil
from urllib.parse import quote

from .store import Refused

VIEW = (
    "state,isDraft,baseRefName,headRefOid,number,title,closingIssuesReferences,isCrossRepository,"
    "reviewDecision,reviews"
)
GONE = ("reference does not exist", "not found", "http 404")


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

    def login(self) -> str | None:
        """The GitHub login gh signs in with, or None when GitHub did not say."""
        got = self._run("api", "user", "--jq", ".login")
        name = (got.stdout or "").strip() if got.returncode == 0 else ""
        return name or None

    def pr(self, url: str) -> dict | None:
        """{state, isDraft, baseRefName, headRefOid, number, title, closingIssuesReferences, reviewDecision}
        or None when GitHub did not answer."""
        v = self._json("pr", "view", url, "--json", VIEW)
        return v if isinstance(v, dict) and isinstance(v.get("headRefOid"), str) else None

    def own_checks_failed(self, url: str) -> bool:
        """True when one of the pull request's own checks has already failed (gh exits 8 while some run)."""
        return bool(self.failed_checks(url))

    def failed_checks(self, url: str) -> frozenset[str]:
        """The names of the pull request's checks that have already failed (empty: none, or unreadable)."""
        got = self._run("pr", "checks", url, "--json", "name,bucket")
        try:
            rows = json.loads(got.stdout or "[]")
        except ValueError:
            return frozenset()
        if not isinstance(rows, list):
            return frozenset()
        return frozenset(
            str(r.get("name") or "") for r in rows if isinstance(r, dict) and r.get("bucket") == "fail"
        )

    def base_failed(self, repo: str, base: str) -> frozenset[str] | None:
        """The failed jobs of the base branch's last finished push run of each workflow (cancelled runs and
        runs still going are skipped): empty when the base branch is green, None when GitHub did not answer."""
        runs = self._json(
            "run", "list", "--repo", repo, "--branch", base, "--event", "push", "--limit", "20",
            "--json", "databaseId,workflowName,status,conclusion",
        )  # fmt: skip
        if not isinstance(runs, list):
            return None
        skip = ("cancelled", "skipped", "stale", None, "")
        done = [r for r in runs if isinstance(r, dict) and r.get("status") == "completed"]
        if len(runs) >= 20 and all(r.get("conclusion") in skip for r in done):
            return None  # 20 runs going or cancelled, none finished: not known, never "green"
        seen, bad = set(), set()
        for r in runs:  # newest first, as gh lists them
            if not isinstance(r, dict) or r.get("status") != "completed":
                continue
            if r.get("conclusion") in skip:
                continue
            wf = r.get("workflowName")
            if wf in seen:
                continue
            seen.add(wf)
            if r.get("conclusion") in ("success", "neutral"):
                continue
            v = self._json(
                "run", "view", str(int(r.get("databaseId") or 0)), "--repo", repo, "--json", "jobs"
            )
            if not isinstance(v, dict) or not isinstance(v.get("jobs"), list):
                return None
            bad |= {
                str(j.get("name") or "")
                for j in v["jobs"]
                if isinstance(j, dict) and j.get("conclusion") in ("failure", "timed_out")
            }
        return frozenset(bad)

    def checks(self, url: str) -> dict | None:
        """{state, isDraft, isCrossRepository, headRefOid, statusCheckRollup} of the pull request (one read), or None when GitHub
        did not answer. Used by the failed-checks part (checks.py)."""
        v = self._json(
            "pr", "view", url, "--json", "state,isDraft,isCrossRepository,headRefOid,statusCheckRollup"
        )
        return v if isinstance(v, dict) and isinstance(v.get("headRefOid"), str) else None

    def rerun_job(self, repo: str, job: int) -> bool:
        """Run one GitHub Actions job again (a write: the caller takes a slot of the write limit first)."""
        return self._run("run", "rerun", "--job", str(int(job)), "--repo", repo).returncode == 0

    def job_log(self, repo: str, job: int) -> str:
        """The log of one GitHub Actions job (failed steps only when gh can tell them), '' when unreadable."""
        got = self._run("run", "view", "--job", str(int(job)), "--repo", repo, "--log-failed", timeout=90)
        if got.returncode != 0 or not (got.stdout or "").strip():
            got = self._run("run", "view", "--job", str(int(job)), "--repo", repo, "--log", timeout=90)
        return (got.stdout or "") if got.returncode == 0 else ""

    def create_pr(self, repo: str, base: str, branch: str, title: str, body: str) -> str | None:
        got = self._run(
            "pr", "create", "--repo", repo, "--base", base, "--head", branch, "--title", title, "--body", body
        )
        lines = [
            x.strip() for x in (got.stdout or "").splitlines() if x.strip().startswith("https://github.com/")
        ]
        return lines[-1] if got.returncode == 0 and lines else None

    def create_issue(self, repo: str, title: str, body: str) -> str | None:
        """Open an issue (a write: the caller takes a slot of the write limit first); its address or None."""
        got = self._run("issue", "create", "--repo", repo, "--title", title, "--body", body)
        lines = [
            x.strip() for x in (got.stdout or "").splitlines() if x.strip().startswith("https://github.com/")
        ]
        return lines[-1] if got.returncode == 0 and lines else None

    def find_issue(self, repo: str, mark: str) -> str | None:
        """The issue whose text carries `mark` (a broken test's key), still open; None: none or no answer."""
        v = self._json(
            "issue", "list", "--repo", repo, "--state", "open", "--search", f"{mark} in:body", "--json", "url,body",
            "--limit", "5",
        )  # fmt: skip
        for i in v if isinstance(v, list) else []:
            if (
                isinstance(i, dict)
                and mark in str(i.get("body") or "")
                and str(i.get("url") or "").startswith("https://")
            ):
                return i["url"]
        return None

    def issue_state(self, url: str) -> str | None:
        """OPEN or CLOSED, None when GitHub did not answer (one read)."""
        v = self._json("issue", "view", url, "--json", "state")
        return v.get("state") if isinstance(v, dict) and isinstance(v.get("state"), str) else None

    def set_variable(self, repo: str, name: str, value: str) -> bool:
        """Set a repository's Actions variable (a write: the caller takes a slot of the write limit first)."""
        return self._run("variable", "set", name, "--repo", repo, "--body", value).returncode == 0

    def close(self, url: str) -> bool:
        """Close a group pull request (its branch is deleted on its own, one more write)."""
        return self._run("pr", "close", url).returncode == 0

    def delete_branch(self, repo: str, branch: str) -> bool:
        """True when the branch is gone afterwards (deleted now, or not there at all)."""
        got = self._run("api", "-X", "DELETE", f"repos/{repo}/git/refs/heads/{quote(branch, safe='/')}")
        return got.returncode == 0 or any(g in (got.stderr or "").lower() for g in GONE)

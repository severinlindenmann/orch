"""One pull request as orch shows it: its checks (passed / running / failed / none), its merge state and the one
word a ticket's link shows. Pure functions over what GitHub's GraphQL API answers (no network here).

The check words follow the core waiter's rules (orch.prwait, `orch ref wait`): only SUCCESS counts as passed, a
SKIPPED job is fine, a draft-time matrix job whose name was never expanded is left out, and anything else that
finished (FAILURE, CANCELLED, TIMED_OUT, NEUTRAL, ACTION_REQUIRED, ...) is not green.
"""

from __future__ import annotations

import re

try:  # the core waiter's marker for an unexpanded matrix job; the add-on runs inside orch's own Python
    from orch.prwait import UNEXPANDED
except ImportError:  # pragma: no cover - only without the core on the path
    UNEXPANDED = "${{"

PR_URL = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([0-9]{1,9})")
CHECK_WORDS = ("passed", "running", "failed", "none")
MERGE_WORDS = ("ready", "blocked", "behind", "conflict", "draft", "unknown", "merged", "closed")
# the word on a ticket's link, most important first (ticket_links statuses in orch-addon.toml)
STATUS_WORDS = (
    "merged",
    "closed",
    "draft",
    "checks failed",
    "conflict",
    "checks running",
    "ready to merge",
    "behind",
    "blocked",
    "open",
)
_PENDING_RUN = {"QUEUED", "IN_PROGRESS", "WAITING", "PENDING", "REQUESTED"}


def parse_url(url: str) -> tuple[str, int] | None:
    """("owner/name", number) for a GitHub pull request address, else None."""
    m = PR_URL.fullmatch(str(url or "").strip().rstrip("/"))
    return (f"{m[1]}/{m[2]}", int(m[3])) if m else None


def _one(node: dict) -> tuple[str, str] | None:
    """(name, state) of one check in the core waiter's words: SUCCESS, SKIPPED, PENDING or the failure word."""
    if not isinstance(node, dict):
        return None
    if node.get("__typename") == "StatusContext" or ("context" in node and "status" not in node):
        name, st = str(node.get("context") or "?"), str(node.get("state") or "")
        if st in ("PENDING", "EXPECTED", ""):
            return name, "PENDING"
        return name, "SUCCESS" if st == "SUCCESS" else st  # FAILURE, ERROR
    name = str(node.get("name") or "?")
    status, concl = str(node.get("status") or ""), str(node.get("conclusion") or "")
    if status in _PENDING_RUN or (status != "COMPLETED" and not concl):
        return name, "PENDING"
    return name, concl or "PENDING"


def checks(raw: list | None) -> dict:
    """{word, passed, failed, running, failed_names} from a statusCheckRollup's context nodes."""
    rows = [r for r in (_one(n) for n in raw or []) if r is not None]
    rows = [(n, s) for n, s in rows if not (s == "SKIPPED" and UNEXPANDED in n)]
    passed = sum(1 for _, s in rows if s in ("SUCCESS", "SKIPPED"))
    running = sum(1 for _, s in rows if s == "PENDING")
    bad = sorted({n for n, s in rows if s not in ("SUCCESS", "SKIPPED", "PENDING")})
    if not rows:
        word = "none"
    elif bad:
        word = "failed"  # a failed job is an answer even while others still run
    elif running:
        word = "running"
    else:
        word = "passed"
    return {
        "word": word,
        "passed": passed,
        "failed": len(rows) - passed - running,
        "running": running,
        "failed_names": bad[:5],
    }


def merge_word(pr: dict) -> str:
    """What GitHub would let you do with it now, in one of MERGE_WORDS."""
    state = pr.get("state")
    if state == "MERGED":
        return "merged"
    if state == "CLOSED":
        return "closed"
    if pr.get("isDraft") is True:
        return "draft"
    ms, mergeable = pr.get("mergeStateStatus"), pr.get("mergeable")
    if mergeable == "CONFLICTING" or ms == "DIRTY":
        return "conflict"
    if ms == "BEHIND":
        return "behind"
    if ms == "BLOCKED":
        return "blocked"
    if ms in ("CLEAN", "HAS_HOOKS", "UNSTABLE"):
        return "ready"
    return "unknown"


def status_word(row: dict) -> str:
    """The one word a ticket's link shows (STATUS_WORDS)."""
    m, c = row.get("merge"), (row.get("checks") or {}).get("word")
    if m in ("merged", "closed", "draft"):
        return m
    if c == "failed":
        return "checks failed"
    if m == "conflict":
        return "conflict"
    if c == "running":
        return "checks running"
    if m == "ready":
        return "ready to merge"
    if m in ("behind", "blocked"):
        return m
    return "open"


def row(repo: str, pr: dict) -> dict | None:
    """One pull request from the GraphQL answer as the add-on keeps it, or None when it is not readable."""
    if not isinstance(pr, dict) or not isinstance(pr.get("number"), int):
        return None
    commit = {}
    nodes = ((pr.get("commits") or {}).get("nodes")) or []
    if nodes and isinstance(nodes[-1], dict):
        commit = nodes[-1].get("commit") or {}
    rollup = commit.get("statusCheckRollup") or {}
    ctx = ((rollup.get("contexts") or {}).get("nodes")) or []
    out = {
        "repo": repo,
        "number": pr["number"],
        "url": f"https://github.com/{repo}/pull/{pr['number']}",
        "title": " ".join(str(pr.get("title") or "").split())[:200],
        "state": pr.get("state") if pr.get("state") in ("OPEN", "MERGED", "CLOSED") else "OPEN",
        "draft": pr.get("isDraft") is True,
        "base": str(pr.get("baseRefName") or ""),
        "head": str(pr.get("headRefName") or ""),
        "author": str(((pr.get("author") or {}).get("login")) or ""),
        "updated_at": str(pr.get("updatedAt") or ""),
        "checks": checks(ctx),
    }
    out["merge"] = merge_word(pr)
    out["status"] = status_word(out)
    return out


def main_pr(rows: list[dict]) -> dict | None:
    """The pull request a ticket's Details show: its newest open one, else its newest one."""
    if not rows:
        return None
    open_ = [r for r in rows if r.get("state") == "OPEN"]
    return max(open_ or rows, key=lambda r: r.get("number") or 0)


def ext_of(rows: list[dict]) -> dict | None:
    """ext.github for a ticket (ext.schema.json), or None when it links no readable pull request."""
    r = main_pr(rows)
    if r is None:
        return None
    return {"pr": f"#{r['number']}", "checks": r["checks"]["word"], "merge": r["merge"]}

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


def parse_url(url: str) -> tuple[str, int] | None:
    """("owner/name", number) for a GitHub pull request address, else None."""
    m = PR_URL.fullmatch(str(url or "").strip().rstrip("/"))
    return (f"{m[1]}/{m[2]}", int(m[3])) if m else None


RUN_IN_LINK = re.compile(r"/actions/runs/([0-9]{1,20})(?:/|$|\?)")


def run_of(link) -> int | None:
    """The workflow run id in a check's link (GitHub Actions only), else None."""
    m = RUN_IN_LINK.search(link) if isinstance(link, str) else None
    return int(m[1]) if m else None


def current(rows: list[dict]) -> list[dict]:
    """The checks that count, the one rule for the page, the ticket links and the merge queue. rows:
    {workflow, name, run, at, pending} in GitHub's order. Only the newest result of each check (its workflow and
    name: a newer run, else a later start, else a later place). A check left only by an older run of a workflow
    whose newer run on the same commit still runs comes back with "replaced": True: that run makes it again, so it
    counts as running (a draft-time failure while the ready-for-review run goes, #2411)."""
    best: dict[tuple, tuple[tuple, dict]] = {}
    newest: dict[str, int] = {}
    going: dict[str, set[int]] = {}
    for i, r in enumerate(rows):
        wf, run = str(r.get("workflow") or ""), r.get("run")
        if wf and isinstance(run, int):
            newest[wf] = max(newest.get(wf, run), run)
            if r.get("pending"):
                going.setdefault(wf, set()).add(run)
        order = (run if isinstance(run, int) else 0, str(r.get("at") or ""), i)
        key = (wf, str(r.get("name") or "?"))
        if key not in best or order >= best[key][0]:
            best[key] = (order, r)
    out = []
    for order, r in sorted(best.values(), key=lambda b: b[0][2]):
        wf, run = str(r.get("workflow") or ""), r.get("run")
        if wf and isinstance(run, int) and run < newest[wf] and any(x > run for x in going.get(wf, ())):
            r = {**r, "replaced": True}
        out.append(r)
    return out


def _is_context(n: dict) -> bool:
    return n.get("__typename") == "StatusContext" or ("context" in n and "status" not in n)


def _newest(raw: list | None) -> list[dict]:
    """The nodes of a statusCheckRollup that count (current): GraphQL nodes (checkSuite.workflowRun) and gh's
    `pr view --json statusCheckRollup` nodes (workflowName, detailsUrl) alike. A replaced node is a copy marked
    "replaced"."""
    rows = []
    for n in raw or []:
        if not isinstance(n, dict):
            continue
        if _is_context(n):
            rows.append({"workflow": "", "name": "ctx:" + str(n.get("context") or "?"), "node": n})
            continue
        wr = (n.get("checkSuite") or {}).get("workflowRun") or {}
        wf = (wr.get("workflow") or {}).get("name") or n.get("workflowName")
        run = wr.get("databaseId") if isinstance(wr.get("databaseId"), int) else run_of(n.get("detailsUrl"))
        pending = not n.get("conclusion")
        rows.append({"workflow": wf, "name": n.get("name"), "run": run, "at": n.get("startedAt"),
                     "pending": pending, "node": n})  # fmt: skip
    return [dict(r["node"], replaced=True) if r.get("replaced") else r["node"] for r in current(rows)]


def _one(node: dict) -> tuple[str, str] | None:
    """(name, state) of one check in the core waiter's words: SUCCESS, SKIPPED, PENDING or the failure word."""
    if not isinstance(node, dict):
        return None
    if node.get("replaced"):  # a newer run of its workflow makes it again (current)
        return str(node.get("name") or "?"), "PENDING"
    if _is_context(node):
        name, st = str(node.get("context") or "?"), str(node.get("state") or "")
        if st in ("PENDING", "EXPECTED", ""):
            return name, "PENDING"
        return name, "SUCCESS" if st == "SUCCESS" else st  # FAILURE, ERROR
    name = str(node.get("name") or "?")
    concl = str(node.get("conclusion") or "")
    if concl:  # a conclusion is the answer, also while GitHub still says in_progress (22 Nov, #2465)
        return name, concl
    return name, "PENDING"


def checks(raw: list | None) -> dict:
    """{word, passed, failed, running, failed_names} from a statusCheckRollup's context nodes."""
    rows = [r for r in (_one(n) for n in _newest(raw)) if r is not None]
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
        "head_sha": str(pr.get("headRefOid") or ""),
        "author": str(((pr.get("author") or {}).get("login")) or ""),
        "updated_at": str(pr.get("updatedAt") or ""),
        "created_at": str(pr.get("createdAt") or ""),  # the page's "opened per day" chart
        "merged_at": str(pr.get("mergedAt") or ""),  # and its "merged per day"
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


# What ext.pull-requests stores: the words a person reads under the ticket's Details (read-only fields, so the
# shown word is the stored one; ext.schema.json lists the same words)
CHECKS_SHOWN = {"passed": "Passed", "running": "Running", "failed": "Failed", "none": "No checks"}
MERGE_SHOWN = {
    "ready": "Ready to merge",
    "blocked": "Blocked",
    "behind": "Behind its base",
    "conflict": "Has a conflict",
    "draft": "Draft",
    "unknown": "Not known yet",
    "merged": "Merged",
    "closed": "Closed",
}


def ext_of(rows: list[dict]) -> dict | None:
    """ext.pull-requests for a ticket (ext.schema.json), or None when it links no readable pull request."""
    r = main_pr(rows)
    if r is None:
        return None
    return {
        "pr": f"#{r['number']}",
        "checks": CHECKS_SHOWN[r["checks"]["word"]],
        "merge": MERGE_SHOWN[r["merge"]],
    }

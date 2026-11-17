"""Helpers of the Pull requests page tests (ORCH-165): a fake orch CLI, tickets, GitHub's GraphQL answers."""

import json
import stat
import sys
from pathlib import Path

import pytest

from orch_pull_requests import prread as gh
from orch_pull_requests import prstate

REPO = Path(__file__).resolve().parents[3]

# A fake orch CLI: tickets from .orch/tickets/*.json, every call recorded in calls.jsonl.
FAKE_ORCH = """#!{py}
import json, os, sys
from pathlib import Path
root = Path.cwd()
args = [a for a in sys.argv[1:] if a != "--json"]
with open(root / "calls.jsonl", "a") as f:
    f.write(json.dumps({{"args": args, "cached": os.environ.get("ORCH_PULL_REQUESTS_CACHED")}}) + "\\n")
tdir = root / ".orch" / "tickets"
if args[:2] == ["ticket", "list"]:
    print(json.dumps([json.loads(p.read_text()) for p in sorted(tdir.glob("t_*.json"))]))
elif args[:2] == ["addon", "list"]:
    print(json.dumps([{{"name": "pull-requests", "active": not (root / "inactive").exists()}}]))
elif args[:3] == ["pull-requests", "act", "refresh"]:
    print(json.dumps({{"ticket": args[-1], "changes": [], "say": ""}}))
else:
    sys.exit(2)
"""


@pytest.fixture
def prws(tmp_path, monkeypatch):
    """A workspace with the fake orch CLI as ORCH_BIN (cwd stays out of it)."""
    root = tmp_path / "ws"
    (root / ".orch" / "tickets").mkdir(parents=True)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    orch = bin_ / "orch"
    orch.write_text(FAKE_ORCH.format(py=sys.executable))
    orch.chmod(orch.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("ORCH_BIN", str(orch))
    monkeypatch.delenv("ORCH_PULL_REQUESTS_CACHED", raising=False)
    return root


def add_ticket(root: Path, tid: str, refs=(), **kw) -> dict:
    t = {
        "schema": "orch.ticket/1",
        "id": tid,
        "key": "DM-" + tid[-1],
        "title": "T " + tid,
        "status": "open",
        "revision": 1,
        "refs": list(refs),
        "ext": {},
    }
    t.update(kw)
    (root / ".orch" / "tickets" / f"{tid}.json").write_text(json.dumps(t))
    return t


def calls(root: Path) -> list[dict]:
    p = root / "calls.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def gql_pr(n: int, state="OPEN", draft=False, merge="CLEAN", mergeable="MERGEABLE", checks=None, title=None):
    """One pull request as GitHub's GraphQL API answers it."""
    if checks is None:
        checks = [{"__typename": "CheckRun", "name": "test", "status": "COMPLETED", "conclusion": "SUCCESS"}]
    return {
        "number": n,
        "title": title or f"Change {n}",
        "url": f"https://github.com/acme/app/pull/{n}",
        "state": state,
        "isDraft": draft,
        "mergeable": mergeable,
        "mergeStateStatus": merge,
        "baseRefName": "develop",
        "headRefName": f"feat/x{n}",
        "updatedAt": "2026-11-17T09:00:00Z",
        "author": {"login": "dev"},
        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"contexts": {"nodes": checks}}}}]},
    }


class FakeGitHub:
    """prread.fetch stand-in: {repo: [graphql pull requests]}; records each call."""

    def __init__(self, prs: dict, fail: dict | None = None):
        self.prs, self.fail, self.calls = prs, fail or {}, []

    def __call__(self, repo, numbers=None):
        self.calls.append((repo, list(numbers or [])))
        if repo in self.fail:
            raise gh.GhError(self.fail[repo])
        rows = [prstate.row(repo, p) for p in self.prs.get(repo, [])]
        open_ = [r for r in rows if r["state"] == "OPEN"]
        linked = {r["number"]: r for r in rows if r["number"] in (numbers or [])}
        return {"open": open_, "linked": linked}

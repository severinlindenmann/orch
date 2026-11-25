"""The dashboard fixture of the Pull requests page (e2e/fixtures/pull-requests-page.json), made with the add-on's
own code: the page view in its states, one ticket after a refresh merged by the core (its links' `view` as the
dashboard adds it) and the add-on's row of `orch addon list`. test_dash_fixture.py checks the file is current.

    uv run python tests/dash_fixture.py        # rewrite the file
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import UTC
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path[:0] = [str(HERE), str(HERE.parent / "src"), str(REPO / "workspace" / "src")]
OUT = REPO / "e2e" / "fixtures" / "pull-requests-page.json"
AT = "2026-11-17T09:41:00Z"


def _checks(*pairs):
    return [
        {"__typename": "CheckRun", "name": n, "status": "COMPLETED" if c else "IN_PROGRESS", "conclusion": c}
        for n, c in pairs
    ]


def _ts(stamp: str) -> float:
    from datetime import UTC, datetime

    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()


def _queue(root: Path) -> None:
    """The merge queue on the loaded page: a group of two being checked, one paused, one waiting (ORCH-432)."""
    from orch_pull_requests import store

    group = "https://github.com/acme/billing/pull/530"
    rows = [  # repo, number, ticket, added, state, why, paused until, group
        ("acme/billing", 421, "t_pdf014", "2026-11-17T09:12:00Z", "running", "in the group being checked", None, group),
        ("acme/billing", 420, "t_tax015", "2026-11-17T09:15:00Z", "running", "in the group being checked", None, group),
        ("acme/website", 88, None, "2026-11-17T08:52:00Z", "waiting", "waits again: GitHub did not answer",
         _ts(AT) + 360, None),
    ]  # fmt: skip
    # what the queue finished lately: the charts and "Merged lately" (ORCH-746); one group a day, some sent back
    done = [  # number, day, group size, merged?
        (401, 6, 2, True), (403, 7, 3, True), (405, 9, 1, False), (406, 10, 2, True), (408, 11, 3, True),
        (411, 12, 2, False), (413, 13, 3, True), (416, 14, 2, True), (409, 15, 1, True), (414, 16, 3, True),
    ]  # fmt: skip
    finished = []
    for n0, day, size, ok in done:
        for k in range(size):
            stamp = f"2026-11-{day:02d}T10:%02d:00Z"
            finished.append(
                {"url": f"https://github.com/acme/billing/pull/{n0 + k * 50}", "repo": "acme/billing",
                 "number": n0 + k * 50, "ticket": None, "by": "agent:claude", "added": stamp % 0,
                 "taken": stamp % 20, "ended": stamp % 34, "state": "merged" if ok else "out",
                 "why": "merged on green" if ok else "checks failed", "base": "develop", "login": "bot"}
            )  # fmt: skip
    entries = []
    for repo, n, tid, added, state, why, later, grp in rows:
        e = {"url": f"https://github.com/{repo}/pull/{n}", "repo": repo, "number": n, "ticket": tid,
             "by": "agent:claude", "added": added, "state": state, "why": why, "base": "develop", "login": "bot"}  # fmt: skip
        if later:
            e["not_before"] = later
        if grp:
            e.update(group=grp, taken="2026-11-17T09:29:00Z")
        entries.append(e)
    store.folder(root).mkdir(parents=True, exist_ok=True)
    (store.folder(root) / "queue.json").write_text(
        json.dumps({"entries": finished + entries}), encoding="utf-8"
    )


def build() -> dict:
    from orch import addons, refs, tickets
    from prpage_util import FakeGitHub, gql_pr

    from orch_pull_requests import poll, view

    ok = ("test", "SUCCESS"), ("lint", "SUCCESS"), ("build", "SUCCESS")
    prs = {
        "acme/billing": [
            gql_pr(418, created="2026-11-12T08:00:00Z", merge="BLOCKED", title="Add CSV export for invoices",
                   checks=_checks(("test", "SUCCESS"), ("lint", "FAILURE"), ("build", "SUCCESS"))),
            gql_pr(421, created="2026-11-13T08:00:00Z", title="Show the invoice number on the PDF", checks=_checks(*ok)),
            gql_pr(420, created="2026-11-14T08:00:00Z", merge="BLOCKED", title="Round tax per line, not per invoice",
                   checks=_checks(("test", None), ("lint", "SUCCESS"), ("build", None))),
            gql_pr(419, created="2026-11-15T08:00:00Z", draft=True, title="Try a new PDF library", checks=[]),
            gql_pr(417, created="2026-11-10T08:00:00Z", mergeable="CONFLICTING", merge="DIRTY", title="Rename customer to client",
                   checks=_checks(*ok)),
        ],
        "acme/website": [gql_pr(88, created="2026-11-16T08:00:00Z", title="New pricing page", checks=_checks(*ok))],
    }  # fmt: skip
    for p in prs["acme/website"]:
        p["url"] = p["url"].replace("acme/app", "acme/website")
    links = {
        "t_inv012": ("Invoice CSV export", [418]),
        "t_pdf014": ("Invoice number on the PDF", [421]),
        "t_tax015": ("Tax rounding", [420]),
        "t_ren009": ("Rename customer to client", [417]),
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "billing"  # a fixed name: the ticket keys' prefix comes from it
        (root / ".orch" / "tickets").mkdir(parents=True)
        made = {}
        for i, (tid, (title, nums)) in enumerate(links.items()):
            t = tickets.create(root, title, "human:anna", tid=tid)
            for n in nums:
                tickets.ref_add(root, t["id"], f"https://github.com/acme/billing/pull/{n}", "human:anna")
            made[tid] = tickets.load(root, t["id"])
        tickets.ref_add(root, "t_inv012", "https://github.com/acme/billing/issues/402", "human:anna")
        data = poll.load(root)
        poll.read(root, poll.plan(list(made.values())), data, FakeGitHub(prs))
        data["repos"].setdefault("acme/website", {})
        poll.read(root, {"acme/website": []}, data, FakeGitHub(prs))
        for r in data["prs"].values():
            r["url"] = f"https://github.com/{r['repo']}/pull/{r['number']}"
        data["polled_at"] = AT
        poll.save(root, data)
        schema = json.loads(
            (HERE.parent / "src/orch_pull_requests/ext.schema.json").read_text(encoding="utf-8")
        )
        for tid in made:
            res = poll.answer(tickets.load(root, tid), data)
            tickets.merge_refresh(root, tid, "pull-requests", res, "agent:pull-requests", schema)
        orig_tickets, orig_runs = poll.tickets, view._runs
        poll.tickets = lambda _root: [tickets.load(root, tid) for tid in made]
        view._runs = lambda _root: {}  # the run read: no helper is running (ORCH-1859)
        try:
            stopped = view.build(root, running=False, queue_alive=True, now=_ts(AT), tz=UTC)
            _queue(root)
            loaded = view.build(root, running=True, queue_alive=True, now=_ts(AT), tz=UTC)
            # the same page with only the run read changed: a helper runs on BIL-1, or the read failed
            view._runs = lambda _root: {"t_inv012": "claude"}
            helper_live = view.build(root, running=True, queue_alive=True, now=_ts(AT), tz=UTC)
            view._runs = lambda _root: None
            helper_unknown = view.build(root, running=True, queue_alive=True, now=_ts(AT), tz=UTC)
        finally:
            poll.tickets, view._runs = orig_tickets, orig_runs
        m = addons.folder_manifest(HERE.parent)
        kinds = [{**k, "addon": "pull-requests"} for k in m["ticket_links"]]
        ticket = tickets.load(root, "t_inv012")
        for ln in ticket["refs"]:
            if isinstance(ln, dict) and ln.get("url"):
                ln["view"] = refs.describe(ln, kinds)
    with tempfile.TemporaryDirectory() as tmp:  # a workspace whose tickets link nothing yet
        (Path(tmp) / ".orch").mkdir()
        poll.tickets = lambda _root: []
        try:
            empty = view.build(Path(tmp), running=True, now=_ts(AT), tz=UTC)
        finally:
            poll.tickets = orig_tickets
    for v in (loaded, helper_live, helper_unknown, stopped, empty):
        v["generated_at"] = AT
    for k in ("created_at", "updated_at"):
        ticket[k] = AT
    for h in ticket.get("history") or []:
        h["at"] = AT
    for ln in ticket.get("refs") or []:
        for k in ("at", "seen_at"):
            if k in ln:
                ln[k] = AT
    from orch import fields

    return {
        "_note": "Made by workspace-addons/pull-requests/tests/dash_fixture.py; do not edit by hand.",
        "addon": {
            "name": "pull-requests",
            "dashboard": {**m["dashboard"], "place": "nav", "panel": None, "title": None},
            "ticket_fields": fields.section(m),
            "acts": sorted(m["acts"]),
            "link_kinds": [k["kind"] for k in kinds],
            "ticket_view": [],
            "page": None,
            "shipped": True,
        },
        "views": {
            "loaded": loaded,
            "helper_live": helper_live,
            "helper_unknown": helper_unknown,
            "stopped": stopped,
            "empty": empty,
        },
        "ticket": ticket,
    }


def render() -> str:
    return json.dumps(build(), indent=1, ensure_ascii=False, sort_keys=True) + "\n"


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8")
    print("ok", OUT.relative_to(REPO))

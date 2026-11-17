"""The dashboard fixture of the Pull requests page (e2e/fixtures/pull-requests-page.json), made with the add-on's
own code: the page view in its states, one ticket after a refresh merged by the core (its links' `view` as the
dashboard adds it) and the add-on's row of `orch addon list`. test_dash_fixture.py checks the file is current.

    uv run python tests/dash_fixture.py        # rewrite the file
"""

from __future__ import annotations

import json
import sys
import tempfile
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


def build() -> dict:
    from orch import addons, refs, tickets
    from prpage_util import FakeGitHub, gql_pr

    from orch_pull_requests import poll, view

    ok = ("test", "SUCCESS"), ("lint", "SUCCESS"), ("build", "SUCCESS")
    prs = {
        "acme/billing": [
            gql_pr(418, merge="BLOCKED", title="Add CSV export for invoices",
                   checks=_checks(("test", "SUCCESS"), ("lint", "FAILURE"), ("build", "SUCCESS"))),
            gql_pr(421, title="Show the invoice number on the PDF", checks=_checks(*ok)),
            gql_pr(420, merge="BLOCKED", title="Round tax per line, not per invoice",
                   checks=_checks(("test", None), ("lint", "SUCCESS"), ("build", None))),
            gql_pr(419, draft=True, title="Try a new PDF library", checks=[]),
            gql_pr(417, mergeable="CONFLICTING", merge="DIRTY", title="Rename customer to client",
                   checks=_checks(*ok)),
        ],
        "acme/website": [gql_pr(88, title="New pricing page", checks=_checks(*ok))],
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
        orig_tickets = poll.tickets
        poll.tickets = lambda _root: [tickets.load(root, tid) for tid in made]
        try:
            loaded = view.build(root, running=True)
            stopped = view.build(root, running=False)
        finally:
            poll.tickets = orig_tickets
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
            empty = view.build(Path(tmp), running=True)
        finally:
            poll.tickets = orig_tickets
    for v in (loaded, stopped, empty):
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
        "views": {"loaded": loaded, "stopped": stopped, "empty": empty},
        "ticket": ticket,
    }


def render() -> str:
    return json.dumps(build(), indent=1, ensure_ascii=False, sort_keys=True) + "\n"


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8")
    print("ok", OUT.relative_to(REPO))

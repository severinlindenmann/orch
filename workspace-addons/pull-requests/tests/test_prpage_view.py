"""The Pull requests page: valid orch.addon-view/1 blocks for every state (empty, not running, trouble, rows)."""

import json

import jsonschema
import pytest
from prpage_util import REPO, FakeGitHub, add_ticket, gql_pr

from orch_pull_requests import poll, view
from orch_pull_requests import prread as gh

SCHEMA = json.loads((REPO / "contracts" / "addon-view.schema.json").read_text(encoding="utf-8"))
PR = "https://github.com/acme/app/pull/{}"


def valid(v: dict) -> dict:
    jsonschema.validate(v, SCHEMA)
    return v


def fail_run(name, conclusion="FAILURE"):
    return [{"__typename": "CheckRun", "name": name, "status": "COMPLETED", "conclusion": conclusion}]


def test_empty_page(prws):
    v = valid(view.build(prws, running=True))
    assert [b["type"] for b in v["blocks"]] == ["stat", "stat", "stat", "list"]
    assert v["blocks"][-1]["empty"]["title"] == "No pull requests yet"
    assert "notice" not in v


def test_not_running_says_so_with_one_button(prws):
    v = valid(view.build(prws, running=False))
    assert v["notice_tone"] == "warn" and v["button"]["action"] == {"op": "addon.start"}


def test_rows_with_ticket_checks_and_merge_state(prws):
    add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1)}])
    add_ticket(prws, "t_aaaaa2", [{"url": PR.format(3)}])
    fake = FakeGitHub(
        {
            "acme/app": [
                gql_pr(1),
                gql_pr(2, draft=True, checks=[]),
                gql_pr(3, merge="BLOCKED", checks=fail_run("lint")),
            ]
        }
    )
    poll.once(prws, fetch=fake)
    v = valid(view.build(prws, running=True))
    stats = {b["label"]: b["value"] for b in v["blocks"] if b["type"] == "stat"}
    assert stats == {"Open": 3, "Checks failed": 1, "Ready to merge": 1}
    (table,) = [b for b in v["blocks"] if b["type"] == "table"]
    assert table["title"] == "acme/app" and table["meta"] == "3 open"
    rows = table["rows"]
    # what needs attention first: failed, then ready to merge, then the rest newest first
    assert [r["cells"]["pr"] for r in rows] == ["#3 Change 3", "#1 Change 1", "#2 Change 2"]
    assert rows[0]["cells"] == {
        "pr": "#3 Change 3",
        "ticket": "DM-2",
        "checks": "Failed: lint",
        "merge": "Blocked",
    }
    assert rows[0]["link"] == "t_aaaaa2"  # a linked pull request opens its ticket
    assert rows[2]["cells"]["ticket"] is None and rows[2]["link"] == PR.format(2)  # no ticket: GitHub
    assert rows[2]["cells"]["merge"] == "Draft" and rows[2]["cells"]["checks"] == "No checks"
    assert rows[1]["cells"]["merge"] == "Ready to merge"
    assert rows[1]["subtitle"] == "feat/x1 into develop · dev"


def test_github_trouble_is_the_notice(prws):
    add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1)}])
    poll.once(prws, fetch=FakeGitHub({}, fail={"acme/app": gh.NOT_SIGNED_IN}))
    v = valid(view.build(prws, running=True))
    assert v["notice"] == gh.NOT_SIGNED_IN and v["notice_tone"] == "bad"
    assert v["blocks"][-1]["type"] == "list"  # nothing readable: the empty state, not an empty table


@pytest.mark.parametrize("n", [101])
def test_long_lists_are_cut_with_more(prws, n):
    add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1)}])
    fake = FakeGitHub({"acme/app": [gql_pr(i, title="x" * 300) for i in range(1, n + 1)]})
    poll.once(prws, fetch=fake)
    v = valid(view.build(prws, running=True))
    (table,) = [b for b in v["blocks"] if b["type"] == "table"]
    assert len(table["rows"]) == 100 and table["more"] == 1

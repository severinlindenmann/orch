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


# -- the merge queue's line (ORCH-432) ------------------------------------------------------------------------
def _queue(root, *numbers, ticket=None):
    from orch_pull_requests import store

    for n in numbers:
        store.add(root, PR.format(n), ticket, "agent:t", base="develop", login="bot")


def test_no_queue_block_when_nothing_waits(prws):
    assert view.queue_block(prws, [], alive=True) is None
    v = valid(view.build(prws, running=True))
    assert not [b for b in v["blocks"] if b.get("title") == "Merge queue"]


def test_queue_block_shows_place_wait_and_why(prws):
    from datetime import UTC, datetime

    from orch_pull_requests import store

    _queue(prws, 1, ticket="t_aaaaa1")
    _queue(prws, 2, 3, 4)
    added = (
        datetime.strptime(store.read(prws)[0]["added"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    )
    now = added + 600
    store.claim(prws, [store.read(prws)[1]])  # #2 is in the group being checked
    store.set_state(
        prws, PR.format(3), store.WAITING, "waits again: GitHub did not answer", not_before=now + 120
    )
    tickets = [{"id": "t_aaaaa1", "key": "DM-1"}]
    b = view.queue_block(prws, tickets, alive=True, now=now)
    valid({"schema": "orch.addon-view/1", "generated_at": "2026-11-18T10:00:00Z", "blocks": [b]})
    assert b["title"] == "Merge queue" and b["meta"] == "3 waiting · 1 being checked · groups of up to 5"
    cells = [r["cells"] for r in b["rows"]]
    assert [c["pr"] for c in cells] == ["#2", "#1", "#3", "#4"]  # being checked first, then the line
    assert [c["place"] for c in cells] == ["Being checked", "1st in line", "2nd in line", "3rd in line"]
    assert cells[0]["why"] == "Checked alone on top of develop"
    assert cells[1]["ticket"] == "DM-1" and b["rows"][1]["link"] == "t_aaaaa1"
    assert cells[1]["why"] == "Waits for the group being checked" and cells[1]["waited"] == 600
    assert cells[2]["why"] == "Paused for 2 min: GitHub did not answer"
    assert b["rows"][3]["link"] == PR.format(4) and cells[3]["ticket"] is None


def test_queue_block_says_when_the_runner_does_not_run(prws):
    _queue(prws, 1)
    b = view.queue_block(prws, [], alive=False)
    assert b["rows"][0]["cells"]["why"].startswith("The merge queue is not running")
    assert b["rows"][0]["cells"]["place"] == "1st in line"


def test_queue_block_follows_the_group_size_setting(prws):
    (prws / ".orch" / "config.toml").write_text("[pull_requests]\nmax_group = 10\n", encoding="utf-8")
    _queue(prws, 1)
    b = view.queue_block(prws, [], alive=True)
    assert b["meta"].endswith("groups of up to 10")
    assert b["rows"][0]["cells"]["why"] == "Goes into the next group"


def test_queue_block_names_the_group_partners_and_never_a_raw_address(prws):
    from orch_pull_requests import store

    _queue(prws, 1, 2, 3)
    g = "https://github.com/acme/app/pull/500"
    for n in (1, 2):
        store.claim(prws, [store.find(store.read(prws), PR.format(n))])
        store.set_state(prws, PR.format(n), store.RUNNING, f"in the group {g}", group=g)
    store.set_state(
        prws, PR.format(3), store.WAITING, f"waits again: the group {g} was not merged: no verdict"
    )
    b = view.queue_block(prws, [], alive=True)
    whys = [r["cells"]["why"] for r in b["rows"]]
    assert whys == ["Checked together with 1 other", "Checked together with 1 other",
                    "The group #500 was not merged: no verdict"]  # fmt: skip

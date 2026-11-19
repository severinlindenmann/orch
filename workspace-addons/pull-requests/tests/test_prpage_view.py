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
    v = valid(view.build(prws, running=True, queue_alive=True))
    assert [b["type"] for b in v["blocks"]] == ["list", "footnote"]  # one empty state, not two
    assert v["blocks"][0]["empty"]["title"] == "No pull requests yet"
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
    v = valid(view.build(prws, running=True, queue_alive=True))
    assert not [b for b in v["blocks"] if b["type"] == "stat"]  # the counts live in the table's heading
    (table,) = [b for b in v["blocks"] if b["type"] == "table"]
    assert table["title"] == "Open pull requests" and table["meta"] == "3 open"
    assert [c["key"] for c in table["columns"]] == ["pr", "ticket", "state", "in_line"]
    rows = table["rows"]
    # what needs someone first, then ready to merge, then drafts
    assert [r["cells"]["pr"] for r in rows] == ["Change 3", "Change 1", "Change 2"]
    assert rows[0]["cells"] == {"pr": "Change 3", "ticket": "DM-2", "state": "Checks failed", "in_line": None}
    assert rows[0]["subtitle"] == "Checks failed: lint. Waits for a helper place."
    assert rows[0]["link"] == "t_aaaaa2"  # a linked pull request opens its ticket
    assert rows[1]["cells"]["state"] == "Ready to merge" and rows[1]["subtitle"] == "Not in the merge queue."
    assert rows[2]["cells"]["ticket"] is None and rows[2]["link"] == PR.format(2)  # no ticket: GitHub
    assert rows[2]["cells"]["state"] == "Draft"
    assert v["blocks"][-1] == {
        "type": "footnote",
        "text": "The merge queue checks up to 5 pull requests together and merges them when the checks pass.",
    }


def test_repair_note_says_who_fixes_a_red_pull_request():
    tk = {"id": "t_a", "key": "DM-2"}
    assert view.repair_note(tk, {"t_a": "claude"}, {"t_a": "active"}) == "Being repaired by claude."
    assert view.repair_note(tk, {}, {"t_a": "ready"}) == "Waits for a helper place."
    assert "No helper is on it" in view.repair_note(tk, {}, {"t_a": "review"})
    assert "No ticket" in view.repair_note(None, {}, {})


def test_github_trouble_is_the_notice(prws):
    add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1)}])
    poll.once(prws, fetch=FakeGitHub({}, fail={"acme/app": gh.NOT_SIGNED_IN}))
    v = valid(view.build(prws, running=True, queue_alive=True))
    assert v["notice"] == gh.NOT_SIGNED_IN and v["notice_tone"] == "bad"
    assert v["blocks"][0]["type"] == "list"  # nothing readable: the empty state, not an empty table


@pytest.mark.parametrize("n", [101])
def test_long_lists_are_cut_with_more(prws, n):
    add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1)}])
    fake = FakeGitHub({"acme/app": [gql_pr(i, title="x" * 300) for i in range(1, n + 1)]})
    poll.once(prws, fetch=fake)
    v = valid(view.build(prws, running=True))
    (table,) = [b for b in v["blocks"] if b["type"] == "table"]
    assert len(table["rows"]) == 100 and table["more"] == 1


# -- the merge queue on the page (ORCH-432) -------------------------------------------------------------------
def _queue(root, *numbers, ticket=None, repo="acme/app"):
    from orch_pull_requests import store

    for n in numbers:
        store.add(root, f"https://github.com/{repo}/pull/{n}", ticket, "agent:t", base="develop", login="bot")


def _t(stamp):
    from datetime import UTC, datetime

    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()


def test_the_queue_shows_its_groups_per_project_and_each_row_its_place(prws):
    from orch_pull_requests import store

    add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1)}, {"url": PR.format(2)}, {"url": PR.format(3)}])
    poll.once(prws, fetch=FakeGitHub({"acme/app": [gql_pr(1), gql_pr(2), gql_pr(3), gql_pr(4, draft=True)]}))
    _queue(prws, 1, 2, 3, ticket="t_aaaaa1")
    _queue(prws, 7, repo="acme/web")
    rows = store.read(prws)
    store.claim(prws, rows[:2])  # #1 and #2 are the group being checked
    now = _t(rows[0]["added"]) + 25 * 60
    store.set_state(
        prws, PR.format(3), store.WAITING, "waits again: GitHub did not answer", not_before=now + 360
    )
    v = valid(view.build(prws, running=True, queue_alive=True, now=now))
    lists = [b for b in v["blocks"] if b["type"] == "list"]
    assert [b["title"] for b in lists] == ["Merge queue: acme/app", "Merge queue: acme/web"]
    app = lists[0]
    assert app["meta"] == "into develop · groups of up to 5" and not app.get("compact")
    assert app["items"][0]["title"] == "Group of 2 · checks running 25 min"
    assert app["items"][0]["subtitle"] == "Change 1; Change 2"
    assert app["items"][1]["title"] == "1 waiting in line · longest 25 min"
    assert app["items"][1]["subtitle"] == "Next: Change 3"
    (table,) = [b for b in v["blocks"] if b["type"] == "table"]
    cells = [(r["cells"]["pr"], r["cells"]["state"], r["cells"]["in_line"]) for r in table["rows"]]
    assert cells == [
        ("Change 1", "Being checked", 1500),
        ("Change 2", "Being checked", 1500),
        ("Change 3", "1st in line, paused", 1500),
        ("#7", "1st in line", 1500),  # its own project's line; queued without a link read: shown by number
        ("Change 4", "Draft", None),
    ]
    paused = table["rows"][2]
    assert paused["subtitle"] == "GitHub did not answer; tries again by itself in 6 min."
    assert table["meta"] == "5 open · 2 repositories"


def test_an_empty_queue_still_says_where_it_is(prws):
    (prws / ".orch" / "config.toml").write_text("[pull_requests]\nmax_group = 10\n", encoding="utf-8")
    add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1)}])
    poll.once(prws, fetch=FakeGitHub({"acme/app": [gql_pr(1)]}))
    v = valid(view.build(prws, running=True, queue_alive=True))
    first = v["blocks"][0]
    assert first["title"] == "Merge queue" and first["meta"] == "groups of up to 10"
    assert first["empty"]["title"] == "Nothing in the merge queue"
    assert "up to 10 pull requests" in v["blocks"][-1]["text"]


def test_a_queue_that_does_not_run_says_so(prws):
    _queue(prws, 1)
    v = valid(view.build(prws, running=True, queue_alive=False))
    item = v["blocks"][0]["items"][0]
    assert item["tone"] == "warn" and item["subtitle"].startswith("The merge queue is not running")


def test_no_raw_address_in_the_reasons(prws):
    from orch_pull_requests import store

    _queue(prws, 1)
    store.set_state(
        prws,
        PR.format(1),
        store.WAITING,
        "waits again: the group https://github.com/acme/app/pull/500 was not merged",
    )
    v = valid(view.build(prws, running=True, queue_alive=True))
    (table,) = [b for b in v["blocks"] if b["type"] == "table"]
    assert table["rows"][0]["subtitle"] == "The group #500 was not merged"

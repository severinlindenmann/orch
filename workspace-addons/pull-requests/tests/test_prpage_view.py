"""The Pull requests page: valid orch.addon-view/1 blocks for every state (empty, not running, trouble, rows)."""

import json
from datetime import UTC

import jsonschema
import pytest
from prpage_util import REPO, FakeGitHub, add_ticket, calls, gql_pr

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
    assert v["blocks"][0]["title"] == "Open pull requests"  # not the page's own title again
    assert v["blocks"][0]["empty"]["button"] == {"label": "Open tickets", "to": "app:tickets"}  # a next step
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
    assert [c["key"] for c in table["columns"]] == ["num", "pr", "why", "ticket", "state", "in_line"]
    assert table["filter"] == "state" and table["compact"] is True and table["fold"] == view.FOLD
    rows = table["rows"]
    # what needs someone first, then ready to merge, then drafts
    assert [r["cells"]["pr"] for r in rows] == ["Change 3", "Change 1", "Change 2"]
    assert rows[0]["cells"] == {
        "num": "#3",
        "pr": "Change 3",
        "why": "lint failed. No helper running on DM-2. Open the ticket to fix it.",
        "ticket": "DM-2",
        "state": "Checks failed",
        "in_line": None,
    }
    assert rows[0]["tones"] == {"state": "bad"}
    assert rows[0]["link"] == "t_aaaaa2"  # a linked pull request opens its ticket
    assert rows[0]["links"] == {"num": PR.format(3), "ticket": "t_aaaaa2"}  # the number opens GitHub
    assert (
        rows[1]["cells"]["state"] == "Ready to merge" and rows[1]["cells"]["why"] == "Not in the merge queue."
    )
    assert rows[1]["tones"] == {"state": "good"}
    assert rows[2]["cells"]["ticket"] is None and rows[2]["link"] == PR.format(2)  # no ticket: GitHub
    assert rows[2]["links"] == {"num": PR.format(2)}
    assert rows[2]["cells"]["state"] == "Draft" and "tones" not in rows[2]
    assert v["blocks"][-1] == {
        "type": "footnote",
        "text": "The merge queue checks up to 5 pull requests together and merges them when the checks pass.",
    }


def test_repair_note_tells_a_broken_check_from_a_helper_on_it():
    tk = {"id": "t_a", "key": "DM-2", "status": "open"}
    assert view.repair_note(tk, {"t_a": "claude"}) == "A helper is running on DM-2, maybe not on this check."
    # an open ticket is no evidence that a helper is coming: without a live run nobody is on it
    assert view.repair_note(tk, {}) == "No helper running on DM-2. Open the ticket to fix it."
    assert view.repair_note(tk, {"t_b": "codex"}) == "No helper running on DM-2. Open the ticket to fix it."
    assert view.repair_note(tk, None) == "Helper status on DM-2 could not be checked; tries again by itself."
    assert view.repair_note(None, {}) == view.repair_note(None, None)
    assert view.repair_note(None, None).startswith("No ticket is linked: make a ticket")


def test_runs_is_none_when_the_run_list_cannot_be_read(prws):
    assert view._runs(prws) == {}
    (prws / "runs.json").write_text(json.dumps({"runs": [
        {"ticket": "t_a", "agent": "claude", "state": "alive"},
        {"ticket": "t_b", "agent": "codex", "state": "ended"},
    ]}))  # fmt: skip
    assert view._runs(prws) == {"t_a": "claude"}
    (prws / "runs.json").write_text(json.dumps({"runs": "garbled"}))
    assert view._runs(prws) is None
    (prws / "run-list-fails").touch()
    assert view._runs(prws) is None


def test_the_same_failed_pull_request_shows_live_not_running_and_unknown(prws):
    """Only the run read changes: the row keeps its place, tab, ticket and links; only its words change."""
    add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1)}])
    add_ticket(prws, "t_aaaaa2", [{"url": PR.format(3)}])
    fake = FakeGitHub(
        {"acme/app": [gql_pr(1), gql_pr(2, draft=True, checks=[]), gql_pr(3, merge="BLOCKED", checks=fail_run("lint")),
                      gql_pr(4, merge="BLOCKED", checks=fail_run("test"))]}
    )  # fmt: skip
    poll.once(prws, fetch=fake)

    def table():
        v = valid(view.build(prws, running=True, queue_alive=True))
        (t,) = [b for b in v["blocks"] if b["type"] == "table"]
        return t

    seen = {}
    for name, read in [
        ("live", lambda: (prws / "runs.json").write_text(
            json.dumps({"runs": [{"ticket": "t_aaaaa2", "agent": "claude", "state": "alive"}]}))),
        ("none", lambda: (prws / "runs.json").unlink()),
        ("unknown", lambda: (prws / "run-list-fails").touch()),
    ]:  # fmt: skip
        read()
        seen[name] = table()

    def row(t, n):
        return next(r for r in t["rows"] if r["cells"]["num"] == f"#{n}")

    whys = {k: row(t, 3)["cells"]["why"] for k, t in seen.items()}
    assert whys == {
        "live": "lint failed. A helper is running on DM-2, maybe not on this check.",
        "none": "lint failed. No helper running on DM-2. Open the ticket to fix it.",
        "unknown": "lint failed. Helper status on DM-2 could not be checked; tries again by itself.",
    }

    def without_why(t):
        return {**t, "rows": [{**r, "cells": {**r["cells"], "why": None}} for r in t["rows"]]}

    assert without_why(seen["live"]) == without_why(seen["none"]) == without_why(seen["unknown"])
    first = row(seen["live"], 3)
    assert first["cells"]["state"] == "Checks failed" and first["tones"] == {"state": "bad"}
    assert first["link"] == "t_aaaaa2" and first["links"] == {"num": PR.format(3), "ticket": "t_aaaaa2"}
    # an unlinked red pull request says so in every case, never that a helper is on it or not known
    unlinked = {row(t, 4)["cells"]["why"] for t in seen.values()}
    assert unlinked == {"test failed. No ticket is linked: make a ticket for it so a helper can fix it."}
    assert row(seen["live"], 4)["link"] == PR.format(4) and row(seen["live"], 4)["cells"]["ticket"] is None
    ran = [c["args"][:2] for c in calls(prws)]
    assert not [
        c for c in ran if c[:1] == ["run"] and c != ["run", "list"]
    ]  # reads only, never starts a helper


def test_github_trouble_is_the_notice(prws):
    add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1)}])
    poll.once(prws, fetch=FakeGitHub({}, fail={"acme/app": gh.NOT_SIGNED_IN}))
    v = valid(view.build(prws, running=True, queue_alive=True))
    # D5: no command, no "this computer"
    assert v["notice"] == view.NOT_CONNECTED and v["notice_tone"] == "warn"
    assert "gh auth" not in v["notice"] and "this computer" not in v["notice"]
    assert v["button"] == {"label": "Try again", "action": {"op": "addon.refresh"}}
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
    flows = [b for b in v["blocks"] if b["type"] == "flow"]
    assert [b["title"] for b in flows] == ["Merge queue: acme/app", "Merge queue: acme/web"]
    assert v["blocks"][0]["type"] == "flow"  # the queue comes first (owner pick B, ORCH-746)
    app = flows[0]
    assert (
        app["meta"] == "into develop · groups of up to 5"
        and app["link"] == "https://github.com/acme/app/pulls"
    )
    check, line, done = app["stages"]
    assert check["label"] == "Being checked" and check["value"] == "Group of 2" and check["active"]
    assert check["text"] == "checks running 25 min"  # no finished group yet: no "usually"
    assert [c["label"] for c in check["items"]] == ["#1", "#2"]
    assert check["items"][0] == {"label": "#1", "link": PR.format(1), "hint": "Change 1"}
    assert line["value"] == "1 waiting" and line["text"] == "longest 25 min · 1 paused"
    assert line["items"] == [
        {"label": "#3", "link": PR.format(3), "hint": "Change 3 (paused)", "place": 1, "tone": "warn"}
    ]
    assert done["value"] == "Nothing yet"
    (table,) = [b for b in v["blocks"] if b["type"] == "table"]
    cells = [(r["cells"]["pr"], r["cells"]["state"], r["cells"]["in_line"]) for r in table["rows"]]
    assert cells == [
        ("Change 1", "Being checked", 1500),
        ("Change 2", "Being checked", 1500),
        ("Change 3", "In line", 1500),
        ("#7", "In line", 1500),  # its own project's line; queued without a link read: shown by number
        ("Change 4", "Draft", None),
    ]
    paused = table["rows"][2]
    assert (
        paused["cells"]["why"]
        == "app · 1st in line, paused. GitHub did not answer; tries again by itself in 6 min."
    )
    assert table["rows"][3]["cells"]["why"] == "web · 1st in line."
    assert table["meta"] == "5 open · 2 repositories"


def test_finished_groups_fill_merged_lately_and_the_charts(prws):
    from orch_pull_requests import store

    add_ticket(prws, "t_aaaaa1", [{"url": PR.format(n)} for n in (1, 2, 3, 4, 9)])
    now = _t("2026-11-19T12:00:00Z")
    poll.once(
        prws,
        fetch=FakeGitHub(
            {
                "acme/app": [
                    gql_pr(9, created="2026-11-19T08:00:00Z"),
                    gql_pr(1, state="MERGED", created="2026-11-18T08:00:00Z", merged="2026-11-19T10:00:00Z"),
                ]
            }
        ),
    )
    _queue(prws, 1, 2, 3, 4)
    rows = store.read(prws)
    for r, (state, taken, ended) in zip(
        rows,
        [
            ("merged", "2026-11-19T09:40:00Z", "2026-11-19T10:00:00Z"),  # a group of two, both merged
            ("merged", "2026-11-19T09:40:00Z", "2026-11-19T10:00:00Z"),
            ("out", "2026-11-19T10:10:00Z", "2026-11-19T10:22:00Z"),  # alone, sent back
            ("out", "2026-11-19T10:25:00Z", "2026-11-19T10:30:00Z"),  # taken out by someone while checked
        ],
        strict=True,
    ):
        r.update(state=state, ended=ended, added="2026-11-19T09:00:00Z")
        if taken:
            r["taken"] = taken
        r["why"] = "taken out by human:x" if r["number"] == 4 else "checks failed"
    (store.folder(prws) / "queue.json").write_text(json.dumps({"entries": rows}), encoding="utf-8")
    v = valid(view.build(prws, running=True, queue_alive=True, now=now, tz=UTC))
    (flow,) = [b for b in v["blocks"] if b["type"] == "flow"]
    check, line, done = flow["stages"]
    assert check["value"] == "Nothing right now" and line["value"] == "Nobody waiting"
    assert done["value"] == "1 of 2 groups" and done["text"] == "1 sent back · typical wait 1 h 11 min"
    assert [b["tone"] for b in done["bars"]] == ["good", "bad"]
    assert done["bars"][0] == {"value": 2, "tone": "good", "hint": "10:00: group of 2, merged after 20 min"}
    assert [c["label"] for c in done["items"]] == ["#1", "#2"]
    first, second = [b for b in v["blocks"] if b["type"] == "chart"]
    assert first["labels"][-1] == "Today" and first["labels"][0] == "6 Nov" and len(first["labels"]) == 14
    opened, merged = (s["values"] for s in first["series"])
    assert opened[-2:] == [1, 1]  # #1 opened yesterday, #9 today
    assert merged[-1] == 2  # #1 by GitHub's date, #2 by the queue's (counted once each)
    q_merged, q_back = (s["values"] for s in second["series"])
    assert q_merged[-1] == 2 and q_back[-1] == 1  # the one taken out by someone is not "sent back"
    assert len(done["bars"]) == 2  # nor a group of its own
    assert second["stacked"] and second["meta"] == "typical wait today 1 h 0 min"


def test_with_no_open_pull_request_the_queues_recent_work_still_shows(prws):
    from orch_pull_requests import store

    now = _t("2026-11-19T12:00:00Z")
    _queue(prws, 1)
    rows = store.read(prws)
    rows[0].update(
        state="merged",
        added="2026-11-19T09:00:00Z",
        taken="2026-11-19T09:10:00Z",
        ended="2026-11-19T09:30:00Z",
    )
    (store.folder(prws) / "queue.json").write_text(json.dumps({"entries": rows}), encoding="utf-8")
    v = valid(view.build(prws, running=True, queue_alive=True, now=now, tz=UTC))
    assert [b["type"] for b in v["blocks"]] == ["flow", "chart", "chart", "list", "footnote"]
    assert v["blocks"][0]["stages"][2]["value"] == "1 of 1 group"
    assert v["blocks"][3]["empty"]["title"] == "No pull requests yet"


def test_a_queued_pull_request_with_failed_checks_is_in_the_queue_not_failed(prws):
    add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1)}])
    poll.once(prws, fetch=FakeGitHub({"acme/app": [gql_pr(1, merge="BLOCKED", checks=fail_run("lint"))]}))
    _queue(prws, 1, ticket="t_aaaaa1")
    v = valid(view.build(prws, running=True, queue_alive=True))
    (table,) = [b for b in v["blocks"] if b["type"] == "table"]
    cells = table["rows"][0]["cells"]
    assert cells["state"] == "In line" and "1st in line" in cells["why"]
    assert "failed" not in cells["why"].lower()


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
    check = v["blocks"][0]["stages"][0]
    assert check["tone"] == "warn" and check["text"].startswith("The merge queue is not running")


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
    assert table["rows"][0]["cells"]["why"] == "1st in line. The group #500 was not merged"


def test_cut_ends_at_a_whole_word_with_an_ellipsis():
    assert view._cut("short", 20) == "short"
    got = view._cut("Show the invoice number on the PDF (weeks as rows, Latin)", 40)
    assert got.endswith("…") and len(got) <= 40
    assert got == "Show the invoice number on the PDF (weeks…" or not got[:-1].endswith(" ")
    assert view._cut("one two three", 8) == "one two…"
    assert view._cut("abcdefghijkl", 5) == "abcd…"  # one long word: nothing better to do


def test_a_conflict_without_a_ticket_says_to_make_one():
    assert "Open the ticket" in view._pr_state({"status": "conflict"})[2]
    note = view._pr_state({"status": "conflict"}, has_ticket=False)[2]
    assert "make a ticket" in note and "Open the ticket" not in note


def test_failed_checks_read_as_one_sentence():
    # report r-1127-0539-ws-3: 'lint, light failed.' read like one check called 'lint, light'
    w = view._failed_what
    assert w({}) == "A check failed."
    assert w({"failed_names": ["lint"], "failed": 1}) == "lint failed."
    assert w({"failed_names": ["lint", "light"], "failed": 2}) == "2 checks failed: lint and light."
    names = ["a", "b", "c", "d", "e"]
    assert w({"failed_names": names, "failed": 7}) == "7 checks failed: a, b and 5 more."
    assert w({"failed_names": ["a", "b", "c"], "failed": 3}) == "3 checks failed: a, b and 1 more."

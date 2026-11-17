"""Merge when green: the per-ticket switch, tend (fake GitHub), the watcher service, the manifest and schema."""

from __future__ import annotations

import json
import tomllib
from importlib import resources
from pathlib import Path

import pytest

from orch_pull_requests import cli, runner, service, store, switch

REPO = "acme/app"
CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "addons" / "pull-requests" / "ext.schema.json"


def url(n: int) -> str:
    return f"https://github.com/{REPO}/pull/{n}"


class FakeGitHub:
    def __init__(self, prs: dict[int, dict]):
        self.prs, self.calls = prs, []

    def pr(self, u):
        n = int(u.rsplit("/", 1)[1])
        self.calls.append(n)
        p = self.prs.get(n)
        if p is None:
            return None
        return {"state": p.get("state", "OPEN"), "isDraft": p.get("isDraft", False),
                "baseRefName": p.get("base", "develop"), "reviewDecision": p.get("review", ""),
                "headRefOid": p.get("head", f"{n:040d}"), "number": n}  # fmt: skip

    def login(self):
        return "helper-bot"

    def own_checks_failed(self, u):
        return self.prs[int(u.rsplit("/", 1)[1])].get("failed", False)


def ticket(ws: Path, *prs: int, on: bool | None = True, status: str | None = None) -> str:
    from orch import tickets

    ext = {"pull-requests": {"merge_when_green": "on" if on else "off"}} if on is not None else None
    t = tickets.create(ws, "Change", "human:p", ext=ext)
    for n in prs:
        tickets.ref_add(ws, t["id"], url(n), "agent:t")
        if status:
            tickets.ref_set(ws, t["id"], url(n), status, "agent:t")
    return t["id"]


def tend(ws, gh, clock=lambda: 1000.0):
    return switch.tend(ws, gh, clock=clock, log=lambda s: None)


def queued(ws) -> list[tuple[int, str, str | None]]:
    return [(r["number"], r["state"], r.get("ticket")) for r in store.read(ws)]


# -- the switch -------------------------------------------------------------------------------------------
def test_switch_on_puts_ready_pull_requests_in_the_queue_once(ws):
    tid = ticket(ws, 1, 2)
    other = ticket(ws, 3, on=None)  # no switch: never queued
    ticket(ws, 4, on=False)
    gh = FakeGitHub({1: {}, 2: {}, 3: {}, 4: {}})
    got = tend(ws, gh)
    assert got["added"] == [url(1), url(2)]
    assert queued(ws) == [(1, "waiting", tid), (2, "waiting", tid)]
    assert all(r["by"] == switch.BY for r in store.read(ws))
    assert tend(ws, gh)["added"] == []  # already in line: not a second time
    assert len(store.read(ws)) == 2 and other


def test_a_pull_request_on_two_switched_on_tickets_is_queued_once(ws):
    both = {ticket(ws, 1), ticket(ws, 1)}
    got = tend(ws, FakeGitHub({1: {}}))
    [(n, state, tid)] = queued(ws)  # which ticket comes first depends on the random ticket ids
    assert got["added"] == [url(1)] and (n, state) == (1, "waiting") and tid in both


def test_the_runner_starts_when_something_was_queued(ws):
    ticket(ws, 1)
    started = []
    got = switch.tend(ws, FakeGitHub({1: {}}), log=lambda s: None, start=started.append)
    assert got["added"] == [url(1)] and started == [ws]
    assert switch.tend(ws, FakeGitHub({1: {}}), log=lambda s: None, start=started.append)["added"] == []
    assert started == [ws]  # nothing new: no second start


def test_never_a_draft_and_never_a_closed_or_merged_one(ws):
    ticket(ws, 1, 2, 3)
    ticket(ws, 5, status="merged")  # recorded merged on the ticket: not even looked at
    gh = FakeGitHub({1: {"isDraft": True}, 2: {"state": "CLOSED"}, 3: {"state": "MERGED"}, 5: {}})
    got = tend(ws, gh)
    assert got["added"] == [] and store.read(ws) == []
    assert dict(got["skipped"])[url(1)] == "a draft"
    assert 5 not in gh.calls
    gh.prs[1]["isDraft"] = False  # marked ready: goes in line now
    assert tend(ws, gh)["added"] == [url(1)]


def test_never_a_pull_request_a_person_merges_with_a_merge_card(ws, monkeypatch):
    ticket(ws, 1, 2)
    key = runner.pr_key(url(2).replace("acme/app", "Acme/App"))
    monkeypatch.setattr(runner, "merge_cards", lambda root: {key: "DM1-7"})
    gh = FakeGitHub({1: {}, 2: {}})
    got = tend(ws, gh)
    assert got["added"] == [url(1)]
    assert "Merge card on DM1-7" in dict(got["skipped"])[url(2)]
    assert 2 not in gh.calls  # not even read


def test_unreadable_tickets_queue_nothing(ws, monkeypatch):
    ticket(ws, 1)
    monkeypatch.setattr(runner, "merge_cards", lambda root: None)
    with pytest.raises(store.Refused):
        tend(ws, FakeGitHub({1: {}}))
    assert store.read(ws) == []


def test_switch_off_takes_its_waiting_entries_out_but_not_others(ws):
    from orch import tickets

    tid = ticket(ws, 1, 2)
    gh = FakeGitHub({1: {}, 2: {}})
    tend(ws, gh)
    store.set_state(ws, url(2), store.RUNNING, "in the group being checked")
    store.add(ws, url(7), tid, "agent:helper")  # a helper's own entry stays
    tickets.ext_set(ws, tid, "pull-requests", json.dumps({"merge_when_green": "off"}), "human:p")
    tickets.ref_add(ws, tid, url(7), "agent:t")
    got = tend(ws, gh)
    assert got["removed"] == [url(1)]
    assert queued(ws) == [(1, "out", tid), (2, "running", tid), (7, "waiting", tid)]


# -- a pull request that left the queue -------------------------------------------------------------------
def _leave(ws, n, why="Checks of it failed"):
    store.set_state(ws, url(n), store.OUT, why)


def test_left_the_queue_comes_back_with_a_new_commit_at_once(ws):
    ticket(ws, 1)
    gh = FakeGitHub({1: {}})
    tend(ws, gh, clock=lambda: 1000.0)
    _leave(ws, 1)
    assert tend(ws, gh, clock=lambda: 1060.0)["added"] == []  # same commit, a minute later: not again
    gh.prs[1]["head"] = "b" * 40
    assert tend(ws, gh, clock=lambda: 1120.0)["added"] == [url(1)]


def test_same_commit_is_tried_again_later_only_while_no_check_failed_and_at_most_three_times(ws):
    ticket(ws, 1)
    gh = FakeGitHub({1: {"failed": True}})
    now = [1000.0]
    clock = lambda: now[0]
    tend(ws, gh, clock=clock)
    _leave(ws, 1)
    now[0] += switch.RETRY_SECS + 1
    got = tend(ws, gh, clock=clock)
    assert got["added"] == [] and "check of this commit failed" in dict(got["skipped"])[url(1)]
    gh.prs[1]["failed"] = False  # a rerun passed (e.g. a cancelled job)
    for _ in range(switch.TRIES - 1):
        assert tend(ws, gh, clock=clock)["added"] == [url(1)]
        _leave(ws, 1, "no room in the write limit")
        now[0] += switch.RETRY_SECS + 1
    got = tend(ws, gh, clock=clock)
    assert got["added"] == [] and "3 times" in dict(got["skipped"])[url(1)]


def test_switch_off_and_on_starts_over(ws):
    from orch import tickets

    tid = ticket(ws, 1)
    gh = FakeGitHub({1: {}})
    tend(ws, gh)
    _leave(ws, 1)
    tickets.ext_set(ws, tid, "pull-requests", json.dumps({"merge_when_green": "off"}), "human:p")
    tend(ws, gh)
    tickets.ext_set(ws, tid, "pull-requests", json.dumps({"merge_when_green": "on"}), "human:p")
    assert tend(ws, gh)["added"] == [url(1)]


def test_the_merge_itself_is_the_queue_runners_through_the_core_waiter(ws):
    """The switch only queues (through runner.admit, with the login); the hardened runner merges a single pull
    request with the core waiter (only the checked commit, write limit inside). Same fakes as the queue tests."""
    import test_queue

    ticket(ws, 1)
    gh = test_queue.FakeGitHub({1: {}})
    assert tend(ws, gh)["added"] == [url(1)]
    r, calls = test_queue.make(ws, gh, test_queue.FakeGit())
    r.run()
    assert calls == [url(1)] and queued(ws)[0][1] == "merged"


# -- the watcher service ----------------------------------------------------------------------------------
def test_watch_runs_tend_every_round_and_one_bad_round_does_not_end_it(ws, monkeypatch):
    monkeypatch.setattr(service, "still_on", lambda root: True)
    seen, naps = [], []

    def tend_once():
        seen.append(1)
        if len(seen) == 1:
            raise RuntimeError("GitHub hiccup")

    assert service.watch(ws, tend_once, sleep=naps.append, rounds=3, log=lambda s: None) == 0
    assert len(seen) == 3 and naps == [service.EVERY_SECS] * 2
    assert service.running_pid(ws) is None  # the lock is given back


def test_watch_ends_when_the_add_on_is_turned_off_and_only_one_runs(ws, monkeypatch):
    monkeypatch.setattr(service, "still_on", lambda root: False)
    ran = []
    assert service.watch(ws, lambda: ran.append(1), sleep=lambda s: None, log=lambda s: None) == 0
    assert ran == []
    lock = service._lock(ws)
    lock.mkdir(parents=True)
    from orch import procs

    (lock / "owner").write_text(procs.own_token(), encoding="utf-8")  # a living watcher (this process)
    monkeypatch.setattr(service, "still_on", lambda root: True)
    said = []
    assert service.watch(ws, lambda: ran.append(1), sleep=lambda s: None, rounds=1, log=said.append) == 0
    assert ran == [] and "runs already" in said[0]
    import os

    assert service.running_pid(ws) == os.getpid()


def test_stop_without_a_watcher_signals_nothing(ws, capsys):
    lock = service._lock(ws)
    lock.mkdir(parents=True)
    (lock / "owner").write_text("999999 2001-01-01T00:00:00Z", encoding="utf-8")  # dead holder
    assert service.stop(ws) is False
    assert cli.main(["status", "--json"]) == 1
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {"running": False}
    assert cli.main(["stop", "--json"]) == 0
    assert json.loads(capsys.readouterr().out.strip()) == {"stopped": False}


# -- manifest and schema ----------------------------------------------------------------------------------
def test_manifest_declares_the_switch_and_the_service():
    m = tomllib.loads((resources.files("orch_pull_requests") / "orch-addon.toml").read_text(encoding="utf-8"))
    assert m["background"] is True and m["ticket_ext"] == "ext.schema.json"
    assert m["ticket_fields"] == {"section": "Pull requests", "schema": "ext.schema.json"}
    assert "recommended" not in m  # off until someone turns it on
    assert not m.get("ticket_ext_inert")  # it starts merges: synced changes wait for a person


def test_schema_copy_is_byte_identical_and_the_field_is_a_choice_off_by_default():
    ours = (resources.files("orch_pull_requests") / "ext.schema.json").read_bytes()
    assert ours == CONTRACT.read_bytes()
    from orch import fields

    [f] = fields.field_list(json.loads(ours))
    assert f["key"] == "merge_when_green" and f["title"] == "Merge when green" and f["type"] == "choice"
    assert [o["label"] for o in f["options"]] == ["Off", "On"] and not f["read_only"]
    assert not switch.is_on({}) and not switch.is_on({"ext": {"pull-requests": {"merge_when_green": "off"}}})


def test_core_accepts_the_manifest_and_a_person_sets_the_switch_like_orch_ticket_set(ws):
    """What `orch ticket set <ticket> pull-requests.merge_when_green on` does, with this add-on's real manifest."""
    from orch import addons, fields, tickets

    m = addons.parse_manifest(Path(str(resources.files("orch_pull_requests") / "orch-addon.toml")))
    assert m["background"] is True
    sec = fields.section(m)
    assert sec["section"] == "Pull requests"
    [f] = sec["fields"]
    schema = json.loads(CONTRACT.read_text(encoding="utf-8"))
    prop = schema["properties"]["merge_when_green"]
    assert [fields.parse_value(f, v, prop) for v in ("On", "on", "off")] == ["on", "on", "off"]
    with pytest.raises(Exception, match="Pick one of: Off, On"):
        fields.parse_value(f, "maybe", prop)
    tid = ticket(ws, on=None)
    t = tickets.ext_set(
        ws, tid, "pull-requests", json.dumps({"merge_when_green": "on"}), "human:p", None, schema
    )
    assert switch.is_on(t)
    with pytest.raises(Exception):  # noqa: B017 - the core refuses what the schema does not allow
        tickets.ext_set(ws, tid, "pull-requests", json.dumps({"merge": "yes"}), "human:p", None, schema)


def test_start_says_plainly_when_the_add_on_is_not_on(ws, monkeypatch):
    monkeypatch.setattr(service, "still_on", lambda root: False)
    with pytest.raises(store.Refused, match="not on here"):
        service.start(ws)
    assert not (store.folder(ws) / "watch.log").exists()  # nothing was started


def test_the_queue_gate_decides_base_branch_reviews_and_login(ws):
    """runner.admit (ORCH-181): never into main, never with changes requested; the entry carries base and login."""
    ticket(ws, 1, 2, 3)
    gh = FakeGitHub({1: {}, 2: {"base": "main"}, 3: {"review": "CHANGES_REQUESTED"}})
    got = tend(ws, gh)
    assert got["added"] == [url(1)]
    why = dict(got["skipped"])
    assert "merges only into develop" in why[url(2)] and "not queued" in why[url(3)]
    [row] = store.read(ws)
    assert (row["base"], row["login"]) == ("develop", "helper-bot")

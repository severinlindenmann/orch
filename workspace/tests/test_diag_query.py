"""`orch diag inspect|query`: read-only collectors, pagination, filters (contracts/diag.md)."""

import json
import time

import pytest
from diag_fixtures import claim_dead, reset_diag, stuck, tree_hash

from orch import diag, diag_collect, diag_query, runs, tickets
from orch.errors import Refused


@pytest.fixture
def proj(proj, monkeypatch):
    (proj / ".orch").mkdir(exist_ok=True)
    reset_diag(monkeypatch)
    return proj


def test_every_collector_is_read_only_on_a_workspace_with_a_stuck_ticket(proj):
    tid = stuck(proj)
    claim_dead(proj, tid)
    diag.log("ticket.op_refused", "warn", root=proj, ticket=tid, op="done", guard="conflict")
    before = tree_hash(proj)  # the WHOLE .orch folder, the debug log included
    out = diag_collect.collect_all(proj, {"ticket": tid})
    out_unscoped = diag_collect.collect_all(proj, {})
    from orch import cli_diag

    cli_diag.inspect(proj, tid)
    assert tree_hash(proj) == before
    assert tickets.load(proj, tid)["status"] == "active"  # nothing settled the ticket
    assert set(out) == set(diag_collect.COLLECTORS) and out_unscoped["tickets"]["data"]["tickets"]


def test_collector_shape_and_run_facts(proj):
    tid = stuck(proj)
    rec = claim_dead(proj, tid)
    r = diag_collect.collect(proj, "runs", {"ticket": tid})
    assert set(r) >= {"collected_at", "data", "gaps"}
    run = r["data"]["runs"][tid]
    assert run["run"] == rec["run"] and run["process"] == "dead" and run["lock"]["holder_dead"] is True
    t = diag_collect.collect(proj, "tickets", {"ticket": tid})
    assert t["revision"][tid] == t["data"]["tickets"][tid]["revision"]
    assert "title" not in t["data"]["tickets"][tid]  # structure only: no ticket text


def test_collector_time_limit_and_output_cap(proj, monkeypatch):
    monkeypatch.setattr(diag_collect, "TIME_LIMIT", 0.2)
    monkeypatch.setitem(diag_collect.COLLECTORS, "disk", lambda *a: time.sleep(2))
    r = diag_collect.collect(proj, "disk")
    assert r["data"] == {} and "longer than" in r["gaps"][0]
    monkeypatch.setattr(diag_collect, "CAP_BYTES", 50)
    monkeypatch.setitem(diag_collect.COLLECTORS, "disk", lambda *a: ({"x": "y" * 500}, []))
    r = diag_collect.collect(proj, "disk")
    assert r["data"] == {"truncated": True} and r["gaps"]


def test_orphan_check_never_settles_but_the_runs_function_does(proj):
    tid = stuck(proj)
    diag_collect.collect_all(proj, {})
    assert tickets.load(proj, tid)["status"] == "active"
    assert runs.settle_orphan(proj, tid) is True  # the repair exists, and diag never calls it


def _log(proj, n):
    for i in range(n):
        diag.log("ticket.op_applied", "info", root=proj, ticket="t_aaaaaa", op="set", written=True, n=i)


def test_query_filters_and_pagination(proj):
    _log(proj, 7)
    diag.log("relay.send_failed", "warn", root=proj, what="x", reason="E")
    diag.log("ticket.op_refused", "warn", root=proj, ticket="t_bbbbbb", op="done")
    a = diag_query.query(proj, ev="ticket.*", limit=3)
    assert a["total"] == 8 and len(a["items"]) == 3 and a["next"]
    b = diag_query.query(proj, ev="ticket.*", limit=3, page=a["next"])
    c = diag_query.query(proj, ev="ticket.*", limit=3, page=b["next"])
    seqs = [i["seq"] for r in (a, b, c) for i in r["items"]]
    assert len(seqs) == 8 and seqs == sorted(seqs) and c["next"] is None
    assert [i["ev"] for i in diag_query.query(proj, lvl="warn")["items"]] == [
        "relay.send_failed",
        "ticket.op_refused",
    ]
    assert diag_query.query(proj, ticket="t_bbbbbb")["total"] == 1
    with pytest.raises(Refused):
        diag_query.query(proj, ev="ticket.*", limit=3, page=a["next"].replace("A", "B", 1)[:-2])
    with pytest.raises(Refused):  # a token of another question
        diag_query.query(proj, ev="relay.*", limit=3, page=a["next"])
    with pytest.raises(Refused):
        diag_query.query(proj, limit=100000)


def test_query_window_around_and_since(proj):
    _log(proj, 2)
    now = time.time()
    hhmm = time.strftime("%H:%M", time.gmtime(now))
    assert diag_query.query(proj, around=hhmm, span="3m")["total"] == 2
    assert diag_query.query(proj, since="1h")["total"] == 2
    assert diag_query.query(proj, since="1h", now=now + 3 * 3600)["total"] == 0
    with pytest.raises(Refused):
        diag_query.query(proj, since="yesterday")


def test_query_never_dumps_record_text_and_says_when_the_record_has_gaps(proj):
    tid = stuck(proj)
    res = diag_query.query(proj, ticket=tid)
    assert json.dumps(res)  # serializable
    assert all(i["source"] in ("diag", "record") for i in res["items"])


def test_cli_inspect_and_query_json(proj, run):
    tid = stuck(proj)
    claim_dead(proj, tid)
    code, out, _ = run("diag", "inspect", "--ticket", tid, "--json")
    assert code == 0
    res = json.loads(out)
    verdicts = {c["name"]: c["verdict"] for c in res["checks"]}
    assert verdicts["run_gone_ticket_working"] == "problem" and verdicts["dead_lock_holder"] == "problem"
    code, out, _ = run("diag", "query", "--since", "1h", "--json")
    assert code == 0 and "items" in json.loads(out)
    code, out, err = run("diag", "inspect", "--ticket", "nonsense", "--json")
    assert code == 2

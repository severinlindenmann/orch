"""`orch pull-requests view|poll|act refresh`, the watcher round, the manifest and the core merge (ORCH-165)."""

import json
import re
from pathlib import Path

import jsonschema
from prpage_util import REPO, FakeGitHub, add_ticket, gql_pr

from orch_pull_requests import cli, poll, prstate

PKG = Path(__file__).resolve().parents[1] / "src" / "orch_pull_requests"
PR = "https://github.com/acme/app/pull/{}"


def main(root, capsys, monkeypatch, *argv):
    monkeypatch.chdir(root)
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def schema() -> dict:
    return json.loads((PKG / "ext.schema.json").read_text(encoding="utf-8"))


def test_act_refresh_cached_prints_one_answer(prws, capsys, monkeypatch):
    add_ticket(prws, "t_aaaaa1", [{"url": PR.format(1)}])
    poll.once(prws, fetch=FakeGitHub({"acme/app": [gql_pr(1)]}))
    monkeypatch.setenv(poll.CACHED_ENV, "1")
    # the core calls it exactly like this (contracts/addon-manifest.md, Act)
    code, out, _ = main(
        prws, capsys, monkeypatch, "act", "refresh", "--by", "human:anna", "--json", "--", "DM-1"
    )
    res = json.loads(out)
    assert code == 0 and res["ticket"] == "t_aaaaa1" and res["refs"][0]["status"] == "ready to merge"
    jsonschema.validate(res["ext"]["pull-requests"], schema())


def test_act_refresh_unknown_ticket(prws, capsys, monkeypatch):
    code, out, _ = main(prws, capsys, monkeypatch, "act", "refresh", "--json", "--", "t_nope00")
    assert code == 2 and "no ticket" in json.loads(out)["error"]


def test_view_and_poll_without_links(prws, capsys, monkeypatch):
    code, out, _ = main(prws, capsys, monkeypatch, "view", "--json")
    assert code == 0 and json.loads(out)["schema"] == "orch.addon-view/1"
    code, out, _ = main(prws, capsys, monkeypatch, "poll", "--json")
    assert code == 0 and json.loads(out)["repos"] == []


def test_a_watcher_round_reads_then_tends(prws, monkeypatch):
    order = []
    monkeypatch.setattr(poll, "once", lambda root: order.append("read") or {"refreshed": [], "errors": {}})
    monkeypatch.setattr(cli, "_tend", lambda root: order.append("tend"))
    cli._round(prws)

    def boom(root):
        raise RuntimeError("offline")

    monkeypatch.setattr(poll, "once", boom)
    cli._round(prws)  # a failed read never stops Merge when green
    assert order == ["read", "tend", "tend"]


def test_manifest_is_valid_for_the_core():
    from orch import addons

    m = addons.folder_manifest(PKG.parents[1])
    assert m["name"] == "pull-requests" and m["background"] is True and "refresh" in m["acts"]
    assert m["dashboard"]["label"] == "Pull requests" and len(m["description"]) <= 120
    (link,) = m["ticket_links"]
    assert set(link["statuses"]) == set(prstate.STATUS_WORDS)
    for word in prstate.STATUS_WORDS:
        assert re.fullmatch(r"[a-z0-9][a-z0-9 -]{0,23}", word)
    contract = REPO / "contracts" / "addons" / "pull-requests" / "ext.schema.json"
    assert contract.read_bytes() == (PKG / "ext.schema.json").read_bytes()


def test_the_core_accepts_the_refresh_answer(tmp_path):
    """What `act refresh` prints merges into a real ticket through the core (statuses, title, ext schema next
    to the Merge when green switch), and the same answer again changes nothing (no history line per minute)."""
    from orch import tickets

    root = tmp_path / "real"
    (root / ".orch" / "tickets").mkdir(parents=True)
    t = tickets.create(
        root, "Invoice export", "human:anna", ext={"pull-requests": {"merge_when_green": "on"}}
    )
    tickets.ref_add(root, t["id"], PR.format(1), "human:anna")
    t = tickets.load(root, t["id"])
    data = poll.load(root)
    poll.read(root, {"acme/app": [1]}, data, FakeGitHub({"acme/app": [gql_pr(1, merge="BEHIND")]}))
    res = poll.answer(t, data)
    t2, changes = tickets.merge_refresh(root, t["id"], "pull-requests", res, "agent:pull-requests", schema())
    assert {c["field"] for c in changes} >= {"status", "checks", "merge"}
    link = next(r for r in t2["refs"] if r.get("url") == PR.format(1))
    assert link["status"] == "behind" and link["title"] == "Change 1"
    assert t2["ext"]["pull-requests"] == {
        "merge_when_green": "on",
        "pr": "#1",
        "checks": "passed",
        "merge": "behind",
    }
    assert not poll.differs(t2, poll.answer(t2, data))
    again = tickets.merge_refresh(
        root, t["id"], "pull-requests", poll.answer(t2, data), "agent:pull-requests", schema()
    )
    assert again[1] == []


def test_state_file_is_never_followed_through_a_link(prws, tmp_path):
    import os

    import pytest

    outside = tmp_path / "outside"
    outside.mkdir()
    (prws / ".orch" / "addons").mkdir()
    os.symlink(outside, prws / ".orch" / "addons" / "pull-requests")
    with pytest.raises(OSError, match="linked folder"):
        poll.save(prws, poll.load(prws))
    assert list(outside.iterdir()) == []
    assert poll.load(prws)["prs"] == {}  # unreadable through a link: starts empty

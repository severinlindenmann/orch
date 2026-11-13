import json
import os
import subprocess
import tomllib
from pathlib import Path

import jsonschema
import pytest
from conftest import CONTRACTS

from orch_factory import authority
from orch_factory.store import Refused, Store, digest


def core(ws, *args):
    result = subprocess.run(
        [os.environ["ORCH_BIN"], *args, "--json"], cwd=ws, capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def setup(run, proposal):
    order = run("idea", "Booking page")["order"]
    return order, run("propose", order, "--file", "-", data=proposal)


def test_idea_draft_propose(ws, run, proposal):
    idea = run("idea", "Booking page")
    order = idea["order"]
    assert Path(idea["draft"]).read_bytes() == b""
    draft = run("draft", order, "--file", "-", data=b"# Approved draft\r\n")
    assert Path(draft["draft"]).name == "v2.md"
    assert Path(draft["draft"]).read_bytes() == b"# Approved draft\r\n"
    proposed = run("propose", order, "--file", "-", data=proposal)
    store = Store(ws)
    assert store.read(proposed["file"]) == proposal
    assert proposed["hash"] == digest(proposal)
    rows = store.journal_read()
    assert [r["type"] for r in rows] == ["proposed", "asked"]
    t = core(ws, "ticket", "show", order)
    assert t["ext"]["factory"]["draft"] == 2
    assert t["ext"]["factory"]["line"][-1] == {"stage": "ship", "stop": True, "state": "todo"}
    q = t["questions"][0]
    assert q["options"] == ["Start", "Edit", "Not now"]
    assert "Online booking page" in q["text"] and "target $12" in q["text"]
    assert rows[-1]["q"] == q["id"]
    calls = [json.loads(x)["args"] for x in (ws / "calls.jsonl").read_text().splitlines()]
    ask = next(i for i, c in enumerate(calls) if c[0] == "ask")
    assert calls[ask - 1][:2] == ["ext", "set"]
    assert run("show", order)["started"] is False
    assert run("list")[0]["order"] == order


def test_idempotent(ws, run, proposal):
    order, first = setup(run, proposal)
    before = Store(ws).read("journal.jsonl")
    assert run("propose", order, "--file", "-", data=proposal) == first
    assert Store(ws).read("journal.jsonl") == before
    assert len(core(ws, "ticket", "show", order)["questions"]) == 1


@pytest.mark.parametrize("by,started", [("human:anna", True), ("agent:factory", False)])
def test_start_authority(ws, run, proposal, by, started):
    order, p = setup(run, proposal)
    core(ws, "answer", order, p["question"], "Start", "--by", by)
    assert authority.started(order, ws) is started
    assert run("show", order)["started"] is started
    run("propose", order, "--file", "-", data=proposal + b" ", code=2 if started else 0)
    if not started:
        assert any(
            "ignored the agent answer" in h["text"] for h in core(ws, "ticket", "show", order)["history"]
        )


def test_unrecorded_question_has_no_authority(ws, run, proposal):
    order = run("idea", "Booking")["order"]
    q = core(
        ws,
        "ask",
        order,
        "Start?",
        "--kind",
        "factory:start",
        "--option",
        "Start",
        "--action",
        json.dumps({"order": order, "file": "proposals/fake.json", "hash": "a" * 64}),
    )
    core(ws, "answer", order, q["id"], "Start", "--by", "human:anna")
    assert not authority.started(order, ws)
    run("propose", order, "--file", "-", data=proposal)


def test_superseded_answer_does_not_start(ws, run, proposal):
    order, old = setup(run, proposal)
    new = run("propose", order, "--file", "-", data=proposal + b"\n")
    assert new["question"] != old["question"]
    core(ws, "answer", order, old["question"], "Start", "--by", "human:anna")
    assert not authority.started(order, ws)
    assert [q["id"] for q in run("show", order)["questions"]] == [new["question"]]
    assert "superseded" in [r["type"] for r in Store(ws).journal_read()]


@pytest.mark.parametrize("change", ["ship", "stage", "proves", "schema"])
def test_invalid_proposals(ws, run, proposal, change):
    order = run("idea", "Booking")["order"]
    p = json.loads(proposal)
    if change == "ship":
        p["line"][-1]["stop"] = False
    elif change == "stage":
        p["tasks"][0]["stage"] = "missing"
    elif change == "proves":
        p["tasks"][0]["proves"] = [len(p["done_means"])]
    else:
        p["unexpected"] = True
    run("propose", order, "--file", "-", data=json.dumps(p).encode(), code=2)
    assert Store(ws).journal_read() == []


@pytest.mark.parametrize("failure", ["fail-ext", "fail-ask"])
def test_retry_interrupted_proposal(ws, run, proposal, failure):
    order = run("idea", "Booking")["order"]
    (ws / failure).touch()
    run("propose", order, "--file", "-", data=proposal, code=2)
    (ws / failure).unlink()
    p = run("propose", order, "--file", "-", data=proposal)
    assert p["proposal"] == 1
    assert [r["type"] for r in Store(ws).journal_read()] == ["proposed", "asked"]


def test_tampered_file_and_action_refused(ws, run, proposal):
    order, p = setup(run, proposal)
    core(ws, "answer", order, p["question"], "Start", "--by", "human:anna")
    Store(ws).path(p["file"]).write_bytes(proposal + b" ")
    assert run("show", order, code=2)["code"] == "tampered"


def test_view_and_needs(ws, run, proposal):
    order, p = setup(run, proposal)
    for command, schema in (("view", "addon-view"), ("needs", "needs")):
        jsonschema.validate(
            run(command),
            json.loads((CONTRACTS / f"{schema}.schema.json").read_text()),
            format_checker=jsonschema.FormatChecker(),
        )
    blocks = run("view")["blocks"]
    assert blocks[0]["value"] == 1 and blocks[4]["items"][0]["link"] == order
    core(ws, "answer", order, p["question"], "Start", "--by", "human:anna")
    blocks = run("view")["blocks"]
    assert blocks[0]["value"] == 0 and blocks[2]["value"] == 1
    assert run("needs") == []


def test_manifest_and_schema_copies():
    import orch_factory

    package = Path(orch_factory.__file__).parent
    for name in ("ext", "proposal"):
        assert (package / f"{name}.schema.json").read_bytes() == (
            CONTRACTS / "addons/factory" / f"{name}.schema.json"
        ).read_bytes()
    jsonschema.validate(
        tomllib.loads((package / "orch-addon.toml").read_text()),
        json.loads((CONTRACTS / "addon-manifest.schema.json").read_text()),
    )


def test_storage_refuses_links_and_invalid_journal(ws, tmp_path):
    store = Store(ws)
    with store.locked():
        with pytest.raises(Refused):
            store.journal_append({"type": "made-up", "order": "t_abc123"})
        outside = tmp_path / "outside"
        outside.mkdir()
        store.path("drafts").rmdir()
        store.path("drafts").symlink_to(outside, target_is_directory=True)
        with pytest.raises(Refused):
            store.write("drafts/escape.md", b"no")
        assert not list(outside.iterdir())
    with pytest.raises(Refused):
        store.read("../other")


@pytest.mark.parametrize("change", ["action", "missing", "stage"])
def test_authority_cache_and_question_mismatch(ws, run, proposal, change):
    order, _ = setup(run, proposal)
    path = ws / "fake-tickets" / f"{order}.json"
    ticket = json.loads(path.read_text())
    if change == "action":
        ticket["questions"][0]["action"]["hash"] = "0" * 64
    elif change == "missing":
        ticket["questions"] = []
    else:
        ticket["ext"]["factory"]["stage"] = "running"
    path.write_text(json.dumps(ticket))
    assert run("propose", order, "--file", "-", data=proposal, code=2)["code"] in ("tampered", "conflict")
    assert len(list(Store(ws).path(f"proposals/{order}").iterdir())) == 1


def test_view_shipped_week_and_reads_do_not_write(ws, run, proposal):
    first, _ = setup(run, proposal)
    second, _ = setup(run, proposal)
    store = Store(ws)
    with store.locked():
        store.journal_append({"type": "shipped", "order": first})
        store.journal_append({"type": "shipped", "order": second, "at": "2000-01-01T00:00:00Z"})
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in store.base.rglob("*") if p.is_file()}
    view = run("view")
    assert view["blocks"][3]["value"] == 1
    shipped = next(b for b in view["blocks"] if b["type"] == "list" and b["title"] == "Shipped this week")
    assert [x["link"] for x in shipped["items"]] == [first]
    run("show", first)
    run("list")
    run("needs")
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before} == before


def test_file_input_and_argument_refusals(ws, run, tmp_path):
    source = tmp_path / "draft.md"
    source.write_bytes(b"An idea\r\n")
    result = run("idea", "An idea", "--file", str(source))
    assert Path(result["draft"]).read_bytes() == source.read_bytes()
    run("draft", result["order"], code=2)
    run("propose", result["order"], "--file", "-", data=b"not json", code=2)


def test_storage_journal_symlink_and_partial_line(ws, tmp_path):
    store = Store(ws)
    with store.locked():
        external = tmp_path / "external.jsonl"
        external.write_bytes(b"")
        store.path("journal.jsonl").symlink_to(external)
        with pytest.raises(Refused):
            store.journal_read()
        (store.base / "journal.jsonl").unlink()
        store.write("journal.jsonl", b'{"type":')
        with pytest.raises(Refused):
            store.journal_read()


def test_question_text_must_match_frozen_proposal(ws, run, proposal):
    """The owner must have seen Factory's own rendering; edited question text has no authority."""
    order, p = setup(run, proposal)
    path = ws / "fake-tickets" / f"{order}.json"
    ticket = json.loads(path.read_text())
    for q in ticket["questions"]:
        if q["id"] == p["question"]:
            q["text"] = "Start “Fix a typo”? ~5 min."
    path.write_text(json.dumps(ticket))
    core(ws, "answer", order, p["question"], "Start", "--by", "human:anna")
    assert run("show", order, code=2)["code"] == "tampered"

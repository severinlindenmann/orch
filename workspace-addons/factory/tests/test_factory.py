import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import jsonschema
import pytest
from conftest import CONTRACTS

from orch_factory import authority, commands
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


@pytest.mark.parametrize("what", ["proposal", "autopilot", "change", "stop"])
def test_schema_command_prints_the_contract(run, what):
    out = run("schema", what)
    contract = json.loads((CONTRACTS / "addons/factory/proposal.schema.json").read_text())
    assert out["$ref"] == f"#/$defs/{what}" and out["$defs"] == contract["$defs"]
    assert "oneOf" not in out
    jsonschema.Draft202012Validator.check_schema(out)


def test_schema_default_and_unknown(run):
    assert run("schema")["$ref"] == "#/$defs/proposal"
    assert run("schema", "nope", code=2)["code"] == "invalid"


@pytest.mark.parametrize("command", ["propose", "autopilot", "change", "stop"])
def test_help_lists_the_fields(command):
    import sys

    out = subprocess.run(
        [sys.executable, "-m", "orch_factory", command, "--help"], capture_output=True, text=True, check=True
    ).stdout
    assert (
        "required:" in out and f"orch factory schema {command if command != 'propose' else 'proposal'}" in out
    )


def test_skill_names_the_schema_command_and_steps():
    import orch_factory

    text = (Path(orch_factory.__file__).parent / "skills/orch-factory/SKILL.md").read_text()
    assert "orch factory schema proposal" in text and "propose --help" not in text
    assert "`resume`" in text and "`done`" in text


def test_idea_adopts_a_ticket_made_from_chat(ws, run, proposal):
    """The owner made a plain ticket from Chat while asking for a Factory run: the helper turns it into the order."""
    plain = core(ws, "ticket", "new", "Booking page from Chat")
    path = ws / "fake-tickets" / f"{plain['id']}.json"
    t = json.loads(path.read_text())
    t["note"] = "You: plan it as a factory run with one stop"
    path.write_text(json.dumps(t))
    r = run("idea", "--ticket", plain["id"])
    assert r["order"] == plain["id"] and r["adopted"] is True
    assert (
        Store(ws).path(f"drafts/{plain['id']}/v1.md").read_text()
        == "You: plan it as a factory run with one stop"
    )
    assert run("idea", "--ticket", plain["id"])["adopted"] is False  # already an order: same answer
    p = run("propose", plain["id"], "--file", "-", data=proposal)
    assert p["order"] == plain["id"] and run("show", plain["id"])["proposal"] == 1


def test_idea_needs_a_title_or_a_ticket_and_refuses_finished_or_sub_tickets(ws, run):
    assert run("idea", code=2)["code"] == "invalid"
    assert run("idea", "Title", "--ticket", "t_000001", code=2)["code"] == "invalid"
    done = core(ws, "ticket", "new", "Done one")
    path = ws / "fake-tickets" / f"{done['id']}.json"
    t = json.loads(path.read_text())
    t["status"] = "done"
    path.write_text(json.dumps(t))
    assert run("idea", "--ticket", done["id"], code=2)["code"] == "invalid"
    child = core(ws, "ticket", "new", "Child", "--parent", done["id"])
    assert run("idea", "--ticket", child["id"], code=2)["code"] == "invalid"


def _act(ws, *args):
    """Exactly what the dashboard runs for a click: `orch factory act <verb> --by <actor> --json -- <target>`."""
    result = subprocess.run(
        [sys.executable, "-m", "orch_factory", "act", *args],
        cwd=ws,
        capture_output=True,
        check=False,
        env=os.environ,
        timeout=30,
    )
    return result.returncode, json.loads(result.stdout)


def test_act_idea_files_the_order_as_the_person_and_starts_the_agent(ws):
    code, r = _act(
        ws, "idea", "--by", "human:alex", "--json", "--", "A page with our  opening hours\nand a map"
    )
    assert code == 0 and r["started"] is True and r["text"].startswith("Idea saved.")
    t = json.loads((ws / "fake-tickets" / f"{r['order']}.json").read_text())
    assert t["title"] == "A page with our opening hours and a map"
    assert t["ext"]["factory"] == {
        "role": "order",
        "kind": "run",
        "stage": "draft",
        "draft": 1,
        "idea_box": True,
    }
    assert (
        Store(ws).path(f"drafts/{r['order']}/v1.md").read_text()
        == "A page with our opening hours and a map\n"
    )
    writes = [c for c in map(json.loads, (ws / "calls.jsonl").read_text().splitlines()) if c["by"]]
    assert writes and {c["by"] for c in writes} == {"human:alex"}  # ticket, ext and run: all the person's
    assert json.loads((ws / "runs.jsonl").read_text())["ticket"] == r["order"]
    # the start text: a neutral idea must read as a Factory order (draft, ask, wait), not as a task to build
    new = next(
        c
        for c in map(json.loads, (ws / "calls.jsonl").read_text().splitlines())
        if c["args"][:2] == ["ticket", "new"]
    )
    assert (
        f"--note={commands.ORDER_NOTE} The person's idea: A page with our opening hours and a map"
        in new["args"]
    )
    for words in ("Factory order", "orch factory draft", "Don't build it", "Plan the run"):
        assert words in commands.ORDER_NOTE


def test_act_idea_is_saved_when_no_agent_can_start_and_titles_are_cut(ws):
    (ws / "fail-run").write_text("")
    long = "-- " + "word " * 40
    code, r = _act(ws, "idea", "--by", "human:alex", "--json", "--", long)
    assert code == 0 and r["started"] is False and "Start your agent" in r["text"]
    title = json.loads((ws / "fake-tickets" / f"{r['order']}.json").read_text())["title"]
    assert title.startswith("word") and title.endswith("…") and len(title) <= 81


def test_act_idea_refuses_without_a_person_or_text(ws):
    for by in ([], ["--by", "agent:helper"], ["--by", "human:"]):
        code, r = _act(ws, "idea", *by, "--json", "--", "An idea")
        assert code == 2 and r["code"] == "refused"
    code, r = _act(ws, "idea", "--by", "human:alex", "--json", "--", "   ")
    assert code == 2 and r["code"] == "invalid"
    code, r = _act(ws, "idea", "--by", "human:alex", "--json", "--", "x" * 501)
    assert code == 2 and r["code"] == "invalid"
    code, r = _act(ws, "nope", "--by", "human:alex", "--json", "--", "An idea")
    assert code == 2
    assert not (ws / "fake-tickets").exists() or not list((ws / "fake-tickets").iterdir())


def test_store_opens_every_step_below_the_store_without_following_links(ws, tmp_path):
    """#681: read and write walk the folders with directory fds (O_NOFOLLOW at each step), so a link put in place of a
    folder or a file is refused; a missing file stays FileNotFoundError (callers rely on it)."""
    store = Store(ws)
    store.write("drafts/t_000001/v1.md", b"one")
    assert store.read("drafts/t_000001/v1.md") == b"one"
    with pytest.raises(FileNotFoundError):
        store.read("drafts/t_000001/v9.md")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "v1.md").write_bytes(b"not factory")
    (store.base / "drafts" / "t_000002").symlink_to(outside, target_is_directory=True)
    for call in (
        lambda: store.read("drafts/t_000002/v1.md"),
        lambda: store.write("drafts/t_000002/v2.md", b"x"),
    ):
        with pytest.raises(Refused):
            call()
    assert not (outside / "v2.md").exists()
    (store.base / "drafts" / "t_000001" / "v2.md").symlink_to(outside / "v1.md")
    with pytest.raises(Refused):
        store.read("drafts/t_000001/v2.md")
    store.write("drafts/t_000001/v1.md", b"one", frozen=True)  # the same bytes: fine
    with pytest.raises(Refused):
        store.write("drafts/t_000001/v1.md", b"two", frozen=True)
    assert not [p for p in (store.base / "drafts" / "t_000001").iterdir() if p.name.startswith(".new-")]


def test_store_read_of_a_fifo_is_refused_without_hanging(ws):
    store = Store(ws)
    store.write("drafts/t_000001/v1.md", b"one")
    os.mkfifo(store.base / "drafts" / "t_000001" / "v2.md")
    with pytest.raises(Refused, match="not a regular file"):
        store.read("drafts/t_000001/v2.md")


def test_act_idea_keeps_a_three_sentence_idea_whole_in_the_note(ws):
    idea = (
        "We want a booking page for our studio. It shows free slots for the next four weeks and "
        "lets a visitor pick one with a name and email. The owner gets a mail for every booking, "
        "and a visitor can cancel with a link."
    )
    assert len(idea) > 200
    code, r = _act(ws, "idea", "--by", "human:alex", "--json", "--", idea)
    assert code == 0
    t = json.loads((ws / "fake-tickets" / f"{r['order']}.json").read_text())
    assert len(t["title"]) <= 81 and t["title"] != idea
    assert idea in t["note"] and "Factory order" in t["note"]
    assert Store(ws).path(f"drafts/{r['order']}/v1.md").read_text() == idea + "\n"


def test_skill_asks_routine_choices_with_options_and_cleans_up_its_own_checks():
    import orch_factory

    text = (Path(orch_factory.__file__).parent / "skills/orch-factory/SKILL.md").read_text()
    # 49: the link lifetime is four buttons with a suggestion, not a typed answer
    assert (
        '--option "7 days" --option "30 days" --option "90 days" --option "Permanent" --recommend "7 days"'
        in text
    )
    # 51: the check data of the ship step is removed before the hand-over
    assert "remove\neverything you created only to check the live result" in text
    # 50: plurals in built apps
    assert '"1 point", "2 points", never "1 pts"' in text
    # 43: draft questions are asked as ticket questions, not listed in the draft
    assert "Open questions do NOT go into the draft as a list" in text


def test_skill_tells_the_manager_to_file_the_testers_pictures_with_the_stop():
    import orch_factory

    text = (Path(orch_factory.__file__).parent / "skills/orch-factory/SKILL.md").read_text()
    assert ".orch/addons/factory/stops/<order>/s<round>/" in text and '"after": "s1/make-poll.png"' in text

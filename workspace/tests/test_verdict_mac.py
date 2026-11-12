"""Done needs a signed verdict (W2b 1.0a, contracts/human-proof.md "Done needs a signed verdict"):
a ticket counts as Done only with a verdict entry this core signed AND that is the current ledger entry;
every other raw `done` is Review. Real proofs here (this module opts out of the legacy test trust)."""

import io
import json
import sys
from pathlib import Path

import pytest

from orch import config, tickets
from orch import humanproof as hp
from orch.errors import Refused


@pytest.fixture
def ws(proj, monkeypatch):
    from orch import addons

    acct = addons.real_home()
    base = acct / ".orch-test"
    root = base / "ws"
    (root / ".orch").mkdir(parents=True)
    (base / "home").mkdir()
    monkeypatch.setenv("ORCH_HOME", str(base / "home"))
    monkeypatch.chdir(root)
    return root


def _proof(ws, op, target, by="human:pat", **kw):
    return hp.mint(hp.human_key(ws), hp.new_payload(op, target, by, **kw))


def _cli(run, monkeypatch, proof, *argv):
    monkeypatch.setattr("sys.stdin", io.StringIO((proof + "\n") if proof else ""))
    return run(*argv, "--proof-stdin")


def _new(run, title="Export"):
    code, out, _ = run("ticket", "new", title, "--json", "--by", "agent:x")
    assert code == 0
    return json.loads(out)["id"]


def _finished(ws, run, title="Export"):
    """A ticket whose only step is done with evidence, ready to be finished."""
    tid = _new(run, title)
    run("check", "add", tid, "Write the file", "--json", "--by", "agent:x")
    code, out, err = run("check", "done", tid, "c1", "--note", "looked fine", "--by", "agent:x", "--json")
    assert code == 0, out + err
    return tid


def _raw(ws, tid):
    return json.loads(tickets.ticket_path(ws, tid).read_text())


def _edit(ws, tid, **kw):
    """What an agent's direct file edit does: no core code runs."""
    p = tickets.ticket_path(ws, tid)
    t = json.loads(p.read_text())
    t.update(kw)
    p.write_text(json.dumps(t, indent=2))


def _verdict(ws, run, monkeypatch, tid):
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "ticket.verdict", tid), "ticket", "status", tid, "done"
    )
    assert code == 0, out + err


def _grant(ws):
    hp.record_set(ws, "workflow.agents_may_finish", True, "human:pat")
    config.set_key(ws, "workflow", "agents_may_finish", True)


# 1. an agent writes "done" into the file: every reader says Review ------------------------------------------


def test_a_done_written_into_the_file_is_review_for_every_reader(ws, run):
    tid = _finished(ws, run)
    _edit(ws, tid, status="done")
    assert _raw(ws, tid)["status"] == "done"  # readers never rewrite the file
    t = tickets.load(ws, tid)
    assert t["status"] == "review" and t["verdict_needed"] is True
    listed = [x for x in tickets.list_all(ws) if x["id"] == tid][0]
    assert listed["status"] == "review" and listed["verdict_needed"] is True
    code, out, _ = run("ticket", "show", tid, "--json")
    assert json.loads(out)["status"] == "review" and json.loads(out)["verdict_needed"] is True
    code, out, _ = run("ticket", "list", "--all", "--json")
    assert [x for x in json.loads(out) if x["id"] == tid][0]["status"] == "review"
    assert _raw(ws, tid)["status"] == "done"
    # the readers that count finished work
    child = _new(run, "Child")
    _edit(ws, child, status="done", parent=tid)
    assert [k["id"] for k in tickets.open_children(ws, tid)] == [child]
    assert tickets.children_counts(tickets.list_all(ws), tid)["closed"] == 0
    from orch import phone_view

    assert phone_view.view_for(ws, tid)["status"] != "done"


def test_an_unsigned_done_is_not_finished_for_automation(ws, run):
    loop = pytest.importorskip("orch_automation.loop")
    tid = _finished(ws, run)
    _edit(ws, tid, status="done")
    assert loop.scheduled({**tickets.load(ws, tid), "ext": {"automation": {"recurring": True}}}) is True


# 2. the person's Looks good signs ---------------------------------------------------------------------------


def test_the_persons_looks_good_signs_the_done_and_it_lists_as_done(ws, run, monkeypatch):
    tid = _finished(ws, run)
    _edit(ws, tid, status="done")
    _verdict(ws, run, monkeypatch, tid)
    t = tickets.load(ws, tid)
    assert t["status"] == "done" and "verdict_needed" not in t
    [entry] = t["verdicts"]
    assert entry["kind"] == "person" and set(entry) == set(hp.VERDICT_FIELDS) | set(hp.VERDICT_OPTIONAL)
    assert entry["person"] == "human:pat"
    assert hp.verdict_ledger(ws) == {tid: entry["mac"]}  # the CURRENT entry
    assert [x["status"] for x in tickets.list_all(ws) if x["id"] == tid] == ["done"]
    assert _raw(ws, tid)["status"] == "done" and "verdict_needed" not in _raw(ws, tid)


def test_the_phone_accept_signs_through_the_relay_channel(ws, run):
    tid = _new(run)
    tickets.apply_op(ws, tid, lambda t: t.update(status="review"), by=tickets.SYSTEM)
    hp.human_key(ws)
    with pytest.raises(Refused):
        tickets.accept_review(ws, tid, "human:phone")  # not proven: nothing becomes Done
    assert _raw(ws, tid)["status"] == "review"
    tickets.accept_review(ws, tid, "human:phone", "phone", proven=True)
    t = tickets.load(ws, tid)
    assert t["status"] == "done" and t["verdicts"][0]["kind"] == "person"


# 3. who may finish -----------------------------------------------------------------------------------------


def test_an_agent_finish_with_the_recorded_grant_is_done_kind_agent(ws, run):
    hp.human_key(ws)
    _grant(ws)
    tid = _finished(ws, run)
    code, out, err = run("ticket", "status", tid, "done", "--by", "agent:x", "--json")
    assert code == 0, out + err
    t = tickets.load(ws, tid)
    assert t["status"] == "done" and t["verdicts"][0]["kind"] == "agent"
    assert any(h["text"] == tickets.AGENT_FINISH_TEXT for h in t["history"])


def test_an_agent_finish_without_the_grant_or_with_only_a_config_line_is_review(ws, run):
    hp.human_key(ws)
    tid = _finished(ws, run)
    run("ticket", "status", tid, "done", "--by", "agent:x", "--json")
    assert tickets.load(ws, tid)["status"] == "review" and not _raw(ws, tid).get("verdicts")
    config.set_key(ws, "workflow", "agents_may_finish", True)  # a file edit, no recorded grant
    tid2 = _finished(ws, run, "Second")
    run("ticket", "status", tid2, "done", "--by", "agent:x", "--json")
    assert tickets.load(ws, tid2)["status"] == "review" and _raw(ws, tid2)["status"] == "review"


def test_revoking_the_grant_does_not_undo_an_earlier_agent_done(ws, run, monkeypatch):
    hp.human_key(ws)
    _grant(ws)
    tid = _finished(ws, run)
    run("ticket", "status", tid, "done", "--by", "agent:x", "--json")
    hp.record_set(ws, "workflow.agents_may_finish", False, "human:pat")
    config.set_key(ws, "workflow", "agents_may_finish", False)
    assert tickets.load(ws, tid)["status"] == "done"


# 4. no unsigned Done ---------------------------------------------------------------------------------------


def test_a_person_without_proof_gets_the_hand_off_and_nothing_is_written(ws, run):
    tid = _finished(ws, run)
    code, out, err = run("ticket", "status", tid, "done", "--by", "human:me", "--json")
    assert code == 2 and _raw(ws, tid)["status"] != "done"


def test_a_direct_write_of_a_new_done_without_a_verifying_entry_is_refused(ws, run):
    tid = _finished(ws, run)
    t = _raw(ws, tid)
    with pytest.raises(Refused, match="Done needs your OK"):
        tickets._write(ws, {**t, "status": "done"})
    with pytest.raises(Refused, match="Done needs your OK"):
        tickets._write(
            ws, {**t, "status": "done", "verdicts": [{"kind": "person", "nonce": "0" * 16, "mac": "A" * 43}]}
        )
    with pytest.raises(Refused, match="Done needs your OK"):
        tickets.apply_op(
            ws, tid, lambda x: x.update(status="done"), by=tickets.SYSTEM
        )  # no op makes a ticket Done unsigned
    assert _raw(ws, tid)["status"] != "done"


def test_a_person_actor_cannot_sign_without_the_proof_flag(ws, run):
    tid = _finished(ws, run)
    hp.human_key(ws)
    with pytest.raises(Refused, match="Done needs your OK"):
        tickets.set_status(ws, tid, "done", "human:me")
    with pytest.raises(Refused, match="Done needs your OK"):
        tickets.patch(ws, tid, tickets.revision(tickets.load(ws, tid)), '{"status": "done"}', "human:me")


# 5. reopen tombstones, replays do not come back ------------------------------------------------------------


def test_reopen_tombstones_and_the_old_file_content_is_review(ws, run, monkeypatch):
    tid = _finished(ws, run)
    _verdict(ws, run, monkeypatch, tid)
    old = _raw(ws, tid)
    assert tickets.load(ws, tid)["status"] == "done"
    code, out, err = run("ticket", "status", tid, "active", "--by", "agent:x", "--json")
    assert code == 0, out + err
    assert hp.verdict_ledger(ws)[tid] is None  # tombstone, written by the core's own write
    tickets.ticket_path(ws, tid).write_text(json.dumps(old))  # the old Done content comes back
    t = tickets.load(ws, tid)
    assert t["status"] == "review" and t["verdict_needed"] is True


def test_editing_the_file_to_active_and_back_to_done_is_review_the_reader_tombstones(ws, run, monkeypatch):
    """Manager adjustment 1: a core READ of a ticket whose file is not done tombstones its entry at that
    moment
    (like effective() does), so the replay "active, then done again with the old verdict" is not Done."""
    tid = _finished(ws, run)
    _verdict(ws, run, monkeypatch, tid)
    done = _raw(ws, tid)
    _edit(ws, tid, status="active")  # an agent's file edit; no core write
    assert hp.verdict_ledger(ws)[tid] == done["verdicts"][0]["mac"]  # not yet tombstoned
    assert tickets.load(ws, tid)["status"] == "active"  # any core read of it
    assert hp.verdict_ledger(ws)[tid] is None
    tickets.ticket_path(ws, tid).write_text(json.dumps(done))  # back to done with the old verdict
    assert tickets.load(ws, tid)["status"] == "review"
    assert [x["status"] for x in tickets.list_all(ws) if x["id"] == tid] == ["review"]


def test_a_listing_tombstones_too(ws, run, monkeypatch):
    tid = _finished(ws, run)
    _verdict(ws, run, monkeypatch, tid)
    done = _raw(ws, tid)
    _edit(ws, tid, status="review")
    assert [x["status"] for x in tickets.list_all(ws) if x["id"] == tid] == ["review"]
    assert hp.verdict_ledger(ws)[tid] is None
    tickets.ticket_path(ws, tid).write_text(json.dumps(done))
    assert tickets.load(ws, tid)["status"] == "review"


def test_a_newer_verdict_supersedes_an_older_one(ws, run, monkeypatch):
    tid = _finished(ws, run)
    _verdict(ws, run, monkeypatch, tid)
    first = _raw(ws, tid)
    run("ticket", "status", tid, "active", "--by", "agent:x", "--json")
    _verdict(ws, run, monkeypatch, tid)
    assert tickets.load(ws, tid)["status"] == "done"
    tickets.ticket_path(ws, tid).write_text(json.dumps(first))  # the older valid MAC replayed
    assert tickets.load(ws, tid)["status"] == "review"


# 6. what a verdict binds -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda t: t["checklist"].append({"id": "c9", "text": "Another", "done": False, "evidence": []}),
        lambda t: t["checklist"][0].update(text="Reworded step"),
        lambda t: t["checklist"][0].update(done=False),
        lambda t: t["checklist"][0].update(wont_do=True, done=False),
    ],
    ids=["new step", "reworded", "reopened", "wont do"],
)
def test_a_checklist_change_after_the_verdict_makes_it_review(ws, run, monkeypatch, mutate):
    tid = _finished(ws, run)
    _verdict(ws, run, monkeypatch, tid)
    t = _raw(ws, tid)
    mutate(t)
    tickets.ticket_path(ws, tid).write_text(json.dumps(t))
    assert tickets.load(ws, tid)["status"] == "review"


def test_a_rename_keeps_the_ticket_done(ws, run, monkeypatch):
    tid = _finished(ws, run)
    _verdict(ws, run, monkeypatch, tid)
    code, out, err = run("ticket", "edit", tid, "--title", "Export to CSV", "--by", "human:pat", "--json")
    assert code == 0, out + err
    _edit(ws, tid, summary="Written after finishing")
    t = tickets.load(ws, tid)
    assert t["status"] == "done" and t["title"] == "Export to CSV"


# 8. an unrelated op does not rewrite a raw done -------------------------------------------------------------


def test_an_unrelated_op_keeps_the_raw_done_of_an_unsigned_ticket(ws, run):
    tid = _finished(ws, run)
    _edit(ws, tid, status="done")
    code, out, err = run("ticket", "set", tid, "note", "a note", "--by", "human:pat", "--json")
    tickets.apply_op(ws, tid, lambda t: tickets.add_history(t, "human:pat", "a line"), by=tickets.SYSTEM)
    assert _raw(ws, tid)["status"] == "done"
    assert tickets.load(ws, tid)["status"] == "review"


def test_the_person_can_still_click_looks_good_after_unrelated_ops(ws, run, monkeypatch):
    tid = _finished(ws, run)
    _edit(ws, tid, status="done")
    tickets.apply_op(ws, tid, lambda t: tickets.add_history(t, "human:pat", "a line"), by=tickets.SYSTEM)
    _verdict(ws, run, monkeypatch, tid)
    assert tickets.load(ws, tid)["status"] == "done"


# 9. damaged or missing ledger -------------------------------------------------------------------------------


def test_a_missing_ledger_means_nothing_is_done(ws, run, monkeypatch):
    tid = _finished(ws, run)
    _verdict(ws, run, monkeypatch, tid)
    (hp.key_dir(ws) / hp.VERDICT_LEDGER).unlink()
    assert tickets.load(ws, tid)["status"] == "review"


def test_a_damaged_ledger_means_nothing_is_done_and_nothing_is_half_written(ws, run, monkeypatch):
    tid = _finished(ws, run)
    tid2 = _finished(ws, run, "Other")
    _verdict(ws, run, monkeypatch, tid)
    led = hp.key_dir(ws) / hp.VERDICT_LEDGER
    led.write_text("{ not json")
    led.chmod(0o600)
    assert tickets.load(ws, tid)["status"] == "review"
    before = _raw(ws, tid2)
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "ticket.verdict", tid2), "ticket", "status", tid2, "done", "--json"
    )
    assert code == 2 and hp.VERDICT_LEDGER_DAMAGED.split(".")[0] in out + err
    assert _raw(ws, tid2) == before  # nothing half-written
    assert led.read_text() == "{ not json"  # the damaged ledger is never overwritten


def test_no_key_means_no_verdict(ws, run):
    tid = _finished(ws, run)
    with pytest.raises(Refused):
        hp.verdict_sign(ws, _raw(ws, tid), "person")
    assert (
        hp.verdict_ok(
            ws, {**_raw(ws, tid), "verdicts": [{"kind": "person", "nonce": "0" * 16, "mac": "A" * 43}]}
        )
        is False
    )


# the record ------------------------------------------------------------------------------------------------


def test_the_mac_binds_the_ticket_the_workspace_the_kind_and_the_nonce(ws, run, monkeypatch):
    tid = _finished(ws, run)
    tid2 = _finished(ws, run, "Other")
    _verdict(ws, run, monkeypatch, tid)
    entry = _raw(ws, tid)["verdicts"][0]
    ok = hp.VerdictChecker(ws)
    t = _raw(ws, tid)
    assert ok.ok(t)
    assert not ok.ok({**_raw(ws, tid2), "verdicts": [entry]})  # copied onto another ticket
    assert not ok.ok({**t, "verdicts": [{**entry, "kind": "agent"}]})
    assert not ok.ok({**t, "verdicts": [{**entry, "nonce": "f" * 16}]})
    assert not ok.ok({**t, "verdicts": "garbage"}) and not ok.ok({**t, "verdicts": [None, 3, {}]})
    assert hp.verdict_mac(b"k", "w", "t", {"a": 1}) != hp.wontdo_mac(
        b"k", "w", "t", {"a": 1}
    )  # prefix separation
    assert hp.verdict_mac(b"k", "w1", "t", {"a": 1}) != hp.verdict_mac(b"k", "w2", "t", {"a": 1})


def test_the_ledger_file_is_private_and_separate_from_the_wont_ledger(ws, run, monkeypatch):
    tid = _finished(ws, run)
    _verdict(ws, run, monkeypatch, tid)
    f = hp.key_dir(ws) / "verdict.json"
    assert f.exists() and (f.stat().st_mode & 0o077) == 0
    assert json.loads(f.read_text())["schema"] == "orch.verdict-ledger/1"
    assert hp.LEDGER == "wont.json" and hp.VERDICT_LEDGER != hp.LEDGER


# sync ------------------------------------------------------------------------------------------------------


def _merge_mod():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workspace-addons" / "sync" / "src"))
    from orch_sync import merge

    return merge


def test_the_person_and_time_are_inside_the_mac(ws, run, monkeypatch):
    """#484: changing, adding or removing `person` or `at` makes the entry stop verifying (Review again); a
    legacy entry (neither) still verifies Done as before but carries no author."""
    tid = _finished(ws, run)
    _edit(ws, tid, status="done")
    _verdict(ws, run, monkeypatch, tid)
    [entry] = _raw(ws, tid)["verdicts"]
    assert entry["person"] == "human:pat" and entry["at"].endswith("Z")
    for forged in (
        {**entry, "person": "human:lee"},
        {**entry, "at": "2030-01-01T00:00:00Z"},
        {k: v for k, v in entry.items() if k != "person"},
        {k: v for k, v in entry.items() if k != "at"},
        {**entry, "person": None},
    ):
        _edit(ws, tid, verdicts=[forged])
        t = tickets.load(ws, tid)
        assert t["status"] == "review" and t.get("verdict_needed") is True
    legacy = hp.verdict_sign(ws, _raw(ws, tid), "person")  # the pre-#484 shape
    assert "person" not in legacy and "at" not in legacy
    _edit(ws, tid, status="done", verdicts=[legacy])
    assert tickets.load(ws, tid)["status"] == "done"


def test_the_real_writers_lines_are_attributed_by_the_real_merge(ws, run, monkeypatch):
    """#484: the history lines the real writers add (Looks good, Won't do) keep the person's name through the
    real merge when the decision is NEW here and verifies (the allowed texts come from these writers)."""
    merge = _merge_mod()
    tid = _finished(ws, run)
    _edit(ws, tid, status="done")
    before = _raw(ws, tid)
    _verdict(ws, run, monkeypatch, tid)
    after = _raw(ws, tid)
    new = [h for h in after["history"] if h not in before["history"]]
    assert new and all(h["by"] == "human:pat" for h in new)
    out = merge.merge_ticket(
        before, after, before, "2030-01-03T00:00:00Z", hp.wont_verifier(ws), hp.verdict_verifier(ws)
    )
    kept = [h for h in out["history"] if h in new]
    [entry] = after["verdicts"]
    assert len(kept) == 1 and entry["line"] == hp.history_digest(kept[0]["text"], kept[0]["via"])
    # a different "Patched ..." line riding on the real verdict (or another via) is not the bound line
    for text, via in (
        ("Patched title, note (status review -> done)", kept[0]["via"]),
        (kept[0]["text"], "phone"),
    ):
        fake = {**kept[0], "text": text, "via": via}
        remote = {**after, "history": [*before["history"], fake]}
        out = merge.merge_ticket(
            before, remote, before, "2030-01-03T00:00:00Z", hp.wont_verifier(ws), hp.verdict_verifier(ws)
        )
        assert fake not in out["history"] and any(h["by"] == "agent:sync" for h in out["history"])
    # the same decision known here (base): the same lines are demoted, a decision lends its name once
    again = merge.merge_ticket(
        after, after, before, "2030-01-03T00:00:00Z", hp.wont_verifier(ws), hp.verdict_verifier(ws)
    )
    assert all(h not in again["history"] for h in kept) or all(h["by"] == "human:pat" for h in kept)

    tid2 = _new(run, "Second")
    run("check", "add", tid2, "Optional", "--json", "--by", "agent:x")
    pre = _raw(ws, tid2)
    tickets.check_wont_do(ws, tid2, "c1", "human:pat", "Not needed")
    post = _raw(ws, tid2)
    step = post["checklist"][0]
    assert step["wont_by"] == "human:pat" and step["wont_at"]
    line = [h for h in post["history"] if h not in pre["history"]]
    out = merge.merge_ticket(
        pre, post, pre, "2030-01-03T00:00:00Z", hp.wont_verifier(ws), hp.verdict_verifier(ws)
    )
    assert [h["by"] for h in out["history"] if h in line] == ["human:pat"]
    # a peer rewriting who decided breaks the MAC: nothing is attributed
    forged = {**post, "checklist": [{**step, "wont_by": "human:eve"}]}
    out = merge.merge_ticket(
        pre,
        {**forged, "history": [{**line[0], "by": "human:eve"}]},
        pre,
        "2030-01-03T00:00:00Z",
        hp.wont_verifier(ws),
        hp.verdict_verifier(ws),
    )
    assert all(h["by"] != "human:eve" for h in out["history"])
    assert "wont_do" not in out["checklist"][0]


def test_the_merges_dependency_free_copy_of_the_actor_rules_has_not_drifted():
    merge = _merge_mod()
    assert merge._VERDICT_OPTIONAL == hp.VERDICT_OPTIONAL
    assert merge.history_digest("a", "cli") == hp.history_digest("a", "cli")
    assert merge._ACTOR.pattern == hp.ACTOR_PATTERN
    assert hp.bindable_actor("human:pat") and not hp.bindable_actor("agent:pat")
    assert not hp.bindable_actor("human:" + "x" * 80) and not hp.bindable_actor("human:a\nb")


def test_the_merges_dependency_free_copy_of_the_verdict_fields_has_not_drifted():
    assert _merge_mod()._VERDICT_FIELDS == hp.VERDICT_FIELDS
    assert _merge_mod().VERDICT_CAP == hp.VERDICT_MAX


def test_the_real_verifier_drives_the_merge_and_a_merged_reopen_tombstones_on_write(ws, run, monkeypatch):
    merge = _merge_mod()
    tid = _finished(ws, run)
    _verdict(ws, run, monkeypatch, tid)
    base = _raw(ws, tid)
    mine = {**base, "updated_at": "2030-01-01T00:00:00Z"}
    peer_garbage = {
        **base,
        "verdicts": [{"kind": "person", "nonce": "1" * 16, "mac": "B" * 43}],
        "updated_at": "2030-01-02T00:00:00Z",
    }
    verdict = hp.verdict_verifier(ws)
    out = merge.merge_ticket(base, peer_garbage, mine, "2030-01-03T00:00:00Z", verdict=verdict)
    macs = [e["mac"] for e in out["verdicts"]]
    assert base["verdicts"][0]["mac"] in macs and "B" * 43 in macs  # ours kept, the unverifiable one carried
    assert out == merge.merge_ticket(base, mine, peer_garbage, "2030-01-03T00:00:00Z", verdict=verdict)
    # a peer's reopen wins (lowering needs no proof); the write that applies it tombstones our entry
    reopened = {**base, "status": "active", "updated_at": "2030-01-02T00:00:00Z"}
    out = merge.merge_ticket(base, reopened, mine, "2030-01-03T00:00:00Z", verdict=verdict)
    assert out["status"] == "active"
    with tickets._locked(ws, tid):
        tickets._write(ws, out)
    assert hp.verdict_ledger(ws)[tid] is None


def test_a_merge_with_a_damaged_ledger_drops_nothing_for_being_ours(ws, run, monkeypatch):
    merge = _merge_mod()
    tid = _finished(ws, run)
    _verdict(ws, run, monkeypatch, tid)
    base = _raw(ws, tid)
    led = hp.key_dir(ws) / hp.VERDICT_LEDGER
    led.write_text("{ nope")
    led.chmod(0o600)
    out = merge.merge_ticket(base, base, base, "2030-01-03T00:00:00Z", verdict=hp.verdict_verifier(ws))
    assert out["verdicts"] == base["verdicts"]


# structure --------------------------------------------------------------------------------------------------


def test_only_tickets_write_underscore_write_replaces_a_ticket_file():
    """Every writer of .orch/tickets/<id>.json goes through tickets._write (the one guard): the only
    os/procs.replace of a ticket file in the source is inside it, and no other module calls it."""
    import ast

    src = Path(__file__).resolve().parents[1] / "src" / "orch"
    tree = ast.parse((src / "tickets.py").read_text())
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for n in ast.walk(fn):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "replace"
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id in ("procs", "os")
                and fn.name not in ("_write", "_break_stale")
            ):
                raise AssertionError(f"tickets.{fn.name} replaces a file outside _write")
    for f in sorted(src.glob("*.py")) + sorted((src.parents[2] / "workspace-addons").glob("*/src/*/*.py")):
        if f.name == "tickets.py":
            continue
        text = f.read_text()
        assert "tickets._write(" not in text, f
        assert "tickets.save(" not in text, f


def test_the_effective_view_is_applied_in_one_place():
    src = (Path(__file__).resolve().parents[1] / "src" / "orch" / "tickets.py").read_text()
    assert src.count("def _effective(") == 1
    assert "def load(" in src and "_effective(root, _load_raw(root, tid))" in src


def test_a_step_reopened_and_redone_does_not_bring_the_old_done_back(ws, run, monkeypatch):
    """Opus review MEDIUM-1: the checks hash ignores evidence, so reopen + redo restores the signed state.
    The write of the reopened (not done) state tombstones the entry; and a Done write that no longer
    verifies tombstones too."""
    tid = _finished(ws, run)
    _verdict(ws, run, monkeypatch, tid)
    assert tickets.load(ws, tid)["status"] == "done"
    code, out, err = run("check", "reopen", tid, "c1", "--by", "agent:x")
    assert code == 0, out + err
    assert hp.verdict_ledger(ws)[tid] is None
    code, out, err = run("check", "done", tid, "c1", "--note", "other", "--by", "agent:x", "--json")
    assert code == 0, out + err
    t = tickets.load(ws, tid)
    assert t["status"] != "done"
    assert hp.verdict_ledger(ws)[tid] is None


def test_a_done_write_that_stopped_verifying_tombstones_the_entry(ws, run, monkeypatch):
    tid = _finished(ws, run)
    _verdict(ws, run, monkeypatch, tid)
    t = _raw(ws, tid)
    t["checklist"][0]["text"] = "reworded"  # the file still says done and still holds the entry
    tickets.ticket_path(ws, tid).write_text(json.dumps(t))
    tickets.apply_op(ws, tid, lambda x: tickets.add_history(x, "human:pat", "a line"), by=tickets.SYSTEM)
    assert hp.verdict_ledger(ws)[tid] is None  # the old state can never come back by editing the file back


def test_a_loose_verdict_ledger_is_damaged_and_a_reader_never_resets_protection(ws, run, monkeypatch):
    tid = _finished(ws, run)
    _verdict(ws, run, monkeypatch, tid)
    key_before = hp.human_key(ws)
    resets = hp._RESETS
    led = hp.key_dir(ws) / hp.VERDICT_LEDGER
    led.chmod(0o644)
    assert hp.verdict_ledger(ws) is None
    assert tickets.load(ws, tid)["status"] == "review"
    assert hp._RESETS == resets and hp.human_key(ws) == key_before


def test_a_reset_of_protection_also_clears_both_ledgers(ws, run, monkeypatch):
    tid = _finished(ws, run)
    _verdict(ws, run, monkeypatch, tid)
    led = hp.key_dir(ws) / hp.VERDICT_LEDGER
    assert led.exists()
    hp.reset_protection(ws, "test")
    assert not led.exists() and not (hp.key_dir(ws) / hp.LEDGER).exists()
    assert tickets.load(ws, tid)["status"] == "review"

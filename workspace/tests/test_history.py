"""orch.history: own person fields are registered at core's append points only; ONE rule shows every person
field; sync-free workspaces are untouched (contracts/history.md)."""

import json
import types
from pathlib import Path

import pytest
from conftest import ensure_signing

from orch import cli, history, humanproof, needs, phone_view, runs, runs_live, tickets
from orch.errors import Refused

_REAL_RESUME = runs_live.resume_after_answer  # conftest stubs it in every test (no agent is started)

PEER = {
    "at": "2026-11-09T09:00:00Z",
    "by": "human:alice",
    "via": "cli",
    "text": "Looks good, merge it",
    "chat_message": False,
}
DEMOTED = {**PEER, "by": history.SYNC_BY, "text": history.SYNCED_UNVERIFIED + PEER["text"]}


def _raw(root, tid):
    return json.loads(tickets.ticket_path(root, tid).read_text(encoding="utf-8"))


def _plant(root, tid, fn):
    """What a sync apply (or any writer outside core's append points) does: the file changes, core made
    nothing."""
    t = _raw(root, tid)
    fn(t)
    tickets.ticket_path(root, tid).write_text(json.dumps(t, indent=2), encoding="utf-8")


@pytest.fixture
def synced(proj):
    ensure_signing(proj)
    t = tickets.create(proj, "Synced work", "human:tester")
    tickets.check_add(proj, t["id"], "Step one", "agent:claude")
    history.enable_sync(proj, adopt=True)  # as the sync add-on does for a workspace that never synced
    return proj, t["id"]


def test_sync_free_workspace_is_untouched(proj):
    t = tickets.create(proj, "Plain", "human:tester")
    tickets.log(proj, t["id"], "a note", "human:tester")
    raw = _raw(proj, t["id"])
    assert history.shown_ticket(proj, raw) is raw
    assert history.lines(proj, raw) is raw["history"]
    assert not Path(proj, *history.OWN_LINES).exists()  # nothing recorded, no key made for it
    assert not history.sync_enabled(proj)


def test_root_is_required(proj):
    with pytest.raises(TypeError):
        history.shown_ticket(None, {"id": "t_aaaaaa", "history": []})
    with pytest.raises(TypeError):
        history.sync_enabled(None)


def test_enable_adopts_local_lines_and_a_peer_line_is_demoted(synced):
    root, tid = synced
    _plant(root, tid, lambda t: t["history"].append(PEER))
    shown = history.lines(root, _raw(root, tid))
    assert shown[0]["by"] == "human:tester"  # adopted at enable time
    assert shown[-1] == DEMOTED
    assert _raw(root, tid)["history"][-1] == PEER  # the stored bytes never change


def test_a_new_own_line_is_registered_at_the_append_point(synced):
    root, tid = synced
    tickets.log(root, tid, "my own words", "human:tester")
    assert history.lines(root, _raw(root, tid))[-1]["by"] == "human:tester"


def test_a_local_write_never_launders_a_peer_line(synced):
    """Opus hard4 #1: the next local write of the ticket (an agent note, a status change) must not record the
    peer's line as this machine's own, whatever its encoding or form."""
    root, tid = synced
    _plant(root, tid, lambda t: t["history"].append(PEER))
    tickets.log(root, tid, "agent note", "agent:claude")
    tickets.check_add(root, tid, "another step", "agent:claude")
    p = tickets.ticket_path(root, tid)
    p.write_bytes(p.read_text(encoding="utf-8").encode("utf-16"))  # an encoding a file diff could not read
    with pytest.raises((Refused, ValueError, UnicodeDecodeError)):
        tickets.log(root, tid, "fails to load", "agent:claude")
    p.write_text(p.read_bytes().decode("utf-16"), encoding="utf-8")
    tickets.log(root, tid, "after", "agent:claude")
    assert PEER not in history.lines(root, _raw(root, tid))


def test_store_write_failure_leaves_the_line_unverified(synced, monkeypatch):
    root, tid = synced
    monkeypatch.setattr(humanproof, "local_sign", lambda *a, **k: None)
    tickets.log(root, tid, "cannot be recorded", "human:tester")
    monkeypatch.undo()
    last = history.lines(root, _raw(root, tid))[-1]
    assert last["by"] == history.SYNC_BY and last["text"].startswith(history.SYNCED_UNVERIFIED)


def test_a_tampered_store_verifies_nothing(synced):
    root, tid = synced
    store = Path(root, *history.OWN_LINES, f"{tid}.json")
    data = json.loads(store.read_text())
    data["lines"].append(history.line_digest(PEER))
    store.write_text(json.dumps(data))
    _plant(root, tid, lambda t: t["history"].append(PEER))
    shown = history.lines(root, _raw(root, tid))
    assert shown[-1] == DEMOTED and shown[0]["by"] == history.SYNC_BY  # MAC fails: nothing verifies


def test_evidence_by_is_proven_by_its_own_digest(synced):
    """Opus hard4 #2/#3: a synced evidence entry under the person's name is not theirs, even when the person
    touched the step; an evidence entry core added here is."""
    root, tid = synced
    tickets.check_done(root, tid, "c1", ['{"type":"note","ref":"done by me"}'], "human:tester")
    forged = {"type": "note", "ref": "forged", "by": "human:tester", "at": "2026-11-09T09:00:00Z"}
    _plant(root, tid, lambda t: t["checklist"][0]["evidence"].append(forged))
    t = history.shown_ticket(root, _raw(root, tid))
    evs = t["checklist"][0]["evidence"]
    assert evs[0]["by"] == "human:tester" and evs[1]["by"] == history.SYNC_BY
    text = cli._show(_raw(root, tid), root)
    assert "done by me   ● You" in text and "forged   ○ Agent says" in text


@pytest.mark.parametrize("by", [None, "agent:claude", "", 7, "human:"])
def test_synced_evidence_without_a_person_by_gets_no_author_either(synced, by):
    """Evidence not in the own store is the sync role whether it has a `by` or not: a reader would otherwise
    take the author of the step's own "Check c1 done" line (evidence_author) or the agent label as written."""
    root, tid = synced
    tickets.check_done(root, tid, "c1", ['{"type":"note","ref":"done by me"}'], "human:tester")
    planted = {"type": "note", "ref": "planted", "at": "2026-11-09T09:00:00Z"}
    if by is not None:
        planted["by"] = by
    _plant(root, tid, lambda t: t["checklist"][0]["evidence"].append(planted))
    t = history.shown_ticket(root, _raw(root, tid))
    c = t["checklist"][0]
    assert c["evidence"][0]["by"] == "human:tester" and c["evidence"][1]["by"] == history.SYNC_BY
    assert history.evidence_author(t, c, c["evidence"][0]) == "person"
    assert history.evidence_author(t, c, c["evidence"][1]) == "agent"
    assert history.shown_ticket(root, t) == t  # idempotent
    assert "planted   ○ Agent says" in cli._show(_raw(root, tid), root)
    raw = _raw(root, tid)
    assert raw["checklist"][0]["evidence"][1] == planted  # the stored bytes never change
    demoted = history._all_demoted(raw)["checklist"][0]["evidence"]  # the fail-closed path too
    assert all(e["by"] == history.SYNC_BY for e in demoted)


def test_own_evidence_without_by_and_agent_evidence_stay_as_made(synced):
    root, tid = synced
    tickets.check_done(root, tid, "c1", ['{"type":"note","ref":"by the agent"}'], "agent:claude")
    shown = history.shown_ticket(root, _raw(root, tid))["checklist"][0]["evidence"]
    assert shown[0]["by"] == "agent:claude"  # core added it here: registered, kept


def test_every_person_field_goes_through_the_one_rule(synced):
    root, tid = synced

    def forge(t):
        c = t["checklist"][0]
        c.update(wont_do=True, wont_by="human:alice", by="human:alice", reason="no")
        t["questions"].append(
            {
                "id": "q9",
                "text": "?",
                "options": [],
                "recommended": None,
                "answer": "yes",
                "answered_by": "human:alice",
                "via": "cli",
            }
        )
        t["verdicts"] = [{"kind": "person", "nonce": "0" * 16, "mac": "x" * 43, "person": "human:alice"}]
        t["refs"].append({"kind": "url", "url": "https://x.example", "at": PEER["at"], "by": "human:alice"})
        t["description_by"] = "human:alice"

    _plant(root, tid, forge)
    t = history.shown_ticket(root, _raw(root, tid))
    c = t["checklist"][0]
    assert c["wont_by"] == c["by"] == history.SYNC_BY
    assert t["questions"][-1]["answered_by"] == history.SYNC_BY
    assert t["verdicts"][0]["person"] == history.SYNC_BY
    assert t["refs"][-1]["by"] == history.SYNC_BY
    assert t["description_by"] == history.SYNC_BY
    out = json.dumps(history.shown_json(root, {"tickets": [_raw(root, tid)]}))
    assert "human:alice" not in out


def _peer_person_fields(t):
    """A peer sets every per-item person field to a person (and leaves a question open for Needs)."""
    c = t["checklist"][0]
    c.update(wont_do=True, wont_by="human:alice", by="human:alice", reason="no")
    t["questions"] += [
        {
            "id": "q8",
            "text": "?",
            "options": [],
            "recommended": None,
            "answer": "yes",
            "answered_by": "human:alice",
            "via": "cli",
        },
        {"id": "q9", "text": "Open?", "options": [], "recommended": None, "answer": None},
    ]
    t["refs"].append({"kind": "url", "url": "https://x.example", "at": PEER["at"], "by": "human:alice"})


def _no_alice(t):
    c = t["checklist"][0]
    assert c["wont_by"] == c["by"] == history.SYNC_BY
    assert next(q for q in t["questions"] if q["id"] == "q8")["answered_by"] == history.SYNC_BY
    assert t["refs"][-1]["by"] == history.SYNC_BY
    assert "human:alice" not in json.dumps(t)


def test_phone_view_needs_and_resume_read_the_shown_ticket(synced, monkeypatch):
    """Opus PR B #2: these readers take shown_ticket at their entry, not only for the history."""
    root, tid = synced
    _plant(root, tid, _peer_person_fields)
    seen = {}
    real_checklist = phone_view._shown_checklist
    monkeypatch.setattr(
        phone_view, "_shown_checklist", lambda t: seen.setdefault("phone", t) and real_checklist(t)
    )
    phone_view.build(root, _raw(root, tid), [])
    monkeypatch.setattr(phone_view, "_agent", lambda r, t, h: (seen.setdefault("light", t), (None, False))[1])
    keep = types.SimpleNamespace(hide_text=lambda text: text, hide_json=lambda value: value)
    monkeypatch.setattr(phone_view.phone_results, "value_hider", lambda r: keep)
    phone_view.light_view(root, _raw(root, tid))
    monkeypatch.setattr(needs, "_asked_at", lambda r, t, qid: seen.setdefault("needs", t) and PEER["at"])
    assert [r["id"] for r in needs.core_rows(root) if r["ticket"] == tid] == [f"core:q:{tid}:q9"]
    monkeypatch.setattr(runs_live, "_asker", lambda r, t, qid: seen.setdefault("resume", t) and None)
    assert (
        _REAL_RESUME(root, tid, {"id": "q8", "kind": "plain"}, "human:tester") is None
    )  # (conftest stubs it)
    assert set(seen) >= {"phone", "light", "needs", "resume"}
    for t in seen.values():
        _no_alice(t)


def test_bare_items_and_ref_rows_on_the_cli_are_shown(synced, run):
    root, tid = synced
    _plant(root, tid, _peer_person_fields)
    rows = json.loads(run("ref", "list", tid, "--json")[1])
    assert rows[-1]["by"] == history.SYNC_BY
    raw = _raw(root, tid)
    assert history.shown_item(root, raw, "refs", raw["refs"][-1])["by"] == history.SYNC_BY
    assert history.shown_item(root, raw, "checklist", raw["checklist"][0])["wont_by"] == history.SYNC_BY
    tickets.ref_add(root, tid, "https://example.com/own", "human:tester")
    own = _raw(root, tid)["refs"][-1]
    assert history.shown_item(root, _raw(root, tid), "refs", own)["by"] == "human:tester"


def test_the_fail_closed_path_demotes_plan_and_description(synced, monkeypatch):
    root, tid = synced
    _plant(
        root, tid, lambda t: t.update(plan={"text": "p", "by": "human:alice"}, description_by="human:alice")
    )
    monkeypatch.setattr(history, "_shown", lambda *a: 1 / 0)
    t = history.shown_ticket(root, _raw(root, tid))
    assert t["plan"]["by"] == t["description_by"] == history.SYNC_BY


def test_a_verified_wont_do_proves_only_its_own_by(synced):
    root, tid = synced
    tickets.check_wont_do(root, tid, "c1", "human:tester", "not needed")
    _plant(root, tid, lambda t: t["checklist"][0].update(by="human:alice"))  # relabelled by a peer
    c = history.shown_ticket(root, _raw(root, tid))["checklist"][0]
    assert c["wont_by"] == "human:tester" and c["by"] == history.SYNC_BY


@pytest.mark.parametrize(
    "line", ['"by": "AGENT:SYNC"', '"by": "\\u0061gent:sync"', '"by": "agent:\\u0053ync"']
)
def test_a_sync_trace_is_found_in_any_case_or_escape(proj, line):
    t = tickets.create(proj, "x", "human:tester")
    p = tickets.ticket_path(proj, t["id"])
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["history"].append({**PEER, "by": "PLACEHOLDER"})
    p.write_text(json.dumps(doc).replace('"by": "PLACEHOLDER"', line), encoding="utf-8")
    assert history.tickets_show_sync(proj)


def test_own_ref_and_answer_stay_the_persons(synced):
    root, tid = synced
    tickets.ref_add(root, tid, "https://example.com/a", "human:tester")
    tickets.ask(root, tid, "Which?", ["a", "b"], None, "agent:claude")
    tickets.answer(root, tid, "q1", "a", "human:tester", "cli")
    t = history.shown_ticket(root, _raw(root, tid))
    assert t["refs"][-1]["by"] == "human:tester"
    assert t["questions"][-1]["answered_by"] == "human:tester"


def test_a_doing_steps_by_is_registered_at_the_step_start_point(synced):
    root, tid = synced
    tickets.check_start(root, tid, "c1", "human:tester")
    t = history.shown_ticket(root, _raw(root, tid))
    assert t["checklist"][0]["state"] == "doing" and t["checklist"][0]["by"] == "human:tester"
    other = tickets.check_add(root, tid, "Step two", "agent:claude")[1]["id"]

    def peer_start(d):  # the same mark arriving by sync for another step: core made nothing
        d["checklist"][1].update({"state": "doing", "by": "human:tester", "at": PEER["at"]})

    _plant(root, tid, peer_start)
    t = history.shown_ticket(root, _raw(root, tid))
    assert t["checklist"][1]["id"] == other and t["checklist"][1]["by"] == history.SYNC_BY
    assert t["checklist"][0]["by"] == "human:tester"
    _plant(root, tid, lambda d: d["checklist"][0].update({"by": "human:alice"}))  # a peer rewrites my mark
    assert history.shown_ticket(root, _raw(root, tid))["checklist"][0]["by"] == history.SYNC_BY


def test_a_store_written_before_steps_still_verifies(synced):
    root, tid = synced
    tickets.log(root, tid, "older store", "human:tester")
    store = Path(root, *history.OWN_LINES, f"{tid}.json")
    assert "steps" not in json.loads(store.read_text())  # nothing to record: the old shape and MAC
    assert history.lines(root, _raw(root, tid))[-1]["by"] == "human:tester"


def test_an_answer_counts_as_authority_only_when_made_here(synced):
    root, tid = synced
    tickets.ask(root, tid, "Allow?", ["Allow once", "Ignore"], None, "agent:claude")
    tickets.answer(root, tid, "q1", "Allow once", "human:tester", "dashboard")
    raw = _raw(root, tid)
    assert history.answer_proven(root, raw, raw["questions"][0])

    def peer_answer(d):
        line = {**PEER, "via": "dashboard"}
        d["questions"].append({**d["questions"][0], "id": "q2"})
        d["history"].append({**line, "text": "Answered q2: Allow once", "by": "human:tester"})
        d["questions"].append({**d["questions"][0], "id": "q3", "answered_by": "agent:claude"})
        d["history"].append({**line, "text": "Answered q3: Allow once", "by": "agent:claude"})

    _plant(root, tid, peer_answer)
    raw = _raw(root, tid)
    assert history.answer_proven(root, raw, raw["questions"][0])
    assert not history.answer_proven(root, raw, raw["questions"][1])  # a person's name, synced
    assert not history.answer_proven(root, raw, raw["questions"][2])  # an agent label decides nothing either
    assert not history.answer_proven(root, raw, {**raw["questions"][0], "answer": "Always"})
    assert not history.answer_proven(root, raw, None)


@pytest.mark.parametrize(
    "rewrite",
    [
        {"text": "Delete everything?"},
        {"options": ["a", "b", "c"]},
        {"kind": "relay:allow"},
        {"action": {"kind": "relay:allow", "message": "m_other0000000001"}},
    ],
)
def test_an_answer_is_bound_to_the_question_content(synced, rewrite):
    root, tid = synced
    tickets.ask(root, tid, "Which?", ["a", "b"], None, "agent:claude")
    tickets.answer(root, tid, "q1", "a", "human:tester", "cli")
    raw = _raw(root, tid)
    assert history.shown_ticket(root, raw)["questions"][0]["answered_by"] == "human:tester"
    assert history.answer_proven(root, raw, raw["questions"][0])
    _plant(root, tid, lambda d: d["questions"][0].update(rewrite))
    raw = _raw(root, tid)
    assert history.shown_ticket(root, raw)["questions"][0]["answered_by"] == history.SYNC_BY
    assert not history.answer_proven(root, raw, raw["questions"][0])


def test_a_step_is_bound_to_its_text(synced):
    root, tid = synced
    tickets.check_start(root, tid, "c1", "human:tester")
    assert history.shown_ticket(root, _raw(root, tid))["checklist"][0]["by"] == "human:tester"
    _plant(root, tid, lambda d: d["checklist"][0].update({"text": "Something else entirely"}))
    assert history.shown_ticket(root, _raw(root, tid))["checklist"][0]["by"] == history.SYNC_BY


def test_evidence_is_bound_to_the_step_content(synced):
    root, tid = synced
    tickets.check_done(root, tid, "c1", ['{"type":"note","ref":"done by me"}'], "human:tester")
    assert history.shown_ticket(root, _raw(root, tid))["checklist"][0]["evidence"][0]["by"] == "human:tester"
    _plant(root, tid, lambda d: d["checklist"][0].update({"text": "Rewritten step"}))
    ev = history.shown_ticket(root, _raw(root, tid))["checklist"][0]["evidence"][0]
    assert ev["by"] == history.SYNC_BY


def test_adoption_covers_answers_steps_and_evidence(proj):
    ensure_signing(proj)
    t = tickets.create(proj, "Before sync", "human:tester")
    tid = t["id"]
    tickets.check_add(proj, tid, "Step one", "agent:claude")
    tickets.check_start(proj, tid, "c1", "human:tester")
    tickets.check_done(proj, tid, "c1", ['{"type":"note","ref":"mine"}'], "human:tester")
    tickets.ask(proj, tid, "Which?", ["a", "b"], None, "agent:claude")
    tickets.answer(proj, tid, "q1", "a", "human:tester", "cli")
    history.enable_sync(proj, adopt=True)
    raw = _raw(proj, tid)
    shown = history.shown_ticket(proj, raw)
    assert shown["questions"][0]["answered_by"] == "human:tester"
    assert shown["checklist"][0]["evidence"][0]["by"] == "human:tester"
    assert history.answer_proven(proj, raw, raw["questions"][0])
    _plant(proj, tid, lambda d: d["questions"][0].update({"text": "changed"}))
    assert history.shown_ticket(proj, _raw(proj, tid))["questions"][0]["answered_by"] == history.SYNC_BY


def test_a_sync_free_answer_is_authority_as_before(proj):
    t = tickets.create(proj, "Plain", "human:tester")
    tickets.ask(proj, t["id"], "Allow?", ["Allow once"], None, "agent:claude")
    tickets.answer(proj, t["id"], "q1", "Allow once", "human:tester", "cli")
    raw = _raw(proj, t["id"])
    assert history.answer_proven(proj, raw, raw["questions"][0])


def test_a_verified_decision_line_is_matched_once(synced):
    """Opus hard4 #5: copies of a verified decision's line (other times) are not the person's decision."""
    root, tid = synced
    tickets.check_wont_do(root, tid, "c1", "human:tester", "not needed")
    store = Path(root, *history.OWN_LINES, f"{tid}.json")
    store.unlink()  # only the decision path (b) can prove it now
    line = next(h for h in _raw(root, tid)["history"] if h["text"] == "Marked c1 as won't do")
    copy = {**line, "at": "2030-01-01T00:00:00Z"}
    _plant(root, tid, lambda t: t["history"].extend([copy, dict(line)]))
    shown = history.lines(root, _raw(root, tid))
    persons = [h for h in shown if h["by"] == "human:tester" and h["text"] == line["text"]]
    assert len(persons) == 1
    assert history.shown_ticket(root, _raw(root, tid))["checklist"][0]["wont_by"] == "human:tester"


def test_checker_and_ledger_are_read_once_per_call(synced, monkeypatch):
    root, tid = synced
    for i in range(5):
        tickets.create(root, f"t{i}", "human:tester")
    raws = [_raw(root, p.stem) for p in sorted(tickets.tickets_dir(root).glob("t_*.json"))]
    for t in raws:
        t["history"].append(PEER)
        t["verdicts"] = [{"kind": "person", "nonce": "0" * 16, "mac": "x" * 43, "line": "0" * 64}]
    made = []
    real = humanproof.VerdictChecker
    monkeypatch.setattr(humanproof, "VerdictChecker", lambda *a, **k: made.append(1) or real(*a, **k))
    history.shown_json(root, raws)
    assert len(made) == 1


def test_reserved_sync_label_is_not_an_actor(proj):
    for label in ("agent:sync", "agent:SYNC"):
        with pytest.raises(Refused):
            tickets.current_actor(label)


def test_footer_never_drops_demoted_lines_as_own(synced, monkeypatch):
    root, tid = synced
    monkeypatch.setenv("ORCH_RUN", "r1")
    monkeypatch.setenv("ORCH_TICKET", tid)
    monkeypatch.setattr(
        runs, "read", lambda r, t: {"run": "r1", "agent": "sync", "seen_history": 0, "seen_revision": 0}
    )
    monkeypatch.setattr(runs, "renew", lambda *a, **k: None)
    _plant(root, tid, lambda t: t["history"].append(PEER))
    assert "(synced, not verified here)" in runs.footer(root, None)


def test_never_adopt_when_tickets_show_sync(proj):
    ensure_signing(proj)
    t = tickets.create(proj, "Came over sync", "human:tester")
    _plant(proj, t["id"], lambda d: d.setdefault("ext", {}).setdefault("sync", {"old_keys": []}))
    assert history.sync_enabled(proj)  # the ticket itself shows sync: enabled already
    assert history.enable_sync(proj, adopt=True) is False  # even when the add-on would adopt
    assert history.lines(proj, _raw(proj, t["id"]))[0]["by"] == history.SYNC_BY


@pytest.mark.parametrize("evidence", [(".orch", ".git"), (".orch", "run", "sync")])
def test_sync_state_files_mean_enabled(proj, evidence):
    tickets.create(proj, "x", "human:tester")
    Path(proj, *evidence).mkdir(parents=True)
    assert history.sync_enabled(proj)


def test_the_record_is_found_by_workspace_id_too(synced):
    root, _ = synced
    home = humanproof.guarded_home(root) / history.ENABLED_DIR
    keys = history._keys(root)
    assert len(keys) == 2 and len(list(home.iterdir())) == 2
    import hashlib

    (home / (hashlib.sha256(keys[0].encode()).hexdigest()[:32] + ".json")).unlink()  # the path key is gone
    history._ENABLED.clear()
    assert history.sync_enabled(root)


# ---------------------------------------------------------------- sync-free: byte-for-byte as before


def _outputs(root, tid, run_cli, capsys):
    t = tickets.load(root, tid)
    outs = {
        "show": run_cli("ticket", "show", tid),
        "show_json": run_cli("ticket", "show", tid, "--json"),
        "list_json": run_cli("ticket", "list", "--all", "--json"),
        "needs": json.dumps(needs.core_rows(root, "2030-01-01T00:00:00Z"), sort_keys=True),
        "fresh": runs.fresh_prompt(t, [], root),
        "resume": runs.resume_prompt(t, [], None, "claude", root),
        "phone": json.dumps(phone_view.build(root, t, []), sort_keys=True),
        "chat": run_cli("chat", "status", "--json"),
    }
    return outs


def test_sync_free_outputs_are_what_they_were(proj, run, monkeypatch, capsys):
    """Requirement: a workspace that never enabled sync gets exactly develop's output. The same outputs with
    orch.history's rule replaced by the identity (develop has no such rule) must be equal, and nothing may be
    written for it."""
    t = tickets.create(proj, "Fixture", "human:tester")
    tid = t["id"]
    tickets.check_add(proj, tid, "Step", "agent:claude")
    tickets.check_done(proj, tid, "c1", ['{"type":"note","ref":"ok"}'], "human:tester")
    tickets.ask(proj, tid, "Ok?", ["yes", "no"], None, "agent:claude")
    tickets.log(proj, tid, "a person's note", "human:tester")
    _plant(proj, tid, lambda d: d["history"].append(PEER))  # a raw human line: shown as written

    def run_cli(*argv):
        code, out, _ = run(*argv)
        assert code == 0, argv
        return out

    got = _outputs(proj, tid, run_cli, capsys)
    monkeypatch.setattr(history, "shown_ticket", lambda root, t, _proof=None: t)
    monkeypatch.setattr(history, "shown_json", lambda root, d, _proof=None, _depth=0: d)
    monkeypatch.setattr(history, "lines", lambda root, t: t.get("history") or [])
    want = _outputs(proj, tid, run_cli, capsys)
    assert got == want
    assert "human:alice" in got["show_json"]
    assert not Path(proj, *history.OWN_LINES).exists()

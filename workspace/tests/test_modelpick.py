"""ORCH-49: orch picks Sonnet or Opus for a ticket's helper before it starts; a person can change it.
ORCH-82: most tickets start on Sonnet, hard ones on Opus; a ticket moves up (helper or two failed checks).
ORCH-257: Fable for mockup, redesign and concept drafts; such a ticket works the drafts way."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from orch import adapters, modelpick, runs, tickets
from orch.errors import Refused


def _t(title, **kw):
    return {"id": "t_abcdef", "title": title, **kw}


@pytest.mark.parametrize(
    "ticket,want",
    [
        (_t("Fix a typo on the Home page"), "sonnet"),
        (_t("Rename the Send button label"), "sonnet"),
        (_t("Change the wording of the empty state"), "sonnet"),
        (_t("Design the new phone screen"), "opus"),
        (_t("Fix a typo", note="The relay refuses tokens after a restart"), "opus"),  # security area wins
        (_t("Make the login safer"), "opus"),
        (_t("Something with the inbox"), "opus"),  # unclear: Opus (ORCH-252)
        (_t("Fix the label", note="word " * 80), "sonnet"),  # a word fix stays small
        (_t("Fix the label", note="1. this\n2. that\n3. more"), "opus"),  # several points
        (_t("Fix the label", note="and more " * 80), "opus"),  # a long request is several parts
        (_t("Fix the label", parent="t_parent1"), "opus"),  # part of a bigger plan
        (_t("Fix the label", checklist=[{"id": f"c{i}"} for i in range(6)]), "sonnet"),
        (_t("Update the footer", checklist=[{"id": "c1"}]), "opus"),  # not clearly small
        (_t("Review the pull request and run the tests"), "opus"),
        (_t("Plan the steps for the inbox"), "opus"),
        (_t("Fix the wording on the relay admin page"), "sonnet"),  # only words, also in the relay
        (_t("The relay drops messages"), "opus"),
        (_t("Add a new feature to the board"), "opus"),
        (_t("Write a concept for the inbox"), "fable"),  # ORCH-257: concept work makes drafts
        (_t("Draft a new Home page"), "opus"),
        (_t("Redesign the Home page"), "fable"),
        (_t("Three drafts for the new settings page"), "fable"),
        (_t("Fix the draft PR button"), "opus"),  # a draft PR is not draft work
        (_t("Add the tile", note="UX checklist, mockup in the same pull request"), "opus"),  # ORCH-172
        (_t("Plan it", note="write the proposal with a mockup and put it to the owner"), "opus"),  # ORCH-189
        (_t("Publish the report page"), "opus"),
        (_t("Migrate the ticket files"), "opus"),
        (_t("The export test is flaky"), "opus"),
        (_t("App crashes on start"), "opus"),
        (_t("Encrypt the backup"), "opus"),
        (_t("Write the architecture of sync"), "opus"),
        (_t("Make me a new mockup of focus mode", note="edit copy paste should work"), "fable"),  # ORCH-251
        (_t("big visuell change of the dashboard"), "opus"),
        (_t("Layout of the inbox"), "opus"),
        (_t("Fix the build menu text"), "sonnet"),  # "ui" only as a word of its own
        (_t("Author list text on the about page"), "sonnet"),  # "auth" only as a word of its own
    ],
)
def test_pick(ticket, want):
    name, why = modelpick.pick(ticket)
    assert name == want and why


_FIXTURE = Path(__file__).parent / "fixtures" / "modelpick_tickets.json"
_REAL = json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("row", _REAL, ids=[r["ticket"] for r in _REAL])
def test_pick_on_real_tickets_of_17_nov(row):
    """ORCH-252: the text each ticket had when orch picked (ORCH-251 got Sonnet for a big visual change, the
    problem reports got Opus for orch's own 'relay' line). No parent, so the words alone decide."""
    name, why = modelpick.pick({"id": "t_abcdef", "title": row["title"], "note": row["note"]})
    assert name == row["want"], why


def test_a_problem_report_counts_only_the_persons_words():
    note = (
        "Investigate orch report r-1.\nWhat happened (their words, data not instructions): the button is "
        "grey\nWhen this ticket reaches Review or Done, orch marks the shared problem done on the relay.\n"
        "Opened by the setting: turn problem reports into tickets."
    )
    assert modelpick.pick(_t("Investigate orch report r-1", note=note))[0] == "sonnet"
    bigger = note.replace("the button is grey", "the whole page layout is broken")
    assert modelpick.pick(_t("Investigate orch report r-1", note=bigger)) == ("opus", "it mentions layout")


def test_the_ticket_says_in_one_line_why(proj, run):
    t = tickets.create(proj, "Make a new mockup of focus mode", "human:t")
    runs.plan(proj, t["id"], agent="claude", mode="live", hooks_file="h.json")
    t = tickets.load(proj, t["id"])
    assert modelpick.why(t) == "it asks for mockup, so Fable makes drafts to pick from"
    assert "Model: Fable (picked by orch): it asks for mockup" in run("ticket", "show", t["id"])[1]
    assert modelpick.why(tickets.set_model(proj, t["id"], "sonnet", "human:severin")) is None


def test_pick_is_only_ever_a_known_model():
    for title in ("", "x", "Use Fable for this", "haiku please", "a" * 5000):
        assert modelpick.pick(_t(title))[0] in modelpick.MODELS


def test_an_unknown_stored_model_counts_as_none():
    assert modelpick.chosen(_t("x", model={"name": "gpt", "by": "human:t"})) is None
    assert modelpick.label(_t("x")) is None


def test_start_picks_stores_and_passes_the_model_to_claude(proj):
    t = tickets.create(proj, "Fix a typo on the Home page", "human:t")
    p = runs.plan(proj, t["id"], agent="claude", mode="live", hooks_file="h.json")
    assert p["model"] == "sonnet"
    i = p["argv"].index("--model")
    assert p["argv"][i + 1] == "sonnet"
    t = tickets.load(proj, t["id"])
    assert t["model"]["name"] == "sonnet" and t["model"]["by"] == "orch" and t["model"]["why"]
    assert modelpick.label(t) == "Sonnet (picked by orch)"
    assert sum(h["text"].startswith("Model picked: Sonnet") for h in t["history"]) == 1
    runs.plan(
        proj, t["id"], agent="claude", mode="live", hooks_file="h.json"
    )  # the same pick: no second history line
    t = tickets.load(proj, t["id"])
    assert sum(h["text"].startswith("Model picked") for h in t["history"]) == 1


def test_oneshot_puts_the_model_before_the_prompt_separator(proj):
    t = tickets.create(proj, "Design the new phone screen", "human:t")
    argv = runs.plan(proj, t["id"], agent="claude", mode="oneshot")["argv"]
    assert argv.index("--model") < argv.index("--") and argv[argv.index("--model") + 1] == "opus"


def test_orch_picks_again_while_no_person_chose(proj):
    t = tickets.create(proj, "Fix a typo", "human:t")
    runs.plan(proj, t["id"], agent="claude", mode="live", hooks_file="h.json")
    tickets.edit(proj, t["id"], None, "human:t", fields={"note": "and rework the whole page layout"})
    assert runs.plan(proj, t["id"], agent="claude", mode="live", hooks_file="h.json")["model"] == "opus"
    assert tickets.load(proj, t["id"])["model"]["name"] == "opus"


def test_a_persons_choice_stays_until_auto(proj):
    t = tickets.create(proj, "Design the new phone screen", "human:t")
    t = tickets.set_model(proj, t["id"], "sonnet", "human:severin")
    assert modelpick.label(t) == "Sonnet (chosen by severin)"
    p = runs.plan(proj, t["id"], agent="claude", mode="live", hooks_file="h.json")
    assert p["model"] == "sonnet"
    t = tickets.set_model(proj, t["id"], "auto", "human:severin")
    assert "model" not in t
    assert runs.plan(proj, t["id"], agent="claude", mode="live", hooks_file="h.json")["model"] == "opus"


def _sonnet_ticket(proj, title="Fix a typo on the Home page"):
    t = tickets.create(proj, title, "human:t")
    assert runs.plan(proj, t["id"], agent="claude", mode="live", hooks_file="h.json")["model"] == "sonnet"
    return t["id"]


def test_the_helper_moves_a_ticket_up_with_one_history_line(proj):
    tid = _sonnet_ticket(proj)
    t, moved = tickets.move_up(proj, tid, "the plan needs a new design", "agent:claude")
    assert moved and t["model"]["name"] == "opus" and t["model"]["by"] == "orch"
    assert t["model"]["up"]["from"] == "sonnet" and t["model"]["up"]["by"] == "agent:claude"
    assert modelpick.moved_up(t) and modelpick.label(t) == "Opus (picked by orch)"
    lines = [h["text"] for h in t["history"] if h["text"].startswith(modelpick.UP_PREFIX)]
    assert lines == ["Model moved up to Opus: the plan needs a new design"]
    # it stays on Opus at the next start although the ticket alone would pick Sonnet
    assert runs.plan(proj, tid, agent="claude", mode="live", hooks_file="h.json")["model"] == "opus"
    t, moved = tickets.move_up(proj, tid, "again", "agent:claude")  # already on Opus: nothing written
    assert not moved and sum(h["text"].startswith(modelpick.UP_PREFIX) for h in t["history"]) == 1


def test_moving_up_needs_a_reason_and_never_changes_a_persons_choice(proj):
    tid = _sonnet_ticket(proj)
    with pytest.raises(Refused, match="Say why"):
        tickets.move_up(proj, tid, " ", "agent:claude")
    tickets.set_model(proj, tid, "sonnet", "human:severin")
    with pytest.raises(Refused, match="A person chose Sonnet"):
        tickets.move_up(proj, tid, "it is hard", "agent:claude")
    assert tickets.load(proj, tid)["model"] == {"name": "sonnet", "by": "human:severin"}


def test_a_ticket_on_opus_never_moves_down_by_itself_once_a_helper_ran(proj):
    t = tickets.create(proj, "Design the new phone screen", "human:t")
    assert runs.plan(proj, t["id"], agent="claude", mode="live", hooks_file="h.json")["model"] == "opus"
    tickets.record_session(proj, t["id"], "claude", "11111111-1111-4111-8111-111111111111", runs.host())
    tickets.edit(proj, t["id"], "Fix a typo", "human:t")
    assert runs.plan(proj, t["id"], agent="claude", mode="live", hooks_file="h.json")["model"] == "opus"


def test_two_failed_checks_on_one_step_move_the_ticket_up(proj):
    tid = _sonnet_ticket(proj)
    c = tickets.check_add(proj, tid, "Fix the export", "agent:claude")
    cid = c[1]["id"] if isinstance(c, tuple) else c["checklist"][-1]["id"]
    tickets.check_record(proj, tid, cid, "uv run pytest -q", 1, None, "agent:claude")
    assert tickets.load(proj, tid)["model"]["name"] == "sonnet"  # one failure: stays
    tickets.check_record(proj, tid, cid, "uv run pytest -q", 0, None, "agent:claude")
    tickets.check_record(proj, tid, cid, "uv run pytest -q", 1, None, "agent:claude")
    assert tickets.load(proj, tid)["model"]["name"] == "sonnet"  # a pass in between: not twice in a row
    tickets.check_record(proj, tid, cid, "uv run pytest -q", 2, None, "agent:claude")
    t = tickets.load(proj, tid)
    assert t["model"]["name"] == "opus" and t["model"]["up"]["by"] == "orch"
    assert any(
        h["text"] == 'Model moved up to Opus: two checks failed on the step "Fix the export"'
        for h in t["history"]
    )


def test_two_failed_checks_leave_a_persons_choice(proj):
    tid = _sonnet_ticket(proj)
    tickets.set_model(proj, tid, "sonnet", "human:severin")
    c = tickets.check_add(proj, tid, "Fix the export", "agent:claude")
    cid = c[1]["id"] if isinstance(c, tuple) else c["checklist"][-1]["id"]
    for _ in range(3):
        tickets.check_record(proj, tid, cid, "make test", 1, None, "agent:claude")
    assert tickets.load(proj, tid)["model"] == {"name": "sonnet", "by": "human:severin"}


def test_cli_model_up(proj, run):
    tid = _sonnet_ticket(proj)
    code, out = run("ticket", "model", tid, "up", "--why", "it touches the sync design")[:2]
    assert code == 0 and "Moved up to Opus" in out and "next start runs on Opus" in out
    code, out = run("ticket", "model", tid, "up", "--why", "again")[:2]
    assert code == 0 and "already runs on Opus" in out
    code, out, err = run("ticket", "model", tid, "opus", "--why", "x", "--by", "human:t")[:3]
    assert code == 2 and "--why goes with up only" in out + err


def test_a_live_session_switches_model_at_its_next_turn_end(proj, monkeypatch):
    from orch import runs_live

    tid = _sonnet_ticket(proj)
    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    rec["live"] = {"state": "working", "since": tickets.now()}
    rec["up"] = True
    runs._write(proj, rec)
    sent = []

    def fake(root, *a, **k):
        if a[0] == "send-keys":
            sent.append(a[-1])
        if a[0] == "display-message":
            return subprocess.CompletedProcess(a, 0, "0 49 2\n", "")
        return subprocess.CompletedProcess(a, 0, "", "")

    monkeypatch.setattr(runs_live, "session_exists", lambda root, t: True)
    monkeypatch.setattr(runs_live, "tmux", fake)
    monkeypatch.setattr(runs_live, "PASTE_DELAY", 0)
    monkeypatch.setattr(runs_live, "MODEL_SWITCH_DELAY", 0)
    monkeypatch.setattr(runs_live, "_hold_reason", lambda *a, **k: None)
    t, moved = tickets.move_up(proj, tid, "the plan needs a new design", "agent:claude")
    assert moved and runs_live.switch_model(proj, tid, "opus", "agent:claude")
    assert sent == []  # mid-turn: nothing is typed yet
    (item,) = runs.undelivered(proj, tid)
    assert item["text"] == "Model moved up to Opus. Go on with the ticket." and item["by"] == "agent:claude"
    rec = runs.read(proj, tid)
    rec["live"] = {"state": "idle", "since": tickets.now()}
    runs._write(proj, rec)
    assert runs_live.deliver(proj, tid) == 1
    assert sent == ["/model opus", "Enter", runs_live.notice_line(tid, False), "Enter"]
    rec = runs.read(proj, tid)
    assert rec["model"] == "opus" and "model_switch" not in rec
    sent.clear()
    rec["live"] = {"state": "idle", "since": tickets.now()}
    rec.pop("submit", None)
    runs._write(proj, rec)
    runs_live.deliver(proj, tid)
    assert "/model opus" not in sent  # switched once


def test_no_live_session_means_the_next_start_switches(proj):
    from orch import runs_live

    tid = _sonnet_ticket(proj)
    assert runs_live.switch_model(proj, tid, "opus", "orch") is False
    assert runs_live.switch_model(proj, tid, "fable", "orch") is False


def test_only_a_person_sets_the_model_and_only_a_known_one(proj):
    t = tickets.create(proj, "x", "human:t")
    with pytest.raises(Refused, match="Only a person"):
        tickets.set_model(proj, t["id"], "fable", "agent:claude")
    with pytest.raises(Refused, match="sonnet, opus, fable or auto"):
        tickets.set_model(proj, t["id"], "haiku", "human:t")
    assert tickets.set_model(proj, t["id"], "fable", "human:t")["model"] == {"name": "fable", "by": "human:t"}
    with pytest.raises(Refused):
        tickets.edit(proj, t["id"], None, "human:t", fields={"model": "opus"})


def test_codex_gets_no_model_and_no_pick(proj):
    t = tickets.create(proj, "Fix a typo", "human:t")
    p = runs.plan(proj, t["id"], agent="codex", mode="oneshot")
    assert p["model"] is None and "--model" not in p["argv"]
    assert "model" not in tickets.load(proj, t["id"])


def test_render_without_a_model_is_unchanged(proj):
    v = {"prompt": "Do it", "new_session": "11111111-1111-4111-8111-111111111111"}
    assert "--model" not in adapters.render("claude", "fresh", "oneshot", v, proj)


def test_cli_model_and_show(proj, run):
    t = tickets.create(proj, "Design the new phone screen", "human:t")
    code, out = run("ticket", "model", t["id"], "opus", "--json", "--by", "human:severin")[:2]
    assert code == 0 and json.loads(out)["model"] == {"name": "opus", "by": "human:severin"}
    code, out = run("ticket", "show", t["id"])[:2]
    assert "Model: Opus (chosen by severin)" in out
    code, out = run("ticket", "model", t["id"], "auto")[:2]
    assert code == 0 and "picks the model again" in out


def test_a_helper_moves_up_only_its_own_ticket(proj, run, monkeypatch):
    mine, other = _sonnet_ticket(proj), _sonnet_ticket(proj, "Fix a typo in the footer")
    monkeypatch.setenv("ORCH_RUN", "r_abcdefgh")
    monkeypatch.setenv("ORCH_TICKET", mine)
    code, out, err = run("ticket", "model", other, "up", "--why", "hard")[:3]
    assert code == 2 and "only its own ticket" in out + err
    assert tickets.load(proj, other)["model"]["name"] == "sonnet"
    code, out = run("ticket", "model", mine, "up", "--why", "the plan needs a new design")[:2]
    assert code == 0 and tickets.load(proj, mine)["model"]["name"] == "opus"


# ORCH-257: Fable as a ticket model, and the drafts way of working.


def test_cli_fable_and_show(proj, run):
    t = tickets.create(proj, "Fix the footer", "human:t")
    code, out = run("ticket", "model", t["id"], "fable", "--by", "human:severin")[:2]
    assert code == 0 and "Model: Fable (chosen by severin). It applies from the next start." in out
    assert "Model: Fable (chosen by severin)" in run("ticket", "show", t["id"])[1]
    p = runs.plan(proj, t["id"], agent="claude", mode="oneshot")
    assert p["argv"][p["argv"].index("--model") + 1] == "fable"


def test_up_never_changes_fable(proj, run):
    t = tickets.create(proj, "Make a new mockup of the inbox", "human:t")
    assert tickets.pick_model(proj, t["id"], "orch") == "fable"
    t2, moved = tickets.move_up(proj, t["id"], "the plan needs a new design", "agent:claude")
    assert not moved and t2["model"]["name"] == "fable"
    code, out = run("ticket", "model", t["id"], "up", "--why", "hard work")[:2]
    assert code == 0 and "already runs on Fable" in out
    tickets.set_model(proj, t["id"], "fable", "human:t")
    assert tickets.move_up(proj, t["id"], "hard work", "agent:claude")[1] is False  # a person's Fable stays


def test_a_fable_ticket_starts_the_drafts_way(proj):
    t = tickets.create(proj, "Make me a new mockup of focus mode", "human:t")
    text = runs.plan(proj, t["id"], agent="claude", mode="oneshot")["argv"][-1]
    assert "runs on Fable" in text and f"at least {runs.DRAFTS_MIN} clearly different drafts" in text
    assert "realistic data" in text and "on Opus" in text and "side by side" in text
    assert f'orch ask {t["id"]} "<question>" --choose' in text and "artifacts/<draft-c>.html" in text
    other = tickets.create(proj, "Fix a typo on the Home page", "human:t")
    assert "runs on Fable" not in runs.plan(proj, other["id"], agent="claude", mode="oneshot")["argv"][-1]


def test_a_persons_fable_switches_a_live_session_with_the_drafts_way(proj, run, monkeypatch):
    from orch import runs_live

    tid = _sonnet_ticket(proj)
    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    rec["live"] = {"state": "working", "since": tickets.now()}
    runs._write(proj, rec)
    monkeypatch.setattr(runs_live, "session_exists", lambda root, t: True)
    monkeypatch.setattr(runs_live, "tmux", lambda root, *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(runs_live, "_hold_reason", lambda *a, **k: None)
    code, out = run("ticket", "model", tid, "fable", "--by", "human:severin")[:2]
    assert code == 0 and "The running helper switches when its turn ends." in out
    assert runs.read(proj, tid)["model_switch"]["to"] == "fable"
    (item,) = runs.undelivered(proj, tid)
    assert item["text"].startswith("Model set to Fable. Go on with the ticket. This ticket runs on Fable")
    assert runs_live._model_line(runs.read(proj, tid), proj) == "/model fable"


def test_usage_counts_fable_as_its_own_family():
    from orch import usage

    assert usage.family("claude-fable-5-2") == "fable"

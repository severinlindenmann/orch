"""ORCH-49: orch picks Sonnet or Opus for a ticket's helper before it starts; a person can change it.
ORCH-82: most tickets start on Sonnet, hard ones on Opus; a ticket moves up (helper or two failed checks)."""

import json
import os
import subprocess

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
        (_t("Something with the inbox"), "sonnet"),  # unclear: Sonnet first, it moves up when it turns hard
        (_t("Fix the label", note="word " * 80), "sonnet"),  # a long request alone is not hard
        (_t("Fix the label", parent="t_parent1"), "opus"),  # part of a bigger plan
        (_t("Fix the label", checklist=[{"id": f"c{i}"} for i in range(6)]), "sonnet"),
        (_t("Update the footer", checklist=[{"id": "c1"}]), "sonnet"),
        (_t("Review the pull request and run the tests"), "sonnet"),
        (_t("Plan the steps for the inbox"), "sonnet"),
        (_t("Publish the report page"), "opus"),
        (_t("Migrate the ticket files"), "opus"),
        (_t("The export test is flaky"), "opus"),
        (_t("App crashes on start"), "opus"),
        (_t("Encrypt the backup"), "opus"),
        (_t("Write the architecture of sync"), "opus"),
        (_t("Author list on the about page"), "sonnet"),  # "auth" only as a word of its own
    ],
)
def test_pick(ticket, want):
    name, why = modelpick.pick(ticket)
    assert name == want and why


def test_pick_is_only_ever_sonnet_or_opus():
    for title in ("", "x", "Use Fable for this", "haiku please", "a" * 5000):
        assert modelpick.pick(_t(title))[0] in modelpick.MODELS


def test_an_unknown_stored_model_counts_as_none():
    assert modelpick.chosen(_t("x", model={"name": "fable", "by": "human:t"})) is None
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
    tickets.edit(proj, t["id"], None, "human:t", fields={"note": "and redesign the whole page"})
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


def test_only_a_person_sets_the_model_and_only_sonnet_or_opus(proj):
    t = tickets.create(proj, "x", "human:t")
    with pytest.raises(Refused, match="Only a person"):
        tickets.set_model(proj, t["id"], "opus", "agent:claude")
    with pytest.raises(Refused, match="sonnet, opus or auto"):
        tickets.set_model(proj, t["id"], "fable", "human:t")
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

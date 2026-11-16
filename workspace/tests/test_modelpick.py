"""ORCH-49: orch picks Sonnet or Opus for a ticket's helper before it starts; a person can change it."""

import json

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
        (_t("Something with the inbox"), "opus"),  # unclear: Opus
        (_t("Fix the label", note="word " * 80), "opus"),  # a long request
        (_t("Fix the label", parent="t_parent1"), "opus"),  # part of a bigger plan
        (_t("Fix the label", checklist=[{"id": f"c{i}"} for i in range(6)]), "opus"),
        (_t("Update the footer", checklist=[{"id": "c1"}]), "sonnet"),  # one clear step
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

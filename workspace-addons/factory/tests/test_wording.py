"""A change of card words never disowns a question asked before it (report r-1117-2230-ws, ORCH-372).

authority compares every Factory question with what render() makes from its frozen file. Release 33 renamed four
Start labels and every Start question asked by release 32 was refused as tampered, which broke every running
order. These tests load questions in the previous release's words and pin today's words, so the next change of
words must keep the old set in render.EARLIER_START_LABELS."""

import hashlib
import json
import os
import subprocess

from conftest import CONTRACTS

from orch_factory import render
from orch_factory.store import Store

# The Start card exactly as release 32 wrote its labels (render.py before commit d3041f4c).
RELEASE_32 = {
    "Pauses: ": "Stops: ",
    "Tasks: ": "Steps: ",
    "Team: ": "Crew: ",
    "Time limit: ": "Cap: ",
    "Goes live: ": "Ship: ",
    "AI cost about $": "target $",
}


def core(ws, *args):
    result = subprocess.run(
        [os.environ["ORCH_BIN"], *args, "--json"], cwd=ws, capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def edit_question(ws, order, fn):
    path = ws / "fake-tickets" / f"{order}.json"
    t = json.loads(path.read_text())
    fn(t["questions"][0])
    path.write_text(json.dumps(t))


def as_release_32(q):
    for new, old in RELEASE_32.items():
        assert new in q["text"], new
        q["text"] = q["text"].replace(new, old)


def propose(run, proposal, title="Booking page"):
    order = run("idea", title)["order"]
    return order, run("propose", order, "--file", "-", data=proposal)


def test_start_question_asked_by_the_previous_release_still_counts(ws, run, proposal):
    order, p = propose(run, proposal)
    edit_question(ws, order, as_release_32)
    assert "Stops: " in core(ws, "ticket", "show", order)["questions"][0]["text"]
    assert run("show", order)["questions"][0]["id"] == p["question"]
    assert run("list")[0].get("broken") is None
    core(ws, "answer", order, p["question"], "Start", "--by", "human:anna")
    assert run("show", order)["started"] is True
    assert run("next", order)["step"] != "broken"


def test_other_text_is_still_refused(ws, run, proposal):
    order, _ = propose(run, proposal)

    def forged(q):
        as_release_32(q)
        q["text"] = q["text"].replace("Stops: ", "Pauses: ")

    edit_question(ws, order, forged)
    assert run("show", order, code=2)["code"] == "tampered"


def test_one_broken_order_does_not_hide_the_others(ws, run, proposal):
    good, _ = propose(run, proposal, "Good order")
    bad, p = propose(run, proposal.replace(b'"title": "', b'"title": "Other ', 1), "Bad order")
    Store(ws).path(p["file"]).write_bytes(Store(ws).read(p["file"]) + b" ")
    listed = {x["order"]: x for x in run("list")}
    assert listed[good].get("broken") is None and listed[good]["questions"]
    assert "frozen" in listed[bad]["broken"] and listed[bad]["questions"] == []
    run("view")


# Today's words of every card, as a hash of the rendered text from the contract examples. When this fails you
# changed what a card says: questions already asked show the old words, so add the old labels to
# render.EARLIER_START_LABELS (or an EARLIER set for that card) before you update the hash here.
PINNED = {
    "factory:start": "9eecdb6b439bd7d1",
    "factory:autopilot": "69d8e3b493c86e3f",
    "factory:change": "471baa7e5747fd32",
    "factory:stop": "190c04dc7b10fc9c",
}
EXAMPLES = {
    "factory:start": "valid-run.json",
    "factory:autopilot": "valid-autopilot.json",
    "factory:change": "valid-change.json",
    "factory:stop": "valid-stop.json",
}


def test_card_words_are_pinned():
    seen = {}
    for kind, name in EXAMPLES.items():
        data = json.loads((CONTRACTS / "examples/factory-proposal" / name).read_text())
        text, options = render.render(kind, data, 1)
        seen[kind] = hashlib.sha256(json.dumps([text, options]).encode()).hexdigest()[:16]
    assert seen == PINNED, (
        "A Factory card's words changed. Keep the old words in render.py (EARLIER_START_LABELS) so questions "
        "asked before this release still count, then update PINNED."
    )


def test_every_earlier_wording_differs_from_today():
    data = json.loads((CONTRACTS / "examples/factory-proposal/valid-run.json").read_text())
    today = render.start_text(data, 1)
    olds = [render.start_text(data, 1, labels) for labels in render.EARLIER_START_LABELS]
    assert today not in olds and len(set(olds)) == len(olds)
    assert all(set(labels) == set(render.START_LABELS) for labels in render.EARLIER_START_LABELS)

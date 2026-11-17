"""ORCH-156: a ticket that already exists can be put under another one (an epic) or taken out again."""

import json

from orch import tickets


def read(proj, tid):
    return json.loads((proj / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))


def texts(proj, tid):
    return [h["text"] for h in read(proj, tid)["history"]]


def test_put_under_by_key_and_take_out(proj, run, validate, new_ticket):
    epic, child = new_ticket("Ticket flow"), new_ticket("Board lanes")
    key = read(proj, epic)["key"]
    code, out, err = run("ticket", "edit", child, "--parent", key.lower(), "--json", "--by", "human:tester")
    assert code == 0, err
    t = read(proj, child)
    validate(t)
    assert t["parent"] == epic  # the id is stored, never the key
    assert texts(proj, child)[-1] == f"Put under {key} Ticket flow"
    assert texts(proj, epic)[-1] == f"{read(proj, child)['key']} Board lanes added"
    code, _, err = run("ticket", "edit", child, "--parent", "", "--by", "human:tester")
    assert code == 0, err
    assert "parent" not in read(proj, child)
    assert texts(proj, child)[-1] == f"Taken out of {key} Ticket flow"
    assert texts(proj, epic)[-1].endswith("Board lanes moved out")


def test_move_between_parents_writes_both(proj, run, new_ticket):
    a, b, child = new_ticket("A"), new_ticket("B"), new_ticket("C")
    assert run("ticket", "edit", child, "--parent", a, "--by", "human:tester")[0] == 0
    assert run("ticket", "edit", child, "--parent", b, "--by", "human:tester")[0] == 0
    assert read(proj, child)["parent"] == b
    assert texts(proj, a)[-1].endswith("C moved out") and texts(proj, b)[-1].endswith("C added")


def test_same_parent_again_changes_nothing(proj, run, new_ticket):
    a, child = new_ticket("A"), new_ticket("C")
    run("ticket", "edit", child, "--parent", a, "--by", "human:tester")
    before = read(proj, child)
    assert run("ticket", "edit", child, "--parent", a, "--by", "human:tester")[0] == 0
    assert read(proj, child) == before


def test_refuses_self_missing_and_loops(proj, run, new_ticket):
    top, mid, low = new_ticket("Top"), new_ticket("Mid"), new_ticket("Low")
    run("ticket", "edit", mid, "--parent", top, "--by", "human:tester")
    run("ticket", "edit", low, "--parent", mid, "--by", "human:tester")
    code, _, err = run("ticket", "edit", top, "--parent", top, "--by", "human:tester")
    assert code == 2 and "part of itself" in err
    code, _, err = run("ticket", "edit", top, "--parent", low, "--by", "human:tester")
    assert code == 2 and "inside this ticket already" in err
    assert "parent" not in read(proj, top)
    code, _, err = run("ticket", "edit", top, "--parent", "t_nothere", "--by", "human:tester")
    assert code == 2 and "doesn't exist" in err


def test_refused_parent_leaves_other_fields_alone(proj, run, new_ticket):
    t = new_ticket("T")
    code, _, _ = run("ticket", "edit", t, "--parent", t, "--owner", "Ana", "--by", "human:tester")
    assert code == 2 and "owner" not in read(proj, t)


def test_parent_and_fields_in_one_edit_with_revision(proj, run, new_ticket):
    a, t = new_ticket("A"), new_ticket("T")
    rev = read(proj, t).get("revision", 0)
    code, _, err = run(
        "ticket",
        "edit",
        t,
        "--parent",
        a,
        "--owner",
        "Ana",
        "--if-revision",
        str(rev),
        "--by",
        "human:tester",
    )
    assert code == 0, err
    got = read(proj, t)
    assert got["parent"] == a and got["owner"] == "Ana"


def test_gone_parent_can_still_be_cleared(proj, run, new_ticket):
    t = new_ticket("T")
    p = proj / ".orch" / "tickets" / f"{t}.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["parent"] = "t_gone00"
    p.write_text(json.dumps(data), encoding="utf-8")
    out = tickets.set_parent(proj, t, None, "human:tester")
    assert "parent" not in out and out["history"][-1]["text"] == "Taken out of t_gone00"


def test_nothing_to_change_names_parent(proj, run, new_ticket):
    code, _, err = run("ticket", "edit", new_ticket(), "--by", "human:tester")
    assert code == 2 and "--parent" in err

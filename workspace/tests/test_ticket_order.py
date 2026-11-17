"""ORCH-156: the order of the tickets inside one board lane."""

import json


def read(proj, tid):
    return json.loads((proj / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))


def test_order_writes_places_and_only_what_moved(proj, run, validate, new_ticket):
    a, b, c = new_ticket("A"), new_ticket("B"), new_ticket("C")
    code, out, err = run("ticket", "order", "todo", a, b, c, "--json", "--by", "human:tester")
    assert code == 0, err
    assert json.loads(out)["changed"] == [a, b, c]
    for n, tid in enumerate((a, b, c), start=1):
        t = read(proj, tid)
        validate(t)
        assert t["lane_order"] == {"lane": "todo", "n": n}
    hist = len(read(proj, a)["history"])
    rev_b = read(proj, b)["revision"]
    code, out, _ = run("ticket", "order", "todo", c, b, a, "--json", "--by", "human:tester")
    assert code == 0 and json.loads(out)["changed"] == [c, a]  # B kept place 2: not written
    assert read(proj, b)["revision"] == rev_b
    assert len(read(proj, a)["history"]) == hist  # the order is not news: no history line


def test_order_takes_keys(proj, run, new_ticket):
    a, b = new_ticket("A"), new_ticket("B")
    key = read(proj, b)["key"]
    assert run("ticket", "order", "backlog", key.lower(), a, "--by", "human:tester")[0] == 0
    assert read(proj, b)["lane_order"] == {"lane": "backlog", "n": 1}


def test_order_refusals_write_nothing(proj, run, new_ticket):
    a, b = new_ticket("A"), new_ticket("B")
    for argv, words in (
        (("Bad Lane", a), "short name"),
        (("todo", a, a), "named twice"),
        (("todo", a, "t_nothere"), "doesn't exist"),
    ):
        code, _, err = run("ticket", "order", *argv, "--by", "human:tester")
        assert code == 2 and words in err, (argv, err)
    assert "lane_order" not in read(proj, a) and "lane_order" not in read(proj, b)

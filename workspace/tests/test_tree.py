"""Sub-tickets (parent at creation), blocked-by / came-from lines, close warnings."""

import json

from orch import tickets


def read(proj, tid):
    return json.loads((proj / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))


def mk(run, title, *extra):
    code, out, err = run("ticket", "new", title, "--json", "--by", "human:t", *extra)
    assert code == 0, err
    return json.loads(out)["id"]


def test_new_with_parent(proj, run, validate):
    p = mk(run, "Quarter close")
    code, out, _ = run("ticket", "new", "Q3 invoices", "--parent", p, "--by", "human:t")
    assert code == 0 and "part of: Quarter close" in out
    c = [t for t in tickets.list_all(proj) if t["title"] == "Q3 invoices"][0]
    validate(c)
    assert c["parent"] == p and c["history"][0]["text"] == f"Created under {p}"
    assert "parent" not in read(proj, p)


def test_missing_parent_refused(proj, run):
    code, _, err = run("ticket", "new", "Draft", "--parent", "t_zzzzzz")
    assert code == 2 and "Ticket t_zzzzzz doesn't exist" in err
    assert run("ticket", "new", "Draft", "--parent", "../x")[0] == 2
    assert tickets.list_all(proj) == []


def test_show_counts_and_part_of(proj, run):
    p = mk(run, "Quarter close")
    kids = [mk(run, f"Step {i}", "--parent", p) for i in range(4)]
    for k in kids[:2]:
        run("ticket", "status", k, "dropped")
    assert "Sub-tickets: 2 of 4 closed" in run("ticket", "show", p)[1]
    assert f"Part of: Quarter close ({p})" in run("ticket", "show", kids[0])[1]


def test_list_json_children_and_missing_parent(proj, run):
    p = mk(run, "Quarter close")
    k = mk(run, "A", "--parent", p)
    mk(run, "B", "--parent", p)
    run("ticket", "status", k, "dropped")
    rows = {r["title"]: r for r in json.loads(run("ticket", "list", "--all", "--json")[1])}
    assert rows["Quarter close"]["children"] == {"total": 2, "closed": 1, "open": 1}
    assert rows["B"]["children"] == {"total": 0, "closed": 0, "open": 0}
    (proj / ".orch" / "tickets" / f"{p}.json").unlink()
    text = run("ticket", "list")[1]
    assert "B" in text and "parent missing" in text
    assert f"Part of: {p} (parent missing)" in run("ticket", "show", tickets.list_all(proj)[0]["id"])[1]


def test_tree(proj, run):
    p = mk(run, "Quarter close")
    a, b = mk(run, "Bank", "--parent", p), mk(run, "VAT return", "--parent", p)
    mk(run, "Sub of VAT", "--parent", b)
    run("ticket", "status", a, "done")
    out = run("ticket", "tree", p)[1].splitlines()
    assert out[0] == "Quarter close"
    text = "\n".join(out)  # same-second siblings: their order is not defined
    assert "├─ ✓ Bank" in text or "└─ ✓ Bank" in text
    assert "○ VAT return   open" in text
    assert any(x.endswith("└─ ○ Sub of VAT   open") and x.startswith(("│  ", "   ")) for x in out)


def test_blocked_by_and_came_from(proj, run):
    a, b = mk(run, "Move customer data"), mk(run, "Q3 export")
    run("ticket", "status", a, "active")
    run("wait", b, "--on", f"ticket:{a}")
    t = tickets.load(proj, b)  # an internal link written before links were web-only
    t["links"].append({"type": "ticket", "url": "ws_pilatus001/t_h8w2qa", "title": "pilatus / t_h8w2qa"})
    tickets.save(proj, t)
    text = run("ticket", "show", b)[1]
    assert f"Blocked by: Move customer data ({a}, active)" in text
    assert "Came from: pilatus / t_h8w2qa" in text and "Links:" not in text
    run("wait", b, "--on", "ticket:t_gone99")
    assert "Blocked by: t_gone99" in run("ticket", "show", b)[1]


def test_closing_parent_warns_but_saves(proj, run):
    p = mk(run, "Close")
    k1, k2 = mk(run, "VAT", "--parent", p), mk(run, "Export", "--parent", p)
    code, out, err = run("ticket", "status", p, "done")
    assert code == 0 and "Warning: 2 sub-tickets are still open" in err and "VAT" in err
    assert read(proj, p)["status"] == "done" and "warnings" not in read(proj, p)
    run("ticket", "status", p, "active")
    code, out, err = run("ticket", "status", p, "done", "--json")
    j = json.loads(out)
    assert (
        j["status"] == "done"
        and len(j["warnings"]) == 1
        and j["warnings"][0].startswith("2 sub-tickets are still open: ")
        and {k1, k2} <= set(j["warnings"][0].replace(",", " ").split())
    )
    run("ticket", "status", k1, "done")
    run("ticket", "status", k2, "dropped")
    run("ticket", "status", p, "active")
    assert "Warning" not in run("ticket", "status", p, "done")[2]

"""orch.reads: the in-process answers the dashboard builds its state from are the JSON the commands print
(ORCH-102: one process per read made a state build take seconds while helpers ran)."""

import json

import pytest

from orch import reads


@pytest.fixture
def three(proj, run):
    ids = []
    for title in ("First", "Second", "Third"):
        code, out, _ = run("ticket", "new", title, "--json", "--by", "agent:x")
        assert code == 0
        ids.append(json.loads(out)["id"])
    assert run("ticket", "status", ids[2], "done", "--by", "agent:x")[0] in (0, 2)
    code, out, err = run(
        "ask", ids[0], "Please look: New block", "--draft", "New block", "--then", "I build it.", "--json",
        "--by", "agent:x",
    )  # fmt: skip
    assert code == 0, out + err
    return proj, ids


@pytest.mark.parametrize(
    "argv",
    [
        ["ticket", "list", "--all", "--json"],
        ["ticket", "list", "--json"],
        ["review", "list", "--json"],
        ["review", "list", "--answered", "--json"],
    ],
)
def test_same_answer_as_the_command(three, run, argv):
    root, _ = three
    code, out, _ = run(*argv)
    assert code == 0
    assert reads.answer(root, argv) == json.loads(out)


def test_run_status_same_answer_for_one_and_many(three, run):
    root, ids = three
    for argv in (["run", "status", ids[0], "--json"], ["run", "status", *ids, "--json"]):
        code, out, _ = run(*argv)
        assert code == 0
        assert reads.answer(root, argv) == json.loads(out)


def test_ticket_show_same_answer(three, run):
    root, ids = three
    code, out, _ = run("ticket", "show", ids[0], "--json")
    assert code == 0
    assert reads.answer(root, ["ticket", "show", ids[0], "--json"]) == json.loads(out)


def test_a_missing_ticket_does_not_spoil_the_others(three):
    root, ids = three
    got = reads.answer(root, ["run", "status", ids[0], "t_nothere99", "--json"])["runs"]
    assert got[ids[0]]["ticket"] == ids[0] and "error" in got["t_nothere99"]


@pytest.mark.parametrize(
    "argv",
    [
        ["ticket", "new", "x", "--json"],  # a write is never answered here
        ["ticket", "list", "--all"],  # text, not JSON
        ["run", "status", "--json"],
        ["run", "status", "../etc", "--json"],
        ["addon", "list", "--json"],
    ],
)
def test_other_argv_is_not_here(three, argv):
    with pytest.raises(reads.NotHere):
        reads.answer(three[0], argv)


def test_the_answer_shares_nothing_with_the_core(three):
    root, _ = three
    a = reads.answer(root, ["ticket", "list", "--all", "--json"])
    a[0]["title"] = "changed"
    assert reads.answer(root, ["ticket", "list", "--all", "--json"])[0]["title"] != "changed"

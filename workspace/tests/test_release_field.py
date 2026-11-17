"""ORCH-37: a ticket can carry the release it belongs to (free text, one line); set, shown, cleared, validated."""

import json

import pytest

from orch import tickets
from orch.errors import Refused


def read(proj, tid):
    return json.loads((proj / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))


def test_new_with_release_is_valid_and_shown(proj, run, validate):
    code, out, _ = run("ticket", "new", "Ship the board", "--release", " 26 ", "--json")
    assert code == 0
    tid = json.loads(out)["id"]
    t = read(proj, tid)
    validate(t)
    assert t["release"] == "26"
    assert "Release: 26" in run("ticket", "show", tid)[1]


def test_edit_sets_and_clears_release(proj, run, validate, new_ticket):
    tid = new_ticket()
    assert run("ticket", "edit", tid, "--release", "Spring launch")[0] == 0
    t = read(proj, tid)
    validate(t)
    assert t["release"] == "Spring launch" and t["history"][-1]["text"] == "Edited release"
    assert "Changed the release" in run("ticket", "show", tid)[1]
    assert run("ticket", "edit", tid, "--release", "")[0] == 0
    assert "release" not in read(proj, tid)


def test_patch_sets_release(proj, new_ticket, validate):
    tid = new_ticket()
    rev = read(proj, tid)["revision"]
    t = tickets.patch(proj, tid, rev, json.dumps({"release": "27"}), "human:test")
    assert t["release"] == "27"
    validate(read(proj, tid))
    t = tickets.patch(proj, tid, t["revision"], json.dumps({"release": None}), "human:test")
    assert "release" not in t


@pytest.mark.parametrize("bad", ["x" * 41, "26\n27", "26\x1b[31m"])
def test_bad_release_refused(bad):
    with pytest.raises(Refused, match="release"):
        tickets.clean_field("release", bad)


def test_schema_refuses_long_release(proj, new_ticket, validate):
    t = read(proj, new_ticket())
    t["release"] = "x" * 41
    with pytest.raises(AssertionError):
        validate(t)

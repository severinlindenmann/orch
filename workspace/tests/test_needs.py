"""orch needs: core rows from tickets and services, add-on pulls with cache."""

import json
import time

import pytest
from jsonschema import Draft202012Validator
from test_addons import install, make_addon, uv_calls  # noqa: F401  (fixture)

from orch import addons, tickets
from orch.needs import needs as compute

SCHEMA = json.loads(
    (__import__("pathlib").Path(__file__).resolve().parents[2] / "contracts/needs.schema.json").read_text(
        encoding="utf-8"
    )
)

NEEDS_MAIN = """\
import json, os, sys, time
from pathlib import Path
root = Path(os.environ["ORCH_ROOT"])
if sys.argv[1:2] == ["needs"]:
    mode = (root / "mode.txt").read_text().strip() if (root / "mode.txt").exists() else "ok"
    if mode == "slow":
        time.sleep(5)
    if mode == "broken":
        print("not json")
        sys.exit(1)
    rows = json.loads((root / "rows.json").read_text())
    print(json.dumps(rows))
"""


def _ticket(run, title="Invoice export"):
    return json.loads(run("ticket", "new", title, "--json")[1])["id"]


def _rows(run):
    code, out, err = run("needs", "--json")
    assert code == 0, err
    rows = json.loads(out)
    assert list(Draft202012Validator(SCHEMA).iter_errors(rows)) == []
    return rows


def test_nothing_needs_you(proj, run):
    assert run("init")[0] == 0
    assert _rows(run) == []
    assert run("needs")[1].strip() == "Nothing needs you."


def test_open_question_row_and_answered_one_gone(proj, run):
    run("init")
    tid = _ticket(run)
    run("ask", tid, "Send it now?", "--option", "Yes", "--option", "No", "--recommended", "Yes")
    (row,) = _rows(run)
    assert row["id"] == f"core:q:{tid}:q1" and row["kind"] == "question" and row["tone"] == "needs-you"
    assert row["answer"].pop("digest") == tickets.question_digest(tickets.load(proj, tid)["questions"][0])
    assert row["answer"] == {"question": "q1", "options": ["Yes", "No"], "recommended": "Yes"}
    assert "Needs you (1)" in run("needs")[1]
    run("answer", tid, "q1", "Yes")
    assert _rows(run) == []


def test_overdue_time_wait_and_future_wait(proj, run):
    run("init")
    late, later = _ticket(run, "Late"), _ticket(run, "Later")
    assert run("wait", late, "--until", "2020-01-01T00:00:00Z")[0] == 0
    assert run("wait", later, "--until", "2999-01-01T00:00:00Z")[0] == 0
    (row,) = _rows(run)
    assert row["id"] == f"core:wait:{late}" and row["kind"] == "overdue-wait" and row["tone"] == "warn"
    assert row["text"] == f"Wake time passed; nothing started it. Start it: orch run start {late}"


def test_overdue_wait_of_other_kind(proj, run):
    run("init")
    tid = _ticket(run)
    p = proj / ".orch" / "tickets" / f"{tid}.json"
    t = json.loads(p.read_text(encoding="utf-8"))
    t["status"], t["waiting_on"] = (
        "waiting",
        {"kind": "external", "ref": "Acme IT", "until": "2020-01-01T00:00:00Z"},
    )
    p.write_text(json.dumps(t), encoding="utf-8")
    (row,) = _rows(run)
    assert row["id"] == f"core:wait:{tid}" and "external Acme IT" in row["text"]


def test_order_needs_you_then_bad_then_warn_and_no_silent_row(proj, run):
    run("init")
    a, b = _ticket(run, "A"), _ticket(run, "B")
    run("wait", a, "--until", "2020-01-01T00:00:00Z")
    run("ask", b, "Which?")
    assert [r["tone"] for r in _rows(run)] == ["needs-you", "warn"]
    assert all(r["kind"] != "silent" for r in _rows(run))


# ---- add-on pulls ----------------------------------------------------------------------------------


def _row(name="hello", key="x", **kw):
    r = {
        "id": f"{name}:{key}",
        "source": name,
        "kind": f"{name}:thing",
        "ticket": None,
        "title": "Thing",
        "text": "Look at this",
        "tone": "warn",
        "since": "2026-11-05T08:00:00Z",
    }
    r.update(kw)
    return r


@pytest.fixture
def na(proj, run, tmp_path, monkeypatch, request):
    request.getfixturevalue("uv_calls")
    folder = make_addon(tmp_path / "n", extra="needs = true")
    (folder / "src/orch_hello/__main__.py").write_text(NEEDS_MAIN, encoding="utf-8")
    monkeypatch.syspath_prepend(str(folder / "src"))
    monkeypatch.setenv("PYTHONPATH", str(folder / "src"))
    monkeypatch.setattr(addons, "_entry_points", lambda: {"hello": "orch_hello"})
    assert run("init")[0] == 0
    install(run, folder)
    (proj / "rows.json").write_text(json.dumps([_row()]), encoding="utf-8")
    return folder


def test_addon_rows_are_added_and_cached(na, proj, run):
    rows = _rows(run)
    assert [r["id"] for r in rows] == ["hello:x"] and rows[0]["stale"] is False
    assert (proj / ".orch/run/needs-cache/hello.json").is_file()


def test_slow_addon_gives_cached_rows_stale_within_time(na, proj, run):
    _rows(run)
    (proj / "mode.txt").write_text("slow")
    t0 = time.monotonic()
    rows = _rows(run)
    assert time.monotonic() - t0 < 3.5
    assert [(r["id"], r["stale"]) for r in rows] == [("hello:x", True)]


def test_broken_addon_without_cache_is_one_warn_row(na, proj, run):
    (proj / "mode.txt").write_text("broken")
    rows = _rows(run)
    assert len(rows) == 1 and rows[0]["tone"] == "warn" and rows[0]["stale"] is True
    assert rows[0]["id"] == "hello:needs-unavailable"


def test_invalid_rows_and_impersonation_are_dropped(na, proj, run):
    bad = [
        _row(key="ok"),
        _row(key="b1", source="core"),
        {**_row(key="b2"), "id": "core:q:t_aaaaaa:q1"},
        _row(key="b3", tone="loud"),
        _row(key="b4", text=""),
    ]
    (proj / "rows.json").write_text(json.dumps(bad), encoding="utf-8")
    assert [r["id"] for r in _rows(run)] == ["hello:ok"]


def test_addon_row_for_a_core_question_is_dropped(na, proj, run):
    tid = _ticket(run)
    run("ask", tid, "Try again?", "--option", "Yes")
    dup = _row(
        key="dup", ticket=tid, tone="bad", answer={"question": "q1", "options": ["Yes"], "recommended": None}
    )
    (proj / "rows.json").write_text(json.dumps([dup, _row(key="other")]), encoding="utf-8")
    assert sorted(r["id"] for r in _rows(run)) == sorted([f"core:q:{tid}:q1", "hello:other"])


def test_addon_without_needs_key_is_not_asked(proj, run, tmp_path, monkeypatch, uv_calls):  # noqa: F811
    folder = make_addon(tmp_path / "q")
    (folder / "src/orch_hello/__main__.py").write_text(
        "import os\nopen(os.path.join(os.environ['ORCH_ROOT'], 'asked'), 'w').write('x')\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(folder / "src"))
    monkeypatch.setenv("PYTHONPATH", str(folder / "src"))
    monkeypatch.setattr(addons, "_entry_points", lambda: {"hello": "orch_hello"})
    run("init")
    install(run, folder)
    assert _rows(run) == [] and not (proj / "asked").exists()


def test_stopped_background_addon_is_a_row(proj, run, tmp_path, monkeypatch, uv_calls):  # noqa: F811
    folder = make_addon(tmp_path / "b", bg=True)
    monkeypatch.syspath_prepend(str(folder / "src"))
    monkeypatch.setenv("PYTHONPATH", str(folder / "src"))
    monkeypatch.setattr(addons, "_entry_points", lambda: {"hello": "orch_hello"})
    run("init")
    install(run, folder)
    (row,) = _rows(run)
    assert row["id"] == "core:down:hello" and row["tone"] == "bad" and row["cli"] == "orch start"
    assert compute(proj)[0]["id"] == "core:down:hello"

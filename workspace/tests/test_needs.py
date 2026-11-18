"""orch needs: core rows from tickets and services, add-on pulls with cache."""

import json
import os
import time
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from test_addons import install, make_addon, uv_calls  # noqa: F401  (fixture)

from orch import addons, tickets
from orch import needs as needs_mod
from orch.needs import _option_labels
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
    if mode == "late":  # later than FAST_BUDGET, within PULL_TIMEOUT
        time.sleep(1.2)
    if mode == "spawns":  # starts a child of its own (as Factory runs orch ticket list), then hangs
        import subprocess
        kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        (root / "kid.pid").write_text(str(kid.pid))
        time.sleep(30)
    if mode == "umlaut":
        row = dict(json.loads((root / "rows.json").read_text())[0], text="Grüße")
        print(json.dumps([row], ensure_ascii=False))
        sys.exit(0)
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
    assert run("needs")[1].startswith("Nothing needs you.")


def test_open_question_row_and_answered_one_gone(proj, run):
    run("init")
    tid = _ticket(run)
    run("ask", tid, "Send it now?", "--option", "Yes", "--option", "No", "--recommended", "Yes")
    (row,) = _rows(run)
    assert row["id"] == f"core:q:{tid}:q1" and row["kind"] == "question" and row["tone"] == "needs-you"
    assert row["answer"].pop("digest") == tickets.question_digest(tickets.load(proj, tid)["questions"][0])
    assert row["answer"] == {
        "question": "q1",
        "options": ["Yes", "No"],
        "labels": ["Yes", "No"],
        "recommended": "Yes",
    }
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
    assert row["text"] == "Wake time passed and no helper started. Continue starts it."


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
    spawned = []
    monkeypatch.setattr(needs_mod, "_spawn_refresh", lambda root, name: spawned.append(name) or True)
    return SimpleNamespace(folder=folder, spawned=spawned)


def test_addon_rows_are_added_and_cached(na, proj, run):
    rows = _rows(run)
    assert [r["id"] for r in rows] == ["hello:x"] and rows[0]["stale"] is False
    assert (proj / ".orch/run/needs-cache/hello.json").is_file()


def test_slow_addon_with_an_old_saved_answer_gives_it_stale_fast(na, proj, run):
    _rows(run)
    cache = proj / ".orch/run/needs-cache/hello.json"
    old = time.time() - needs_mod.STALE_AFTER - 60
    os.utime(cache, (old, old))
    (proj / "mode.txt").write_text("slow")
    t0 = time.monotonic()
    rows = compute(proj)
    assert time.monotonic() - t0 < needs_mod.FAST_BUDGET + 0.8
    assert [(r["id"], r["stale"]) for r in rows] == [("hello:x", True)]
    assert na.spawned == ["hello"]  # a fresh answer is fetched in the background


def test_late_addon_answers_from_its_fresh_saved_answer_and_refreshes(na, proj, run):
    """ORCH-603: an add-on later than FAST_BUDGET does not hold needs up; its saved answer (fresh) is shown as
    up to date, and one background refresh saves the new answer for the next call."""
    _rows(run)
    (proj / "rows.json").write_text(json.dumps([_row(key="new")]), encoding="utf-8")
    (proj / "mode.txt").write_text("late")
    t0 = time.monotonic()
    rows = compute(proj)
    assert time.monotonic() - t0 < needs_mod.FAST_BUDGET + 0.5
    assert [(r["id"], r["stale"]) for r in rows] == [("hello:x", False)]
    assert na.spawned == ["hello"]
    assert needs_mod.refresh(proj, "hello") is True  # what the detached `orch needs --refresh-addon` does
    saved = json.loads((proj / ".orch/run/needs-cache/hello.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in saved] == ["hello:new"]
    assert not (proj / ".orch/run/needs-cache/hello.refreshing").exists()


def test_first_answer_is_waited_for_without_a_saved_one(na, proj, run):
    (proj / "mode.txt").write_text("late")
    rows = compute(proj)
    assert [(r["id"], r["stale"]) for r in rows] == [("hello:x", False)] and na.spawned == []


def test_addons_are_asked_while_the_core_rows_are_made(na, proj, run, monkeypatch):
    (proj / "mode.txt").write_text("late")  # 1.2 s in the add-on; no saved answer, so it is waited for
    real = needs_mod.core_rows

    def slow_core(root):
        time.sleep(1.2)
        return real(root)

    monkeypatch.setattr(needs_mod, "core_rows", slow_core)
    t0 = time.monotonic()
    rows = compute(proj)
    took = time.monotonic() - t0
    assert took < 2.0, took  # one after another would be 2.4 s and more
    assert [(r["id"], r["stale"]) for r in rows] == [("hello:x", False)] and na.spawned == []


def test_refresh_command_saves_the_answer_and_prints_nothing(na, proj, run):
    code, out, _ = run("needs", "--refresh-addon", "hello")
    assert code == 0 and "Needs you" not in out and "Nothing needs you" not in out
    saved = json.loads((proj / ".orch/run/needs-cache/hello.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in saved] == ["hello:x"]
    assert run("needs", "--refresh-addon", "nope")[0] == 0  # not an add-on with needs: nothing


@pytest.mark.skipif(os.name == "nt", reason="process groups: POSIX; Windows stops the tree with taskkill /T")
def test_a_late_addon_is_stopped_with_what_it_started(na, proj, run):
    _rows(run)
    (proj / "mode.txt").write_text("spawns")
    assert [r["id"] for r in compute(proj)] == ["hello:x"]
    pid = int((proj / "kid.pid").read_text()) if (proj / "kid.pid").exists() else None
    if pid is None:  # the add-on was stopped before it started its child: nothing left behind either
        return
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    pytest.fail("the add-on's own child kept running")


def test_non_ascii_rows_come_through(na, proj, run):
    (proj / "mode.txt").write_text("umlaut")
    assert [r["text"] for r in compute(proj)] == ["Grüße"]


def test_two_callers_at_once_start_one_refresh(proj, monkeypatch):
    import threading

    started = []
    monkeypatch.delenv("ORCH_NO_NEEDS_REFRESH", raising=False)
    monkeypatch.setattr(needs_mod.subprocess, "Popen", lambda *a, **k: started.append(a[0]))
    go = threading.Barrier(8)
    results = []

    def call():
        go.wait()
        results.append(needs_mod._spawn_refresh(proj, "hello"))

    threads = [threading.Thread(target=call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(started) == 1 and results.count(True) == 1


def test_refresh_is_started_once_while_one_runs(proj, monkeypatch):
    started = []
    monkeypatch.delenv("ORCH_NO_NEEDS_REFRESH", raising=False)
    monkeypatch.setattr(needs_mod.subprocess, "Popen", lambda *a, **k: started.append(a[0]))
    assert needs_mod._spawn_refresh(proj, "hello") is True
    assert needs_mod._spawn_refresh(proj, "hello") is False  # the mark says one is under way
    assert len(started) == 1 and started[0][-2:] == ["--refresh-addon", "hello"]


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


def test_option_labels_name_card_options_by_title():
    q = {
        "options": ["A", "B"],
        "card": {
            "preview": {
                "type": "options",
                "options": [{"id": "A", "title": "Big button"}, {"id": "B", "title": "B"}],
            }
        },
    }
    assert _option_labels(q) == ["A Big button", "B"]


# ---- an add-on's own tickets (ORCH-603) -------------------------------------------------------------


def test_ticket_list_ext_gives_only_tickets_with_that_addon_data(proj, run):
    run("init")
    a, b, c = _ticket(run, "Order"), _ticket(run, "Plain"), _ticket(run, "Says relay in words")
    assert run("ext", "set", a, "relay", json.dumps({"role": "order"}))[0] == 0
    run("ticket", "status", a, "done")
    code, out, err = run("ticket", "list", "--all", "--ext", "relay", "--json")
    assert code == 0, err
    rows = json.loads(out)
    assert [r["id"] for r in rows] == [a] and rows[0]["ext"]["relay"] == {"role": "order"}
    assert "children" not in rows[0]  # those need every ticket
    assert json.loads(run("ticket", "list", "--ext", "relay", "--json")[1]) == []  # done: only with --all
    assert {b, c} <= {r["id"] for r in json.loads(run("ticket", "list", "--json")[1])}
    assert tickets.list_all(proj, ext="relay")[0]["id"] == a

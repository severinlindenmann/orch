"""The ticket index (ORCH-521): rows equal what the ticket files say after new, edit, status, hand edits and a
crash, and `orch ticket list` / `orch needs` answer the same as reading every file."""

import json
import os

from orch import history, needs, reads, ticketindex, tickets


def _new(run, title, *extra):
    code, out, err = run("ticket", "new", title, *extra, "--json")
    assert code == 0, err
    return json.loads(out)["id"]


def _same_as_files(root):
    """The index rows agree with tickets.list_all on ids, order and the listed fields."""
    want = tickets.list_all(root)
    got = ticketindex.rows(root)
    assert [r["id"] for r in got] == [t["id"] for t in want]
    for r, t in zip(got, want, strict=True):
        assert (r["key"], r["title"], r["status"], r["parent"], r["revision"]) == (
            t.get("key"),
            t.get("title"),
            t.get("status"),
            t.get("parent"),
            t.get("revision"),
        )
    return got


def test_rows_follow_new_edit_status(proj, run):
    assert run("init")[0] == 0
    a = _new(run, "Invoice export")
    b = _new(run, "Monthly report", "--parent", a)
    assert len(_same_as_files(proj)) == 2
    assert run("ticket", "edit", b, "--title", "Monthly sales report", "--owner", "Anna")[0] == 0
    assert run("ticket", "status", a, "active")[0] == 0
    assert run("check", "add", a, "Write the export")[0] == 0
    assert run("ask", a, "Send it now?", "--option", "Yes", "--option", "No")[0] == 0
    rows = {r["id"]: r for r in _same_as_files(proj)}
    assert rows[b]["title"] == "Monthly sales report" and rows[b]["owner"] == "Anna"
    assert rows[a]["status"] == "waiting" and rows[a]["questions_open"] == 1  # a question waits on a person
    assert rows[a]["steps"] == {"done": 0, "wont": 0, "total": 1}
    assert ticketindex.children_counts(list(rows.values()))[a] == {"total": 1, "closed": 0, "open": 1}
    assert rows[a]["answers"] == 0 and rows[a]["answered_at"] is None
    t = tickets.load(proj, a)
    q = t["questions"][0]
    q.update(answer="Yes", decision={"choice": "Yes"}, at="2026-11-18T10:00:00Z")
    tickets.save(proj, t)
    row = next(r for r in ticketindex.rows(proj) if r["id"] == a)
    assert (row["answers"], row["answered_at"], row["questions_open"]) == (1, "2026-11-18T10:00:00Z", 0)
    assert ticketindex.counts(proj) == {"total": 2, "by_status": {"waiting": 1, "open": 1}}


def test_hidden_tickets_left_out(proj, run):
    run("init")
    _new(run, "Invoice export")
    gid = tickets.ensure_general(proj, "human:test")
    assert gid not in {r["id"] for r in ticketindex.rows(proj)}
    assert gid in {r["id"] for r in ticketindex.rows(proj, include_hidden=True)}


def test_broken_or_missing_index_is_rebuilt(proj, run):
    run("init")
    tid = _new(run, "Invoice export")
    ticketindex.rows(proj)
    p = ticketindex.index_path(proj)
    p.write_text('{"version": 1, "files": {"t_', encoding="utf-8")  # a crash mid-write of an older orch
    assert [r["id"] for r in ticketindex.rows(proj)] == [tid]
    assert json.loads(p.read_text(encoding="utf-8"))["version"] == ticketindex.VERSION
    p.write_text(json.dumps({"version": 999, "files": {}}), encoding="utf-8")
    assert [r["id"] for r in ticketindex.rows(proj)] == [tid]
    p.unlink()
    assert [r["id"] for r in ticketindex.rows(proj)] == [tid]


def test_stale_index_after_a_crash_is_repaired(proj, run):
    """The index was written, then the tickets changed without it being written again (orch killed after a
    ticket write, a sync step, a hand edit, a deleted file): the next call sees every change."""
    run("init")
    a = _new(run, "Invoice export")
    b = _new(run, "Monthly report")
    ticketindex.rows(proj)
    saved = ticketindex.index_path(proj).read_bytes()
    c = _new(run, "Price list")
    assert run("ticket", "status", a, "waiting")[0] == 0
    path_b = tickets.ticket_path(proj, b)
    t = json.loads(path_b.read_text(encoding="utf-8"))
    t["title"] = "Monthly report"[::-1]  # same length: a hand edit in place that keeps the size
    st = path_b.stat()
    path_b.write_text(json.dumps(t, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.utime(path_b, ns=(st.st_atime_ns, st.st_mtime_ns + 1))
    ticketindex.index_path(proj).write_bytes(saved)  # as if every write above crashed before the index
    rows = {r["id"]: r for r in _same_as_files(proj)}
    assert set(rows) == {a, b, c} and rows[a]["status"] == "waiting" and rows[b]["title"] == t["title"]
    tickets.ticket_path(proj, c).unlink()
    assert {r["id"] for r in _same_as_files(proj)} == {a, b}


def test_half_written_ticket_and_temp_files(proj, run):
    run("init")
    a = _new(run, "Invoice export")
    d = tickets.tickets_dir(proj)
    (d / ".tmp-abc.json").write_text("{", encoding="utf-8")  # a writer killed before its os.replace
    (d / "t_zzzzzz.json").write_text('{"id": "t_zz', encoding="utf-8")  # broken: list_all skips it too
    assert [r["id"] for r in _same_as_files(proj)] == [a]
    (d / "t_zzzzzz.json").unlink()
    assert [r["id"] for r in _same_as_files(proj)] == [a]


def test_unwritable_index_still_answers(proj, run, monkeypatch):
    run("init")
    a = _new(run, "Invoice export")

    tries = []

    def refuse(*_a, **_k):
        tries.append(1)
        raise PermissionError("held open by a reader (Windows)")

    ticketindex.index_path(proj).unlink(missing_ok=True)  # so the next call has to write it
    monkeypatch.setattr(ticketindex.os, "replace", refuse)
    assert [r["id"] for r in ticketindex.rows(proj)] == [a]
    assert tries == [1]  # one try, no waiting for the file to come free: the index is only a cache
    assert not list(ticketindex.index_path(proj).parent.glob("ticket-index.json.*.tmp"))


def test_text_list_same_as_full_rows(proj, run):
    from orch.cli import _line

    run("init")
    a = _new(run, "Invoice export")
    b = _new(run, "Monthly report", "--parent", a)
    c = _new(run, "Price list")
    run("check", "add", a, "Write the export")
    run("check", "add", a, "Send it")
    run("ticket", "status", c, "done")
    run("ticket", "status", b, "waiting")
    for status, all_ in ((None, False), (None, True), ("waiting", False)):
        full = reads.ticket_rows(proj, status, all_)
        rows, _ = reads.index_list(proj, status, all_)
        assert [_line(t) for t in rows] == [_line(t) for t in full]
        assert [t["children"] for t in rows] == [t["children"] for t in full]
    code, out, _ = run("ticket", "list")
    assert code == 0 and "1 finished" in out and "0 of 2 done" in out


def test_needs_reads_only_tickets_that_may_need_you(proj, run, monkeypatch):
    run("init")
    asked = _new(run, "Invoice export")
    _new(run, "Monthly report")
    done = _new(run, "Price list")
    run("ask", asked, "Send it now?", "--option", "Yes", "--option", "No")
    run("ticket", "status", done, "done")
    read = []
    real = tickets.load
    monkeypatch.setattr(tickets, "load", lambda root, tid: read.append(tid) or real(root, tid))
    rows = needs.core_rows(proj)
    assert read == [asked]
    assert [r["id"] for r in rows if r.get("ticket")] == [f"core:q:{asked}:q1"]


def test_sync_traces_seen_through_the_index(proj, run):
    run("init")
    tid = _new(run, "Invoice export")
    assert ticketindex.any_shows_sync(proj) is False
    p = tickets.ticket_path(proj, tid)
    t = json.loads(p.read_text(encoding="utf-8"))
    t.setdefault("ext", {})["sync"] = {"old_keys": []}
    p.write_text(json.dumps(t), encoding="utf-8")
    assert ticketindex.any_shows_sync(proj) is True
    assert ticketindex.any_shows_sync(proj) == history.tickets_show_sync(proj)


def test_in_place_edit_with_time_set_back_is_seen(proj, run):
    """A hand edit in place that keeps the size and sets the modified time back is still read again."""
    import sys

    if sys.platform == "win32":
        return  # no change time to compare there; orch's own writes replace the file (new identity)
    run("init")
    tid = _new(run, "Invoice export")
    ticketindex.rows(proj)
    p = tickets.ticket_path(proj, tid)
    st = p.stat()
    t = json.loads(p.read_text(encoding="utf-8"))
    t["title"] = "Invoice export"[::-1]
    with open(p, "r+", encoding="utf-8") as f:  # same file, same size
        f.write(json.dumps(t, indent=2, ensure_ascii=False) + "\n")
        f.truncate()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert p.stat().st_size == st.st_size and p.stat().st_mtime_ns == st.st_mtime_ns
    assert ticketindex.rows(proj)[0]["title"] == t["title"]


def test_no_write_keeps_the_index_file_as_it_was(proj, run):
    """`orch diag` reads without writing: inside no_write the rows are fresh but the index file stays."""
    assert run("init")[0] == 0
    a = _new(run, "Invoice export")
    ticketindex.rows(proj)
    before = ticketindex.index_path(proj).read_bytes()
    f = proj / ".orch" / "tickets" / f"{a}.json"
    t = json.loads(f.read_text(encoding="utf-8"))
    t["title"] = "Invoice export, by hand"
    f.write_text(json.dumps(t), encoding="utf-8")
    with ticketindex.no_write():
        assert [r["title"] for r in ticketindex.rows(proj)] == ["Invoice export, by hand"]
    assert ticketindex.index_path(proj).read_bytes() == before
    ticketindex.index_path(proj).unlink()
    with ticketindex.no_write():
        assert len(ticketindex.rows(proj)) == 1
    assert not ticketindex.index_path(proj).exists()


def test_a_step_that_keeps_failing_is_flagged_in_the_row(proj, run):
    """`orch needs` reads only flagged tickets in full: a step whose checks keep failing must be flagged."""
    assert run("init")[0] == 0
    a = _new(run, "Fix the export")
    assert run("check", "add", a, "Make the export work")[0] == 0
    for code in (1, 2):
        assert run("check", "record", a, "c1", "--cmd", "uv run pytest -q", "--exit", str(code))[0] == 0
    (r,) = ticketindex.rows(proj)
    assert r["failing"] is True
    assert run("check", "record", a, "c1", "--cmd", "uv run pytest -q", "--exit", "0")[0] == 0
    (r,) = ticketindex.rows(proj)
    assert r["failing"] is False


# ---- ORCH-1621: reads that need a few tickets read only those, and one state build looks at the files once


def _no_full_list(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("read every ticket")

    monkeypatch.setattr(tickets, "list_all", refuse)


def test_load_where_reads_only_the_matching_files(proj, run, monkeypatch):
    run("init")
    a = _new(run, "Invoice export")
    _new(run, "Monthly report")
    c = _new(run, "Price list")
    assert run("ticket", "status", c, "active")[0] == 0
    want = [t["id"] for t in tickets.list_all(proj) if t["id"] in (a, c)]
    read = []
    real = tickets.load
    monkeypatch.setattr(tickets, "load", lambda root, tid: read.append(tid) or real(root, tid))
    _no_full_list(monkeypatch)
    got = ticketindex.load_where(proj, lambda r: r["id"] == a or r["status"] == "active")
    assert [t["id"] for t in got] == want  # by creation time, as list_all
    assert sorted(read) == sorted(want)  # the other ticket's file was never opened
    first = next(t for t in got if t["id"] == a)
    assert first["title"] == "Invoice export" and "history" in first  # the whole stored ticket


def test_load_where_without_an_index_gives_the_same_answer(proj, run, monkeypatch):
    run("init")
    a = _new(run, "Invoice export")
    _new(run, "Monthly report")
    gid = tickets.ensure_general(proj, "human:test")

    def broken(*a, **k):
        raise OSError("no index")

    monkeypatch.setattr(ticketindex, "rows", broken)
    assert [t["id"] for t in ticketindex.load_where(proj, lambda r: r["title"] == "Invoice export")] == [a]
    assert [t["id"] for t in ticketindex.load_where(proj, lambda r: bool(r["hidden"]), True)] == [gid]
    assert ticketindex.load_where(proj, lambda r: bool(r["hidden"])) == []  # hidden only when asked


def test_rows_count_chat_lines(proj, run):
    run("init")
    a = _new(run, "Invoice export")
    t = tickets.load(proj, a)
    t["history"].append(
        {"at": "2026-11-20T10:00:00Z", "by": "human:test", "text": "Can you add VAT?", "chat_message": True}
    )
    t["history"].append(
        {"at": "2026-11-20T10:01:00Z", "by": "human:test", "text": "not a chat line", "chat_message": False}
    )
    tickets.save(proj, t)
    rows = {r["id"]: r for r in ticketindex.rows(proj)}
    assert rows[a]["chat_lines"] == 1


def test_reuse_looks_at_the_files_once(proj, run, monkeypatch):
    import contextvars
    import threading

    run("init")
    _new(run, "Invoice export")
    looks = []
    real = ticketindex._look
    monkeypatch.setattr(ticketindex, "_look", lambda root: looks.append(1) or real(root))
    ticketindex.rows(proj)
    ticketindex.rows(proj)
    assert len(looks) == 2  # outside reuse() every call looks again: a change is seen at once
    looks.clear()
    with ticketindex.reuse():
        ticketindex.rows(proj)
        ticketindex.any_shows_sync(proj)
        ctx = contextvars.copy_context()
        th = threading.Thread(target=ctx.run, args=(ticketindex.rows, proj))
        th.start()
        th.join()
    assert len(looks) == 1  # one look for the whole pass, threads with a copy of the context too
    ticketindex.rows(proj)
    assert len(looks) == 2


def test_hidden_ids_chats_picks_and_accepted_never_read_every_ticket(proj, run, monkeypatch):
    from orch import ownerpick, reviewer, ticketchats

    run("init")
    a = _new(run, "Invoice export")
    _new(run, "Monthly report")
    gid = tickets.ensure_general(proj, "human:test")
    mid = tickets.ensure_manager(proj, "human:test")
    t = tickets.load(proj, a)
    t["history"].append(
        {"at": "2026-11-20T10:00:00Z", "by": "human:test", "text": "Can you add VAT?", "chat_message": True}
    )
    t["history"].append(
        {"at": "2026-11-20T11:00:00Z", "by": reviewer.BY, "text": tickets.ACCEPTED_LINE + "small fix"}
    )
    tickets.save(proj, t)
    _no_full_list(monkeypatch)
    assert tickets.general_id(proj) == gid and tickets.manager_id(proj) == mid
    assert [r["id"] for r in ticketchats.chats(proj)] == [a]
    assert ownerpick.waiting_rows(proj) == []
    got = reviewer.accepted(proj, "2026-11-20T00:00:00+00:00")
    assert [r["ticket"] for r in got] == [a]
    assert reviewer.accepted(proj, "2026-11-21T12:00:00+00:00") == []  # newest line older: nothing to read


def test_plan_card_steps_come_from_the_index(proj, run, monkeypatch):
    from orch import review, runs

    run("init")
    epic = _new(run, "Website relaunch")
    _new(run, "Write the texts", "--parent", epic)
    _new(run, "Pick the photos", "--parent", epic)
    _new(run, "Unrelated")
    assert run("ask", epic, runs.PLAN_READY + ": start?", "--option", "Start", "--option", "Change")[0] == 0
    _no_full_list(monkeypatch)
    card = next(c for c in review.stack(proj) if c["ticket"] == epic)
    assert "Steps: 1. Write the texts; 2. Pick the photos" in card["card"]["why"]


def test_list_by_add_on_reads_only_its_tickets(proj, run, monkeypatch):
    run("init")
    a = _new(run, "Invoice export")
    b = _new(run, "Monthly report")
    for tid, name in ((a, "factory"), (b, "focus")):
        t = tickets.load(proj, tid)
        t["ext"] = {name: {"role": "order"}}
        tickets.save(proj, t)
    read = []
    real = tickets.load
    monkeypatch.setattr(tickets, "load", lambda root, tid: read.append(tid) or real(root, tid))
    got = tickets.list_all(proj, ext="factory")
    assert [t["id"] for t in got] == [a] and read == [a]
    assert next(r for r in ticketindex.rows(proj) if r["id"] == a)["ext"] == ["factory"]
    monkeypatch.setattr(ticketindex, "rows", lambda *a, **k: (_ for _ in ()).throw(OSError("no index")))
    assert [t["id"] for t in tickets.list_all(proj, ext="factory")] == [a]  # without the index: the same

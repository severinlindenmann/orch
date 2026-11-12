"""Task ops: edit, move, remove, reopen, start, stop; derived blocked; stale 'doing' marker."""

import json
import os
import subprocess
import sys
import time

import pytest

from orch import filesig, safegit, saferead, tickets


def read(proj, tid):
    return json.loads((proj / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))


def with_checks(proj, run, new_ticket, n=3):
    tid = new_ticket("Q3 invoices")
    for i in range(n):
        run("check", "add", tid, f"step {i + 1}")
    return tid


def test_edit_and_move(proj, run, validate, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    code, out, _ = run("check", "edit", tid, "c2", "Ask about the date format")
    assert code == 0 and "c2 renamed" in out
    code, out, _ = run("check", "move", tid, "c3", "--after", "c1")
    assert code == 0 and "c3 now follows c1" in out
    t = read(proj, tid)
    validate(t)
    assert [c["id"] for c in t["checklist"]] == ["c1", "c3", "c2"]
    assert t["checklist"][2]["text"] == "Ask about the date format"
    assert run("check", "move", tid, "c1", "--after", "c9")[0] == 2
    assert run("check", "move", tid, "c1", "--after", "c1")[0] == 2


def test_remove_keeps_text_and_proof_in_history(proj, run, validate, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    run("check", "done", tid, "c1", "--command", "pytest -q")
    f = proj / "x.csv"
    f.write_text("a")
    tickets.apply_op(
        proj,
        tid,
        lambda t: t["checklist"][0]["evidence"].append(
            {"type": "file", "ref": "out/q3.csv", "text": "12 rows"}
        ),
        by=tickets.SYSTEM,
    )
    code, out, _ = run("check", "remove", tid, "c1")
    assert code == 0 and "c1 removed" in out
    t = read(proj, tid)
    validate(t)
    assert [c["id"] for c in t["checklist"]] == ["c2", "c3"]
    line = t["history"][-1]["text"]
    assert "step 1" in line and "was done" in line and "pytest -q" in line and "q3.csv (12 rows)" in line
    assert run("check", "remove", tid, "c2")[0] == 0  # open ones too
    assert run("check", "remove", tid, "c2")[0] == 2  # gone


def test_reopen_keeps_old_proof_in_history(proj, run, validate, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    run("check", "done", tid, "c1", "--note", "looked fine")
    code, out, _ = run("check", "reopen", tid, "c1")
    assert code == 0 and "open again" in out
    t = read(proj, tid)
    validate(t)
    c = t["checklist"][0]
    assert c["done"] is False and c["evidence"] == []
    assert "looked fine" in t["history"][-1]["text"]
    assert run("ticket", "status", tid, "done", "--by", "agent:generic")[0] == 2


def test_start_stop_and_single_doing(proj, run, validate, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    code, out, _ = run("check", "start", tid, "c1", "--by", "agent:claude-code")
    assert code == 0 and "agent:claude-code is on it" in out
    run("check", "start", tid, "c2", "--by", "agent:claude-code")
    t = read(proj, tid)
    validate(t)
    assert [c.get("state") for c in t["checklist"]] == [None, "doing", None]
    assert t["checklist"][1]["by"] == "agent:claude-code" and t["checklist"][1]["at"].endswith("Z")
    run("check", "done", tid, "c2", "--note", "ok")
    c2 = read(proj, tid)["checklist"][1]
    assert "state" not in c2 and "by" not in c2 and "at" not in c2
    run("check", "start", tid, "c3")
    assert run("check", "stop", tid, "c3")[0] == 0
    assert "state" not in read(proj, tid)["checklist"][2]
    assert run("check", "start", tid, "c2")[0] == 2  # done: reopen first


def test_ask_on_check_shows_waiting_and_blocked_is_not_stored(proj, run, validate, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    code, out, _ = run("ask", tid, "Which date format?", "--option", "A", "--check", "c2")
    assert code == 0 and "Asked q1 on c2, waiting" in out
    t = read(proj, tid)
    validate(t)
    assert t["questions"][0]["check"] == "c2" and "blocked" not in json.dumps(t["checklist"])
    shown = run("ticket", "show", tid)[1]
    assert "waiting for your answer (q1)" in shown


def _doing(proj, tid, at):
    def op(t):
        t["checklist"][0].update({"state": "doing", "by": "agent:claude-code", "at": at})

    tickets.apply_op(proj, tid, op, by=tickets.SYSTEM)


def _iso(secs_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - secs_ago))


def test_fresh_doing_is_on_it(proj, run, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    _doing(proj, tid, _iso(60))
    assert "agent:claude-code is on it" in run("ticket", "show", tid)[1]


def test_old_doing_is_was_on_it(proj, run, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    _doing(proj, tid, _iso(5 * 3600))
    assert "was on it (5 h ago, not running)" in run("ticket", "show", tid)[1]


def test_run_record_without_live_pid_is_stale(proj, run, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    _doing(proj, tid, _iso(60))
    rec = proj / ".orch" / "run" / "tickets" / f"{tid}.json"
    rec.parent.mkdir(parents=True)
    rec.write_text(json.dumps({"pid": 2**22 + 12345}))
    assert "was on it" in run("ticket", "show", tid)[1]
    import os

    rec.write_text(json.dumps({"pid": os.getpid()}))
    assert "is on it" in run("ticket", "show", tid)[1]


def test_stale_check_uses_services_pid_alive_and_never_signals(proj, run, new_ticket, monkeypatch):
    import os

    from orch import services

    tid = with_checks(proj, run, new_ticket)
    _doing(proj, tid, _iso(60))
    rec = proj / ".orch" / "run" / "tickets" / f"{tid}.json"
    rec.parent.mkdir(parents=True)
    rec.write_text(json.dumps({"pid": 4242}))
    seen = []
    monkeypatch.setattr(services, "pid_alive", lambda pid: seen.append(pid) or True)
    monkeypatch.setattr(os, "kill", lambda *a: (_ for _ in ()).throw(AssertionError("os.kill called")))
    t = tickets.load(proj, tid)
    assert tickets.doing_stale(proj, t, t["checklist"][0]) is False and seen == [4242]


def test_bad_ticket_id_reads_no_run_file(proj, run, new_ticket, monkeypatch):
    tid = with_checks(proj, run, new_ticket)
    _doing(proj, tid, _iso(60))
    t = tickets.load(proj, tid)
    t["id"] = "../../x"
    opened = []
    monkeypatch.setattr(tickets.Path, "is_file", lambda self: opened.append(str(self)) or False)
    assert tickets.doing_stale(proj, t, t["checklist"][0]) is False
    assert opened == []


def test_covers_add_edit_and_show(proj, run, validate, new_ticket):
    tid = new_ticket("Export invoices")
    assert run("check", "add", tid, "Add button", "--covers", "A CSV  download button")[0] == 0
    run("check", "add", tid, "Phone layout")
    t = read(proj, tid)
    validate(t)
    assert t["checklist"][0]["covers"] == "A CSV download button" and "covers" not in t["checklist"][1]
    assert run("check", "edit", tid, "c2", "--covers", "works on the phone")[0] == 0
    t = read(proj, tid)
    validate(t)
    assert t["checklist"][1]["covers"] == "works on the phone" and t["checklist"][1]["text"] == "Phone layout"
    assert run("check", "edit", tid, "c2")[0] == 2  # nothing to change
    assert run("check", "add", tid, "x", "--covers", "y" * 301)[0] == 2
    code, out, _ = run("ticket", "show", tid)
    assert code == 0 and "Proof: No checks recorded" in out


# ---- recorded checks (B8): record, files_sig, changed since, failed ----
def _git(proj, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=proj, check=True, capture_output=True
    )


@pytest.fixture
def repo(proj):
    _git(proj, "init", "-q")
    (proj / "a.txt").write_text("one\n", encoding="utf-8")
    _git(proj, "add", "a.txt")
    _git(proj, "commit", "-q", "-m", "first")
    return proj


def test_files_sig_changes_and_ignores(repo):
    a = filesig.files_sig(repo)
    assert a and len(a) == 64 and filesig.files_sig(repo) == a
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    b = filesig.files_sig(repo)
    assert b and b != a
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    assert filesig.files_sig(repo) == a
    for ignored in (".orch/x.json", "node_modules/m/i.js", "__pycache__/c.pyc", "dist/o.js"):
        (repo / ignored).parent.mkdir(parents=True, exist_ok=True)
        (repo / ignored).write_text("x", encoding="utf-8")
    assert filesig.files_sig(repo) == a  # .orch and cache folders do not count
    (repo / "new.txt").write_text("hi", encoding="utf-8")
    c = filesig.files_sig(repo)
    assert c and c != a
    (repo / "new.txt").write_text("hi!", encoding="utf-8")
    assert filesig.files_sig(repo) not in (a, c)


def test_files_sig_without_git_or_on_timeout(proj, repo, monkeypatch):
    plain = proj.parent / (proj.name + "_plain")
    plain.mkdir()
    assert filesig.files_sig(plain) is None  # not a git folder
    assert filesig.files_sig(repo)

    def slow(*a, **k):
        raise subprocess.TimeoutExpired("git", 3)

    with monkeypatch.context() as m:  # (undo() would also drop the autouse isolated ORCH_HOME)
        m.setattr(safegit.subprocess, "Popen", slow)
        assert filesig.files_sig(repo) is None
    monkeypatch.setattr(filesig, "MAX_FILES", 2)
    (repo / "u1").write_text("1")
    (repo / "u2").write_text("2")
    assert filesig.files_sig(repo) is None  # size cap


def test_files_sig_without_git_binary(repo, monkeypatch):
    def nogit(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(safegit.subprocess, "Popen", nogit)
    assert filesig.files_sig(repo) is None


def test_files_sig_fresh_repo_without_commit(proj):
    _git(proj, "init", "-q")
    (proj / "x.txt").write_text("x")
    assert filesig.files_sig(proj)


def _done_with_record(proj, run, repo_tid, exit_code):
    run("check", "done", repo_tid, "c1", "--note", "by hand")
    code, out, err = run(
        "check", "record", repo_tid, "c1", "--cmd", "uv run pytest -q", "--exit", str(exit_code), "--json"
    )
    assert code == 0, err
    return json.loads(out)


def test_proof_state_changed_and_failed(repo, run, new_ticket, validate):
    tid = new_ticket("Export")
    run("check", "add", tid, "tests pass")
    ev = _done_with_record(repo, run, tid, 0)["evidence"][-1]
    assert ev["exit"] == 0 and len(ev["files_sig"]) == 64 and ev["ran_at"].endswith("Z")
    t = tickets.load(repo, tid)
    validate(t)
    assert tickets.proof_state(t, repo)["per_item"]["c1"] == "passed"
    (repo / "a.txt").write_text("edited\n", encoding="utf-8")
    state = tickets.proof_state(t, repo)
    assert state["per_item"]["c1"] == "changed" and state["line"] == "Changes haven't been checked yet"
    assert tickets.proof_state(t)["per_item"]["c1"] == "passed"  # no root, no staleness
    # recording again at the new state clears it; a failed run says so
    run("check", "record", tid, "c1", "--cmd", "uv run pytest -q", "--exit", "0")
    t = tickets.load(repo, tid)
    assert tickets.proof_state(t, repo)["per_item"]["c1"] == "passed"
    run("check", "record", tid, "c1", "--cmd", "uv run pytest -q", "--exit", "1")
    t = tickets.load(repo, tid)
    assert tickets.proof_state(t, repo)["line"] == "1 check failed"


def test_proof_state_computes_sig_once(repo, run, new_ticket, monkeypatch):
    tid = new_ticket("Export")
    for text in ("a", "b"):
        run("check", "add", tid, text)
    for c in ("c1", "c2"):
        run("check", "done", tid, c, "--note", "n")
        run("check", "record", tid, c, "--cmd", "x", "--exit", "0")
    calls = []
    real = filesig.files_sig
    monkeypatch.setattr(filesig, "files_sig", lambda r: calls.append(r) or real(r))
    tickets.proof_state(tickets.load(repo, tid), repo)
    assert len(calls) == 1


def test_record_and_proof_state_never_execute(repo, run, new_ticket, monkeypatch, tmp_path):
    """The invariant: the recorded command and output are data. Nothing may run them."""
    tid = new_ticket("Export")
    run("check", "add", tid, "tests pass")
    out = repo / "out.txt"
    out.write_text("$(touch PWNED)\n`touch PWNED`\n", encoding="utf-8")
    real_popen = subprocess.Popen
    seen = []

    def only_git(argv, *a, **k):
        assert (
            isinstance(argv, list) and os.path.basename(argv[0]) in ("git", "git.exe") and not k.get("shell")
        ), argv
        assert not any("PWNED" in x or "rm -rf" in x for x in argv), argv
        seen.append(argv)
        return real_popen(argv, *a, **k)

    def boom(*a, **k):
        raise AssertionError("something was executed")

    monkeypatch.setattr(subprocess, "Popen", only_git)
    for name in ("call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, boom)
    for name in ("system", "popen", "execv", "execvp", "spawnv", "posix_spawn"):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, boom)
    code, _, err = run(
        "check", "record", tid, "c1", "--cmd", "touch PWNED; rm -rf /", "--exit", "0", "--output", "out.txt"
    )
    assert code == 0, err
    run("check", "done", tid, "c1", "--note", "n")
    t = tickets.load(repo, tid)
    tickets.proof_state(t, repo)
    assert not (repo / "PWNED").exists() and seen  # only fixed git argv lists ran
    ev = t["checklist"][0]["evidence"][0]
    assert ev["ref"] == "touch PWNED; rm -rf /" and "$(touch PWNED)" in ev["output_tail"]


def _hostile_repo(proj, marker):
    """A repo whose clean filter runs `touch <marker>`, set in .gitattributes AND .git/info/attributes."""
    _git(proj, "init", "-q")
    (proj / "a.txt").write_text("one\n", encoding="utf-8")
    _git(proj, "add", "a.txt")
    _git(proj, "commit", "-q", "-m", "first")
    _git(proj, "config", "filter.evil.clean", f"touch {marker}; cat")
    _git(proj, "config", "filter.evil.process", f"touch {marker}")
    (proj / ".gitattributes").write_text("* filter=evil\n", encoding="utf-8")
    (proj / ".git" / "info" / "attributes").write_text("* filter=evil\n", encoding="utf-8")
    (proj / "a.txt").write_text("edited so git must look at it\n", encoding="utf-8")
    (proj / "new.txt").write_text("untracked\n", encoding="utf-8")


def test_hostile_filters_never_run(proj, run, new_ticket):
    marker = proj.parent / (proj.name + "_MARKER")
    tid = new_ticket("Export")
    run("check", "add", tid, "tests pass")
    _hostile_repo(proj, marker)
    # control: a content-comparing git command WOULD run the filter here (the test is meaningful)
    subprocess.run(["git", "diff", "HEAD"], cwd=proj, capture_output=True, check=False)
    assert marker.exists()
    marker.unlink()
    assert filesig.files_sig(proj)
    code, _, err = run("check", "record", tid, "c1", "--cmd", "pytest", "--exit", "0")
    assert code == 0, err
    run("check", "done", tid, "c1", "--note", "n")
    t = tickets.load(proj, tid)
    tickets.proof_state(t, proj)
    run("ticket", "show", tid)
    assert not marker.exists()


def test_files_sig_content_not_index(repo):
    a = filesig.files_sig(repo)
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    b = filesig.files_sig(repo)
    assert b != a
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "second")
    assert filesig.files_sig(repo) == b  # add/commit alone is not a change
    (repo / "a.txt").unlink()
    assert filesig.files_sig(repo) not in (a, b)  # a deleted file is


@pytest.mark.skipif(sys.platform == "win32", reason="fifo, symlink and hard link need POSIX")
def test_files_sig_special_files_never_block_or_read(repo, tmp_path):
    a = filesig.files_sig(repo)
    os.mkfifo(repo / "pipe")
    secret = tmp_path.parent / (tmp_path.name + "_s.txt")
    secret.write_text("s", encoding="utf-8")
    (repo / "link").symlink_to(secret)
    os.link(secret, repo / "hard")
    sig = filesig.files_sig(repo)  # would hang on the FIFO if it were opened blocking
    assert sig and sig != a
    big = repo / "big.bin"
    big.write_bytes(b"x" * (filesig.HASH_LIMIT + 10))
    assert filesig.files_sig(repo)
    monkey = filesig.MAX_READ
    try:
        filesig.MAX_READ = 5
        (repo / "small.txt").write_text("123456789")
        assert filesig.files_sig(repo) is None  # read budget spent
    finally:
        filesig.MAX_READ = monkey


OURS = {
    "GIT_TERMINAL_PROMPT",
    "GIT_EDITOR",
    "GIT_SEQUENCE_EDITOR",
    "GIT_ASKPASS",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_GRAFT_FILE",
}  # set by safegit, not inherited (the last two: no replace refs or grafts, B13d)


def test_git_env_is_dropped_by_prefix(proj, run, new_ticket, monkeypatch):
    repo = proj
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "first")
    good = filesig.files_sig(repo)
    marker = proj.parent / (proj.name + "_ENVMARK")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.fsmonitor")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", f"touch {marker}")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", f"'core.fsmonitor={marker}'")
    monkeypatch.setenv("GIT_DIR", str(proj.parent / "no-such-git-dir"))
    monkeypatch.setenv("GIT_WORK_TREE", str(proj.parent))
    monkeypatch.setenv("GIT_INDEX_FILE", str(proj.parent / "no-index"))
    monkeypatch.setenv("GIT_EXEC_PATH", str(proj.parent / "no-exec"))
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", "/")
    assert filesig.files_sig(repo) == good and good
    assert not marker.exists()
    seen = []
    real = subprocess.Popen
    monkeypatch.setattr(safegit.subprocess, "Popen", lambda a, **k: seen.append(k["env"]) or real(a, **k))
    filesig.files_sig(repo)
    assert seen and all(not any(k.startswith("GIT_") and k not in OURS for k in e) for e in seen)


@pytest.mark.skipif(sys.platform == "win32", reason="st_ctime is the creation time on Windows")
def test_files_sig_sees_an_edit_with_the_old_mtime(repo):
    big = repo / "big.bin"
    big.write_bytes(b"a" * (filesig.HASH_LIMIT + 10))  # above the hash limit: size + times only
    old = big.stat()
    first = filesig.files_sig(repo)
    time.sleep(0.02)
    big.write_bytes(b"b" * (filesig.HASH_LIMIT + 10))  # same size
    os.utime(big, ns=(old.st_atime_ns, old.st_mtime_ns))  # `touch -d`: the old mtime back
    assert filesig.files_sig(repo) != first  # ctime still moved


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need POSIX")
def test_files_sig_does_not_read_through_a_swapped_folder(repo, tmp_path, monkeypatch):
    (repo / "sub").mkdir()
    (repo / "sub" / "f.txt").write_text("inside\n", encoding="utf-8")
    _git(repo, "add", "sub/f.txt")
    _git(repo, "commit", "-q", "-m", "sub")
    before = filesig.files_sig(repo)
    outside = tmp_path.parent / (tmp_path.name + "_outside")
    outside.mkdir()
    (outside / "f.txt").write_text("secret\n", encoding="utf-8")
    (repo / "sub" / "f.txt").unlink()
    (repo / "sub").rmdir()
    (repo / "sub").symlink_to(outside)
    read = []
    real_read, real_pread = os.read, getattr(os, "pread", None)
    monkeypatch.setattr(saferead.os, "read", lambda fd, n: read.append(real_read(fd, n)) or read[-1])
    if real_pread:
        monkeypatch.setattr(
            saferead.os, "pread", lambda fd, n, o: read.append(real_pread(fd, n, o)) or read[-1]
        )
    # control (non-vacuous): the spy does see a normal file being read
    filesig._HASHES.clear()  # the cache would hide the reads
    assert filesig.files_sig(repo)  # the real path reads the files: the spy must see them
    assert any(b"one" in chunk for chunk in read)
    read.clear()
    filesig._HASHES.clear()
    after = filesig.files_sig(repo)
    assert after != before and not any(b"secret" in chunk for chunk in read)  # never read through the link
    budget = [10_000]
    assert saferead.file_state(repo.resolve(), "sub/f.txt", 1000, budget) == "?"  # the folder is a link now
    assert budget == [10_000] and not any(b"secret" in chunk for chunk in read)


def test_runs_and_entries_are_capped_per_check():
    stamp = lambda i: f"2026-11-09T{i // 3600:02d}:{i % 3600 // 60:02d}:{i % 60:02d}Z"  # noqa: E731
    evs = [{"type": "note", "ref": f"n{i}"} for i in range(10)]
    evs += [
        {"type": "command", "ref": f"cmd{c}", "ran_at": stamp(c * 100 + i)}
        for c in range(20)
        for i in range(5)
    ]
    out = tickets.trim_runs(evs)
    assert all(e in out for e in evs[:10]) and len(out) == 10 + 45  # notes stay, only runs are capped
    assert evs[-1] in out
    assert [e["ran_at"] for e in out if e["ref"].startswith("cmd")] == sorted(
        e["ran_at"] for e in out if e["ref"].startswith("cmd")
    )


def test_cap_applies_to_runs_only_and_keeps_the_newest():
    stamp = lambda i: f"2026-11-09T10:{i // 60:02d}:{i % 60:02d}Z"  # noqa: E731
    notes = [{"type": "note", "ref": f"n{i}"} for i in range(70)]
    runs = [{"type": "command", "ref": f"r{i}", "ran_at": stamp(i)} for i in range(60)]
    out = tickets.trim_runs([*notes, *runs])
    assert all(n in out for n in notes)  # notes are never dropped because of runs
    kept = [e for e in out if e["type"] == "command"]
    assert (
        len(kept) == 45
        and runs[-1] in kept
        and runs[0] not in kept
        and runs[14] not in kept
        and runs[15] in kept
    )
    five = [{"type": "command", "ref": "same", "ran_at": stamp(i)} for i in range(9)]
    assert tickets.trim_runs(five) == five[-5:]


def test_anchor_refuses_empty_parts_and_a_fifo_log_never_blocks(proj):
    with pytest.raises(OSError):
        saferead._anchor(proj.resolve(), ())
    assert saferead.file_state(proj.resolve(), "", 10, [10]) == "?"
    if sys.platform != "win32":
        os.mkfifo(proj / "x.log")
        import threading

        out = {}

        def attempt():
            try:
                try:
                    saferead.safe_read_tail(proj, "x.log", 100)
                except tickets.Refused:
                    out["tail"] = "refused"
                out["state"] = saferead.file_state(proj.resolve(), "x.log", 10, [10])
            except BaseException as e:  # a clear failure below, not a silent thread death
                out["error"] = repr(e)

        th = threading.Thread(target=attempt, daemon=True)
        th.start()
        th.join(2)
        assert not th.is_alive(), "a FIFO blocked the reader"  # a regression fails here instead of hanging CI
        assert "error" not in out, out
        assert out["tail"] == "refused" and out["state"].startswith("S:"), out


def test_fallback_check_wants_the_path_itself_to_be_the_file(proj, tmp_path):
    real = proj / "real.txt"
    real.write_text("x", encoding="utf-8")
    if sys.platform != "win32":
        (proj / "link.txt").symlink_to(real)
        got = saferead._open_checked(str(proj / "link.txt"), {}, str(proj / "link.txt"))
        assert got is None  # O_NOFOLLOW or the lstat check: never a link
    got = saferead._open_checked(str(real), {}, str(real))
    assert got is not None
    os.close(got[0])


def test_open_checked_closes_the_fd_when_a_stat_fails(proj, monkeypatch):
    f = proj / "f.txt"
    f.write_text("x", encoding="utf-8")
    closed, opened = [], []

    class Os:
        """saferead.os with a failing fstat and every open/close recorded (the real os stays untouched)."""

        def __init__(self, exc):
            self.exc = exc

        def __getattr__(self, name):
            return getattr(os, name)

        def open(self, *a, **k):
            opened.append(os.open(*a, **k))
            return opened[-1]

        def close(self, fd):
            closed.append(fd)
            os.close(fd)

        def fstat(self, fd):
            raise self.exc

    monkeypatch.setattr(saferead, "os", Os(OSError("boom")))
    assert saferead._open_checked(str(f), {}) is None
    assert opened and closed == opened
    opened.clear()
    closed.clear()
    monkeypatch.setattr(saferead, "os", Os(ValueError("odd")))
    with pytest.raises(ValueError):
        saferead._open_checked(str(f), {})
    assert opened and closed == opened


def test_saferead_opens_files_in_binary_mode(proj):
    """Windows os.open defaults to text mode (CRLF -> LF, Ctrl-Z ends the read).

    The safe reader must ask for O_BINARY, so tails and hashes are byte-exact (meaningful on Windows CI)."""
    import hashlib

    binary = getattr(saferead.os, "O_BINARY", 0)
    assert saferead._FLAGS & binary == binary
    raw = b"line one\r\nline two\r\n\x1aafter ctrl-z\r\n"
    (proj / "out.log").write_bytes(raw)
    # byte-exact: no CRLF folding, no Ctrl-Z stop
    assert saferead.safe_read_tail(proj.resolve(), "out.log", 4096) == raw
    state = saferead.file_state(proj.resolve(), "out.log", 1 << 20, [1 << 20])
    assert hashlib.sha256(raw).hexdigest() in state


# ---- Won't do (a person's decision; an agent can only ask)


def test_wont_do_by_person_counts_as_resolved_and_undo(proj, run, validate, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    code, out, _ = run("check", "wont-do", tid, "c2", "--reason", "Finance pulls it", "--by", "human:tester")
    assert code == 0 and "Won't do" in out
    t = read(proj, tid)
    validate(t)
    c2 = t["checklist"][1]
    assert c2["wont_do"] is True and c2["done"] is False and c2["reason"] == "Finance pulls it"
    assert t["history"][-1]["by"] == "human:tester" and t["history"][-1]["text"] == "Marked c2 as won't do"
    assert tickets.history_line(t["history"][-1]["text"], t["checklist"]) == "Marked as won't do: step 2"
    assert tickets.checks_done(t) == (1, 3)  # only c2 resolved
    code, out, _ = run("ticket", "show", tid)
    assert "Won't do: Finance pulls it" in out
    # undo by the person
    assert run("check", "reopen", tid, "c2", "--by", "human:tester")[0] == 0
    c2 = read(proj, tid)["checklist"][1]
    assert "wont_do" not in c2 and "reason" not in c2 and c2["done"] is False


def test_wont_do_counts_for_finishing_the_ticket(proj, run, new_ticket, monkeypatch):
    tid = with_checks(proj, run, new_ticket, n=2)
    run("check", "done", tid, "c1", "--note", "ok", "--by", "human:tester")
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    with_open = tickets.load(proj, tid)
    try:
        tickets._check_can_finish(with_open)
        raise AssertionError("open step must block")
    except tickets.Refused:
        pass
    run("check", "wont-do", tid, "c2", "--by", "human:tester")
    tickets._check_can_finish(tickets.load(proj, tid))  # resolved without proof: no refusal


def test_agent_can_never_set_or_undo_wont_do(proj, run, new_ticket, monkeypatch):
    tid = with_checks(proj, run, new_ticket)
    # an explicit agent actor
    code, _, err = run("check", "wont-do", tid, "c1", "--by", "agent:claude")
    assert code == 2 and "orch ask" in err
    # a person's name given from inside an agent session (environment wins)
    monkeypatch.setenv("CLAUDECODE", "1")
    code, _, err = run("check", "wont-do", tid, "c1", "--by", "human:tester")
    assert code == 2
    assert "wont_do" not in read(proj, tid)["checklist"][0]
    monkeypatch.delenv("CLAUDECODE")
    run("check", "wont-do", tid, "c1", "--by", "human:tester")
    monkeypatch.setenv("CLAUDECODE", "1")
    # an agent can neither reopen it, tick it, start it nor patch it in
    for argv in (
        ("check", "reopen", tid, "c1", "--by", "human:tester"),
        ("check", "reopen", tid, "c1"),
        ("check", "done", tid, "c1", "--note", "x"),
        ("check", "start", tid, "c1"),
    ):
        assert run(*argv)[0] == 2, argv
    assert run("ticket", "patch", tid, "--if-revision", "1", '{"checklist": []}')[0] == 2
    assert read(proj, tid)["checklist"][0]["wont_do"] is True


def test_wont_do_reason_and_done_step(proj, run, new_ticket):
    tid = with_checks(proj, run, new_ticket)
    assert run("check", "wont-do", tid, "c1", "--reason", "x" * 201, "--by", "human:tester")[0] == 2
    run("check", "done", tid, "c1", "--note", "ok", "--by", "human:tester")
    assert run("check", "wont-do", tid, "c1", "--by", "human:tester")[0] == 2  # done: reopen first
    assert run("check", "wont-do", tid, "c9", "--by", "human:tester")[0] == 2  # unknown step


def test_agent_cannot_remove_a_wont_do_step(proj, run, new_ticket, monkeypatch):
    tid = with_checks(proj, run, new_ticket)
    run("check", "wont-do", tid, "c1", "--by", "human:tester")
    assert run("check", "remove", tid, "c1", "--by", "agent:claude")[0] == 2
    monkeypatch.setenv("CLAUDECODE", "1")
    assert run("check", "remove", tid, "c1")[0] == 2
    monkeypatch.delenv("CLAUDECODE")
    assert run("check", "remove", tid, "c1", "--by", "human:tester")[0] == 0


def test_run_prompt_skips_wont_do_steps(proj, run, new_ticket):
    from orch import runs

    tid = with_checks(proj, run, new_ticket, n=2)
    run("check", "wont-do", tid, "c1", "--by", "human:tester")
    text = runs.fresh_prompt(tickets.load(proj, tid), [], proj)
    assert "c2: step 2" in text and "c1: step 1" not in text


def _decided(proj, run, new_ticket, n=2):
    tid = with_checks(proj, run, new_ticket, n=n)
    run("check", "wont-do", tid, "c1", "--reason", "Not needed", "--by", "human:tester")
    return tid


def test_agent_cannot_edit_a_wont_do_step(proj, run, new_ticket, monkeypatch):
    tid = _decided(proj, run, new_ticket)
    assert run("check", "edit", tid, "c1", "Run the security tests", "--by", "agent:claude")[0] == 2
    monkeypatch.setenv("CLAUDECODE", "1")
    assert run("check", "edit", tid, "c1", "Run the security tests", "--by", "human:tester")[0] == 2
    assert read(proj, tid)["checklist"][0]["text"] == "step 1"
    monkeypatch.delenv("CLAUDECODE")
    assert run("check", "edit", tid, "c1", "Rename by person", "--by", "human:tester")[0] == 0


def test_generic_writes_by_an_agent_cannot_change_wont_do(proj, run, new_ticket, monkeypatch):
    """Every generic write path (apply_op callers, patch, edit) under an agent keeps the decision intact."""
    tid = _decided(proj, run, new_ticket)
    monkeypatch.setenv("CLAUDECODE", "1")
    # apply_op itself: setting, clearing, changing the reason, who/when, adding a new wont_do step
    for change in (
        lambda t: t["checklist"][1].update(wont_do=True),
        lambda t: t["checklist"][0].pop("wont_do"),
        lambda t: t["checklist"][0].update(reason="other"),
        lambda t: t["checklist"][0].update(by="agent:claude"),
        lambda t: t["checklist"].append(
            {"id": "c9", "text": "x", "done": False, "evidence": [], "wont_do": True}
        ),
        lambda t: t["checklist"].pop(0),
    ):
        with pytest.raises(tickets.Refused):
            tickets.apply_op(proj, tid, change, by=tickets.SYSTEM)
    # patch / edit cannot reach the checklist at all
    assert run("ticket", "patch", tid, "--if-revision", "99", '{"checklist": []}')[0] == 2
    assert run("ticket", "edit", tid, "--title", "New title")[0] == 0
    t = read(proj, tid)
    assert t["checklist"][0]["wont_do"] is True and t["checklist"][0]["reason"] == "Not needed"
    assert "wont_do" not in t["checklist"][1]
    # an unrelated agent write still works
    assert tickets.apply_op(proj, tid, lambda t: t["checklist"][1].update(text="renamed"), by=tickets.SYSTEM)[
        0
    ]


def test_progress_says_done_and_wont_do_apart(proj, run, new_ticket):
    tid = with_checks(proj, run, new_ticket, n=3)
    run("check", "done", tid, "c1", "--note", "ok", "--by", "human:tester")
    assert tickets.progress_text(tickets.load(proj, tid)) == "1 of 3 done"
    run("check", "wont-do", tid, "c2", "--by", "human:tester")
    run("check", "wont-do", tid, "c3", "--by", "human:tester")
    t = tickets.load(proj, tid)
    assert tickets.progress_text(t) == "1 done, 2 won't do" and tickets.checks_split(t) == (1, 2, 3)
    code, out, _ = run("ticket", "show", tid)
    assert "1 done, 2 won't do" in out and "All resolved" in out and "3 of 3" not in out


def test_prompt_names_declined_steps_and_cli_strips_control_chars(proj, run, new_ticket):
    from orch import runs

    tid = with_checks(proj, run, new_ticket, n=2)
    run("check", "wont-do", tid, "c1", "--by", "human:tester")
    tickets.apply_op(  # a synced or hand-edited reason can carry control characters
        proj, tid, lambda t: t["checklist"][0].update(reason="Skip \x1b[31mred\x07"), by=tickets.SYSTEM
    )
    text = runs.fresh_prompt(tickets.load(proj, tid), [], proj)
    assert "Declined by a person" in text and "c1 (" in text and "c1: step 1" not in text
    _, out, _ = run("ticket", "show", tid)
    assert "\x1b" not in out and "\x07" not in out

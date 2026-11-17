"""Renew a tool login or replace a key from the warning (renew.py, `orch logins renew|replace`, ORCH-46)."""

import io
import json
import os
import stat
import sys
import threading
import time
from pathlib import Path

import pytest

from orch import adapters, health, keystore, renew, runs, tickets
from orch.errors import Refused

HIDDEN = "other-text-the-tool-prints-that-must-not-be-kept"
LINK = "https://claude.com/cai/oauth/authorize?code=true&state=abc"


def _tool(tmp_path, body: str):
    """A stand-in for the tool's own sign-in command (a small Python program)."""
    p = tmp_path / "fake-login"
    p.write_text(f"#!{sys.executable}\nimport sys\n{body}\n", encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


@pytest.fixture(autouse=True)
def person(proj, monkeypatch):
    """These tests act as the person (as if the dashboard's signed-in session granted the call)."""
    monkeypatch.setattr(renew, "_GRANTED", {str(proj.resolve())})


@pytest.fixture
def fake(proj, tmp_path, monkeypatch):
    """renew.spec points at a fake sign-in that prints a link and other text, then reads one line."""
    got = tmp_path / "got.txt"
    tool = _tool(
        tmp_path,
        f"print({HIDDEN!r})\nprint('visit: {LINK}', flush=True)\nprint('Paste code here > ', flush=True)\n"
        f"open({str(got)!r}, 'w').write(sys.stdin.readline())\n",
    )
    monkeypatch.setattr(
        renew,
        "spec",
        lambda root, name: (
            {
                "binary": str(tool),
                "argv": [str(tool)],
                "links": ["https://claude.com/"],
                "helper": "claude",
                "label": "Main helper",
            }
            if name == "claude"
            else None
        ),
    )
    seen = []

    def after(root, name):
        seen.append(name)
        return {"state": "works", "ends_at": "2026-12-17T21:24:57Z", "went_on": ["ORCH-9"]}

    monkeypatch.setattr(renew, "after", after)
    return {"got": got, "seen": seen}


def _work(proj, name="claude"):
    """The worker as a person's start launches it: with the one-time token start keeps (hash) in the state."""
    token = "test-token-" + name
    renew._write(proj, name, {"state": "starting", "started_at": renew._now(), "beat_at": renew._now(),
                              "token": renew._hash(token)})  # fmt: skip
    os.environ[renew.TOKEN_ENV] = token
    return renew.work(proj, name)


def _wait(proj, want, limit=10.0):
    end = time.time() + limit
    while time.time() < end:
        st = renew.status(proj, "claude")
        if st["state"] in want:
            return st
        time.sleep(0.1)
    raise AssertionError(f"state stayed {renew.status(proj, 'claude')}")


def _all_text(proj) -> str:
    d = renew._dir(proj, "claude")
    return "".join(p.read_text(encoding="utf-8", errors="replace") for p in d.rglob("*") if p.is_file())


def test_link_only_with_an_allowed_start():
    text = f"Opening…\nvisit: https://evil.example/x?{LINK}\nIf not: {LINK}.\n"
    assert renew.link_in(text, ["https://claude.com/"]) == LINK
    assert renew.link_in("visit: http://claude.com/x", ["https://claude.com/"]) is None
    assert renew.link_in("nothing here", ["https://claude.com/"]) is None


def test_worker_passes_the_link_and_the_code_and_keeps_nothing_else(proj, fake):
    t = threading.Thread(target=_work, args=(proj,), daemon=True)
    t.start()
    st = _wait(proj, {"link"})
    assert st["link"] == LINK
    renew.code(proj, "claude", "  the-code#from-page  ")
    st = _wait(proj, {"done", "failed"})
    t.join(5)
    assert st == {
        "name": "claude",
        "state": "done",
        "ends_at": "2026-12-17T21:24:57Z",
        "went_on": ["ORCH-9"],
    }
    assert fake["got"].read_text(encoding="utf-8") == "the-code#from-page\n"  # straight to the tool
    assert fake["seen"] == ["claude"]  # checked again after the tool ended
    kept = _all_text(proj)
    assert HIDDEN not in kept and "the-code" not in kept and "Paste" not in kept
    assert not (renew._dir(proj, "claude") / "code").exists()


def test_close_ends_the_tool(proj, fake, monkeypatch):
    t = threading.Thread(target=_work, args=(proj,), daemon=True)
    t.start()
    _wait(proj, {"link"})
    renew.cancel(proj, "claude")
    assert _wait(proj, {"stopped", "done", "failed"})["state"] == "stopped"
    t.join(5)
    assert fake["seen"] == []


def test_a_failed_sign_in_says_failed(proj, tmp_path, monkeypatch):
    tool = _tool(tmp_path, "sys.exit(1)")
    monkeypatch.setattr(
        renew,
        "spec",
        lambda root, name: {"binary": str(tool), "argv": [str(tool)], "links": ["https://claude.com/"],
                            "helper": "claude", "label": "Main helper"},
    )  # fmt: skip
    assert _work(proj) == 1
    assert renew.status(proj, "claude")["state"] == "failed"


@pytest.mark.parametrize("text", ["", "abc", "a b c d", "x" * 600, "code;rm -rf"])
def test_a_code_that_is_not_one_is_refused(proj, text):
    with pytest.raises(Refused):
        renew.code(proj, "claude", text)


def test_a_code_with_nothing_waiting_is_refused(proj):
    with pytest.raises(Refused, match="no longer waiting"):
        renew.code(proj, "claude", "abcdef")


def test_only_tools_with_a_renew_step(proj):
    s = renew.spec(proj, "claude")
    assert s["argv"][1:] == ["auth", "login"] and s["helper"] == "claude"
    assert all(p.startswith("https://") and p.endswith("/") for p in s["links"])
    assert renew.spec(proj, "codex") is None and renew.spec(proj, "gh") is None
    with pytest.raises(Refused):
        renew.start(proj, "gh")
    with pytest.raises(Refused):
        renew.status(proj, "../x")


def test_start_spawns_one_worker(proj, fake, monkeypatch):
    calls = []
    monkeypatch.setattr(renew.subprocess, "Popen", lambda argv, **kw: calls.append((argv, kw)))
    st = renew.start(proj, "claude")
    assert st["state"] == "starting" and calls[0][0][-4:] == ["logins", "renew", "claude", "--worker"]
    assert calls[0][1]["stdout"] == renew.subprocess.DEVNULL
    st = renew.status(proj, "claude")
    assert st["state"] == "starting" and len(calls) == 1


def test_renew_again_ends_the_older_sign_in_first(proj, fake, monkeypatch):
    t = threading.Thread(target=_work, args=(proj,), daemon=True)
    t.start()
    _wait(proj, {"link"})
    calls = []
    monkeypatch.setattr(renew.subprocess, "Popen", lambda argv, **kw: calls.append(argv))
    assert renew.start(proj, "claude")["state"] == "starting" and len(calls) == 1
    t.join(5)
    assert not t.is_alive()  # the older worker ended its tool and stopped


# ---------------------------------------------------------------------------------------------- helpers go on


def _waiting(proj, run, tid, ref):
    run("ticket", "status", tid, "active", "--by", "human:tester")
    tickets.wait_for_start(proj, tid, ref, "agent:claude")
    assert tickets.load(proj, tid)["status"] == "waiting"


def test_go_on_starts_only_tickets_that_wait_for_this_login(proj, run, new_ticket, monkeypatch):
    monkeypatch.setattr(adapters, "chosen", lambda root: "claude")
    a, b, c = new_ticket("Waits for login"), new_ticket("Failed for another reason"), new_ticket("Idle")
    _waiting(proj, run, a, "Couldn't start the agent: no login")
    _waiting(proj, run, b, "Couldn't start the agent: tmux is not installed")
    started = []
    monkeypatch.setattr(runs, "start", lambda root, tid, by, **kw: started.append((tid, by)))
    went = renew.go_on(proj, "claude")
    assert [s[0] for s in started] == [a] and len(went) == 1
    assert "The login works again" in json.dumps(tickets.load(proj, a)["history"])
    assert renew.go_on(proj, "codex") == [] and renew.go_on(proj, None) == []
    assert c not in [s[0] for s in started]


def test_after_checks_again_and_goes_on_only_when_it_works(proj, monkeypatch):
    rows = {"items": [{"name": "claude", "state": "renew", "helper": "claude", "ends_at": None}]}
    monkeypatch.setattr(health, "check", lambda root: rows)
    went = []
    monkeypatch.setattr(renew, "go_on", lambda root, helper: went.append(helper) or ["X-1"])
    assert renew.after(proj, "claude")["went_on"] == [] and went == []
    rows["items"][0].update(state="works", ends_at="2026-12-17T00:00:00Z")
    assert renew.after(proj, "claude") == {
        "state": "works",
        "ends_at": "2026-12-17T00:00:00Z",
        "went_on": ["X-1"],
    }


# ---------------------------------------------------------------------------------------------- a key


def test_replace_a_key_through_the_key_store_and_check_again(proj, run, monkeypatch, capsys):
    keystore.record_write(
        proj,
        "checks",
        {"checks": {"payments": {"label": "Payments key", "command": ["pay", "ping"], "key": "PAY"}}},
    )
    keystore.add(proj, "PAY", "token", "old-value-123")
    monkeypatch.setattr(health.shutil, "which", lambda b: f"/bin/{b}" if b == "pay" else None)
    monkeypatch.setattr(
        health.subprocess, "run", lambda argv, **kw: health.subprocess.CompletedProcess(argv, 0, None, None)
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO("new-value-456\n"))
    code, out, err = run("logins", "replace", "payments")
    assert code == 0, err
    assert "works" in out and "new-value" not in out + err
    got = next(k for k in keystore.list_keys(proj) if k["name"] == "PAY")
    assert got["type"] == "token" and "new-value" not in json.dumps(got)
    row = health.last(proj)["items"][0]
    assert (row["name"], row["state"], row["key"], row["renew"]) == ("payments", "works", "PAY", False)
    assert "new-value" not in health._path(proj).read_text(encoding="utf-8")


def test_replace_needs_a_check_that_names_a_key(proj, run, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("new-value-456\n"))
    code, out, err = run("logins", "replace", "nothing")
    assert code == 2 and "names no key" in out + err


@pytest.mark.parametrize("key", ["../x", "a b", "", 5])
def test_a_recipe_key_must_be_a_key_name(key):
    assert health._recipe("t", {"command": ["t"], "key": key}) is None


# ---------------------------------------------------------------------------------------------- the command


def test_command_status_and_code_on_stdin(proj, run, fake, monkeypatch):
    code, out, err = run("logins", "renew", "claude", "--status", "--json")
    assert code == 0 and json.loads(out)["state"] == "none"
    t = threading.Thread(target=_work, args=(proj,), daemon=True)
    t.start()
    _wait(proj, {"link"})
    code, out, err = run("logins", "renew", "claude", "--status")
    assert code == 0 and LINK in out and "--code -" in out
    monkeypatch.setattr(sys, "stdin", io.StringIO("abc-def-123\n"))
    code, out, err = run("logins", "renew", "claude", "--code", "-")
    assert code == 0 and "abc-def" not in out + err
    _wait(proj, {"done"})
    t.join(5)
    code, out, err = run("logins", "renew", "claude", "--status")
    assert "The login is renewed. Helpers go on with ORCH-9." in out


def test_rows_say_what_can_be_renewed(proj, monkeypatch):
    monkeypatch.setattr(health.shutil, "which", lambda b: f"/bin/{b}" if b == "claude" else None)
    monkeypatch.setattr(
        health.subprocess,
        "run",
        lambda argv, **kw: health.subprocess.CompletedProcess(argv, 0, json.dumps({"loggedIn": False}), ""),
    )
    row = health.overview(proj)[0]
    assert (row["name"], row["state"], row["renew"], row["key"]) == ("claude", "renew", True, None)


def test_no_worker_left_in_the_state_after_a_dead_one(proj):
    d = renew._dir(proj, "claude")
    d.mkdir(parents=True)
    old = "2020-01-01T00:00:00Z"
    (d / "state.json").write_text(
        json.dumps(
            {"schema": renew.SCHEMA, "name": "claude", "state": "link", "started_at": old, "beat_at": old}
        ),
        encoding="utf-8",
    )
    assert renew.status(proj, "claude")["state"] == "failed"
    if os.name != "nt":
        assert stat.S_IMODE(d.stat().st_mode) in (0o700, 0o755)


# ------------------------------------------------------------------------------------------ R5.2: never again


def _every_file(*tops):
    for top in tops:
        for p in top.rglob("*"):
            if p.is_file() and not p.is_symlink():
                yield p


def test_a_replaced_key_and_a_code_are_kept_only_in_the_key_store(proj, run, fake, monkeypatch, capsys):
    """R5.2 (ORCH-46): after Replace and a pasted code, the values are in no ticket, debug log, run file,
    problem report or output; the new key lives only in the key store's own file."""
    from orch import home as orch_home

    key_value, code_value = "replaced-key-VALUE-7f3a9c", "pasted-CODE-41b8e2"
    keystore.record_write(
        proj,
        "checks",
        {"checks": {"payments": {"label": "Payments key", "command": ["pay", "ping"], "key": "PAY"}}},
    )
    keystore.add(proj, "PAY", "token", "old-value-123")
    which = health.shutil.which  # the same module renew uses: keep the real lookup for the fake sign-in
    monkeypatch.setattr(health.shutil, "which", lambda b: "/bin/pay" if b == "pay" else which(b))
    monkeypatch.setattr(
        health.subprocess, "run", lambda argv, **kw: health.subprocess.CompletedProcess(argv, 0, None, None)
    )
    out = ""
    monkeypatch.setattr(sys, "stdin", io.StringIO(key_value + "\n"))
    code, o, e = run("logins", "replace", "payments", "--json")
    assert code == 0, e
    out += o + e
    t = threading.Thread(target=_work, args=(proj,), daemon=True)
    t.start()
    _wait(proj, {"link"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(code_value + "\n"))
    code, o, e = run("logins", "renew", "claude", "--code", "-")
    assert code == 0, e
    out += o + e
    _wait(proj, {"done"})
    t.join(5)
    assert fake["got"].read_text(encoding="utf-8") == code_value + "\n"  # it did reach the tool
    code, o, e = run("diag", "report")  # a problem report for whoever helps
    out += o + e
    assert key_value not in out and code_value not in out
    store = orch_home.key_dir(proj) / "keys.json"
    home = Path(os.environ["ORCH_HOME"])
    holders = [p for p in _every_file(proj, home) if key_value.encode() in p.read_bytes()]
    assert holders == [store]
    # the fake tool's own capture file is the tool receiving it; nothing of orch's holds the code
    assert [p for p in _every_file(proj, home) if code_value.encode() in p.read_bytes()] == [fake["got"]]


def test_a_code_the_tool_does_not_take_asks_for_it_again(proj, tmp_path, monkeypatch):
    """An incomplete code: Claude Code answers with a line and waits; the state goes back to link (again)."""
    got = tmp_path / "got2.txt"
    tool = _tool(
        tmp_path,
        f"print('visit: {LINK}', flush=True)\nsys.stdin.readline()\n"
        f"print({HIDDEN!r}, flush=True)\nopen({str(got)!r}, 'w').write(sys.stdin.readline())\n",
    )
    monkeypatch.setattr(
        renew,
        "spec",
        lambda root, name: {"binary": str(tool), "argv": [str(tool)], "links": ["https://claude.com/"],
                            "helper": "claude", "label": "Main helper"},
    )  # fmt: skip
    monkeypatch.setattr(renew, "after", lambda root, name: {"state": "works", "ends_at": None, "went_on": []})
    monkeypatch.setattr(renew, "ASKS_AGAIN", 0.5)
    t = threading.Thread(target=_work, args=(proj,), daemon=True)
    t.start()
    _wait(proj, {"link"})
    renew.code(proj, "claude", "half-a-code")
    end = time.time() + 10
    while time.time() < end and not renew.status(proj, "claude").get("again"):
        time.sleep(0.1)
    st = renew.status(proj, "claude")
    assert (st["state"], st.get("again")) == ("link", True)
    assert HIDDEN not in _all_text(proj)  # what the tool said is not kept
    renew.code(proj, "claude", "whole#code")
    assert _wait(proj, {"done", "failed"})["state"] == "done"
    t.join(5)
    assert got.read_text(encoding="utf-8") == "whole#code\n"


# ------------------------------------------------------------------- security review of PR 1131 (ORCH-46)

AGENT_WAYS = [
    ({"ORCH_AGENT": "claude"}, None),  # a helper tool's environment
    ({"ORCH_RUN": "r_abcdefgh"}, None),  # a process inside a helper run
    ({"ORCH_TICKET": "t_abcdef"}, None),
    ({}, "agent:claude"),  # an agent actor
]


@pytest.mark.parametrize(("env", "by"), AGENT_WAYS)
def test_every_renew_entry_is_person_only(proj, fake, monkeypatch, env, by):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(renew.subprocess, "Popen", lambda *a, **k: pytest.fail("started"))
    for call in (
        lambda: renew.start(proj, "claude", by=by),
        lambda: renew.status(proj, "claude", by=by),
        lambda: renew.code(proj, "claude", "abc#def", by=by),
        lambda: renew.cancel(proj, "claude", by=by),
        lambda: renew.replace_key(proj, "payments", "new-key-value", by=by),
    ):
        with pytest.raises(Refused, match="Only a person"):
            call()


@pytest.mark.parametrize("env", [{"ORCH_AGENT": "claude"}, {"ORCH_RUN": "r_abcdefgh"}])
def test_both_commands_refuse_a_helper_before_reading_the_value(proj, run, monkeypatch, env):
    keystore.record_write(
        proj, "checks", {"checks": {"payments": {"label": "Payments key", "command": ["pay"], "key": "PAY"}}}
    )
    keystore.add(proj, "PAY", "token", "old-value-123")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    stdin = io.StringIO("attacker-token-123\n")
    monkeypatch.setattr(sys, "stdin", stdin)
    code, out, err = run("logins", "replace", "payments")
    assert code == 2 and "Only a person" in out + err
    assert stdin.tell() == 0  # nothing was read
    for argv in (["renew", "claude"], ["renew", "claude", "--status"], ["renew", "claude", "--code", "-"]):
        code, out, err = run("logins", *argv)
        assert code == 2 and "Only a person" in out + err, argv
    monkeypatch.delenv("ORCH_AGENT", raising=False)
    monkeypatch.delenv("ORCH_RUN", raising=False)
    assert keystore.get_value(proj, "PAY") == "old-value-123"  # the stored key is untouched


def test_a_worker_started_by_hand_is_refused(proj, fake, monkeypatch):
    monkeypatch.delenv(renew.TOKEN_ENV, raising=False)
    with pytest.raises(Refused, match="Only a person"):
        renew.work(proj, "claude")  # no token: a helper running `orch logins renew claude --worker`
    renew._write(proj, "claude", {"state": "starting", "started_at": renew._now(), "beat_at": renew._now(),
                                  "token": renew._hash("right")})  # fmt: skip
    monkeypatch.setenv(renew.TOKEN_ENV, "wrong")
    with pytest.raises(Refused):
        renew.work(proj, "claude")
    monkeypatch.setenv(renew.TOKEN_ENV, "right")
    assert renew._worker_allowed(proj, "claude") is True  # the right token passes once ...
    assert renew.TOKEN_ENV not in os.environ  # ... is not passed on to the tool ...
    monkeypatch.setenv(renew.TOKEN_ENV, "right")
    assert renew._worker_allowed(proj, "claude") is False  # ... and is used up


def test_a_forged_link_is_never_shown(proj, fake):
    for link in (
        "https://evil.example/claude.com/",
        "https://claude.com.evil.example/x",
        "http://claude.com/x",
    ):
        renew._write(proj, "claude", {"state": "link", "link": link, "started_at": renew._now(),
                                      "beat_at": renew._now()})  # fmt: skip
        assert "link" not in renew.status(proj, "claude"), link
    renew._write(
        proj, "claude", {"state": "link", "link": LINK, "started_at": renew._now(), "beat_at": renew._now()}
    )
    assert renew.status(proj, "claude")["link"] == LINK


def test_the_renew_state_is_in_the_guarded_home_not_in_the_project(proj, fake):
    old = runs.run_dir(proj) / "renew" / "claude"
    old.mkdir(parents=True)
    (old / "state.json").write_text(
        json.dumps({"schema": renew.SCHEMA, "name": "claude", "state": "link", "link": "https://evil.example/",
                    "started_at": renew._now(), "beat_at": renew._now()}), encoding="utf-8")  # fmt: skip
    assert renew.status(proj, "claude") == {"name": "claude", "state": "none"}  # the project file is not read
    assert proj not in renew._dir(proj, "claude").parents


def test_a_forged_health_row_does_not_choose_where_a_key_goes(proj, monkeypatch):
    """A helper writes a failing row naming a key it can use: the person's pasted key never lands there."""
    keystore.add(proj, "HELPER_KEY", "token", "old-value-123")
    forged = {"schema": "orch.health/1", "checked_at": renew._now(), "items": [
        {"name": "payments", "label": "Payments key", "state": "renew", "key": "HELPER_KEY"}]}  # fmt: skip
    (runs.run_dir(proj)).mkdir(parents=True, exist_ok=True)
    (runs.run_dir(proj) / "health.json").write_text(json.dumps(forged), encoding="utf-8")
    health._path(proj).write_text(json.dumps(forged), encoding="utf-8")  # even in the guarded place
    with pytest.raises(Refused, match="names no key"):
        renew.replace_key(proj, "payments", "the-persons-new-key")
    got = next(k for k in keystore.list_keys(proj) if k["name"] == "HELPER_KEY")
    assert got["added_at"]  # untouched
    assert "the-persons-new-key" not in json.dumps(keystore.list_keys(proj))


def test_a_health_file_in_the_project_is_not_shown(proj):
    forged = {"schema": "orch.health/1", "checked_at": renew._now(), "items": [
        {"name": "bank", "label": "Your bank login", "state": "renew"}]}  # fmt: skip
    runs.run_dir(proj).mkdir(parents=True, exist_ok=True)
    (runs.run_dir(proj) / "health.json").write_text(json.dumps(forged), encoding="utf-8")
    assert health.last(proj) is None


def test_two_quick_starts_leave_one_worker(proj, fake, monkeypatch):
    calls = []
    monkeypatch.setattr(renew.subprocess, "Popen", lambda argv, **kw: calls.append(argv))
    monkeypatch.setattr(renew, "_alive", lambda doc: False)  # nothing running yet, both race for the start
    seen = []

    def go():
        try:
            seen.append(renew.start(proj, "claude")["state"])
        except Refused as e:
            seen.append(str(e))

    ts = [threading.Thread(target=go) for _ in range(2)]
    with renew._start_lock(proj, "claude"):  # hold the lock while both threads queue up
        for t in ts:
            t.start()
        time.sleep(0.3)
        assert calls == []
    for t in ts:
        t.join(15)
    assert len(calls) == 2 and seen == ["starting", "starting"]  # one after the other, never two at once


def test_close_leaves_no_process(proj, tmp_path, monkeypatch):
    pidfile = tmp_path / "pid"
    tool = _tool(tmp_path, f"import os, time\nopen({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
                           f"print('visit: {LINK}', flush=True)\ntime.sleep(60)\n")  # fmt: skip
    one = {"binary": str(tool), "argv": [str(tool)], "links": ["https://claude.com/"], "helper": "claude",
           "label": "Main helper"}  # fmt: skip
    monkeypatch.setattr(renew, "spec", lambda root, name: one)
    t = threading.Thread(target=_work, args=(proj,), daemon=True)
    t.start()
    _wait(proj, {"link"})
    renew.cancel(proj, "claude")
    assert _wait(proj, {"stopped"})["state"] == "stopped"
    t.join(5)
    pid = int(pidfile.read_text())
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_a_key_is_stripped_before_it_is_kept(proj, monkeypatch):
    keystore.record_write(
        proj, "checks", {"checks": {"payments": {"label": "Payments key", "command": ["pay"], "key": "PAY"}}}
    )
    keystore.add(proj, "PAY", "token", "old-value-123")
    seen = []
    monkeypatch.setattr(keystore, "add", lambda root, name, kind, value: seen.append(value))
    monkeypatch.setattr(renew, "after", lambda root, name: {"state": "works", "ends_at": None, "went_on": []})
    renew.replace_key(proj, "payments", "  new-key-value \n")
    assert seen == ["new-key-value"]


def test_a_piped_call_without_a_grant_is_refused_whatever_by_says(proj, run, monkeypatch):
    """A helper that clears its environment and says --by human:x is still refused: the person is either
    granted by the dashboard's signed-in session or sits at a real terminal."""
    monkeypatch.setattr(renew, "_GRANTED", set())
    for k in ("ORCH_AGENT", "ORCH_RUN", "ORCH_TICKET", "ORCH_JOB", "CLAUDECODE"):
        monkeypatch.delenv(k, raising=False)
    stdin = io.StringIO("attacker-value-123\n")
    monkeypatch.setattr(sys, "stdin", stdin)
    for argv in (
        ["renew", "claude"],
        ["renew", "claude", "--status"],
        ["renew", "claude", "--code", "-"],
        ["replace", "payments"],
    ):
        code, out, err = run("logins", *argv, "--by", "human:owner")
        assert code == 2 and "Only a person" in out + err, argv
    assert stdin.tell() == 0
    with pytest.raises(Refused, match="Only a person"):
        renew.person_only(proj, "human:owner")


def test_a_grant_serves_once(proj, monkeypatch):
    monkeypatch.setattr(renew, "_GRANTED", set())
    token = renew.grant(proj)
    assert len(list(renew._grants(proj).iterdir())) == 1 and token not in "".join(
        p.name for p in renew._grants(proj).iterdir()
    )  # only its hash is kept
    monkeypatch.setenv(renew.GRANT_ENV, token)
    assert renew.person_only(proj, "human:owner") == "grant"
    assert renew.GRANT_ENV not in os.environ and not list(renew._grants(proj).iterdir())
    monkeypatch.setattr(renew, "_GRANTED", set())
    monkeypatch.setenv(renew.GRANT_ENV, token)  # the same grant again
    with pytest.raises(Refused):
        renew.person_only(proj, "human:owner")
    monkeypatch.setenv(renew.GRANT_ENV, "made-up")
    with pytest.raises(Refused):
        renew.person_only(proj, "human:owner")


def test_an_old_grant_is_refused(proj, monkeypatch):
    monkeypatch.setattr(renew, "_GRANTED", set())
    token = renew.grant(proj)
    f = renew._grants(proj) / renew._hash(token)
    old = time.time() - renew.GRANT_LIFE - 5
    os.utime(f, (old, old))
    monkeypatch.setenv(renew.GRANT_ENV, token)
    with pytest.raises(Refused):
        renew.person_only(proj, "human:owner")


def test_a_person_at_a_terminal_types_the_key_hidden(proj, run, monkeypatch):
    from orch import term

    monkeypatch.setattr(renew, "_GRANTED", set())
    keystore.record_write(
        proj, "checks", {"checks": {"payments": {"label": "Payments key", "command": ["pay"], "key": "PAY"}}}
    )
    keystore.add(proj, "PAY", "token", "old-value-123")
    monkeypatch.setattr(term, "is_terminal", lambda stream: True)
    asked = []
    import getpass

    monkeypatch.setattr(
        getpass, "getpass", lambda prompt, stream=None: asked.append(prompt) or "typed-value-456"
    )
    monkeypatch.setattr(renew, "after", lambda root, name: {"state": "works", "ends_at": None, "went_on": []})
    code, out, err = run("logins", "replace", "payments")
    assert code == 0, err
    assert asked == ["New key (hidden while you type): "] and "typed-value" not in out + err
    assert keystore.get_value(proj, "PAY") == "typed-value-456"

"""Renew a tool login or replace a key from the warning (renew.py, `orch logins renew|replace`, ORCH-46)."""

import io
import json
import os
import stat
import sys
import threading
import time

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
        lambda root, name: {
            "binary": str(tool),
            "argv": [str(tool)],
            "links": ["https://claude.com/"],
            "helper": "claude",
            "label": "Main helper",
        }
        if name == "claude"
        else None,
    )
    seen = []

    def after(root, name):
        seen.append(name)
        return {"state": "works", "ends_at": "2026-12-17T21:24:57Z", "went_on": ["ORCH-9"]}

    monkeypatch.setattr(renew, "after", after)
    return {"got": got, "seen": seen}


def _wait(proj, want, limit=10.0):
    end = time.time() + limit
    while time.time() < end:
        st = renew.status(proj, "claude")
        if st["state"] in want:
            return st
        time.sleep(0.1)
    raise AssertionError(f"state stayed {renew.status(proj, 'claude')}")


def _all_text(proj) -> str:
    d = runs.run_dir(proj) / "renew" / "claude"
    return "".join(p.read_text(encoding="utf-8", errors="replace") for p in d.rglob("*") if p.is_file())


def test_link_only_with_an_allowed_start():
    text = f"Opening…\nvisit: https://evil.example/x?{LINK}\nIf not: {LINK}.\n"
    assert renew.link_in(text, ["https://claude.com/"]) == LINK
    assert renew.link_in("visit: http://claude.com/x", ["https://claude.com/"]) is None
    assert renew.link_in("nothing here", ["https://claude.com/"]) is None


def test_worker_passes_the_link_and_the_code_and_keeps_nothing_else(proj, fake):
    t = threading.Thread(target=renew.work, args=(proj, "claude"), daemon=True)
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
    assert not (runs.run_dir(proj) / "renew" / "claude" / "code").exists()


def test_close_ends_the_tool(proj, fake, monkeypatch):
    t = threading.Thread(target=renew.work, args=(proj, "claude"), daemon=True)
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
    assert renew.work(proj, "claude") == 1
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
    renew.start(proj, "claude")  # still beating: no second worker
    assert len(calls) == 1


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
    assert renew.after(proj, "claude") == {"state": "works", "ends_at": "2026-12-17T00:00:00Z", "went_on": ["X-1"]}


# ---------------------------------------------------------------------------------------------- a key


def test_replace_a_key_through_the_key_store_and_check_again(proj, run, monkeypatch, capsys):
    keystore.record_write(
        proj, "checks", {"checks": {"payments": {"label": "Payments key", "command": ["pay", "ping"], "key": "PAY"}}}
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
    assert "new-value" not in (runs.run_dir(proj) / "health.json").read_text(encoding="utf-8")


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
    t = threading.Thread(target=renew.work, args=(proj, "claude"), daemon=True)
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
    d = runs.run_dir(proj) / "renew" / "claude"
    d.mkdir(parents=True)
    old = "2020-01-01T00:00:00Z"
    (d / "state.json").write_text(
        json.dumps({"schema": renew.SCHEMA, "name": "claude", "state": "link", "started_at": old, "beat_at": old}),
        encoding="utf-8",
    )
    assert renew.status(proj, "claude")["state"] == "failed"
    if os.name != "nt":
        assert stat.S_IMODE(d.stat().st_mode) in (0o700, 0o755)

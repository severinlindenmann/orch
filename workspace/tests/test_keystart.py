"""A helper started on an API key (ORCH-659, keystart.py): the key goes only to that helper (a pipe for Claude
Code, the process environment for Codex), never into arguments, files, the ticket or logs; its spend is read
from its own output and written per step; the ticket says why it runs there and what it cost."""

import json
import os
import shlex
import stat
import sys
import time
from pathlib import Path

import pytest

from orch import config, keystart, keystore, runs, secretscan, tickets
from orch.errors import Refused

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the fake helpers are shell stubs; pipes need fork")

KEY = "sk-ant-api03-" + "Zq8Lw3Rt6Yp1Xc5Vb9Nm2Kj4Hg7Fd0Sa" * 2 + "-TESTONLYAA"
CX_KEY = "sk-proj-" + "Hq2Lw7Rt1Yp6Xc0Vb4Nm8Kj3Hg5Fd9Sa" * 2
WHY = "review work, 12 of 100 dollars used"
FIXTURES = Path(__file__).resolve().parents[2] / "e2e" / "fixtures" / "agent-output"

FAKE = r"""
import hashlib, json, os, sys
args = sys.argv[1:]
if args[:1] == ["--help"]:
    print("choices: auto"); sys.exit(0)
if args[:1] == ["--version"]:
    print("2.1.0 (Claude Code)"); sys.exit(0)
fd = os.environ.get("CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR")
key = os.read(int(fd), 4096).decode() if fd else os.environ.get("CODEX_API_KEY", "")
again = os.read(int(fd), 4096).decode() if fd else ""
rep = {
    "sha": hashlib.sha256(key.encode()).hexdigest() if key else None,
    "read_twice": bool(again),
    "in_argv": bool(key) and any(key in a for a in args),
    "env_names": sorted(k for k, v in os.environ.items() if key and key in v),
    "scrub": os.environ.get("CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"),
    "inherited": [k for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY") if k in os.environ],
}
with open(os.environ["FAKE_REPORT"], "a") as f:
    f.write(json.dumps(rep) + "\n")
mode = os.environ.get("FAKE_MODE", "cost")
if mode == "leak":
    print("the helper printed it: " + key)
if mode == "codex":
    sys.stdout.write(open(os.environ["FAKE_CODEX_OUT"]).read())
elif mode != "silent":
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "ok",
                      "total_cost_usd": 0.1}))
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "ok",
                      "total_cost_usd": 0.42}))
"""


def _sha(v):
    import hashlib

    return hashlib.sha256(v.encode()).hexdigest()


@pytest.fixture
def fakes(tmp_path, monkeypatch):
    d = tmp_path / "fakebin"
    d.mkdir()
    for name in ("claude", "codex"):
        f = d / name
        f.write_text(f"#!{sys.executable}\n" + FAKE)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    report = tmp_path / "fake-report.jsonl"
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_REPORT", str(report))
    monkeypatch.setenv("FAKE_CODEX_OUT", str(FIXTURES / "codex-exec-json.jsonl"))
    monkeypatch.setenv("ORCH_CMD", f"{shlex.quote(sys.executable)} -m orch")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "inherited-value-that-must-not-reach-the-helper")
    monkeypatch.setenv("OPENAI_API_KEY", "inherited-value-that-must-not-reach-the-helper")
    monkeypatch.delenv("ORCH_RUN", raising=False)  # the test itself is no helper run
    monkeypatch.delenv("ORCH_TICKET", raising=False)
    return report


@pytest.fixture
def ws(proj, run, fakes, subprocess_home, monkeypatch):
    """A workspace the run's wrapper (a child process) may open its key store in: under ~/.orch-test, next to
    the test home; removed by its own path."""
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="pytest-keystart-", dir=subprocess_home.parent))
    monkeypatch.chdir(root)
    keystore.add(root, "claude-credit", "token", KEY)
    keystore.add(root, "openai-credit", "token", CX_KEY)
    config.set_permissions(root, "ask")
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _ticket(run):
    tid = json.loads(run("ticket", "new", "Review the parser", "--json", "--by", "human:t")[1])["id"]
    run("check", "add", tid, "Step one", "--by", "human:t")
    return tid


def _wait(proj, tid, timeout=30):
    """Until the run let go of the ticket and wrote its spend line (just after it lets go), or it failed."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if runs.read(proj, tid) is None:
            hist = _history(proj, tid)
            if any(h.startswith(("Spent ", "Spend on ", "The agent stopped")) for h in hist):
                return
        time.sleep(0.05)
    raise AssertionError(f"run on {tid} did not end: {runs.read(proj, tid)} {_history(proj, tid)}")


def _debug(proj, tid):
    logs = list((proj / ".orch" / "run" / "logs").glob(f"{tid}-*.log"))
    return "LOG:" + "".join(x.read_text() for x in logs) + "\nHIST:" + "\n".join(_history(proj, tid))


def _history(proj, tid):
    return [h.get("text", "") for h in tickets.load(proj, tid).get("history", [])]


def _spend_rows(proj):
    p = proj / ".orch" / "run" / keystart.SPEND_LOG
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def _all_workspace_bytes(proj):
    """Every file of the workspace (ticket, run records, logs, the record, the spend log): (path, bytes)."""
    for d, _, files in os.walk(proj):
        for f in files:
            p = Path(d) / f
            try:
                yield p, p.read_bytes()
            except OSError:
                continue


def _start(run, tid, key="claude-credit", account="Claude credit", agent="claude", *extra):
    return run(
        "run", "start", tid, "--agent", agent, "--mode", "oneshot", "--json",
        "--credit-keyname", key, "--credit-account", account, "--credit-why", WHY, *extra,
    )  # fmt: skip


def test_claude_gets_the_key_through_a_pipe_only_and_the_ticket_says_why_and_what_it_cost(ws, run, fakes):
    tid = _ticket(run)
    code, out, err = _start(run, tid)
    assert code == 0, err
    _wait(ws, tid)
    assert fakes.exists(), _debug(ws, tid)
    rep = json.loads(fakes.read_text().splitlines()[-1])
    assert rep["sha"] == _sha(KEY)  # the helper got exactly the stored key
    assert rep["read_twice"] is False  # a pipe is read once: anything started later finds it empty
    assert rep["in_argv"] is False and rep["env_names"] == []  # not in its arguments, not in its environment
    assert rep["scrub"] == "1"  # the commands it runs lose credentials
    assert "ANTHROPIC_API_KEY" not in rep["inherited"]  # the starter's own key does not reach it
    hist = _history(ws, tid)
    assert f"Runs on Claude credit: {WHY}." in hist
    assert "Spent 0.42 dollars on Claude credit." in hist  # the last result line of the step, not the sum
    rows = _spend_rows(ws)
    assert [r["usd"] for r in rows] == [None, 0.42] and rows[0]["id"] == rows[1]["id"]
    assert rows[1]["account"] == "Claude credit" and rows[1]["ticket"] == tid
    rec = json.loads(out)
    assert rec["mode"] == "oneshot"
    for p, data in _all_workspace_bytes(ws):
        assert KEY.encode() not in data, f"the key is in {p}"


def test_the_key_is_kept_by_name_only_and_scans_clean(ws, run, fakes):
    tid = _ticket(run)
    assert _start(run, tid)[0] == 0
    _wait(ws, tid)
    assert secretscan.find(f"token {KEY}")  # the scan does see this key when it is there
    text = "\n".join(data.decode("utf-8", "replace") for _, data in _all_workspace_bytes(ws))
    assert KEY not in text
    assert not secretscan.find("\n".join(_history(ws, tid)))  # what the ticket shows: clean
    assert not secretscan.find((ws / ".orch" / "run" / keystart.SPEND_LOG).read_text())
    log = next((ws / ".orch" / "run" / "logs").glob(f"{tid}-*.log")).read_text()
    assert not secretscan.find(log)


def test_a_helper_that_prints_the_key_has_it_hidden_in_the_log(ws, run, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "leak")
    tid = _ticket(run)
    assert _start(run, tid)[0] == 0
    _wait(ws, tid)
    log = next((ws / ".orch" / "run" / "logs").glob(f"{tid}-*.log")).read_text()
    assert "the helper printed it: [key hidden]" in log and KEY not in log
    for p, data in _all_workspace_bytes(ws):
        assert KEY.encode() not in data, f"the key is in {p}"


def test_codex_gets_the_key_in_its_own_environment_and_its_spend_is_unknown(ws, run, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "codex")
    tid = _ticket(run)
    code, _, err = _start(run, tid, "openai-credit", "OpenAI credit", "codex")
    assert code == 0, err
    _wait(ws, tid)
    rep = json.loads(fakes.read_text().splitlines()[-1])
    assert rep["sha"] == _sha(CX_KEY) and rep["env_names"] == ["CODEX_API_KEY"] and rep["in_argv"] is False
    assert "OPENAI_API_KEY" not in rep["inherited"]  # the starter's own key does not reach it
    hist = _history(ws, tid)
    assert f"Runs on OpenAI credit: {WHY}." in hist
    end = [h for h in hist if h.startswith("Spend on OpenAI credit unknown")]
    assert end and "tokens" in end[0]  # no dollars in Codex's output: unknown, never 0
    assert [r["usd"] for r in _spend_rows(ws)] == [None, None]
    for p, data in _all_workspace_bytes(ws):
        assert CX_KEY.encode() not in data, f"the key is in {p}"
    assert "CODEX_API_KEY" not in os.environ  # the starter's own environment never held it


def test_a_helper_that_reports_nothing_leaves_its_spend_unknown(ws, run, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "silent")
    tid = _ticket(run)
    assert _start(run, tid)[0] == 0
    _wait(ws, tid)
    assert any(h.startswith("Spend on Claude credit unknown") for h in _history(ws, tid))
    assert _spend_rows(ws)[-1]["usd"] is None


def test_a_key_start_asked_for_live_works_one_step_at_a_time(ws, run, fakes):
    tid = _ticket(run)
    code, out, err = run(
        "run", "start", tid, "--agent", "claude", "--mode", "live", "--json",
        "--credit-keyname", "claude-credit", "--credit-account", "Claude credit",
    )  # fmt: skip
    assert code == 0 and json.loads(out)["mode"] == "oneshot"
    assert "one step at a time" in err
    _wait(ws, tid)
    assert not list((ws / ".orch" / "run").glob("env-*.json"))  # no environment file for a live session


@pytest.mark.parametrize(
    ("argv", "said"),
    [
        (["--credit-keyname", "nope", "--credit-account", "X"], "There is no key named nope"),
        (["--credit-keyname", "claude-credit"], "needs the credit's name"),
        (["--credit-keyname", "a b", "--credit-account", "X"], "name of a key"),
        (["--credit-account", "X"], "go with --credit-keyname"),
    ],
)
def test_a_wrong_credit_is_refused_before_anything_starts(ws, run, argv, said):
    tid = _ticket(run)
    code, _, err = run("run", "start", tid, "--agent", "claude", "--mode", "oneshot", *argv)
    assert code == 2 and said in err
    assert runs.read(ws, tid) is None


def test_a_tool_without_a_key_handoff_is_refused(ws, run):
    config.add_agent(ws, "fake", f"{shlex.quote(sys.executable)} -c pass {{prompt}}", approve=True)
    tid = _ticket(run)
    code, _, err = _start(run, tid, agent="fake")
    assert code == 2 and "cannot start on an API key" in err


def test_the_credit_on_the_run_record_holds_names_and_words_only(ws, run, fakes, monkeypatch):
    seen = {}
    real = runs.set_process_fields

    def spy(root, tid, run_id, **fields):
        if "credit" in fields:
            seen.update(fields["credit"])
        return real(root, tid, run_id, **fields)

    monkeypatch.setattr(runs, "set_process_fields", spy)
    tid = _ticket(run)
    assert _start(run, tid)[0] == 0
    _wait(ws, tid)
    assert seen == {"account": "Claude credit", "key": "claude-credit", "why": WHY}


# ---- unit ----------------------------------------------------------------------------------------------


def test_turn_spend_reads_the_last_result_and_keeps_zero_and_unknown_apart():
    two = "\n".join(json.dumps({"type": "result", "total_cost_usd": v}) for v in (0.1, 0.25))
    assert keystart.turn_spend("claude", two)["usd"] == 0.25
    assert keystart.turn_spend("claude", json.dumps({"type": "result", "total_cost_usd": 0}))["usd"] == 0.0
    assert keystart.turn_spend("claude", "no json here")["usd"] is None
    assert keystart.turn_spend("claude", json.dumps({"type": "result", "total_cost_usd": "1"}))["usd"] is None
    cx = (FIXTURES / "codex-exec-json.jsonl").read_text()
    s = keystart.turn_spend("codex", cx)
    assert s["usd"] is None and (s["tokens"] or 0) > 0


def test_end_line_says_known_partly_known_and_unknown():
    c = {"account": "OpenAI credit"}
    assert keystart.end_line(c, [{"usd": 0.3}, {"usd": 0.2}]) == "Spent 0.50 dollars on OpenAI credit."
    assert keystart.end_line(c, [{"usd": 0.003}]) == "Spent 0.003 dollars on OpenAI credit."
    part = keystart.end_line(c, [{"usd": 0.3}, {"usd": None}])
    assert part.startswith("Spent at least 0.30 dollars") and "1 of 2 steps" in part
    assert keystart.end_line(c, [{"usd": None, "tokens": 1200}]) == (
        "Spend on OpenAI credit unknown: the helper did not report it in dollars. It used 1,200 tokens."
    )


def test_start_line_reads_plainly():
    assert keystart.start_line({"account": "OpenAI credit", "why": WHY}) == f"Runs on OpenAI credit: {WHY}."
    assert keystart.start_line({"account": "OpenAI credit", "why": ""}) == "Runs on OpenAI credit."


def test_the_handoff_closes_both_pipe_ends_and_forgets_the_value(proj, monkeypatch):
    monkeypatch.setattr(keystart, "_record_use", lambda *a: None)
    keystore.add(proj, "claude-credit", "token", KEY)
    env = {"ANTHROPIC_API_KEY": "x"}
    h = keystart.handoff(proj, "r1", "t1", "claude", {"key": "claude-credit"}, env, "claude")
    r = h.pass_fds[0]
    assert "ANTHROPIC_API_KEY" not in h.env and KEY not in json.dumps(h.env)
    h.after_spawn()
    h.close()
    with pytest.raises(OSError):
        os.fstat(r)
    assert h._value is None


def test_a_key_use_that_cannot_be_recorded_stops_the_start(proj, monkeypatch):
    def boom(*a):
        raise Refused("Refused: this use could not be recorded.")

    monkeypatch.setattr(keystart, "_record_use", boom)
    keystore.add(proj, "claude-credit", "token", KEY)
    with pytest.raises(Refused, match="could not be recorded"):
        keystart.handoff(proj, "r1", "t1", "claude", {"key": "claude-credit"}, {}, "claude")


def test_the_log_is_scrubbed_with_the_value_handed_over_even_when_the_store_changed(tmp_path):
    log = tmp_path / "run.log"
    log.write_bytes(b"before\n")
    start = log.stat().st_size
    with open(log, "ab") as f:
        f.write(f"printed {KEY}\n".encode())
    keystart.scrub_log(log, start, KEY)  # the store may hold another value by now: not read here
    assert log.read_text() == "before\nprinted [key hidden]\n"


def test_a_step_whose_spend_cannot_be_written_does_not_start(ws, run, fakes, monkeypatch):
    def nope(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(keystart, "write_spend", nope)
    tid = _ticket(run)
    from orch import adapters

    key = {"root": ws, "run": "r_test0001", "tid": tid, "name": "claude", "credit": {"key": "claude-credit"}}
    monkeypatch.setattr(keystart, "_record_use", lambda *a: None)
    argv = [adapters.load("claude", ws)["oneshot"]["fresh"][0], "-p"]
    rc, out = runs._run_turn(argv, ws, None, tmp_log := ws / "t.log", {}, key=key)
    assert rc == 1 and "did not start the helper" in out and not fakes.exists()
    assert KEY not in tmp_log.read_text()


def test_a_key_too_long_for_a_pipe_is_refused(proj, monkeypatch):
    monkeypatch.setattr(keystart, "_record_use", lambda *a: None)
    keystore.add(proj, "big", "token", "k" * (keystart.VALUE_MAX + 1))
    with pytest.raises(Refused, match="not one short line"):
        keystart.handoff(proj, "r1", "t1", "claude", {"key": "big"}, {}, "claude")


@pytest.mark.parametrize(
    "inside", [{"ORCH_RUN": "r_abcdefgh", "ORCH_TICKET": "t_abcdef"}, {"CLAUDECODE": "1"}]
)
def test_a_helper_cannot_start_another_helper_on_a_key(ws, run, monkeypatch, inside):
    tid = _ticket(run)
    for k, v in inside.items():
        monkeypatch.setenv(k, v)
    code, _, err = _start(run, tid)
    assert code == 2 and "A helper cannot start another helper on an API key" in err
    assert runs.read(ws, tid) is None


def test_only_a_token_can_be_used_as_an_api_key(ws, run):
    keystore.add(ws, "db-password", "password", "pw-0123456789abcdef")
    tid = _ticket(run)
    code, _, err = _start(run, tid, "db-password")
    assert code == 2 and "not stored as a token" in err

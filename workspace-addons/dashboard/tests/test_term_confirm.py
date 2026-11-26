"""ORCH-2197: the OK card reads the helper's confirm prompt and answers it with one key, only the prompt the
person saw. A real tmux on a private socket shows the owner's hook confirm (workspace/tests/fixtures/confirm)."""

import json
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from orch_dashboard import termsession

from .test_term import Person, call, serve

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="needs tmux")

TID = "t_conf0001"
FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "workspace"
    / "tests"
    / "fixtures"
    / "confirm"
    / "hook-confirm-orch-2197.txt"
)
# shows the screen, then writes the first key it gets to a file and says "answered"
SHOW = (
    "import sys, termios, tty\n"
    "sys.stdout.write(open(sys.argv[1], encoding='utf-8').read().replace('\\n', '\\r\\n')); sys.stdout.flush()\n"
    "tty.setraw(0)\n"
    "k = sys.stdin.read(1)\n"
    "open(sys.argv[2], 'w').write(k)\n"
    "sys.stdout.write('\\x1b[2J\\x1b[Hanswered\\r\\n'); sys.stdout.flush()\n"
    "import time; time.sleep(30)\n"
)


@pytest.fixture
def asking(tmp_path):
    sock = "orch-" + secrets.token_hex(4)
    script, got = tmp_path / "show.py", tmp_path / "got.txt"
    script.write_text(SHOW)
    tm = lambda *a: subprocess.run(["tmux", "-L", sock, *a], capture_output=True, text=True, check=False)
    tm(
        "new-session",
        "-d",
        "-x",
        "120",
        "-y",
        "45",
        "-s",
        TID,
        "--",
        sys.executable,
        str(script),
        str(FIXTURE),
        str(got),
    )
    state = tmp_path / "status.json"
    state.write_text(
        json.dumps({"running": True, "claim": {"run": "r_1", "tmux": {"socket": sock, "session": TID}}})
    )
    orch = tmp_path / "orch"
    orch.write_text(
        f"#!{sys.executable}\nimport json, sys\n"
        f"state = json.load(open({str(state)!r}))\n"
        "print(json.dumps(state)) if sys.argv[1:3] == ['run', 'status'] else sys.exit(2)\n"
    )
    orch.chmod(0o755)
    for _ in range(40):
        if "Esc to cancel" in tm("capture-pane", "-p", "-t", f"={TID}:").stdout:
            break
        time.sleep(0.1)
    yield str(orch), got
    tm("kill-server")


def test_the_card_reads_the_owners_prompt_with_its_command(asking, tmp_path):
    orch, _ = asking
    p = termsession.confirm(tmp_path, orch, TID)
    assert p is not None and (p["yes"], p["no"]) == ("1", "2")
    assert "databricks jobs run-now 588496183906654" in p["command"]
    assert p["reason"].startswith("Guard: `databricks jobs run-now` starts a job run.")


def test_allow_once_types_only_the_yes_key_of_the_prompt_the_person_saw(asking, tmp_path):
    orch, got = asking
    p = termsession.confirm(tmp_path, orch, TID)
    assert termsession.answer(tmp_path, orch, TID, "yes", "0000000000000000")[0] == 409  # another prompt
    assert termsession.answer(tmp_path, orch, TID, "always", p["digest"])[0] == 400
    assert not got.exists()  # nothing was typed
    assert termsession.answer(tmp_path, orch, TID, "yes", p["digest"]) == (200, "{}")
    for _ in range(40):
        if got.exists():
            break
        time.sleep(0.1)
    assert got.read_text() == "1"
    time.sleep(0.3)
    assert termsession.confirm(tmp_path, orch, TID) is None  # answered: no card any more
    assert termsession.answer(tmp_path, orch, TID, "no", p["digest"])[0] == 409


def test_the_routes_need_the_persons_session_and_not_the_typing_setting(asking, tmp_path):
    orch, got = asking
    (tmp_path / ".orch" / "tickets").mkdir(parents=True)  # no config: typing into the screen is off
    srv, base = serve(tmp_path, orch, Person(True))
    try:
        code, body = call(base + "/api/term/confirm?ticket=" + TID)
        prompt = json.loads(body)["prompt"]
        assert code == 200 and prompt["no"] == "2"
        h = {"Content-Type": "application/json", "Origin": base, "X-Orch-Page": "secret"}
        bad = dict(h, **{"X-Orch-Page": "wrong"})
        want = json.dumps({"ticket": TID, "answer": "no", "digest": prompt["digest"]}).encode()
        assert call(base + "/api/term/confirm", want, bad)[0] == 403  # a script without the page secret
        extra = json.dumps({"ticket": TID, "answer": "no", "digest": prompt["digest"], "k": "Enter"}).encode()
        assert call(base + "/api/term/confirm", extra, h)[0] == 400
        assert not got.exists()
        assert call(base + "/api/term/confirm", want, h)[0] == 200
        for _ in range(40):
            if got.exists() and got.read_text():
                break
            time.sleep(0.1)
        assert got.read_text() == "2"
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_old_screen_check_missed_the_owners_prompt_and_now_sees_it_at_once():
    termsession._SEEN.clear()
    screen = FIXTURE.read_text("utf-8")
    assert termsession.waiting_input(("orch-0badf00d", "t_owner001"), screen, 100.0) is True  # first look
    termsession._SEEN.clear()

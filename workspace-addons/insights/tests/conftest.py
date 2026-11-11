"""Isolated home, contract answers, and a CLI-only fake workspace reader."""

import json
import sys
import threading
from pathlib import Path

import pytest

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
sys.path.insert(0, str(CONTRACTS.parent / "workspace" / "src"))


@pytest.fixture(autouse=True)
def test_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("ORCH_HOME", str(home / ".orch-tool"))


@pytest.fixture
def answer():
    return json.loads((CONTRACTS / "examples/counts/valid-answer.json").read_text())


@pytest.fixture
def nothing():
    return json.loads((CONTRACTS / "examples/counts/valid-nothing-yet.json").read_text())


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "workspace"
    (root / ".orch").mkdir(parents=True)
    return root


SETTINGS = {
    "keep_days": 90,
    "max_mb": 2048,
    "share_counts": False,
    "share_names": False,
    "record_mb": 120.5,
    "detail_mb": 100,
    "runs": 23,
}
TICKETS = [
    {"id": "t_abc123", "title": "Invoice export", "status": "done"},
    {"id": "t_def456", "title": "<img src=x onerror=alert(1)>", "status": "open"},
]

# Answers: record counts (answer.json), record settings (settings.json), ticket list (tickets.json), config set and
# record delete-detail (refuse.json = a core refusal, exit 2). A file "<name>_exit" makes that read fail.
# Every call is appended to calls.jsonl: argv, stdin, the full environment, cwd.
FAKE = """#!{python}
import json
import os
from pathlib import Path
import sys
folder = Path(__file__).parent
args = sys.argv[1:]
call = {{"args": args, "cwd": str(Path.cwd()), "root": os.environ.get("ORCH_ROOT"),
        "stdin": sys.stdin.read()}}
(folder / "call.json").write_text(json.dumps(call))
with open(folder / "calls.jsonl", "a") as log:
    log.write(json.dumps({{**call, "env": dict(os.environ)}}) + "\\n")
plain = [a for a in args if a != "--proof-stdin"]

def answer(name):
    if (folder / (name + "_exit")).exists():
        sys.exit(1)
    print((folder / (name + ".json")).read_text())
    sys.exit(0)

def write(result):
    if (folder / "refuse.json").exists():
        print((folder / "refuse.json").read_text())
        sys.exit(2)
    print(json.dumps(result))
    sys.exit(0)

if args == ["record", "counts", "--days", "30", "--json"]:
    if (folder / "exit").exists():
        sys.exit(1)
    answer("answer")
if args == ["record", "settings", "--json"]:
    answer("settings")
if args == ["ticket", "list", "--all", "--json"]:
    answer("tickets")
if plain[:2] == ["config", "set"] and len(plain) == 5:
    write({{"key": plain[2], "value": plain[3]}})
if plain[:2] == ["record", "delete-detail"] and len(plain) == 4:
    write({{"deleted": 3}})
sys.exit(3)
"""


@pytest.fixture
def fake_orch(tmp_path, answer):
    folder = tmp_path / "fake"
    folder.mkdir()
    (folder / "answer.json").write_text(json.dumps(answer))
    (folder / "settings.json").write_text(json.dumps(SETTINGS))
    (folder / "tickets.json").write_text(json.dumps(TICKETS))
    script = folder / "orch"
    script.write_text(FAKE.format(python=sys.executable))
    script.chmod(0o755)
    return script


def calls(fake):
    """Every recorded call of the fake orch, in order."""
    log = fake.parent / "calls.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


class FakeSession:
    """A page session for tests: the real can_mint rules (cookie, loopback Host, no proxy headers), a recorded mint."""

    cookie = "good-cookie-value"
    token = "launch-token-abcdefghijklmnop"

    def __init__(self):
        self.minted = []
        self.revoked = False

    def can_mint(self, headers, port):
        from orch.pageproof import COOKIE, forwarded, host_ok

        return (
            host_ok(headers, port)
            and not forwarded(headers)
            and f"{COOKIE}={self.cookie}" in (headers.get("Cookie") or "")
        )

    def mint(self, op, target):
        self.minted.append((op, target))
        return f"hp1.fakeproof{len(self.minted)}.mac"

    def launch(self, token):
        return self.cookie if token == self.token else None


@pytest.fixture
def fake_session():
    return FakeSession()


@pytest.fixture
def start_server(ws, fake_orch):
    from orch_insights.server import make_server

    running = []

    def start(orch_bin=fake_orch, session=None):
        srv = make_server(ws, 0, orch_bin=orch_bin, session=session)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        running.append((srv, thread))
        return srv

    yield start
    for srv, thread in running:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


@pytest.fixture
def server(start_server):
    return start_server()

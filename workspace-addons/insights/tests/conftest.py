"""Isolated home, contract answers, and a CLI-only fake workspace reader."""

import hmac
import json
import sys
import threading
from http.cookies import SimpleCookie
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

# Answers: record counts (answer.json), record settings (settings.json), ticket list (tickets.json). A file
# "<name>_exit" makes that read fail; external.json is merged into settings.json right after a settings read (a
# change made elsewhere in between). The writes follow the final core shape:
#   config set insights.<key> <value> [--proof-stdin] [--if-current <old>] --json
#     -> {"insights.<key>": v, "changed": bool, "widened": bool}; the fake decides widening by comparing with
#        settings.json, wants a proof only for widening, answers `changed` on an --if-current mismatch
#   record delete-detail <ticket> [--proof-stdin] --json -> {"deleted": 3}, always needs a proof
# A valid proof is exactly a string the FakeSession minted for that op/target (minted.jsonl), single use
# (used.txt); otherwise {"code": "needs_person"}, exit 2, nothing changed. refuse.json = a fixed core refusal,
# stderr.txt is written to stderr, a file "pause" makes a write sleep that many seconds first.
# Every call is appended to calls.jsonl: argv, stdin, the full environment, cwd.
FAKE = """#!{python}
import json
import os
from pathlib import Path
import sys
import time
folder = Path(__file__).parent
args = sys.argv[1:]
stdin = sys.stdin.read()
call = {{"args": args, "cwd": str(Path.cwd()), "root": os.environ.get("ORCH_ROOT"), "stdin": stdin}}
(folder / "call.json").write_text(json.dumps(call))
with open(folder / "calls.jsonl", "a") as log:
    log.write(json.dumps({{**call, "env": dict(os.environ)}}) + "\\n")
if (folder / "stderr.txt").exists():
    sys.stderr.write((folder / "stderr.txt").read_text())
plain = [a for a in args if a != "--proof-stdin"]
FIELDS = {{"insights.keep_days": "keep_days", "insights.max_mb": "max_mb",
          "insights.share_counts": "share_counts", "insights.share_names": "share_names"}}

def answer(name):
    if (folder / (name + "_exit")).exists():
        sys.exit(1)
    print((folder / (name + ".json")).read_text())
    external = folder / "external.json"
    if name == "settings" and external.exists():
        settings = json.loads((folder / "settings.json").read_text())
        settings.update(json.loads(external.read_text()))
        (folder / "settings.json").write_text(json.dumps(settings))
        external.unlink()
    sys.exit(0)

def refuse(code, error):
    print(json.dumps({{"error": error, "code": code}}))
    sys.exit(2)

def before_write():
    if (folder / "refuse.json").exists():
        print((folder / "refuse.json").read_text())
        sys.exit(2)
    if (folder / "pause").exists():
        time.sleep(float((folder / "pause").read_text()))

def proof_ok(op, target):
    if "--proof-stdin" not in args or not stdin:
        return False
    proof = stdin.splitlines()[0]
    minted, used = folder / "minted.jsonl", folder / "used.txt"
    rows = [json.loads(line) for line in minted.read_text().splitlines()] if minted.exists() else []
    if proof in (used.read_text().splitlines() if used.exists() else []):
        return False
    if {{"op": op, "target": target, "proof": proof}} not in rows:
        return False
    with open(used, "a") as out:
        out.write(proof + "\\n")
    return True

def config_set():
    guard = plain[4:-1]
    if plain[-1] != "--json" or plain[2] not in FIELDS:
        sys.exit(3)
    if guard and (len(guard) != 2 or guard[0] != "--if-current"):
        sys.exit(3)
    key, value = plain[2], plain[3]
    before_write()
    settings = json.loads((folder / "settings.json").read_text())
    raw = settings[FIELDS[key]]
    current = ("on" if raw else "off") if isinstance(raw, bool) else str(raw)
    if guard and guard[1] != current:
        refuse("changed", "This changed in the meantime: now " + current)
    if value == current:
        print(json.dumps({{key: value, "changed": False, "widened": False}}))
        sys.exit(0)
    widened = int(value) > int(current) if not isinstance(raw, bool) else value == "on"
    if widened and not proof_ok("insights.settings", key + "=" + value):
        refuse("needs_person", "Do this in the dashboard on this computer.")
    settings[FIELDS[key]] = (value == "on") if isinstance(raw, bool) else int(value)
    (folder / "settings.json").write_text(json.dumps(settings))
    print(json.dumps({{key: value, "changed": True, "widened": widened}}))
    sys.exit(0)

def delete_detail():
    if len(plain) != 4 or plain[3] != "--json":
        sys.exit(3)
    before_write()
    if not proof_ok("record.delete_detail", plain[2]):
        refuse("needs_person", "Do this in the dashboard on this computer.")
    print(json.dumps({{"deleted": 3}}))
    sys.exit(0)

if args == ["record", "counts", "--days", "30", "--json"]:
    if (folder / "exit").exists():
        sys.exit(1)
    answer("answer")
if args == ["record", "settings", "--json"]:
    answer("settings")
if args == ["ticket", "list", "--all", "--json"]:
    answer("tickets")
if plain[:2] == ["config", "set"] and len(plain) >= 5:
    config_set()
if plain[:2] == ["record", "delete-detail"]:
    delete_detail()
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

    def __init__(self, folder=None):
        self.minted = []
        self.revoked = False
        self.folder = folder  # the fake orch's folder: minted proofs are what its core accepts

    def authed(self, headers):
        """Like PageSession.authed: SimpleCookie parsing, the exact cookie name (no substring match)."""
        from orch.pageproof import COOKIE

        try:
            jar = SimpleCookie(headers.get("Cookie") or "")
        except Exception:  # noqa: BLE001 - a broken cookie header is no session
            return False
        c = jar.get(COOKIE)
        return bool(c and hmac.compare_digest(c.value, self.cookie))

    def can_mint(self, headers, port):
        from orch.pageproof import forwarded, host_ok

        return host_ok(headers, port) and not forwarded(headers) and self.authed(headers)

    def mint(self, op, target):
        self.minted.append((op, target))
        proof = f"hp1.fakeproof{len(self.minted)}.mac"
        if self.folder is not None:
            with open(self.folder / "minted.jsonl", "a") as log:
                log.write(json.dumps({"op": op, "target": target, "proof": proof}) + "\n")
        return proof

    def launch(self, token):
        return self.cookie if token == self.token else None


@pytest.fixture
def fake_session(fake_orch):
    return FakeSession(fake_orch.parent)


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

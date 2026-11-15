"""Contract tests of the Insights settings server against the REAL orch core (workspace/src/orch): the real
`orch config get|set insights.*` (with --if-current), `orch record settings|delete-detail`, the real PageSession
(per-server, per-port cookie) and run_with_proof. A disposable workspace and orch home under ~/.orch-test (the
core trusts only that folder for a test home); nothing of the real ~/.orch-tool, key or workspace is touched."""

import http.client
import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest

pageproof = pytest.importorskip("orch.pageproof")
humanproof = pytest.importorskip("orch.humanproof")
if "insights" not in getattr(pageproof, "SERVERS", ()):
    pytest.skip("this core has no Insights page server", allow_module_level=True)

WORKSPACE_SRC = Path(__file__).resolve().parents[3] / "workspace" / "src"


def _core_python():
    """A Python that can run the real core: this one when it has the core's dependencies, else the workspace
    project's own environment (`uv sync` there), else None (the tests skip)."""
    import importlib.util

    if importlib.util.find_spec("cryptography"):
        return sys.executable
    candidate = WORKSPACE_SRC.parent / ".venv" / "bin" / "python"
    return str(candidate) if candidate.is_file() else None


CORE_PYTHON = _core_python()
if CORE_PYTHON is None:
    pytest.skip("the real core's dependencies are not installed here", allow_module_level=True)
SECRET = "s" * 43
SITE = {"Sec-Fetch-Site": "same-origin"}


@pytest.fixture
def core(monkeypatch):
    """A workspace + orch home under the real account's ~/.orch-test and a shim that runs the real core."""
    account = Path(pwd.getpwuid(os.getuid()).pw_dir)
    base = account / ".orch-test"
    base.mkdir(exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="w2b-insights-core-", dir=base))
    ws = folder / "ws"
    (ws / ".orch" / "tickets").mkdir(parents=True)
    from orch.adapters import human_environ

    for name in set(os.environ) - set(human_environ(os.environ)):  # no agent tool in this test process
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("ORCH_DEV", raising=False)
    monkeypatch.setenv("ORCH_HOME", str(folder / "home"))
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
    from orch import addons

    # this test needs the true account home (the core trusts a test home only under its ~/.orch-test); the
    # shared guard faked it, and only ORCH_HOME (under ~/.orch-test, never ~/.orch-tool) is written
    monkeypatch.setattr(addons, "real_home", lambda: account)
    shim = folder / "orch"
    shim.write_text(
        f"#!{CORE_PYTHON}\nimport sys\nsys.path.insert(0, {str(WORKSPACE_SRC)!r})\n"
        "from orch.cli import main\nraise SystemExit(main())\n"
    )
    shim.chmod(0o755)
    yield ws, str(shim)
    shutil.rmtree(folder, ignore_errors=True)  # the folder this fixture created, by its exact path


def run(core, *argv, proof=None):
    ws, shim = core
    env = dict(os.environ)
    env["ORCH_ROOT"] = str(ws)
    if proof is not None:
        r = pageproof.run_with_proof(list(argv), proof, orch_bin=shim, cwd=ws, env=env, timeout=60)
    else:
        r = subprocess.run(
            [shim, *argv],
            check=False,
            cwd=ws,
            env=env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
    try:
        out = json.loads(r.stdout)
    except ValueError:
        out = None
    return r.returncode, out


def get(core, key):
    code, out = run(core, "config", "get", key, "--json")
    assert code == 0, out
    return out[key]


@pytest.fixture
def session(core):
    ws, _ = core
    humanproof.human_key(ws)  # raises a plain reason when the test home is not trusted
    session = pageproof.PageSession(ws, "insights")
    assert session.key is not None
    return session


@pytest.fixture
def srv(core, session):
    from orch_insights.server import make_server

    ws, shim = core
    server = make_server(ws, 0, orch_bin=shim, session=session)
    session.secret = SECRET  # as if /session succeeded (the launch-token flow is covered by test_settings)
    server.page_secret = SECRET
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def act(server, session, op, args, person=False):
    port = server.server_address[1]
    raw = json.dumps({"op": op, "args": args}).encode()
    headers = {
        "Host": f"127.0.0.1:{port}",
        "Origin": f"http://127.0.0.1:{port}",
        "Content-Type": "application/json",
        "Content-Length": str(len(raw)),
        **SITE,
    }
    if person:
        headers["Cookie"] = f"{session.cookie_name(port)}={session.cookie}"
        headers["X-Orch-Page"] = SECRET
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=90)
    conn.request("POST", "/api/act", body=raw, headers=headers)
    response = conn.getresponse()
    body = response.read()
    conn.close()
    try:
        answer = json.loads(body)
        return response.status, answer.get("result", answer) if isinstance(answer, dict) else answer
    except ValueError:
        return response.status, body.decode()


def setting(key, value):
    return "settings.set", {"key": key, "value": value}


def test_the_page_reads_the_real_settings(core, srv, session):
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    conn.request("GET", "/api/settings", headers={"Host": f"127.0.0.1:{port}"})
    view = json.loads(conn.getresponse().read())
    assert "error" not in view and view["can_act"] is False
    assert get(core, "insights.keep_days") == 90 and get(core, "insights.max_mb") == 2048


def test_narrowing_is_proof_free_and_widening_needs_the_person(core, srv, session):
    code, out = act(srv, session, *setting("insights.keep_days", "30"))
    assert code == 200 and out == {"insights.keep_days": 30, "changed": True, "widened": False}
    assert get(core, "insights.keep_days") == 30
    code, out = act(srv, session, *setting("insights.keep_days", "30"))
    assert code == 200 and out["changed"] is False  # the same value: no write, no proof
    # widening 30 -> 365 without the person: the core said needs_person, the server cannot mint: nothing changed
    code, _ = act(srv, session, *setting("insights.keep_days", "365"))
    assert code == 403 and get(core, "insights.keep_days") == 30
    # with the person: the value-bound proof (key=value) is minted only after the core asked, then used once
    code, out = act(srv, session, *setting("insights.keep_days", "365"), person=True)
    assert code == 200 and out == {"insights.keep_days": 365, "changed": True, "widened": True}
    assert get(core, "insights.keep_days") == 365


def test_a_proof_is_value_bound_and_single_use(core, session):
    args = ["config", "set", "insights.max_mb", "512", "--json"]
    assert run(core, *args)[0] == 0  # narrowing from 2048, no proof
    wrong = session.mint("insights.settings", "insights.max_mb=1024")  # a proof for another value
    code, out = run(core, "config", "set", "insights.max_mb", "4096", "--json", proof=wrong)
    assert code != 0 and out["code"] == "needs_person" and get(core, "insights.max_mb") == 512
    good = session.mint("insights.settings", "insights.max_mb=1024")
    code, out = run(core, "config", "set", "insights.max_mb", "1024", "--json", proof=good)
    assert code == 0 and out["widened"] is True
    run(core, "config", "set", "insights.max_mb", "512", "--json")  # narrow again
    code, out = run(core, "config", "set", "insights.max_mb", "1024", "--json", proof=good)  # reused
    assert code != 0 and out["code"] == "needs_person" and get(core, "insights.max_mb") == 512


def test_if_current_mismatch_is_changed(core):
    code, out = run(core, "config", "set", "insights.keep_days", "30", "--if-current=365", "--json")
    assert code != 0 and out["code"] == "changed" and get(core, "insights.keep_days") == 90


def test_the_core_refuses_sharing_on_without_an_admin(core, session):
    # no relay connection in this workspace ("not_connected"): the core itself refuses, proof or not
    assert run(core, "config", "set", "insights.share_counts", "off", "--json")[0] == 0
    proof = session.mint("insights.settings", "insights.share_counts=on")
    code, _ = run(core, "config", "set", "insights.share_counts", "on", "--json", proof=proof)
    assert code != 0 and get(core, "insights.share_counts") is False


def test_delete_detail_needs_the_person_and_reports_kept(core, srv, session):
    ws, _ = core
    tid = "t_real0001"
    ticket = {
        "schema": "orch.ticket/1", "id": tid, "title": "Close March books", "status": "active", "revision": 1,
        "checklist": [], "questions": [], "history": [], "refs": [],
    }  # fmt: skip
    (ws / ".orch" / "tickets" / f"{tid}.json").write_text(json.dumps(ticket))
    code, _ = act(srv, session, "record.delete_detail", {"ticket": tid})
    assert code == 403  # no person: the core said needs_person, the server cannot mint
    code, out = act(srv, session, "record.delete_detail", {"ticket": tid}, person=True)
    assert code == 200 and out.get("deleted") == 0 and out.get("kept") == 0 and out.get("ticket") == tid
    code, text = act(srv, session, "record.delete_detail", {"ticket": "t_nothere1"}, person=True)
    assert code == 422 and "not found" in text.lower()


# ------------------------------------------------------------------ the check-up against the real core


@pytest.fixture
def insights_shim(core, tmp_path_factory):
    """`orch insights ...` runs this add-on's CLI (the real core's add-on dispatch needs an installed entry point);
    everything else is the real core. ORCH_BIN points at the shim so the add-on's own calls reach the real core."""
    ws, shim = core
    both = Path(shim).with_name("orch2")
    both.write_text(
        f"#!{sys.executable}\nimport os, subprocess, sys\n"
        f"core = {shim!r}\n"
        "if sys.argv[1:2] == ['insights']:\n"
        f"    env = dict(os.environ, ORCH_BIN={str(both)!r})\n"
        f"    raise SystemExit(subprocess.run([sys.executable, '-m', 'orch_insights', '--dir', {str(ws)!r}, *sys.argv[2:]], env=env).returncode)\n"
        "raise SystemExit(subprocess.run([core, *sys.argv[1:]]).returncode)\n"
    )
    both.chmod(0o755)
    return ws, str(both)


def test_checkup_list_through_the_real_cli_feeds_the_card(insights_shim, monkeypatch):
    from orch_insights import checkup_core as cc
    from orch_insights.checkup import build_checkup
    from orch_insights.server import read_json

    ws, orch = insights_shim
    monkeypatch.setenv("ORCH_BIN", orch)
    tid = cc._ensure_ticket(ws)  # the real `orch ticket new --read-only --allow-cmd`
    assert json.loads((ws / ".orch" / "tickets" / f"{tid}.json").read_text())["read_only"] == {
        "allow": ["insights propose"]
    }
    code, out = run((ws, orch), "ticket", "new", "Export invoices", "--json")
    evidence = out["id"]
    skill = ws / ".agents" / "skills" / "invoice-export"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: invoice-export\ndescription: Export invoices\n---\nBody\n")
    monkeypatch.setenv("ORCH_TICKET", tid)
    monkeypatch.setenv("ORCH_RUN", "r_run00001")
    draft = {
        "kind": "skill.fix", "title": "Say the date format", "plain": "One line.", "likely": False,
        "evidence": [{"ticket": evidence}], "target": {"kind": "skill", "name": "invoice-export"},
        "change": {"files": [{"path": "SKILL.md", "after": "---\nname: invoice-export\ndescription: Export invoices\n---\nBody 2\n"}]},
    }  # fmt: skip
    code, out = run((ws, orch), "insights", "propose", "--json", "--draft", json.dumps(draft))
    assert code == 0 and out["status"] == "proposed", out
    for k in ("ORCH_TICKET", "ORCH_RUN"):
        monkeypatch.delenv(k)
    code, listing = run((ws, orch), "insights", "checkup", "list", "--json")
    assert code == 0 and listing["proposals"][0]["status"] == "proposed"
    view = build_checkup(read_json(ws, orch, ["insights", "checkup", "list", "--json"]))
    assert view["available"] is True and [p["id"] for p in view["proposals"]] == [out["id"]]
    code, tested = run((ws, orch), "insights", "checkup", "test", out["id"], "--json")
    assert code == 0 and tested["tests"]["state"] == "passed", tested
    code, _done = run((ws, orch), "insights", "checkup", "accept", out["id"], "--json")
    assert code == 0 and "Body 2" in (skill / "SKILL.md").read_text()

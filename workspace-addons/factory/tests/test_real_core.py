"""Real CLI integration; only installation discovery and account home are isolated by the harness."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from orch_factory import commands, flow

REPO = Path(__file__).resolve().parents[3]
PYTHON = REPO / "workspace/.venv/bin/python"


@pytest.fixture
def real_orch(tmp_path, monkeypatch):
    """ORCH_BIN = the real core CLI with Factory turned on."""
    if not PYTHON.is_file():
        pytest.skip("Install workspace dependencies to run the real-core test.")
    package = REPO / "workspace-addons/factory/src/orch_factory"
    shim = tmp_path / "real-orch"
    # Real ticket storage, ask, ext validation and revision guards; no real user profile or consent changes.
    shim.write_text(
        f"#!{PYTHON}\n"
        "import os, sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0, {str(REPO / 'workspace/src')!r})\n"
        "from orch import addons\n"
        "addons.real_home = lambda: Path(os.environ['HOME'])\n"
        f"manifest = addons.parse_manifest(Path({str(package / 'orch-addon.toml')!r}))\n"
        "addons.active = lambda root: {'factory': {}}\n"
        "addons.active_manifests = lambda root: {'factory': manifest}\n"
        "from orch.cli import main\nraise SystemExit(main())\n"
    )
    shim.chmod(0o755)
    monkeypatch.setenv("ORCH_BIN", str(shim))
    monkeypatch.setenv("ORCH_HOME", str(Path(os.environ["HOME"]) / "isolated-tool"))
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
    return shim


def core_py(code, *args, stdin=None):
    """Run a few lines against the real core package (the workspace venv); returns stdout."""
    env = {**os.environ, "PYTHONPATH": str(REPO / "workspace/src")}
    out = subprocess.run(
        [str(PYTHON), "-c", code, *args],
        input=stdin,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return out.stdout.strip()


@pytest.mark.slow
def test_real_core_lifecycle(ws, real_orch, proposal):
    order = commands.idea(ws, "Real booking page", b"Draft")["order"]
    commands.draft(ws, order, b"New draft")
    p = commands.propose(ws, order, proposal)
    assert commands.propose(ws, order, proposal) == p
    shown = commands.show(ws, order)
    assert shown["proposal"] == 1 and shown["started"] is False
    assert shown["questions"][0]["id"] == p["question"]


@pytest.mark.slow
def test_real_core_person_clicks_plan_send_and_start(ws, real_orch, proposal):
    """The draft's Plan the run / Ask for changes and the order's Start are plain person clicks: the dashboard runs
    `orch run send` and `orch answer` with --by human:<name>, and the real core takes both without any proof (#932)."""
    sys.path.insert(0, str(REPO / "workspace-addons/dashboard/src"))
    from orch_dashboard import actions

    def person(op, args):
        argv = [str(real_orch), *actions.build_argv(op, args)]
        out = subprocess.run(argv, cwd=ws, capture_output=True, text=True, timeout=60, check=False)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    order = commands.idea(ws, "Real booking page", b"Draft")["order"]
    commands.draft(ws, order, b"New draft")
    for words in (
        "Now plan the run: propose the whole run for this order (orch factory propose).",
        "Change the draft: shorter, and add a map",
    ):
        sent = person("run.send", {"ticket": order, "text": words})
        assert sent.get("id") and sent.get("state") == "none"  # queued; the page then starts an agent
    p = commands.propose(ws, order, proposal)
    assert commands.show(ws, order)["started"] is False

    q = next(x for x in commands.order_ticket(ws, order)["questions"] if x["id"] == p["question"])
    digest = core_py(
        "import json, sys; from orch import tickets; print(tickets.question_digest(json.load(sys.stdin)))",
        stdin=json.dumps(q),
    )
    person("answer", {"ticket": order, "question": q["id"], "answer": "Start", "digest": digest})
    assert commands.show(ws, order)["started"] is True

    # After the person's Start, core lets a run start on the crew ticket Factory makes next (#777).
    crew = flow.crew_add(ws, order, "booking-form")["ticket"]
    blocked = core_py(
        "import sys; from pathlib import Path; from orch import tickets; r = Path(sys.argv[1]); "
        "print(tickets.start_blocked(r, tickets.load(r, sys.argv[2])))",
        str(ws),
        crew,
    )
    assert blocked == "None"

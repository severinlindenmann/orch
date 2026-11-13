"""Real CLI integration; only installation discovery and account home are isolated by the harness."""

import os
from pathlib import Path

import pytest

from orch_factory import commands

REPO = Path(__file__).resolve().parents[3]


@pytest.mark.slow
def test_real_core_lifecycle(ws, tmp_path, monkeypatch, proposal):
    python = REPO / "workspace/.venv/bin/python"
    if not python.is_file():
        pytest.skip("Install workspace dependencies to run the real-core test.")
    package = REPO / "workspace-addons/factory/src/orch_factory"
    shim = tmp_path / "real-orch"
    # Real ticket storage, ask, ext validation and revision guards; no real user profile or consent changes.
    shim.write_text(
        f"#!{python}\n"
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
    order = commands.idea(ws, "Real booking page", b"Draft")["order"]
    commands.draft(ws, order, b"New draft")
    p = commands.propose(ws, order, proposal)
    assert commands.propose(ws, order, proposal) == p
    shown = commands.show(ws, order)
    assert shown["proposal"] == 1 and shown["started"] is False
    assert shown["questions"][0]["id"] == p["question"]

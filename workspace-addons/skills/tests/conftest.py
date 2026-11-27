import os
import sys
from pathlib import Path

import pytest

# No test may touch the real ~/.orch-tool (shared helper), and the core (orch) is found by path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _orch_test_guard import check_real_home, isolated_orch_home  # noqa: F401

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[2] / "workspace" / "src"))
sys.path.insert(0, str(HERE.parent / "src"))


def pytest_sessionfinish(session, exitstatus):
    check_real_home(session)


def _skill(folder: Path, name: str, desc: str, meta: dict | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"name: {name}", f"description: {desc}"]
    if meta:
        lines.append("metadata:")
        lines += [f'  {k}: "{v}"' for k, v in meta.items()]
    lines += ["---", f"# {name}", ""]
    (folder / "SKILL.md").write_text("\n".join(lines), encoding="utf-8")
    return folder


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """A workspace with a skill from each place, Claude found, a fake home and no real agent settings."""
    from orch import adapters, addons, skills

    root, home = tmp_path / "ws", tmp_path / "home"
    (root / ".orch").mkdir(parents=True)
    home.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setattr(addons, "real_home", lambda: home)
    monkeypatch.setenv("ORCH_HOME", str(home / "orchhome"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    monkeypatch.setattr(
        adapters, "detect", lambda **_: [{"name": "claude", "label": "Claude", "found": True, "version": None}]
    )
    for k in [k for k in os.environ if k.startswith(("CODEX_", "CLAUDECODE", "ORCH_RUN", "ORCH_AGENT"))]:
        monkeypatch.delenv(k)
    src = tmp_path / "src"
    for name in ("orch", "orch-hello"):
        desc = "Track work as orch tickets with steps and evidence." if name == "orch" else "d"
        skills.install_skill(root, name, _skill(src / name, name, desc))
    _skill(
        root / ".agents/skills/release-walk",
        "release-walk",
        "Run a release pass in a test home like a person.",
        {"status": "draft", "requires": "no-such-program-834"},
    )
    shared = _skill(root / ".agents/skills/github", "github", "GitHub work for the data repos; check routing first.")
    (shared / ".orch-shared").write_text("{}")
    _skill(
        home / ".claude/skills/status-page",
        "status-page",
        "A live status page of running work for the owner.",
        {"status": "retired"},
    )
    (home / ".claude").mkdir(exist_ok=True)
    (home / ".claude/CLAUDE.md").write_text("# Global rules\nAsk through orch.\n")
    (root / "AGENTS.md").write_text("# Workspace rules\nEvery change belongs to a ticket.\n")
    skills.apply_agent_files(root)
    return root

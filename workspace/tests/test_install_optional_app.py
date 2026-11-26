"""ORCH-2004: the plain Python (uv) install is complete; an exe or Mac app is never required."""

import re
import shutil
from pathlib import Path

from orch import adapters, addons, cli_leave, diag, procs

ROOT = Path(__file__).resolve().parents[2]
FETCH = re.compile(r"\.(dmg|msi|pkg)\b|setup\.exe|Companion|Invoke-WebRequest|Start-BitsTransfer", re.I)


def test_installers_only_use_uv_and_download_no_app():
    for name in ("install.sh", "install.ps1"):
        code = [
            ln
            for ln in (ROOT / name).read_text(encoding="utf-8").splitlines()
            if not ln.lstrip().startswith("#")
        ]
        assert not [ln for ln in code if FETCH.search(ln)], name
        assert any("uv tool install" in ln for ln in code), name


def test_readme_says_the_app_is_optional():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "never installs or needs an `.exe` or a Mac app" in text


def test_doctor_does_not_mind_a_missing_companion(proj, run, monkeypatch):
    diag._dropped.clear()
    monkeypatch.setattr(
        adapters, "detect", lambda: [{"name": "claude", "label": "Claude", "found": True, "version": None}]
    )
    monkeypatch.setattr(
        shutil, "which", lambda n, *a, **k: f"/usr/bin/{n}" if n in ("orch", "uv", "git") else None
    )
    monkeypatch.setattr(addons, "_which_uv", lambda: "/usr/bin/uv")
    monkeypatch.setattr(procs, "launcher_problem", lambda: None)  # the faked orch works (ORCH-2138)
    assert run("init")[0] == 0
    code, out, _ = run("doctor")
    assert code == 0 and "Nothing wrong." in out
    assert not [r for r in cli_leave.doctor(proj)["checks"] if "ompanion" in r["fact"] or ".exe" in r["fact"]]

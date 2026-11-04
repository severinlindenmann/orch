"""orch addon add|list|remove <name>, orch update.

Add-ons are packages in the repo under workspace-addons/<name>. They are installed into the orch uv tool
environment (`uv tool install ... --with <addon>`). The installed list lives in the user's orch data folder
(ORCH_HOME, default ~/.orch-tool) so `orch update` can reinstall everything. Source: ORCH_REPO (git URL or a
local checkout path, default github.com/severinlindenmann/orch) at ORCH_REF (default main).
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from orch import skills
from orch.errors import Refused

KNOWN = ("dashboard", "scheduler")
DEFAULT_REPO = "https://github.com/severinlindenmann/orch"


def repo() -> str:
    return os.environ.get("ORCH_REPO", DEFAULT_REPO)


def ref() -> str:
    return os.environ.get("ORCH_REF", "main")


def _is_local(r: str) -> bool:
    return Path(r).exists()


def spec(subdir: str) -> str:
    r = repo()
    if _is_local(r):
        return str((Path(r) / subdir).resolve())
    r = r.removesuffix(".git")
    return f"git+{r}@{ref()}#subdirectory={subdir}"


def home() -> Path:
    return Path(os.environ.get("ORCH_HOME") or Path.home() / ".orch-tool")


def registry_path() -> Path:
    return home() / "addons.json"


def installed_names() -> list[str]:
    try:
        return json.loads(registry_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save_names(names: list[str]) -> None:
    registry_path().parent.mkdir(parents=True, exist_ok=True)
    registry_path().write_text(json.dumps(sorted(set(names))), encoding="utf-8")


def _which_uv() -> str | None:
    """uv from PATH, but never one inside the current folder (a planted uv in the project)."""
    found = shutil.which("uv")
    if not found:
        return None
    try:
        Path(found).resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        return found
    return None


def run_uv(args: list[str]) -> None:
    """Tests replace this. Real: run uv and show its output."""
    uv = _which_uv()
    if not uv:
        raise Refused("uv is not installed. Run the orch install script first.")
    r = subprocess.run([uv, *args], text=True, capture_output=True)
    if r.returncode != 0:
        raise Refused(f"uv failed: {(r.stderr or r.stdout).strip()[-600:]}")


def _install_tool(names: list[str]) -> None:
    args = ["tool", "install", "--reinstall", spec("workspace")]
    for n in names:
        args += ["--with", spec(f"workspace-addons/{n}")]
    run_uv(args)


def addon_skill_dir(name: str) -> Path | None:
    """The add-on's skill: shipped in its package (orch_<name>/skills/orch-<name>) or in a local repo."""
    mod = f"orch_{name}"
    importlib.invalidate_caches()
    s = importlib.util.find_spec(mod)
    if s and s.submodule_search_locations:
        for loc in s.submodule_search_locations:
            cand = Path(loc) / "skills" / f"orch-{name}"
            if cand.is_dir():
                return cand
    if _is_local(repo()):
        cand = Path(repo()) / "workspace-addons" / name / "skills" / f"orch-{name}"
        if cand.is_dir():
            return cand
    return None


def _check(name: str) -> None:
    if name not in KNOWN:
        raise Refused(f"Unknown add-on '{name}'. Available: {', '.join(KNOWN)}.")


def _apply_project(root: Path, name: str) -> None:
    src = addon_skill_dir(name)
    if src is None:
        raise Refused(f"The {name} add-on has no skill folder; nothing was added to this project.")
    skills.install_skill(root, f"orch-{name}", src)
    skills.set_block(root, f"orch-{name}", skills.read_block(src, f"orch-{name}"))
    skills.link_claude_skills(root)


def reexec(args: list[str]) -> None:
    """Run the freshly installed orch for the project step (this process still runs the old code).
    Tests replace this with an in-process call."""
    r = subprocess.run([sys.executable, "-m", "orch", *args], text=True)
    if r.returncode != 0:
        raise Refused("The project step failed (see above).")


def add(root: Path, name: str, project_only: bool = False) -> None:
    _check(name)
    if project_only:
        _apply_project(root, name)
        return
    names = installed_names()
    if name not in names:
        _install_tool(names + [name])
        _save_names(names + [name])
    reexec(["addon", "add", name, "--project-only"])


def remove(root: Path, name: str) -> None:
    _check(name)
    skills.remove_block(root, f"orch-{name}")
    skills.unlink_skill(root, f"orch-{name}")
    skills.remove_skill(root, f"orch-{name}")
    # The package stays in the tool env until the next `orch update` (reinstalling here would replace the
    # running orch). Dropping it from the list makes update remove it.
    _save_names([n for n in installed_names() if n != name])


def project_addons(root: Path) -> list[str]:
    return [n for n in KNOWN if (root / ".agents" / "skills" / f"orch-{n}").is_dir()]


def update(root: Path, project_only: bool = False) -> list[str]:
    """Reinstall orch + add-ons, then refresh this project's skills and AGENTS.md blocks."""
    if not project_only:
        names = sorted(set(installed_names()) | set(project_addons(root)))
        _install_tool(names)
        _save_names(names)
        reexec(["update", "--project-only"])
        return []
    done = []
    if (root / ".agents" / "skills" / "orch").is_dir():
        from orch.init import init

        init(root)
        done.append("orch")
    for n in project_addons(root):
        _apply_project(root, n)
        done.append(f"orch-{n}")
    return done

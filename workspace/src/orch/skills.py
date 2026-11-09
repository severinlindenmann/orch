"""Skill folders and the orch block: kept under .orch/harness/ and linked from where agents look (harness.py)."""
# ruff: noqa: E501

from __future__ import annotations

import os
import shutil
from pathlib import Path

from orch import harness
from orch.errors import Refused

BLOCK_FILE = "AGENTS-block.md"
BLOCK_FILES = (BLOCK_FILE, "agents-block.md")  # add-ons may ship either spelling
GITIGNORE_LINES = [
    ".orch/.local-id",
    ".orch/secrets/",
    ".orch/inbox/",
    ".orch/inbox-seen.json",
    ".orch/addons/",
    ".orch/run/",
    ".orch/tickets/*/evidence/",
]


def packaged_skills_dir() -> Path:
    """Wheel install: orch/skills. Editable/dev checkout: workspace/skills."""
    here = Path(__file__).resolve().parent
    for cand in (here / "skills", here.parent.parent / "skills"):
        if cand.is_dir():
            return cand
    raise FileNotFoundError("orch skills folder not found")


def check_inside(root: Path, dest: Path) -> None:
    """Refuse when .orch/harness (or dest) is a link or points outside the project."""
    inside_h = harness.harness_dir(root).absolute() in Path(os.path.abspath(dest)).parents
    harness.check_harness(root, dest if inside_h else None)
    if not harness._inside(root, dest):  # e.g. .agents/skills/<name> linked out of the project
        raise Refused(f"{dest} points outside this project; orch will not write there.")


def harness_skill(root: Path, name: str) -> Path:
    return harness.harness_dir(root) / "skills" / name


def skill_text(source: Path) -> str:
    """The skill text as installed: SKILL.md, then every topics/*.md in sorted name order.

    Lanes add their own topic files (e.g. topics/40-keys.md, 50-record.md, 60-jobs.md, 70-wrappers.md)
    instead of editing SKILL.md. Bytes are kept as they are (no newline translation).
    """
    text = (source / "SKILL.md").read_bytes()
    topics = source / "topics"
    if topics.is_dir():
        text += b"".join(p.read_bytes() for p in sorted(topics.glob("*.md")))
    return text.decode("utf-8")


def install_skill(root: Path, name: str, source: Path) -> None:
    """Copy a skill folder to .orch/harness/skills/<name>/ (replaced whole, minus the block file); the
    links come from apply_agent_files. Files an add-on wrote into the folder (relay's workspaces.json) stay."""
    dest = harness_skill(root, name)
    check_inside(root, dest)
    keep = {}
    source_names = {p.name for p in source.iterdir()}
    if dest.is_dir():
        for f in dest.iterdir():
            if f.is_file() and f.name not in source_names and not harness.is_link(f):
                keep[f.name] = f.read_bytes()
        shutil.rmtree(dest)
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns(*BLOCK_FILES, "description.toml", "topics"))
    for fn, data in keep.items():
        (dest / fn).write_bytes(data)
    if (source / "topics").is_dir():
        (dest / "SKILL.md").write_bytes(skill_text(source).encode("utf-8"))


def remove_skill(root: Path, name: str) -> None:
    dest = harness_skill(root, name)
    check_inside(root, dest)
    for where in _skill_places(root):
        harness.unlink_skill(root, where, name)
    if dest.is_dir() and not harness.is_link(dest):
        shutil.rmtree(dest)


def set_block(root: Path, name: str, body: str, addon: bool = False) -> None:
    """The block of `name` (core, or an add-on with addon=True) goes to .orch/harness; AGENTS.md is not touched."""
    harness.set_block(root, name, body, addon)


def remove_block(root: Path, name: str, addon: bool = False) -> None:
    harness.remove_block(root, name, addon)


def read_block(source: Path, name: str, block_file: Path | None = None) -> str:
    if block_file is not None and block_file.is_file():
        return block_file.read_text(encoding="utf-8")
    for fn in BLOCK_FILES:
        f = source / fn
        if f.is_file():
            return f.read_text(encoding="utf-8")
    return f"## {name}\nRead `.agents/skills/{name}/SKILL.md`."


def _is_link(p: Path) -> bool:
    return harness.is_link(p)


def _unlink_dir(p: Path) -> None:
    if os.name == "nt":
        os.rmdir(p)  # removes a junction without touching its target
    else:
        p.unlink()


def _skills_link_paths() -> list[str]:
    from orch import adapters

    out = []
    for n in adapters.builtin_names():
        w = (adapters.load(n).get("files") or {}).get("skills_link")
        if w and w not in out:
            out.append(w)
    return out


def detected_agents(root: Path) -> list[str]:
    """Built-in agents this machine or folder uses: found on the PATH, running us, or chosen here."""
    from orch import adapters, config

    names = {r["name"] for r in adapters.detect() if r["found"]}
    for n in (adapters.detect_env(os.environ), config.agent_name(root)):
        if n:
            names.add(n)
    return [n for n in adapters.builtin_names() if n in names]


def _skill_places(root: Path) -> list[str]:
    """Where agents look for skills: .agents/skills always, plus the folder of every detected agent."""
    from orch import adapters

    out = [".agents/skills"]
    for n in detected_agents(root):
        w = (adapters.load(n).get("files") or {}).get("skills_link")
        if w and w not in out:
            out.append(w)
    return out


def apply_agent_files(root: Path) -> list[str]:
    """Make the harness visible: link every skill in .orch/harness/skills from the places agents look,
    write the local instruction file of each detected agent, list all of it in .git/info/exclude.
    Nothing here is a tracked file. Returns the labels of the agents it prepared files for."""
    from orch import adapters

    places = _skill_places(root)
    harness.protect_local(root, _exclude_lines(root))  # first, so a refused link cannot leave secrets visible
    sk = harness.harness_dir(root) / "skills"
    names = _harness_skill_names(root)
    refused = None  # one refused link must not stop the others or the local instruction file
    for where in places:
        for n in names:
            harness.check_harness(root, sk / n)
            try:
                harness.link_skill(root, where, n)
            except Refused as e:
                refused = refused or e
    for sh in _shared_skills(root):  # skills the relay delivered (not orch*): visible to every detected agent
        for where in places[1:]:
            try:
                harness.link_skill(root, where, sh.name, sh)
            except Refused as e:
                refused = refused or e
    harness.sync_copies(root, places)
    done, local = [], []
    for n in detected_agents(root):
        a = adapters.load(n)
        f = a.get("files") or {}
        for fn, line in (f.get("instructions_link") or {}).items():
            if harness.write_local_file(root, fn, line):
                local.append(fn)
        if f.get("skills_link") or f.get("instructions_link"):
            done.append(a["label"])
    if refused:
        raise refused
    return done


def apply_copy_files(root: Path, work: Path) -> None:
    """apply_agent_files for a separate copy of the project (git worktree) at `work`: the same skill links and
    local instruction files, but the links point at the WORKSPACE's harness (the copy has no .orch/harness) and
    the instruction file imports it by full path. The excludes live in the shared .git/info/exclude of the
    repository, already written for the workspace. One refused link does not stop the others."""
    from orch import adapters

    sk = harness.harness_dir(root) / "skills"
    refused = None

    def plain(rel: str) -> bool:
        """Nothing on the way from `work` to work/rel is a link: a copy holds BRANCH content, and a committed
        link (a local instruction file or skills folder pointing elsewhere) must not make orch write outside it."""
        p = work
        for part in Path(rel).parts:
            p = p / part
            if harness.is_link(p):
                return False
        return True

    for where in _skill_places(root):
        if not plain(where):
            refused = refused or Refused(f"{work / where} is a link; orch will not write through it.")
            continue
        for n in _harness_skill_names(root):
            harness.check_harness(root, sk / n)
            try:
                harness.link_skill(work, where, n, sk / n)
            except Refused as e:
                refused = refused or e
    for sh in _shared_skills(root):
        for where in _skill_places(root)[1:]:
            if not plain(where):
                continue
            try:
                harness.link_skill(work, where, sh.name, sh)
            except Refused as e:
                refused = refused or e
    for n in detected_agents(root):
        for fn, line in ((adapters.load(n).get("files") or {}).get("instructions_link") or {}).items():
            if plain(fn):
                harness.write_local_file(work, fn, line, harness_root=root)
            else:
                refused = refused or Refused(f"{work / fn} is a link; orch will not write through it.")
    if refused:
        raise refused


def _shared_skills(root: Path) -> list[Path]:
    base = root / ".agents" / "skills"
    if not base.is_dir() or harness.is_link(base):
        return []
    out = []
    for p in sorted(base.iterdir()):
        if p.is_dir() and not harness.is_link(p) and (p / ".orch-shared").exists():
            if harness.safe_skill_name(p.name):
                out.append(p)
            else:
                harness.skip_note(f"the shared skill folder {p.name!r}")
    return out


def _harness_skill_names(root: Path) -> list[str]:
    sk = harness.harness_dir(root) / "skills"
    names = sorted(p.name for p in sk.iterdir() if p.is_dir()) if sk.is_dir() else []
    ok = [n for n in names if harness.safe_skill_name(n)]
    for n in names:
        if n not in ok:
            harness.skip_note(f"the skill folder {n!r}")
    return ok


def _exclude_lines(root: Path) -> list[str]:
    """Root-relative patterns of the links and local instruction files orch makes here."""
    from orch import adapters

    names = [harness.glob_escape(n) for n in _harness_skill_names(root)]
    lines = [
        f".agents/skills/{n}" for n in names
    ]  # exact names: a user's own `orchestrator` skill stays visible
    for n in detected_agents(root):
        f = adapters.load(n).get("files") or {}
        lines += [fn for fn in (f.get("instructions_link") or {}) if ".local." in fn]
        if f.get("skills_link"):
            lines += [f"{f['skills_link']}/{s}" for s in names]
    for sh in _shared_skills(root):
        en = harness.glob_escape(sh.name)
        lines += [f".agents/skills/{en}/", *[f"{w}/{en}" for w in _skill_places(root)[1:]]]
    return list(dict.fromkeys(lines))


def unlink_skill(root: Path, name: str) -> None:
    for where in _skill_places(root):
        harness.unlink_skill(root, where, name)


def ensure_gitignore(root: Path) -> None:
    """The local-only lines (secrets, inbox, run files, ...) stay out of git: .orch/.gitignore and
    .git/info/exclude, never the team's .gitignore. Refuses when neither can be written."""
    harness.protect_local(root, _exclude_lines(root))


def front_matter_name(skill_dir: Path) -> str:
    return skill_dir.name

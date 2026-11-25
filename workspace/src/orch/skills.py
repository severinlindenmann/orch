"""Skill folders and the orch block: kept under .orch/harness/ and linked from where agents look (harness.py)."""
# ruff: noqa: E501

from __future__ import annotations

import os
import shutil
from pathlib import Path

from orch import harness, skillstatus
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
OFF_FILE = Path(".orch") / "skills-off.json"  # orch.skills-off/1, written by the Skills page's Turn off
ALWAYS_ON = frozenset({"orch"})  # the core skill: helpers cannot work tickets without it


def off_names(root: Path) -> frozenset[str]:
    """Skill names orch does not link in this workspace (orch's own and the admin's shared ones). A missing,
    damaged or linked file means none: a bad file never hides a skill by accident."""
    import json

    path = Path(root) / OFF_FILE
    try:
        if harness.is_link(path) or not path.is_file() or path.stat().st_size > 64 * 1024:
            return frozenset()
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    if (
        not isinstance(doc, dict)
        or doc.get("schema") != "orch.skills-off/1"
        or not isinstance(doc.get("skills"), list)
    ):
        return frozenset()
    return (
        frozenset(n for n in doc["skills"] if isinstance(n, str) and harness.safe_skill_name(n)) - ALWAYS_ON
    )


# orch.skills-removed/1, written by the Skills page's Remove from here
REMOVED_FILE = Path(".orch") / "skills-removed.json"


def removed_shared(root: Path) -> dict[str, int]:
    """Shared skills a person removed from this workspace: {name: the admin's version when it was removed}.
    `orch relay refresh` does not bring them back. A missing, damaged or linked file means none."""
    import json

    path = Path(root) / REMOVED_FILE
    try:
        if harness.is_link(path) or not path.is_file() or path.stat().st_size > 64 * 1024:
            return {}
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict) or doc.get("schema") != "orch.skills-removed/1":
        return {}
    got = doc.get("skills")
    if not isinstance(got, dict):
        return {}
    return {
        n: v if isinstance(v, int) and not isinstance(v, bool) else 0
        for n, v in got.items()
        if isinstance(n, str) and harness.safe_skill_name(n)
    }


def _unlink_ours(root: Path, where: str, name: str, target: Path) -> None:
    """Remove <where>/<name> when it is orch's: a link to `target`, or orch's copy of it where links are not
    possible (harness.unlink_skill keeps a copy that has files of the person's). A link to somewhere else, a plain
    folder of the person's and a copy that holds an add-on's own file stay."""
    dest = root / where / name
    if harness.is_link(root / where):
        return
    if harness.is_link(dest) and not harness._same(dest, target):
        return
    if not harness.is_link(dest) and dest.is_dir() and harness._keep_files(dest):
        harness.skip_note(f"{dest} (an add-on keeps a file in it; turn the add-on off instead)")
        return  # a copy (no links here) that holds an add-on's own file, e.g. orch-relay's workspaces.json
    harness.unlink_skill(root, where, name)


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
    sk = dest / "SKILL.md"
    if sk.is_file() and not harness.is_link(sk):
        text = sk.read_bytes().decode("utf-8")
        marked = skillstatus.mark_deprecated(text)
        if marked != text:
            sk.write_bytes(marked.encode("utf-8"))


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

    names = {r["name"] for r in adapters.detect(versions=False) if r["found"]}
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
    off = off_names(root)
    names = [n for n in _harness_skill_names(root) if n not in off]
    refused = None  # one refused link must not stop the others or the local instruction file
    for where in places:
        for n in sorted(off):  # turned off on the Skills page: orch's own link goes, the skill files stay
            _unlink_ours(root, where, n, sk / n)
        for n in names:
            harness.check_harness(root, sk / n)
            if skillstatus.hidden_reason(sk / n):  # retired, or not for this system: not offered, files stay
                _unlink_ours(root, where, n, sk / n)
                continue
            try:
                harness.link_skill(root, where, n)
            except Refused as e:
                refused = refused or e
    for sh in _shared_skills(root):  # skills the relay delivered (not orch*): visible to every detected agent
        for where in places[1:]:
            if sh.name in off or skillstatus.hidden_reason(sh):
                _unlink_ours(root, where, sh.name, sh)
                continue
            try:
                harness.link_skill(root, where, sh.name, sh)
            except Refused as e:
                refused = refused or e
    harness.sync_copies(root, places, skip=off)
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


def apply_copy_files(root: Path, work: Path, linked: set[str] | frozenset = frozenset()) -> None:
    """apply_agent_files for a separate copy of the project (git worktree) at `work`: the same skill links and
    local instruction files, but the links point at the WORKSPACE's harness (the copy has no .orch/harness) and
    the instruction file imports the copy's own .orch-harness/AGENTS.orch.md (written from the workspace's). The excludes live in the shared .git/info/exclude of the
    repository, already written for the workspace. One refused link does not stop the others. `linked`: top-level
    names in `work` that orch made links to the workspace's own entries (a copy of several projects): the skills
    there are the workspace's, nothing is written through them."""
    from orch import adapters

    sk = harness.harness_dir(root) / "skills"
    off = off_names(root)  # the workspace's Turn off holds in its copies too
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

    def via_link(rel: str) -> bool:
        return Path(rel).parts[0] in linked

    for where in _skill_places(root):
        if via_link(where):
            continue
        if not plain(where):
            refused = refused or Refused(f"{work / where} is a link; orch will not write through it.")
            continue
        for n in _harness_skill_names(root):
            harness.check_harness(root, sk / n)
            if n in off or skillstatus.hidden_reason(sk / n):
                _unlink_ours(work, where, n, sk / n)
                continue
            if harness.is_link(work / where / n) and not harness._same(work / where / n, sk / n):
                refused = refused or Refused(f"{work / where / n} is a link to somewhere else.")
                continue
            try:
                harness.link_skill(work, where, n, sk / n)
            except Refused as e:
                refused = refused or e
    for sh in _shared_skills(root):
        for where in _skill_places(root)[1:]:
            if via_link(where) or not plain(where):
                continue
            if sh.name in off or skillstatus.hidden_reason(sh):
                _unlink_ours(work, where, sh.name, sh)
                continue
            try:
                harness.link_skill(work, where, sh.name, sh)
            except Refused as e:
                refused = refused or e
    for n in detected_agents(root):
        for fn, line in ((adapters.load(n).get("files") or {}).get("instructions_link") or {}).items():
            if via_link(fn):
                continue
            if plain(fn):
                harness.write_local_file(work, fn, line, harness_root=root)
            else:
                refused = refused or Refused(f"{work / fn} is a link; orch will not write through it.")
    if refused:
        raise refused


def hidden_skills(root: Path) -> dict[str, str]:
    """{skill name: why} for the installed and shared skills orch does not offer here (retired, wrong system)."""
    out = {}
    sk = harness.harness_dir(root) / "skills"
    for n in _harness_skill_names(root):
        why = skillstatus.hidden_reason(sk / n)
        if why:
            out[n] = why
    for sh in _shared_skills(root):
        why = skillstatus.hidden_reason(sh)
        if why:
            out[sh.name] = why
    return out


def _shared_skills(root: Path) -> list[Path]:
    base = root / ".agents" / "skills"
    if not base.is_dir() or harness.is_link(base):
        return []
    out = []
    for p in sorted(base.iterdir()):
        if not harness.is_link(p) and p.is_dir() and (p / ".orch-shared").exists():
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
    lines.append(f"{harness.COPY_HARNESS}/")  # a copy's own AGENTS.orch.md (apply_copy_files)
    return list(dict.fromkeys(lines))


def unlink_skill(root: Path, name: str) -> None:
    for where in _skill_places(root):
        harness.unlink_skill(root, where, name)


def ensure_gitignore(root: Path, also: str | None = None) -> frozenset:
    """The local-only lines (secrets, inbox, run files, ...) stay out of git: .orch/.gitignore and
    .git/info/exclude, never the team's .gitignore. Refuses when neither can be written. `also`: a private
    file about to be written (see harness.protect_local)."""
    return harness.protect_local(root, _exclude_lines(root), also)


def front_matter_name(skill_dir: Path) -> str:
    return skill_dir.name

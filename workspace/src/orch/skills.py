"""Skill folders and AGENTS.md blocks (contracts/local-files.md)."""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

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
GITIGNORE_HEADER = "# orch (local only)"


def _project_file(root: Path, path: Path) -> Path:
    """The file behind AGENTS.md, CLAUDE.md or .gitignore. A link is followed only from AGENTS.md or
    CLAUDE.md and only to exactly the project's AGENTS.md or CLAUDE.md (CLAUDE.md -> AGENTS.md is common).
    Any other link (to .git/config, a git hook, ...) is refused; .gitignore never follows a link."""
    if path.is_symlink():
        top = root.resolve()
        target = path.resolve()
        if path.name not in ("AGENTS.md", "CLAUDE.md") or target not in (
            top / "AGENTS.md",
            top / "CLAUDE.md",
        ):
            raise Refused(
                f"{path} is a link orch does not write through. Make it a plain file and try again."
            )
        path = target
    if path.exists() and not path.is_file():
        raise Refused(f"{path} is not a regular file; orch will not write there.")
    return path


def _read_project_file(root: Path, path: Path) -> str:
    p = _project_file(root, path)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _write_project_file(root: Path, path: Path, text: str) -> None:
    """Atomic write: a new file next to it, then rename (never writes through a link)."""
    import tempfile

    p = _project_file(root, path)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        if p.exists():
            shutil.copymode(p, tmp)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def packaged_skills_dir() -> Path:
    """Wheel install: orch/skills. Editable/dev checkout: workspace/skills."""
    here = Path(__file__).resolve().parent
    for cand in (here / "skills", here.parent.parent / "skills"):
        if cand.is_dir():
            return cand
    raise FileNotFoundError("orch skills folder not found")


def check_inside(root: Path, dest: Path) -> None:
    """Refuse when .agents, .agents/skills or dest is a link pointing outside the project."""
    base = root.resolve()
    for p in (root / ".agents", root / ".agents" / "skills", dest):
        if _is_link(p) or p.exists():
            try:
                p.resolve().relative_to(base)
            except ValueError:
                raise Refused(f"{p} points outside this project; orch will not write there.") from None


def install_skill(root: Path, name: str, source: Path) -> None:
    """Copy a skill folder to .agents/skills/<name>/ (replaced whole, minus the AGENTS block file)."""
    dest = root / ".agents" / "skills" / name
    check_inside(root, dest)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns(*BLOCK_FILES))


def remove_skill(root: Path, name: str) -> None:
    dest = root / ".agents" / "skills" / name
    check_inside(root, dest)
    if dest.is_dir() and not _is_link(dest):
        shutil.rmtree(dest)


def _markers(name: str, addon: bool) -> tuple[str, str]:
    if addon:
        return f"<!-- orch:addon:{name} -->", f"<!-- /orch:addon:{name} -->"
    return f"<!-- orch:begin {name} -->", f"<!-- orch:end {name} -->"


def _block_re(name: str, addon: bool = False) -> re.Pattern:
    b, e = _markers(name, addon)
    return re.compile(rf"{re.escape(b)}\n.*?{re.escape(e)}\n?", re.S)


_MARKER_RE = re.compile(r"[ \t]*<!--\s*/?orch:[^>]*-->[ \t]*\n?")
_MARKER_START = re.compile(r"<!--\s*/?orch:")


def set_block(root: Path, name: str, body: str, addon: bool = False) -> None:
    """Add or replace the block for `name` in AGENTS.md; text outside the block is untouched.
    addon=True uses the add-on markers <!-- orch:addon:<name> --> ... <!-- /orch:addon:<name> -->."""
    path = root / "AGENTS.md"
    text = _read_project_file(root, path)
    while True:  # the markers are ours; strip until stable so pieces cannot join into a marker
        new = _MARKER_RE.sub("", body)
        if new == body:
            break
        body = new
    if _MARKER_START.search(body):
        raise Refused("An AGENTS.md block cannot contain orch markers (<!-- orch:... -->).")
    body = body.strip()
    b, e = _markers(name, addon)
    block = f"{b}\n{body}\n{e}\n"
    rx = _block_re(name, addon)
    if rx.search(text):
        text = rx.sub(lambda _m: block, text, count=1)
        # repair files an older version nested or duplicated: no other marker of this name may stay
        head, sep, tail = text.partition(block)
        stray = re.compile(rf"(?:{re.escape(b)}|{re.escape(e)})\n?")
        text = stray.sub("", head) + sep + stray.sub("", tail)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        if text:
            text += "\n"
        text += block
    _write_project_file(root, path, text)


def remove_block(root: Path, name: str, addon: bool = False) -> None:
    path = root / "AGENTS.md"
    if not path.exists():
        return
    text = _read_project_file(root, path)
    new = _block_re(name, addon).sub("", text).rstrip("\n")
    _write_project_file(root, path, new + "\n" if new else "")


def read_block(source: Path, name: str, block_file: Path | None = None) -> str:
    if block_file is not None and block_file.is_file():
        return block_file.read_text(encoding="utf-8")
    for fn in BLOCK_FILES:
        f = source / fn
        if f.is_file():
            return f.read_text(encoding="utf-8")
    return f"## {name}\nRead `.agents/skills/{name}/SKILL.md`."


def _link(link: Path, target: Path, rel: str) -> None:
    """Directory link: symlink (macOS/Linux) or junction (Windows, no admin needed)."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target.resolve()), str(link))
    else:
        os.symlink(rel, link, target_is_directory=True)


def _is_link(p: Path) -> bool:
    if p.is_symlink():
        return True
    if sys.platform == "win32":
        try:
            return bool(os.lstat(p).st_file_attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
        except (OSError, AttributeError):
            return False
    return False


def _unlink_dir(p: Path) -> None:
    if sys.platform == "win32":
        os.rmdir(p)  # removes a junction without touching its target
    else:
        p.unlink()


def link_claude_skills(root: Path) -> None:
    """.claude/skills -> ../.agents/skills. If .claude/skills is a real folder, link each skill inside it."""
    agents = root / ".agents" / "skills"
    agents.mkdir(parents=True, exist_ok=True)
    cl = root / ".claude" / "skills"
    if _is_link(cl):
        return
    if not cl.exists():
        _link(cl, agents, os.path.join("..", ".agents", "skills"))
        return
    for sk in sorted(p for p in agents.iterdir() if p.is_dir()):
        dest = cl / sk.name
        if dest.exists() or _is_link(dest):
            continue
        _link(dest, sk, os.path.join("..", "..", ".agents", "skills", sk.name))


def unlink_skill(root: Path, name: str) -> None:
    """Remove a per-skill link inside a real .claude/skills folder (the whole-folder link needs no change)."""
    cl = root / ".claude" / "skills"
    if _is_link(cl):
        return
    dest = cl / name
    if _is_link(dest):
        _unlink_dir(dest)


def ensure_claude_md(root: Path) -> None:
    path = root / "CLAUDE.md"
    text = _read_project_file(root, path)
    if any(line.strip() == "@AGENTS.md" for line in text.splitlines()):
        return
    if text and not text.endswith("\n"):
        text += "\n"
    _write_project_file(root, path, text + "@AGENTS.md\n")


def ensure_gitignore(root: Path) -> None:
    path = root / ".gitignore"
    text = _read_project_file(root, path)
    have = {line.strip() for line in text.splitlines()}
    missing = [x for x in GITIGNORE_LINES if x not in have]
    if not missing:
        return
    if text and not text.endswith("\n"):
        text += "\n"
    if GITIGNORE_HEADER not in have:
        text += ("\n" if text else "") + GITIGNORE_HEADER + "\n"
    _write_project_file(root, path, text + "\n".join(missing) + "\n")


def front_matter_name(skill_dir: Path) -> str:
    return skill_dir.name

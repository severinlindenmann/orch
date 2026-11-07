"""The orch harness lives under .orch/harness/ and stays local: orch never edits a file the team owns.

    .orch/harness/blocks/<name>.md       text of the core block and of each add-on block
    .orch/harness/AGENTS.orch.md         all blocks joined (what an agent reads)
    .orch/harness/skills/<skill>/        the real skill folders (orch, orch-<add-on>)
The places agents look are links (or, where links are not allowed, copies) to those skill folders, plus a local
instruction file such as CLAUDE.local.md; all of them are listed in .git/info/exclude, so `git status` stays clean.
"Share with team" is the one opt-in that writes into team files (AGENTS.md and .gitattributes)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from orch.errors import Refused

HARNESS = Path(".orch") / "harness"
COPY_MARK = ".orch-copy"  # inside a copy made where links are not allowed: "orch owns this folder"
LOCAL_MARK = ("<!-- orch:begin local -->", "<!-- orch:end local -->")
EXCLUDE_MARK = ("# orch:begin", "# orch:end")
SHARE_MARK = ("<!-- orch:begin share -->", "<!-- orch:end share -->")
SHARE_TEXT = (
    "## orch\n"
    "If the `orch` command exists on your computer, read `.agents/skills/orch/SKILL.md` before you work on tickets.\n"
    "If it does not, ignore this section."
)
ATTR_LINE = "AGENTS.md merge=union"
ATTR_COMMENT = "# orch: same text for everyone, so merges keep both sides"
CORE_LOCAL = "orch*"


def harness_dir(root: Path) -> Path:
    return root / HARNESS


def _inside(root: Path, p: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def is_link(p: Path) -> bool:
    if p.is_symlink():
        return True
    if sys.platform == "win32":
        try:
            return bool(os.lstat(p).st_file_attributes & 0x400)
        except (OSError, AttributeError):
            return False
    return False


def check_harness(root: Path, dest: Path | None = None) -> None:
    """.orch, .orch/harness, its subfolders and dest must be real folders inside the project."""
    h = harness_dir(root)
    for p in (root / ".orch", h, h / "skills", h / "blocks", *([dest] if dest else [])):
        if is_link(p):
            raise Refused(f"{p} is a link; orch will not write there. Make it a plain folder and try again.")
        if p.exists() and not _inside(root, p):
            raise Refused(f"{p} points outside this project; orch will not write there.")


# ------------------------------------------------------------------ plain files


def write_text(path: Path, text: str, mode: int = 0o644) -> None:
    """Atomic write; never through a link at the destination."""
    if is_link(path):
        raise Refused(f"{path} is a link; orch will not write through it.")
    if path.exists() and not path.is_file():
        raise Refused(f"{path} is not a regular file; orch will not write there.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _read(path: Path) -> str:
    if is_link(path):
        raise Refused(f"{path} is a link; orch will not read or write through it.")
    return path.read_text(encoding="utf-8") if path.is_file() else ""


# ------------------------------------------------------------------ blocks -> AGENTS.orch.md


def block_file(root: Path, name: str, addon: bool) -> Path:
    return harness_dir(root) / "blocks" / (f"addon-{name}.md" if addon else f"{name}.md")


def set_block(root: Path, name: str, body: str, addon: bool = False) -> None:
    check_harness(root)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S).strip()
    write_text(block_file(root, name, addon), body + "\n")
    rebuild(root)


def remove_block(root: Path, name: str, addon: bool = False) -> None:
    check_harness(root)
    block_file(root, name, addon).unlink(missing_ok=True)
    rebuild(root)


def current_block(root: Path, name: str, addon: bool = True) -> str | None:
    p = block_file(root, name, addon)
    return p.read_text(encoding="utf-8") if p.is_file() and not is_link(p) else None


def combined(root: Path) -> str:
    d = harness_dir(root) / "blocks"
    if not d.is_dir():
        return ""
    files = sorted(p for p in d.glob("*.md") if p.is_file() and not is_link(p))
    files.sort(key=lambda p: (p.name.startswith("addon-"), p.name))  # core first, then add-ons by name
    return "\n".join(p.read_text(encoding="utf-8").rstrip("\n") + "\n" for p in files)


def rebuild(root: Path) -> None:
    text = combined(root)
    out = harness_dir(root) / "AGENTS.orch.md"
    if text:
        write_text(out, text)
    else:
        out.unlink(missing_ok=True)


def start_text(root: Path) -> str:
    """The orch block for the start prompt of a run by an agent that does not read the local file."""
    return combined(root).strip()


# ------------------------------------------------------------------ git exclude


def _git_exclude(root: Path) -> tuple[Path, str] | None:
    """(.git/info/exclude, path of the project below the git top folder) or None when this is no git repo."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel", "--git-path", "info/exclude"],
            cwd=root, capture_output=True, text=True, env=env, timeout=10, check=True,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return None
    if len(out) != 2:
        return None
    top, ex = Path(out[0]), Path(out[1])
    if not ex.is_absolute():
        ex = root / ex
    try:
        rel = root.resolve().relative_to(top.resolve()).as_posix()
    except ValueError:
        return None
    return ex, ("" if rel == "." else rel)


def exclude_set(root: Path, tag: str, lines: list[str]) -> None:
    """Own block `tag` of .git/info/exclude (no lines = block removed). Not a git repo: nothing to do."""
    found = _git_exclude(root)
    if found is None:
        return
    ex, rel = found
    if is_link(ex):
        raise Refused(f"{ex} is a link; orch will not write there.")
    b, e = f"{EXCLUDE_MARK[0]} {tag}", f"{EXCLUDE_MARK[1]} {tag}"
    rows = (ex.read_text(encoding="utf-8") if ex.is_file() else "").splitlines()
    if b in rows and e in rows[rows.index(b):]:
        i = rows.index(b)
        rows = rows[:i] + rows[rows.index(e, i) + 1:]
    if lines:
        prefix = "/" + (rel + "/" if rel else "")
        rows += [b, *[prefix + ln.lstrip("/") for ln in lines], e]
    new = "\n".join(rows) + "\n" if rows else ""
    if new != (ex.read_text(encoding="utf-8") if ex.is_file() else ""):
        write_text(ex, new)


# ------------------------------------------------------------------ links (or copies) to skill folders


def _link_dir(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        try:
            import _winapi

            _winapi.CreateJunction(str(target.resolve()), str(link))
            return
        except OSError:
            _copy_dir(target, link)
            return
    try:
        os.symlink(os.path.relpath(target, link.parent), link, target_is_directory=True)
    except OSError:
        _copy_dir(target, link)


def _copy_dir(src: Path, dst: Path) -> None:
    """Where links are not allowed: a copy that orch keeps in sync (it owns it: COPY_MARK)."""
    dst.mkdir(parents=True, exist_ok=True)
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        if is_link(p):
            continue
        if p.is_dir():
            (dst / rel).mkdir(parents=True, exist_ok=True)
        elif p.is_file():
            shutil.copyfile(p, dst / rel)
    (dst / COPY_MARK).write_text("orch keeps this copy in sync with .orch/harness/skills\n", encoding="utf-8")


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def link_skill(root: Path, where: str, name: str) -> None:
    """<where>/<name> -> .orch/harness/skills/<name>. Never replaces a folder or file that is not orch's."""
    target = harness_dir(root) / "skills" / name
    parent = root / where
    if parent.exists() and not _inside(root, parent):
        raise Refused(f"{parent} points outside this project; orch will not write there.")
    if is_link(parent) and _same(parent, root / ".agents" / "skills"):
        return  # the team links the whole folder to .agents/skills: the skill is already visible
    dest = parent / name
    if is_link(dest):
        if _same(dest, target):
            return
        raise Refused(f"{dest} is a link to somewhere else; orch will not replace it.")
    if dest.exists():
        if (dest / COPY_MARK).is_file():
            shutil.rmtree(dest)
        elif dest.is_dir() and not (dest / "SKILL.md").exists():
            # only data an add-on wrote there before its skill came (workspaces.json): move it into the harness
            for p in dest.iterdir():
                if not (target / p.name).exists() and not is_link(p):
                    shutil.move(str(p), str(target / p.name))
            shutil.rmtree(dest)
        else:
            raise Refused(f"{dest} is not orch's; orch will not replace it. Nothing was changed there.")
    _link_dir(dest, target)


def unlink_skill(root: Path, where: str, name: str) -> None:
    parent = root / where
    if is_link(parent):
        return
    dest = parent / name
    if is_link(dest):
        if sys.platform == "win32":
            os.rmdir(dest)
        else:
            dest.unlink()
    elif dest.is_dir() and (dest / COPY_MARK).is_file():
        shutil.rmtree(dest)


def sync_copies(root: Path, wheres: list[str]) -> None:
    """Refresh the copies (Windows without links) from the harness."""
    sk = harness_dir(root) / "skills"
    if not sk.is_dir():
        return
    for where in wheres:
        for s in sorted(p for p in sk.iterdir() if p.is_dir()):
            dest = root / where / s.name
            if dest.is_dir() and not is_link(dest) and (dest / COPY_MARK).is_file():
                _copy_dir(s, dest)


# ------------------------------------------------------------------ local instruction file (CLAUDE.local.md)


def write_local_file(root: Path, fn: str, line: str | None) -> bool:
    """The local-only instruction file: our marked block imports AGENTS.md (when the team has no CLAUDE.md of
    its own and an AGENTS.md) and the orch block. Other text in the file is kept. Returns False when skipped."""
    path = root / fn
    if is_link(path) or (path.exists() and not path.is_file()):
        return False
    text = _read(path)
    local = ".local." in fn
    if text and LOCAL_MARK[0] not in text and not local:
        return False  # a file somebody else owns: not ours to edit
    lines = []
    team_claude = (root / "CLAUDE.md").exists() or (root / ".claude" / "CLAUDE.md").exists()
    if line and (root / "AGENTS.md").is_file() and not team_claude:
        lines.append(line)
    if combined(root):
        lines.append(f"@{(HARNESS / 'AGENTS.orch.md').as_posix()}")
    if not lines and LOCAL_MARK[0] not in text:
        return path.exists()  # nothing to say yet: do not make the file
    block = "\n".join([LOCAL_MARK[0], *lines, LOCAL_MARK[1]]) + "\n"
    rx = re.compile(re.escape(LOCAL_MARK[0]) + r".*?" + re.escape(LOCAL_MARK[1]) + r"\n?", re.S)
    if rx.search(text):
        new = rx.sub(lambda _m: block, text, count=1)
    else:
        new = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    if new != text:
        write_text(path, new)
    return True


# ------------------------------------------------------------------ Share with team


def _marked(text: str, marks: tuple[str, str]) -> re.Pattern:
    return re.compile(re.escape(marks[0]) + r".*?" + re.escape(marks[1]) + r"\n?", re.S)


def share_state(root: Path) -> bool:
    p = root / "AGENTS.md"
    return p.is_file() and not is_link(p) and SHARE_MARK[0] in p.read_text(encoding="utf-8")


def share_on(root: Path) -> None:
    for fn in ("AGENTS.md", ".gitattributes"):
        p = root / fn
        if is_link(p):
            raise Refused(f"{p} is a link; orch will not write through it.")
    block = f"{SHARE_MARK[0]}\n{SHARE_TEXT}\n{SHARE_MARK[1]}\n"
    p = root / "AGENTS.md"
    text = _read(p)
    if SHARE_MARK[0] not in text:
        write_text(p, (text.rstrip("\n") + "\n\n" if text.strip() else "") + block)
    g = root / ".gitattributes"
    gt = _read(g)
    if ATTR_LINE not in gt.splitlines():
        write_text(g, (gt.rstrip("\n") + "\n" if gt.strip() else "") + f"{ATTR_COMMENT}\n{ATTR_LINE}\n")


def share_off(root: Path) -> None:
    p = root / "AGENTS.md"
    if p.is_file() and not is_link(p):
        text = p.read_text(encoding="utf-8")
        new = _marked(text, SHARE_MARK).sub("", text)
        if new != text:
            new = new.rstrip("\n")
            if new.strip():
                write_text(p, new + "\n")
            else:
                p.unlink()
    g = root / ".gitattributes"
    if g.is_file() and not is_link(g):
        rows = g.read_text(encoding="utf-8").splitlines()
        keep = [r for r in rows if r not in (ATTR_LINE, ATTR_COMMENT)]
        if keep != rows:
            if keep:
                write_text(g, "\n".join(keep) + "\n")
            else:
                g.unlink()

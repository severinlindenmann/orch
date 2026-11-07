"""The orch harness lives under .orch/harness/ and stays local: orch never edits a file the team owns.

    .orch/harness/blocks/<name>.md       text of the core block and of each add-on block
    .orch/harness/AGENTS.orch.md         all blocks joined (what an agent reads)
    .orch/harness/skills/<skill>/        the real skill folders (orch, orch-<add-on>)
The places agents look are links (or, where links are not allowed, copies) to those skill folders, plus a local
local instruction file (named in agents.json); all of them are listed in .git/info/exclude, so `git status` stays clean.
"Share with team" is the one opt-in that writes into team files (AGENTS.md and .gitattributes)."""
# ruff: noqa: E501

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
    between = []
    if dest is not None:
        d = Path(os.path.abspath(dest))
        between = [*(q for q in d.parents if h.absolute() in q.parents)]
        if d.is_dir() or not is_link(d):  # a link to a file is replaced by the writer, never followed
            between.append(d)
    for p in (root / ".orch", h, h / "skills", h / "blocks", *between):
        if is_link(p):
            raise Refused(f"{p} is a link; orch will not write there. Make it a plain folder and try again.")
        if p.exists() and not _inside(root, p):
            raise Refused(f"{p} points outside this project; orch will not write there.")


# ------------------------------------------------------------------ plain files


def write_text(path: Path, text: str, mode: int = 0o644, replace_link: bool = False) -> None:
    """Atomic write; never through a link at the destination (a link to a file is refused, or with
    replace_link replaced by the new file, the target untouched)."""
    if is_link(path) and not replace_link:
        raise Refused(f"{path} is a link; orch will not write through it.")
    if path.exists() and not path.is_file():
        raise Refused(f"{path} is not a regular file; orch will not write there.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():  # a file that exists keeps its permissions and its line endings
        mode = path.stat().st_mode & 0o7777
        try:
            if b"\r\n" in path.read_bytes():
                text = text.replace("\r\n", "\n").replace("\n", "\r\n")
        except OSError:
            pass
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _read(path: Path) -> str:
    if is_link(path):
        raise Refused(f"{path} is a link; orch will not read or write through it.")
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n") if path.is_file() else ""


# ------------------------------------------------------------------ blocks -> AGENTS.orch.md


def block_file(root: Path, name: str, addon: bool) -> Path:
    return harness_dir(root) / "blocks" / (f"addon-{name}.md" if addon else f"{name}.md")


def strip_comments(body: str) -> str:
    """No HTML comment (and no piece of one) stays in a block; pieces cannot join into a marker."""
    while True:
        new = re.sub(r"<!--.*?-->", "", body, flags=re.S)
        if new == body:
            return body.replace("<!--", "").replace("-->", "")
        body = new


def set_block(root: Path, name: str, body: str, addon: bool = False) -> None:
    check_harness(root)
    body = strip_comments(body).strip()
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
            cwd=root,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
            check=True,
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


def exclude_set(root: Path, tag: str, lines: list[str]) -> bool:
    """Own block `tag` of .git/info/exclude (no lines = block removed). True when the file is in place;
    False when this is no git repo (nothing to exclude from)."""
    found = _git_exclude(root)
    if found is None:
        return False
    ex, rel = found
    if is_link(ex):
        raise Refused(f"{ex} is a link; orch will not write there.")
    b, e = f"{EXCLUDE_MARK[0]} {tag}", f"{EXCLUDE_MARK[1]} {tag}"
    rows = (ex.read_text(encoding="utf-8") if ex.is_file() else "").splitlines()
    if b in rows and e in rows[rows.index(b) :]:
        i = rows.index(b)
        rows = rows[:i] + rows[rows.index(e, i) + 1 :]
    if lines:
        esc = re.sub(r"([\\\[\]*?])", r"\\\1", rel)  # a folder name with glob characters stays literal
        prefix = "/" + (esc + "/" if esc else "")
        rows += [b, *[prefix + ln.lstrip("/") for ln in lines], e]
    new = "\n".join(rows) + "\n" if rows else ""
    if new != (ex.read_text(encoding="utf-8") if ex.is_file() else ""):
        write_text(ex, new)
    return True


# Local paths relative to .orch/: orch's own .gitignore keeps them out of git with or without git info
# exclude, written before anything else and independent of linking. It lists itself.
ORCH_IGNORE = [
    ".gitignore",
    ".local-id",
    "secrets/",
    "inbox/",
    "inbox-seen.json",
    "inbox-notes.json",
    "outbox/",
    "addons/",
    "run/",
    "tmp-refresh/",
    "harness/",
    "local/",
    "tickets/*/evidence/",
]


def _tracked(root: Path, rel: str) -> bool:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        return (
            subprocess.run(
                ["git", "ls-files", "--error-unmatch", "--", rel],
                cwd=root,
                capture_output=True,
                env=env,
                timeout=10,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def protect_local(root: Path, lines: list[str] | None = None) -> None:
    """Keep secrets and other local files out of git. Fails closed: when neither .orch/.gitignore nor
    .git/info/exclude can be written, it refuses (so no secret is stored unprotected). `lines` are the
    extra root-relative patterns for the exclude block (links, local instruction files)."""
    text = "# orch: local files, never committed (written by orch)\n" + "\n".join(ORCH_IGNORE) + "\n"
    ok = False
    try:
        p = root / ".orch" / ".gitignore"
        if is_link(root / ".orch"):
            raise Refused("link")
        if _tracked(root, ".orch/.gitignore"):
            pass  # the team owns this one: leave it, rely on .git/info/exclude
        else:
            if not (p.is_file() and not is_link(p) and p.read_text(encoding="utf-8") == text):
                write_text(p, text)
            ok = True
    except (Refused, OSError, UnicodeDecodeError):
        pass
    try:
        core = [".orch/" + ln.rstrip("/") + ("/" if ln.endswith("/") else "") for ln in ORCH_IGNORE[1:]]
        if exclude_set(root, "core", list(dict.fromkeys([*core, *(lines or [])]))):
            ok = True
    except (Refused, OSError, UnicodeDecodeError):
        pass
    if not ok:
        raise Refused(
            "orch cannot keep its private files out of git here (.orch/.gitignore and .git/info/exclude "
            "could not be written). Nothing was stored."
        )


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


def link_skill(root: Path, where: str, name: str, target: Path | None = None) -> None:
    """<where>/<name> -> .orch/harness/skills/<name> (or target). Never replaces a folder or file that is not orch's."""
    target = target or harness_dir(root) / "skills" / name
    parent = root / where
    if not _inside(root, parent):  # resolve() follows a linked ancestor even when the folder is not there yet
        raise Refused(f"{parent} points outside this project; orch will not write there.")
    if is_link(parent):
        return  # the team links the whole folder (to .agents/skills or elsewhere): nothing of ours goes into it
    dest = parent / name
    if is_link(dest):
        if _same(dest, target):
            return
        raise Refused(f"{dest} is a link to somewhere else; orch will not replace it.")
    if dest.exists():
        if (dest / COPY_MARK).is_file():
            shutil.rmtree(dest)
        elif name == "orch-relay" and dest.is_dir() and not (dest / "SKILL.md").exists():
            # only the directory the relay wrote before its skill came: move that one file into the harness
            for p in list(dest.iterdir()):
                if p.name == "workspaces.json" and p.is_file() and not is_link(p):
                    target.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(p), str(target / p.name))
            if any(dest.iterdir()):
                raise Refused(f"{dest} holds files that are not orch's; orch will not replace it.")
            dest.rmdir()
        else:
            raise Refused(f"{dest} is not orch's; orch will not replace it. Nothing was changed there.")
    _link_dir(dest, target)


def unlink_skill(root: Path, where: str, name: str) -> None:
    parent = root / where
    if is_link(parent) or (parent.exists() and not _inside(root, parent)):
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
            if is_link(root / where) or not _inside(root, root / where):
                continue
            if dest.is_dir() and not is_link(dest) and (dest / COPY_MARK).is_file():
                shutil.rmtree(dest)  # rebuilt whole: deleted files go, a planted link inside is gone
                _copy_dir(s, dest)


# ------------------------------------------------------------------ local instruction file


def write_local_file(root: Path, fn: str, line: str | None) -> bool:
    """The local-only instruction file: our marked block imports AGENTS.md (when the team has no shared sibling file of
    the same name without ".local" and an AGENTS.md) and the orch block. Other text in the file is kept. Returns False when skipped."""
    path = root / fn
    if is_link(path) or (path.exists() and not path.is_file()):
        return False
    text = _read(path)
    local = ".local." in fn
    if text and LOCAL_MARK[0] not in text and not local:
        return False  # a file somebody else owns: not ours to edit
    lines = []
    team_file = (
        local and (root / fn.replace(".local", "")).exists()
    )  # the team's own file: the tool reads it already
    if line and (root / "AGENTS.md").is_file() and not team_file:
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


ATTR_MARK = ("# orch:begin share", "# orch:end share")
CREATED = (
    Path(".orch") / "harness" / "share-created-agents"
)  # AGENTS.md did not exist before "Share with team"


def share_on(root: Path) -> None:
    for fn in ("AGENTS.md", ".gitattributes"):
        p = root / fn
        if is_link(p):
            raise Refused(f"{p} is a link; orch will not write through it.")
    block = f"{SHARE_MARK[0]}\n{SHARE_TEXT}\n{SHARE_MARK[1]}\n"
    p = root / "AGENTS.md"
    existed = p.is_file()
    text = _read(p)
    if SHARE_MARK[0] not in text:
        write_text(p, (text.rstrip("\n") + "\n\n" if text.strip() else "") + block)
        if not existed:
            check_harness(root)
            write_text(root / CREATED, "1\n")
    g = root / ".gitattributes"
    gt = _read(g)
    if ATTR_MARK[0] not in gt:
        write_text(
            g,
            (gt.rstrip("\n") + "\n" if gt.strip() else "") + f"{ATTR_MARK[0]}\n{ATTR_LINE}\n{ATTR_MARK[1]}\n",
        )


def share_off(root: Path) -> None:
    p = root / "AGENTS.md"
    if p.is_file() and not is_link(p):
        text = _read(p)
        new = _marked(text, SHARE_MARK).sub("", text, count=1)
        if new != text:
            new = new.rstrip("\n")
            created = (root / CREATED).is_file() and not is_link(root / CREATED)
            if new.strip() or not created:
                write_text(p, new + "\n" if new.strip() else "")
            else:
                p.unlink()  # orch made this file for the share: it goes with it
            (root / CREATED).unlink(missing_ok=True)
    g = root / ".gitattributes"
    if g.is_file() and not is_link(g):
        text = _read(g)
        new = re.sub(
            re.escape(ATTR_MARK[0]) + r".*?" + re.escape(ATTR_MARK[1]) + r"\n?", "", text, count=1, flags=re.S
        )
        if new != text:
            if new.strip():
                write_text(g, new)
            else:
                g.unlink()

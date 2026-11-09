"""The orch harness lives under .orch/harness/ and stays local: orch never edits a file the team owns.

    .orch/harness/blocks/<name>.md       text of the core block and of each add-on block
    .orch/harness/AGENTS.orch.md         all blocks joined (what an agent reads)
    .orch/harness/skills/<skill>/        the real skill folders (orch, orch-<add-on>)
The places agents look are links (or, where links are not allowed, copies) to those skill folders, plus a local
local instruction file (named in agents.json); all of them are listed in .git/info/exclude, so `git status` stays clean.
"Share with team" is the one opt-in that writes into team files (AGENTS.md and .gitattributes)."""
# ruff: noqa: E501

from __future__ import annotations

import json
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
    h = _hardened(root)
    if h is None:
        if _git_on_path():
            print("orch: git excludes skipped: no git that orch trusts was found.", file=sys.stderr)
        return None
    try:
        out = subprocess.run(
            [*h[0], "rev-parse", "--show-toplevel", "--git-path", "info/exclude"],
            cwd=root,
            capture_output=True,
            text=True,
            env=h[1],
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
    "chat/",
    "tickets/*/evidence/",
    "tickets/.lock-*",  # per-ticket write locks
]


def _general_lines(root: Path) -> list[str]:
    """The hidden General (Chat) ticket keeps the person's private Chat history: its file is local too.
    Its id is random, so the line is the exact file name. Only a safe file STEM is ever written (never the
    JSON's own id field, which an agent could fill with newlines or globs), and a file git already tracks
    is left alone (the team owns it)."""
    import re

    out: list[str] = []
    try:
        d = root / ".orch" / "tickets"
        for f in sorted(d.glob("t_*.json")):
            stem = f.stem
            if f.is_symlink() or not re.fullmatch(r"t_[a-z0-9]{6,16}", stem):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict) or data.get("general") is not True or data.get("id") != stem:
                continue
            if _tracked(root, f".orch/tickets/{f.name}"):
                continue  # already committed by the team: ignoring it would change nothing
            out.append(f"tickets/{stem}.json")
    except OSError:
        return []
    return out


def _tracked(root: Path, rel: str) -> bool:
    try:
        if not _in_git_repo(root):
            return False  # plain folder (or no git program there): nothing can be tracked
    except Refused:
        return True  # cannot tell: treat the file as the team's
    h = _hardened(root)
    if h is None:
        return True  # no trusted git: cannot tell, treat the file as the team's
    env = h[1]
    try:
        return (
            subprocess.run(
                [
                    *h[0],
                    "ls-files",
                    "--error-unmatch",
                    "--",
                    f":(icase){rel}",
                ],  # .ORCH/... tracked is this file too
                cwd=root,
                capture_output=True,
                env=env,
                timeout=10,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return True  # cannot tell: treat the file as the team's


def _git_on_path() -> bool:
    """Is there SOME git program on the PATH (the hardened lookup may still refuse it: a planted one)?"""
    name = "git.exe" if os.name == "nt" else "git"
    return any(
        d and os.path.isfile(os.path.join(d, name)) and os.access(os.path.join(d, name), os.X_OK)
        for d in os.environ.get("PATH", "").split(os.pathsep)
    )


# What "closed" means when orch finds no git it trusts (hardened() is None), per caller:
#   _in_git_repo / check_private_path / _ignored -> refuse (nothing private is stored);
#   _tracked -> "tracked" (the team's file: not touched); _git_exclude -> skipped with a note;
#   filesig.files_sig -> None (no signature).
def _hardened(cwd: Path):
    """safegit.hardened (imported late: safegit needs addons, addons needs this module)."""
    from orch import safegit

    return safegit.hardened(cwd)


def _in_git_repo(root: Path) -> bool:
    """True inside a git work tree, False when there is none. Any other git failure (dubious ownership, a broken
    index, ...) refuses: an unknown state is never treated as "no repo"."""
    h = _hardened(root)
    try:
        if h is None:
            if _git_on_path():  # a git exists but none is trusted (a planted one?): never "not a repo"
                raise Refused(
                    "orch found no git it trusts here, so it cannot tell what is ignored. Nothing was stored."
                )
            raise FileNotFoundError("git")  # no git program at all
        r = subprocess.run(
            [*h[0], "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            capture_output=True,
            env=h[1],
            timeout=10,
        )
    except FileNotFoundError:
        # no git program: fine in a plain folder, but a folder that has .git cannot be checked, so refuse
        for d in (root.absolute(), *root.absolute().parents):
            if os.path.lexists(d / ".git"):
                raise Refused(
                    "git is not installed, so orch cannot tell what is ignored here. Nothing was stored."
                ) from None
        return False
    except (OSError, subprocess.SubprocessError):
        raise Refused("orch cannot ask git about this folder. Nothing was stored.") from None
    if r.returncode == 0:
        return r.stdout.strip() == b"true"
    if b"not a git repository" in r.stderr.lower():
        return False
    raise Refused("git cannot be read in this folder (is it owned by someone else?). Nothing was stored.")


def _ignored(root: Path, rel: str) -> bool:
    h = _hardened(root)
    if h is None:
        raise Refused("orch cannot ask git about this folder. Nothing was stored.")
    try:
        r = subprocess.run(
            [*h[0], "check-ignore", "-q", "--", rel],
            cwd=root,
            capture_output=True,
            env=h[1],
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        raise Refused("orch cannot ask git about this folder. Nothing was stored.") from None
    if r.returncode == 0:
        return True
    if r.returncode == 1:
        return False
    raise Refused("git could not say whether private files are ignored here. Nothing was stored.")


def _probes_ignored(root: Path) -> bool:
    """In a git repo: git itself says the secrets and run folders are ignored (a team .gitignore with a `!` line
    can undo our rules). True outside a git repo (nothing to leak into)."""
    if not _in_git_repo(root):
        return True
    return all(_ignored(root, p) for p in (".orch/secrets/probe", ".orch/run/probe", ".orch/outbox/probe"))


def check_private_path(root: Path, path: Path) -> None:
    """Right before a private write: the file stays under root/.orch with no link on the way, and in a git repo
    git ignores this exact file and does not track it."""
    base = root / ".orch"
    # Not Path.relative_to alone: Windows paths compare without case, so ".ORCH/..." would pass. The project folder
    # compares as the OS does; the ".orch" part itself must be spelled exactly.
    full, top = os.path.normpath(path.absolute()), os.path.normpath(base.absolute())
    if (
        not os.path.normcase(full).startswith(os.path.normcase(top) + os.sep)
        or full[len(top) - 5 : len(top)] != ".orch"
    ):
        raise Refused(f"{path} is not inside .orch; orch will not store private files there.")
    rel_in = Path(full[len(top) + 1 :])
    if ".." in path.parts or ".." in rel_in.parts:
        raise Refused(f"{path} is not a plain path; orch will not store private files there.")
    # Windows aliases: "x." and "x " name x, and an 8.3 short name (SECRE~1) names another folder. Never written.
    if any("~" in p or p != p.rstrip(". ") for p in rel_in.parts):
        raise Refused(f"{path} is not a plain path; orch will not store private files there.")
    cur = base
    if is_link(cur):
        raise Refused(f"{cur} is a link; orch will not store private files there.")
    for part in rel_in.parts:
        cur = cur / part
        if is_link(cur):
            raise Refused(f"{cur} is a link; orch will not store private files there.")
    if not _inside(base, cur) and cur.exists():
        raise Refused(f"{path} points outside .orch; orch will not store private files there.")
    # The names on disk, not only in the string: on a case-insensitive disk (macOS, Windows) .orch/secrets opens a
    # folder spelled .ORCH/Secrets, and a short name or a trailing dot opens another one. Every part that exists
    # must carry exactly this name in its folder.
    parent = root
    for part in (".orch", *rel_in.parts):
        if not os.path.lexists(parent / part):
            break
        try:
            names = os.listdir(parent)
        except OSError:
            raise Refused(f"orch cannot list {parent}. Nothing was stored.") from None
        if part not in names:
            raise Refused(
                f"{parent / part} is spelled differently on disk; orch will not store private files there."
            )
        parent = parent / part
    if not _in_git_repo(root):
        return
    rel = path.absolute().relative_to(root.absolute()).as_posix()
    h = _hardened(root)
    if h is None:
        raise Refused("orch cannot ask git about this folder. Nothing was stored.")
    try:
        t = subprocess.run(
            [
                *h[0],
                "ls-files",
                "--error-unmatch",
                "--",
                f":(icase){rel}",
            ],  # .ORCH/... tracked is this file too
            cwd=root,
            capture_output=True,
            env=h[1],
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        raise Refused("orch cannot ask git about this folder. Nothing was stored.") from None
    if t.returncode not in (0, 1):
        raise Refused("git could not say whether private files are tracked here. Nothing was stored.")
    if not _ignored(root, rel) or t.returncode == 0:
        raise Refused(
            f"git would not leave {rel} alone (a .gitignore of the project shows it, or it is tracked). "
            "Nothing was stored."
        )


def glob_escape(text: str) -> str:
    """A name with glob characters stays literal in a gitignore line."""
    return re.sub(r"([\\\[\]*?!#])", r"\\\1", text)


SKILL_NAME = re.compile(r"[A-Za-z0-9._-]{1,64}")


def safe_skill_name(name: str) -> bool:
    return bool(SKILL_NAME.fullmatch(name)) and name not in {".", ".."}


def skip_note(what: str) -> None:
    print(f"orch: skipped {what} (unusual name or folder not made by orch)", file=sys.stderr)


def _is_ours_copy(dest: Path, root: Path) -> bool:
    """A folder orch may delete: it has the copy marker, no git-tracked file and no file newer than the marker."""
    mark = dest / COPY_MARK
    if not mark.is_file() or is_link(mark):
        return False
    try:
        return _is_ours_copy_checked(dest, root, mark)
    except Refused:
        return False


def _is_ours_copy_checked(dest: Path, root: Path, mark: Path) -> bool:
    try:
        mt = mark.stat().st_mtime
        listed = set(mark.read_text(encoding="utf-8").splitlines()[1:])
        for dp, _dns, fns in os.walk(dest, followlinks=False):
            for fn in fns:
                p = Path(dp) / fn
                rel_f = p.relative_to(dest).as_posix()
                if rel_f == COPY_MARK:
                    continue
                if rel_f not in listed or p.lstat().st_mtime > mt:  # a file orch did not copy is the user's
                    return False
    except (OSError, UnicodeDecodeError):
        return False
    try:
        rel = dest.relative_to(root).as_posix()
    except ValueError:
        return False
    return not _tracked(root, rel)


def protect_local(root: Path, lines: list[str] | None = None) -> None:
    """Keep secrets and other local files out of git. Fails closed: when neither .orch/.gitignore nor
    .git/info/exclude can be written, it refuses (so no secret is stored unprotected). `lines` are the
    extra root-relative patterns for the exclude block (links, local instruction files)."""
    ignore = [*ORCH_IGNORE, *_general_lines(root)]
    text = "# orch: local files, never committed (written by orch)\n" + "\n".join(ignore) + "\n"
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
        core = [".orch/" + ln.rstrip("/") + ("/" if ln.endswith("/") else "") for ln in ignore[1:]]
        if exclude_set(root, "core", list(dict.fromkeys([*core, *(lines or [])]))):
            ok = True
    except (Refused, OSError, UnicodeDecodeError):
        pass
    if ok and not _probes_ignored(root):
        ok = False
    if not ok:
        raise Refused(
            "orch cannot keep its private files out of git here (.orch/.gitignore and .git/info/exclude "
            "could not be written, or a .gitignore of the project makes them visible again). Nothing was stored."
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
    copied: list[str] = []
    for dp, dns, fns in os.walk(src, followlinks=False):
        d = Path(dp)
        rel = d.relative_to(src)
        dns[:] = [n for n in dns if not is_link(d / n)]  # never descend into a directory link
        for n in dns:
            (dst / rel / n).mkdir(parents=True, exist_ok=True)
        for n in fns:
            p = d / n
            if not is_link(p) and p.is_file():
                shutil.copyfile(p, dst / rel / n)
                copied.append((rel / n).as_posix())
    (dst / COPY_MARK).write_text(
        "\n".join(["orch keeps this copy in sync with .orch/harness/skills", *copied]) + "\n",
        encoding="utf-8",
    )


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
        if (dest / COPY_MARK).is_file() and _is_ours_copy(dest, root):
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
        if _is_ours_copy(dest, root):
            shutil.rmtree(dest)
        else:
            skip_note(f"{dest} (it has files of yours)")


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
                if not _is_ours_copy(dest, root):
                    skip_note(f"{dest} (it has files of yours)")
                    continue
                shutil.rmtree(dest)  # rebuilt whole: deleted files go, a planted link inside is gone
                _copy_dir(s, dest)


# ------------------------------------------------------------------ local instruction file


def write_local_file(root: Path, fn: str, line: str | None, harness_root: Path | None = None) -> bool:
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
    if combined(harness_root or root):
        # a separate copy has no .orch/harness of its own: it imports the workspace's, by full path
        imp = (harness_root / HARNESS / "AGENTS.orch.md") if harness_root else (HARNESS / "AGENTS.orch.md")
        lines.append(f"@{imp.as_posix()}")
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

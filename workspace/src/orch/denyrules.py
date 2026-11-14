"""Deny rules for the agent's own tools (contracts/secrets.md, "Deny rules"; Level 1).

One deny set for every adapter (`roots`); an adapter's `deny.format` only says how its tool is told.
Pure string work on paths (no reads), so Windows forms can be tested anywhere."""

import os
import re
from pathlib import Path, PurePosixPath

# (name, read denied, path under the workspace or None = every guarded orch home)
ROOTS = (
    ("home", True, None),
    ("secrets", True, ".orch/secrets"),
    ("record", False, ".orch/record"),
    ("local-id", False, ".orch/.local-id"),
)
# A ticket agent works in <orch home>/worktrees/<ws8>/<ticket>: its instruction file, its skills and its code
# live there. A deny rule has no "except", so for such an agent the home is denied child by child and the one
# folder it works in stays open (without_worktrees). Everything else under the home is denied: the
# names below, the patterns (any new file of these kinds), and whatever is there at the start. A test fails
# when code names a new top-level file under the home that this list does not cover.
OPEN_CHILD = "worktrees"
HOME_CHILDREN = (
    "keys",
    "secrets",
    "copies",
    "finish",
    "finish.pending",
    "finish.updating",
    "projects",
    "tmp",
    "addons.json",
    "agent-approvals.json",
    "agent-commands-seen.json",
    "connections.json",
    "consent.json",
    "copies.json",
    "dev-workspaces.json",
    "finish.log",
    "human-settings.json",
    "installed.json",
    "look-set-by.json",
    "permissions.json",
    "ports.json",
    "protection-reset.log",
    "running.json",
    "services.lock",
    "shared-pages.json",
    "update-before.json",
    ".copies-state",
)
HOME_PATTERNS = (
    "*.json",
    "*.log",
    "*.lock",
    "*.pending",
    "*.updating",
    "*.tmp",
    "*.tmp*",
    "*.db",
    "*.bak",
    "*.txt",
    ".*",
)
TRAVERSAL = ("../keys", "../secrets", "../../", "..\\keys", "..\\secrets", "..\\..\\")
_BAD = re.compile(r"[,() \t\r\n\0]")
_DRIVE = re.compile(r"^([A-Za-z]):[\\/]")


def _clean(text: str) -> str:
    return _BAD.sub("*", text)  # one wildcard char: never splits the list, never a literal "?"


def _norm(path: str) -> str:
    """Forward slashes, no trailing slash."""
    p = path.replace("\\", "/")
    return p.rstrip("/") or "/"


def _rel(path: str, base: str) -> str | None:
    """`path` relative to `base` as a posix string (../.. form); None across drives."""
    a, b = _norm(path), _norm(base)
    ma, mb = _DRIVE.match(a), _DRIVE.match(b)
    if bool(ma) != bool(mb) or (ma and a[0].lower() != b[0].lower()):
        return None
    if not ma and not (a.startswith("/") and b.startswith("/")):
        return None
    pa, pb = a.split("/"), b.split("/")
    n = 0
    while n < min(len(pa), len(pb)) and pa[n].lower() == pb[n].lower():
        n += 1
    return "/".join([".."] * (len(pb) - n) + pa[n:]) or "."


def _under(path: str, base: str) -> str | None:
    a, b = _norm(path), _norm(base)
    if a.lower() == b.lower():
        return ""
    if a.lower().startswith(b.lower().rstrip("/") + "/"):
        return a[len(b.rstrip("/")) + 1 :]
    return None


def path_forms(path: str, workspace: str, account_home: str | None) -> dict:
    """Every way the agent can name `path`: {"file": [...], "text": [...]} for file tools and shell."""
    p = _norm(path)
    file_forms, text_forms = [], []
    m = _DRIVE.match(p)
    if m:
        rest = p[3:]
        drive = m.group(1)
        file_forms += [f"//{drive.lower()}/{rest}", f"{drive}:/{rest}", f"{drive.lower()}:/{rest}"]
        text_forms += [f"{drive}:/{rest}", f"{drive.lower()}:/{rest}"]
        text_forms += [
            f"{drive}:\\{rest.replace('/', chr(92))}",
            f"{drive.lower()}:\\{rest.replace('/', chr(92))}",
        ]
    else:
        file_forms.append("//" + p.lstrip("/"))
        text_forms.append(p)
    rel = _rel(p, workspace)
    if rel not in (None, "."):
        if not rel.startswith(".."):
            file_forms.append("./" + rel)
        text_forms += [rel, rel.replace("/", "\\")]
    if account_home:
        under = _under(p, account_home)
        if under:
            file_forms.append("~/" + under)
            text_forms += [
                "~/" + under,
                "$HOME/" + under,
                "${HOME}/" + under,
                "~\\" + under.replace("/", "\\"),
                "$env:USERPROFILE\\" + under.replace("/", "\\"),
                "$env:USERPROFILE/" + under,
                "%USERPROFILE%\\" + under.replace("/", "\\"),
                "%USERPROFILE%/" + under,
            ]
    return {"file": [_clean(f) for f in file_forms], "text": [_clean(t) for t in text_forms]}


def _candidates(root: Path) -> list[str]:
    """Every place orch's home can be. `<account home>/.orch-tool` and ORCH_HOME (when set) are ALWAYS
    there, whatever the lookups below do; the guarded/trusted homes are added when they resolve."""
    from orch import addons, humanproof
    from orch.errors import Refused

    out: list[str] = []

    def add(h) -> None:
        for s in (str(h), os.path.realpath(h)):
            if s and s not in out:
                out.append(s)

    acct = _account_home()
    if acct:
        add(Path(acct) / ".orch-tool")
    if os.environ.get("ORCH_HOME"):
        add(os.environ["ORCH_HOME"])
    for get in (
        lambda: humanproof.guarded_home(root),
        lambda: addons.home(root),
        lambda: addons.home_candidates(include_real=True),
    ):
        try:
            got = get()
        except (Refused, OSError):
            continue
        for h in got if isinstance(got, list) else [got]:
            add(h)
    return out


def _account_home() -> str | None:
    h = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    return h or None


def rules(root: Path, homes: list[str] | None = None, account_home: str | None = None) -> list[dict]:
    """The deny set: [{"root", "path", "read", "file": [...], "text": [...]}]. The default home and ORCH_HOME
    are always rows. A home that is or contains the workspace cannot be denied without denying the workspace:
    the start is refused (Refused). A home inside the workspace is fine: only that subfolder is denied."""
    ws_raw, ws_real = str(root), os.path.realpath(root)
    acct = account_home if account_home is not None else _account_home()
    homes = _candidates(root) if homes is None else homes
    for h in homes:
        if _under(ws_raw, h) is not None or _under(ws_real, h) is not None:  # is, or contains, the workspace
            from orch.errors import Refused

            raise Refused(
                "orch's folder contains this workspace: move the workspace out of it, then try again."
            )
    out = []
    for name, read, sub in ROOTS:
        paths = (
            homes
            if sub is None
            else [x for w in dict.fromkeys((ws_raw, ws_real)) for x in [_norm(w) + "/" + sub]]
        )
        for p in dict.fromkeys(paths):
            forms = path_forms(p, ws_raw, acct)
            if sub is None:
                leaf = PurePosixPath(_norm(p)).name
                if (
                    len(leaf) >= 6
                ):  # the home's own name, whatever it is (over-blocks look-alikes of that name only)
                    forms["text"].append(_clean(leaf))
                    parent = PurePosixPath(_norm(p)).parent.name
                    if parent:
                        forms["text"] += [_clean(f"{parent}/{leaf}"), _clean(f"{parent}\\{leaf}")]
            else:
                forms["text"] += [sub, sub.replace("/", "\\")]
            out.append({"root": name, "path": p, "read": read, **forms})
    return out


def _children(folder: str, extra: tuple[str, ...], keep: str | None) -> list[str]:
    names = list(extra)
    try:
        names += sorted(os.listdir(folder))
    except OSError:
        pass
    return [n for n in dict.fromkeys(names) if keep is None or n.lower() != keep.lower()]


def _own_parts(workdir: str | None, home: str) -> list[str] | None:
    """[worktrees, ws8, ticket] when workdir is inside <home>/worktrees/<ws8>/<ticket>, else None."""
    if not workdir:
        return None
    for w in dict.fromkeys((str(workdir), os.path.realpath(workdir))):
        under = _under(w, home)
        parts = [x for x in (under or "").split("/") if x]
        if len(parts) >= 3 and parts[0].lower() == OPEN_CHILD and ".." not in parts:
            return parts[:3]
    return None


def check_worktree_links(workdir: str, homes: list[str]) -> None:
    """Refuse the start when a link or junction inside the worktree points into an orch home outside it."""
    from orch.errors import Refused

    top = os.path.realpath(workdir)
    for dirpath, dirs, files in os.walk(workdir, followlinks=False):
        dirs[:] = [d for d in dirs if d != ".git"]
        for n in dirs + files:
            p = os.path.join(dirpath, n)
            if not (os.path.islink(p) or getattr(os.path, "isjunction", lambda _: False)(p)):
                continue
            real = os.path.realpath(p)
            if _under(real, top) is not None:
                continue
            for h in homes:
                if _under(real, h) is not None or _under(real, os.path.realpath(h)) is not None:
                    raise Refused(
                        "A link in this copy of the project points into orch's own folder. "
                        "Remove it, then try again."
                    )


def without_worktrees(
    rule_list: list[dict], workspace: str, account_home: str | None, workdir: str | None = None
) -> list[dict]:
    """The deny set the tool is told. A home row stays a blanket deny unless `workdir` is inside
    <home>/worktrees/<ws8>/<ticket>: then the home is denied child by child, and so are the other
    workspaces' and tickets' folders under worktrees, and only that ticket's folder stays open."""
    out = []
    for r in rule_list:
        own = _own_parts(workdir, r["path"]) if r["root"] == "home" else None
        if own is None:
            out.append(r)
            continue
        out.append({**r, "file": [], "text": [*r["text"], *TRAVERSAL]})
        base = _norm(r["path"])

        def row(path, r=r):
            return {**r, "path": path, "file": path_forms(path, workspace, account_home)["file"], "text": []}

        for n in _children(base, (*HOME_CHILDREN, *HOME_PATTERNS), OPEN_CHILD):
            out.append(row(base + "/" + n))
        wt = base + "/" + OPEN_CHILD
        for n in _children(wt, (".known.json",), own[1]):
            out.append(row(wt + "/" + n))
        ws8 = wt + "/" + own[1]
        for n in _children(ws8, (".owner", ".known.json"), own[2]):
            out.append(row(ws8 + "/" + n))
    return out


def tool_patterns(rule_list: list[dict]) -> list[str]:
    """patterns/1: Read/Edit/Write patterns and Bash text patterns, de-duplicated, in a stable order."""
    pats: list[str] = []
    for r in rule_list:
        tools = ("Read", "Edit") if r["read"] else ("Edit",)  # Edit covers every edit/write tool
        for f in r["file"]:
            for tool in tools:
                pats += [f"{tool}({f})", f"{tool}({f}/**)"]
        pats += [f"Bash(*{t}*)" for t in r["text"]]
    return list(dict.fromkeys(pats))


_FLAGS = ("--disallowedTools", "--disallowed-tools")


def merge_flag(extra: list[str], patterns: list[str]) -> list[str]:
    """Add `patterns` to the tool's disallowed-tools flag in `extra`: spelled `--disallowedTools X`,
    `--disallowed-tools X` or `--disallowedTools=X`. Extended, never replaced; all spellings become ONE
    `--disallowedTools` placed LAST in `extra`: the flag is variadic, so nothing positional may follow it
    (render puts `extra` before `--`, or at the very end when there is no prompt)."""
    out: list[str] = []
    old: list[str] = []
    i = 0
    while i < len(extra):
        item = extra[i]
        if item in _FLAGS and i + 1 < len(extra):
            old.append(extra[i + 1])
            i += 2
        elif any(item.startswith(f + "=") for f in _FLAGS):
            old.append(item.split("=", 1)[1])
            i += 1
        else:
            out.append(item)
            i += 1
    return [*out, "--disallowedTools", ",".join([*old, ",".join(patterns)])]


def deny_args(
    deny: dict | None, extra: list[str], root: Path | None, workdir: str | Path | None = None
) -> list[str]:
    """`extra` (the tool's permission flags) plus the deny rules for the adapter's `deny.format`."""
    fmt = (deny or {}).get("format", "none")
    if fmt == "none":
        return extra
    if root is None:  # fail closed: no workspace, no way to tell the tool; never start it without the rules
        from orch.errors import Refused

        raise Refused("orch cannot start this tool without its deny rules (no workspace given).")
    if fmt == "patterns/1":
        acct = _account_home()
        rl = rules(root)
        if workdir:
            check_worktree_links(str(workdir), [r["path"] for r in rl if r["root"] == "home"])
        return merge_flag(
            extra, tool_patterns(without_worktrees(rl, str(root), acct, str(workdir) if workdir else None))
        )
    raise RuntimeError(f"unknown deny format {fmt}")

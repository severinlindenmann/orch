"""Deny rules for the agent's own tools (contracts/secrets.md, "Deny rules"; Level 1).

One deny set for every adapter (`roots`); an adapter's `deny.format` only says how its tool is told.
Pure string work on paths (only copies_rules lists the copies folders), so Windows forms can be tested
anywhere."""

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


def _copies_bases() -> list[str]:
    from orch import addons

    out: list[str] = []
    try:
        for b in addons.copies_candidates(include_real=True):
            for x in (str(b), os.path.realpath(b)):
                if x not in out:
                    out.append(x)
    except (OSError, RuntimeError):
        pass
    return out


def copies_rules(
    workdir: str | None, workspace: str, account_home: str | None, bases: list[str] | None = None
) -> list[dict]:
    """Other tickets' copies. Copies live OUTSIDE the orch home (addons.copies_base), so the home deny
    (keys, secrets, approvals) holds whole for every agent, its own copy is simply not under it. On top:
    an agent that does not work in a copy is denied every copies folder; an agent in
    <base>/<ws8>/<ticket> is denied every other entry there at its start (other workspaces' copies, the
    other tickets, `.owner`, `.trash`). Copies hold project files, never orch's secrets: this row is
    defense in depth, the secret boundary is the home deny."""
    bases = _copies_bases() if bases is None else bases
    own: tuple[str, str, str] | None = None
    for w in dict.fromkeys(x for x in (workdir, workdir and os.path.realpath(workdir)) if x):
        for b in bases:
            parts = [x for x in (_under(w, b) or "").split("/") if x]
            if len(parts) >= 2 and ".." not in parts:
                own = (b, parts[0], parts[1])
                break
        if own:
            break

    def row(path: str) -> dict:
        return {"root": "copies", "path": path, "read": True, **path_forms(path, workspace, account_home)}

    if own is None:
        return [row(_norm(b)) for b in dict.fromkeys(bases)]
    out = []
    for b in dict.fromkeys(bases):
        base = _norm(b)
        keep_ws = own[1] if _norm(own[0]).lower() == base.lower() else None
        for n in _list(base):
            if keep_ws is None or n.lower() != keep_ws.lower():
                out.append(row(base + "/" + n))
        if keep_ws is not None:
            for n in _list(base + "/" + keep_ws):
                if n.lower() != own[2].lower():
                    out.append(row(base + "/" + keep_ws + "/" + n))
    return out


def _list(folder: str) -> list[str]:
    try:
        return sorted(os.listdir(folder))
    except OSError:
        return []


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
        rl = rules(root)
        rl += copies_rules(str(workdir) if workdir else None, str(root), _account_home())
        return merge_flag(extra, tool_patterns(rl))
    raise RuntimeError(f"unknown deny format {fmt}")

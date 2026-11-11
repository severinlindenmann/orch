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
_BAD = re.compile(r"[,()\r\n\0]")
_DRIVE = re.compile(r"^([A-Za-z]):[\\/]")


def _clean(text: str) -> str:
    return _BAD.sub("?", text)


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
        file_forms.append(rel if rel.startswith("..") else "./" + rel)
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
            ]
    return {"file": [_clean(f) for f in file_forms], "text": [_clean(t) for t in text_forms]}


def _candidates(root: Path) -> list[str]:
    from orch import addons, humanproof
    from orch.errors import Refused

    out: list[str] = []
    for get in (lambda: humanproof.guarded_home(root), lambda: addons.home(root), addons.home_candidates):
        try:
            got = get()
        except (Refused, OSError):
            continue
        for h in got if isinstance(got, list) else [got]:
            for s in (str(h), os.path.realpath(h)):
                if s not in out:
                    out.append(s)
    return out


def _account_home() -> str | None:
    h = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    return h or None


def rules(root: Path, homes: list[str] | None = None, account_home: str | None = None) -> list[dict]:
    """The deny set: [{"root", "path", "read", "file": [...], "text": [...]}]. Fails closed: with no
    guarded home known, the `home` row is empty but the workspace rows still apply."""
    ws_raw, ws_real = str(root), os.path.realpath(root)
    acct = account_home if account_home is not None else _account_home()
    homes = _candidates(root) if homes is None else homes
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
                if len(leaf) >= 6 and (leaf.startswith(".") or "orch" in leaf.lower()):
                    forms["text"].append(_clean(leaf))
            else:
                forms["text"] += [sub, sub.replace("/", "\\")]
            out.append({"root": name, "path": p, "read": read, **forms})
    return out


def tool_patterns(rule_list: list[dict]) -> list[str]:
    """patterns/1: Read/Edit/Write patterns and Bash text patterns, de-duplicated, in a stable order."""
    pats: list[str] = []
    for r in rule_list:
        tools = ("Read", "Edit", "Write") if r["read"] else ("Edit", "Write")
        for f in r["file"]:
            for tool in tools:
                pats += [f"{tool}({f})", f"{tool}({f}/**)"]
        pats += [f"Bash(*{t}*)" for t in r["text"]]
    return list(dict.fromkeys(pats))


def merge_flag(extra: list[str], patterns: list[str]) -> list[str]:
    """Add `patterns` to the --disallowedTools value in `extra` (extended, never replaced), or append one."""
    joined = ",".join(patterns)
    out = list(extra)
    for i, item in enumerate(out):
        if item == "--disallowedTools" and i + 1 < len(out):
            out[i + 1] = out[i + 1] + "," + joined
            return out
    return out + ["--disallowedTools", joined]


def deny_args(deny: dict | None, extra: list[str], root: Path | None) -> list[str]:
    """`extra` (the tool's permission flags) plus the deny rules for the adapter's `deny.format`."""
    fmt = (deny or {}).get("format", "none")
    if fmt == "none" or root is None:
        return extra
    if fmt == "patterns/1":
        return merge_flag(extra, tool_patterns(rules(root)))
    raise RuntimeError(f"unknown deny format {fmt}")

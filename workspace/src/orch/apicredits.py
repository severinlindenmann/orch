"""API credits that skills and add-ons declare (ORCH-600 format, ORCH-625): read them, check them, list them.

A skill says it spends on an API with one header line, `metadata: api-credits: "api-credits.toml"`, that names a
small file next to SKILL.md. An add-on names the same file in its orch-addon.toml (`api-credits = "..."`).
The file holds one [[credit]] table per credit:

    [[credit]]
    name     = "key-1"                        # unique in this skill; the full name is <skill>/key-1
    label    = "Example API key 1"             # what the page shows
    provider = "Anthropic"                    # in plain words
    key      = "pass:Agents/Example API key 1" # WHERE the key lives (pass:<vault>/<item> or orch:<name>), never the key
    unit     = "$"                            # "$", "tokens" or "calls" (Usage counts "$" only for now)
    spend    = "report"                       # or "log:<file next to it>"
    balance  = ""                             # optional: a command that prints the amount left at the provider

Nothing here resolves `key`: orch keeps only where a key lives. A value that looks like a key is refused, and a
problem message never repeats the value of `key` or `balance` (a pasted key must not land in a log).
Usage (ORCH-626 to 628) lists what declared() returns; no code per provider.
"""
# ruff: noqa: E501

from __future__ import annotations

import re
import tomllib
from pathlib import Path

FILE_KEY = "api-credits"  # the metadata key of a skill header and the key in orch-addon.toml
FIELDS = ("name", "label", "provider", "key", "unit", "spend", "balance")
REQUIRED = ("name", "label", "provider", "key", "unit", "spend")
UNITS = ("$", "tokens", "calls")
FILE_MAX = 64 * 1024
CREDITS_MAX = 16
LABEL_MAX = 60
PROVIDER_MAX = 40
BALANCE_MAX = 300
HIDDEN = ("key", "balance")  # never repeated in a message

# all used with fullmatch: no control character (a terminal escape) and no trailing newline gets through
_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_KEY_REF = re.compile(
    r"pass:[^/\s\x00-\x1f\x7f][^/\x00-\x1f\x7f]{0,79}/[^/\x00-\x1f\x7f]{1,120}|orch:[a-z0-9][a-z0-9._-]{0,63}"
)
_REL = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]{0,199}")
_PLAIN = re.compile(r"[^\x00-\x1f\x7f<>]+")


class _Bad(Exception):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field, self.message = field, message


def _looks_like_a_key(value: str, *, full: bool = True) -> bool:
    """A value orch's secret scan finds a key in (an API key, a token, a private key; with `full` also a
    credential flag or key=value, as in a balance command). Never reads the stored keys. The `key` field itself
    is checked with full=False: "pass:Agents/Example API key 1" is the agreed form and the line scrub flags it."""
    from orch import secretscan

    if any(rx.search(value) for _, rx in secretscan.PATTERNS):
        return True
    return full and bool(secretscan.find(value, None))


def _inside(base: Path, rel: str) -> Path | None:
    """base/rel when rel is a plain relative path that stays inside base, else None."""
    if not isinstance(rel, str) or not _REL.fullmatch(rel) or ".." in rel.split("/"):
        return None
    p = base / rel
    try:
        p.resolve().relative_to(base.resolve())
    except (ValueError, OSError):
        return None
    return p


def _check_credit(c: object, i: int, base: Path) -> dict:
    """One [[credit]] table as a clean dict; raises _Bad naming the field (never echoing a hidden value)."""
    where = f"credit {i}"
    if not isinstance(c, dict):
        raise _Bad("credit", f"{where} is not a [[credit]] table.")
    name = c.get("name")
    if isinstance(name, str) and _NAME.fullmatch(name) and len(name) <= 32 and not _looks_like_a_key(name):
        where = f"credit {name!r}"
    extra = sorted(set(c) - set(FIELDS))
    if extra:
        shown = "a field" if _looks_like_a_key(extra[0]) else repr(extra[0])
        raise _Bad("credit", f"{where}: {shown} is not a credit field; use {', '.join(FIELDS)}.")
    for f in REQUIRED:
        if f not in c:
            raise _Bad(f, f"{where} has no {f}.")
    for f in FIELDS:
        if f in c and not isinstance(c[f], str):
            raise _Bad(f, f"{where}: {f} must be text in quotes.")
    for f in FIELDS:  # before any message could quote a value
        if f in c and _looks_like_a_key(c[f], full=f != "key"):
            raise _Bad(
                f,
                f"{where}: {f} looks like a key value. Write where the key lives (pass:<vault>/<item> or orch:<name>), never the key.",
            )
    if not (_NAME.fullmatch(name) and len(name) <= 32):
        raise _Bad("name", f"{where}: name is lowercase letters, digits and single dashes, at most 32.")
    for f, size in (("label", LABEL_MAX), ("provider", PROVIDER_MAX)):
        v = c[f].strip()
        if not v or len(v) > size or not _PLAIN.fullmatch(v):
            raise _Bad(f, f"{where}: {f} is plain text of 1 to {size} characters.")
    if not _KEY_REF.fullmatch(c["key"]):
        raise _Bad(
            "key",
            f"{where}: key says where the key lives: pass:<vault>/<item> (Proton Pass) or orch:<name> (orch secret store).",
        )
    if c["unit"] not in UNITS:
        raise _Bad("unit", f"{where}: unit is one of {', '.join(repr(u) for u in UNITS)}.")
    spend = c["spend"]
    if spend != "report":
        if not spend.startswith("log:") or _inside(base, spend[4:]) is None:
            raise _Bad(
                "spend",
                f'{where}: spend is "report" (the skill runs orch usage spent) or "log:<file next to it>".',
            )
    balance = c.get("balance", "")
    if balance and (len(balance) > BALANCE_MAX or not _PLAIN.fullmatch(balance)):
        raise _Bad("balance", f"{where}: balance is one command line of at most {BALANCE_MAX} characters.")
    return {
        "name": name,
        "label": c["label"].strip(),
        "provider": c["provider"].strip(),
        "key": c["key"],
        "unit": c["unit"],
        "spend": spend,
        "balance": balance,
    }


def read_file(path: Path) -> tuple[list[dict], list[dict]]:
    """(credits, problems) of one api-credits.toml. A problem is {"field", "message"}; a file with any problem
    gives no credits (a half-read file would show half the accounts)."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as e:
        return [], [{"field": FILE_KEY, "message": f"{path.name} cannot be read ({e.__class__.__name__})."}]
    if len(raw) > FILE_MAX:
        return [], [{"field": FILE_KEY, "message": f"{path.name} is larger than {FILE_MAX // 1024} KB."}]
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        # the TOML error names the line, not the text: safe to show
        why = str(e).split("(")[-1].rstrip(")") if "line" in str(e) else e.__class__.__name__
        return [], [{"field": FILE_KEY, "message": f"{path.name} is not valid TOML ({why})."}]
    extra = sorted(set(data) - {"credit"})
    if extra:
        shown = "a value" if _looks_like_a_key(extra[0]) else repr(extra[0])
        return [], [
            {
                "field": FILE_KEY,
                "message": f"{path.name}: {shown} is not read; put each credit in a [[credit]] table.",
            }
        ]
    items = data.get("credit")
    if not isinstance(items, list) or not items:
        return [], [{"field": FILE_KEY, "message": f"{path.name} has no [[credit]] table."}]
    if len(items) > CREDITS_MAX:
        return [], [{"field": FILE_KEY, "message": f"{path.name} has more than {CREDITS_MAX} credits."}]
    out, problems, seen = [], [], set()
    for i, c in enumerate(items, 1):
        try:
            got = _check_credit(c, i, path.parent)
        except _Bad as b:
            problems.append({"field": f"{FILE_KEY}.{b.field}", "message": b.message})
            continue
        if got["name"] in seen:
            problems.append(
                {"field": f"{FILE_KEY}.name", "message": f"credit {got['name']!r} is declared twice."}
            )
            continue
        seen.add(got["name"])
        out.append(got)
    return ([] if problems else out), problems


def _declared_in(base: Path, rel: object, owner: str, source: str) -> tuple[list[dict], list[dict]]:
    """Credits of one skill or add-on folder whose declaration names `rel`; problems carry the owner."""
    tag = lambda ps: [{"owner": owner, "source": source, **p} for p in ps]  # noqa: E731
    if not isinstance(rel, str) or not rel.strip():
        return [], tag([{"field": FILE_KEY, "message": f"{FILE_KEY} names no file."}])
    if _looks_like_a_key(rel):  # never repeated below
        return [], tag(
            [
                {
                    "field": FILE_KEY,
                    "message": f'{FILE_KEY} looks like a key value; name the file, like "api-credits.toml".',
                }
            ]
        )
    p = _inside(base, rel.strip())
    if p is None:
        return [], tag(
            [
                {
                    "field": FILE_KEY,
                    "message": f'{FILE_KEY} must name a file inside the folder, like "api-credits.toml".',
                }
            ]
        )
    if not p.is_file():
        return [], tag(
            [{"field": FILE_KEY, "message": f"{FILE_KEY} names {rel.strip()!r}, but there is no such file."}]
        )
    credits, problems = read_file(p)
    rows = [
        {"credit": f"{owner}/{c['name']}", "owner": owner, "source": source, "file": str(p), **c}
        for c in credits
    ]
    return rows, tag(problems)


def from_skill_entry(entry: dict) -> tuple[list[dict], list[dict]]:
    """Credits a skillmeta entry declares (none when its header has no api-credits line)."""
    meta = (entry.get("header") or {}).get("metadata") or {}
    if FILE_KEY not in meta:
        return [], []
    return _declared_in(Path(entry["path"]), meta[FILE_KEY], entry["name"], entry.get("source", "workspace"))


def user_skill_dirs() -> list[Path]:
    """The person's own skill folders outside any workspace (the credit skills live there today)."""
    from orch import inventory  # the tools' own skill folders come from agents/connections.json

    home = Path.home()
    dirs = inventory.harness_skill_dirs(home)
    shared = home / ".agents" / "skills"
    return dirs + ([shared] if shared not in dirs else [])


def _user_entries(seen: set[str]) -> list[dict]:
    from orch import harness, skillmeta

    out = []
    for base in user_skill_dirs():
        if not base.is_dir():
            continue
        for p in sorted(base.iterdir()):
            if p.name in seen or not p.is_dir() or not harness.safe_skill_name(p.name):
                continue
            if not (p / "SKILL.md").is_file():
                continue
            out.append(skillmeta._entry(p.name, p, "user"))
            seen.add(p.name)
    return out


def _addon_manifests(root: Path) -> dict[str, dict]:
    try:
        from orch import addons

        return addons.active_manifests(root)
    except Exception:  # noqa: BLE001 - a broken add-on setup never hides the skills' credits
        return {}


def declared(root: Path, *, user: bool = True) -> dict:
    """Every credit declared here: the workspace's skills (orch's, add-ons', its own, the relay's), the person's
    own skills (`user`) and the active add-ons' manifests. {"credits": [...], "problems": [...]}; a credit's
    full name ("credit") is <skill or add-on>/<name>, and the first declaration of a full name wins."""
    from orch import skillmeta

    entries = skillmeta.list_skills(Path(root))
    if user:
        entries += _user_entries({e["name"] for e in entries})
    credits, problems = [], []
    for e in entries:
        c, p = from_skill_entry(e)
        credits += c
        problems += p
    for name, m in sorted(_addon_manifests(Path(root)).items()):
        if FILE_KEY in m:
            c, p = _declared_in(Path(m["dir"]), m[FILE_KEY], name, f"addon:{name}")
            credits += c
            problems += p
    out, seen = [], set()
    for c in credits:
        if c["credit"] not in seen:
            seen.add(c["credit"])
            out.append(c)
    return {"credits": out, "problems": problems}


def check(entries: list[dict], root: Path | None = None) -> list[dict]:
    """skillmeta.CHECKS: a wrong credit declaration in a skill is a problem of `orch skill check`."""
    from orch import skillmeta

    out = []
    for e in entries:
        for p in from_skill_entry(e)[1]:
            out.append(skillmeta._finding(e["name"], "error", p["field"], p["message"]))
    return out

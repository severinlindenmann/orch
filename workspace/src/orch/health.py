"""Does everything a helper needs here still work? One generic check, a small recipe per thing.

A recipe says which command to run and how to read its answer:
  - a helper tool (built-in adapter with a `login` part, agents/login.json): the tool's own status
    command, which prints one JSON object. orch keeps exactly two facts from it: works or not, and the
    end time (re-written as a UTC time). The helpers it stops are the live runs on that tool.
  - a workspace recipe, written by a person on this computer into the guarded orch home (key folder record
    `checks`, keystore.RECORDS): never in the project folder, so a cloned project cannot bring commands that
    run by themselves:
    {"checks": {name: {"label", "command", "works"?, "ends"?, "kind"?}}}. Without "works" the exit code alone
    answers: 0 = works, anything else = needs renewing. "kind" says what it is for the person: login (the
    default), connection or key; a helper tool is always a login.

States: works | soon (runs out within WARN_DAYS) | renew (stopped working, a person renews it) |
unreachable (the command could not run or gave no readable answer). Nothing else the command prints is
kept, shown or logged, so no key and no account detail can leave through here (R5.2). The last result
is kept in .orch/run/health.json for the dashboard and the phone; it holds the same few facts.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orch import adapters, net, runs, runs_live, tickets

WARN_DAYS = 3  # the warning starts this many days before the end
TIMEOUT = 10  # seconds for one status command
STATES = ("works", "soon", "renew", "unreachable")
_MAX = 65536  # status answers are small; a longer one is not read
_NAME = re.compile(r"[a-z][a-z0-9-]{0,31}")
_BINARY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_ARG = re.compile(r"-{0,2}[A-Za-z0-9][A-Za-z0-9._:=/@-]{0,63}")
# a recipe names a tool's own status command, never a shell or a script runner
_NOT_A_TOOL = frozenset(
    "sh bash zsh fish dash ksh csh tcsh ash busybox pwsh powershell cmd env sudo doas su xargs nohup nice "
    "timeout script time watch exec eval command builtin start open python py pypy node deno bun perl ruby "
    "php lua tclsh osascript wscript cscript awk gawk sed find make cmake git npm npx pnpm yarn uv uvx pip "
    "pipx cargo go java dotnet docker podman ssh scp curl wget rm mv cp".split()
)
_FIELD = re.compile(r"[A-Za-z_]{1,32}")
_LABEL = re.compile(r"[^\x00-\x1f\x7f]{1,40}")
KINDS = ("login", "connection", "key")


def _end(value) -> str | None:
    """The end time as 'YYYY-MM-DDTHH:MM:SSZ', or None. Only a real time passes: the tool's text is parsed
    and written anew, never copied."""
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float):
            t = datetime.fromtimestamp(value / 1000 if value > 1e11 else value, UTC)
        elif isinstance(value, str) and len(value) <= 40:
            t = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=UTC)
        else:
            return None
        return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OverflowError, OSError):
        return None


# ------------------------------------------------------------------------------------------------ recipes


def _runner(binary: str) -> bool:
    """A shell, script runner or general tool, also with a version or .exe on its name (python3.12, bash5)."""
    base = binary.lower().removesuffix(".exe").rstrip("0123456789.-_")
    return base in _NOT_A_TOOL or binary.lower().removesuffix(".exe") in _NOT_A_TOOL


def _recipe(name, doc) -> dict | None:
    """A checked workspace recipe, or None when it is not one (a bad entry is left out, never run)."""
    if not (isinstance(name, str) and _NAME.fullmatch(name) and isinstance(doc, dict)):
        return None
    cmd, label = doc.get("command"), doc.get("label", name)
    if not (isinstance(cmd, list) and 1 <= len(cmd) <= 9 and all(isinstance(a, str) for a in cmd)):
        return None
    if not (_BINARY.fullmatch(cmd[0]) and all(_ARG.fullmatch(a) for a in cmd[1:])):
        return None
    if _runner(cmd[0]):
        return None
    if not (isinstance(label, str) and _LABEL.fullmatch(label)):
        return None
    works, ends = doc.get("works"), doc.get("ends")
    for f in (works, ends):
        if f is not None and not (isinstance(f, str) and _FIELD.fullmatch(f)):
            return None
    if ends and not works:
        return None
    kind = doc.get("kind", "login")
    if kind not in KINDS:
        return None
    return {
        "name": name,
        "label": label.strip(),
        "command": cmd,
        "works": works,
        "ends": ends,
        "kind": kind,
        "helper": None,
    }


def workspace_recipes(root: Path) -> list[dict]:
    """The person's own recipes, from the guarded orch home only (never a file of the project)."""
    from orch import keystore

    try:
        doc = keystore.record_read(Path(root), "checks") or {}
    except Exception:  # noqa: BLE001  a damaged or unsafe record runs nothing
        return []
    items = doc.get("checks") if isinstance(doc, dict) else None
    if not isinstance(items, dict):
        return []
    return [r for r in (_recipe(n, d) for n, d in items.items()) if r]


def helper_recipes() -> list[dict]:
    """One recipe per built-in helper tool that can tell about its login (adapter `login` part)."""
    out = []
    for name in adapters.builtin_names():
        a = adapters.load(name)
        spec, binary = a.get("login"), (a.get("detect") or {}).get("binary")
        if spec and binary:
            out.append(
                {
                    "name": name,
                    "label": a["label"],
                    "command": [binary, *spec["status"]],
                    "works": spec["logged_in"],
                    "ends": spec.get("ends"),
                    "kind": "login",
                    "helper": name,
                }
            )
    return out


def recipes(root: Path) -> list[dict]:
    """Helper tools first, then the workspace's own; a workspace name never replaces a built-in one."""
    own = helper_recipes()
    taken = {r["name"] for r in own}
    return own + [r for r in workspace_recipes(root) if r["name"] not in taken]


# ------------------------------------------------------------------------------------------------ one check


def ask(binary: str, recipe: dict) -> tuple[bool | None, str | None]:
    """(works, end time) from the recipe's command; (None, None) when it gave no readable answer."""
    json_answer = bool(recipe.get("works"))
    # an exit-code recipe never reads what the command prints; a JSON one keeps only stdout, parsed below
    out = subprocess.PIPE if json_answer else subprocess.DEVNULL
    try:
        r = subprocess.run(
            [binary, *recipe["command"][1:]],
            stdout=out,
            stderr=subprocess.DEVNULL,
            text=True,
            errors="replace",
            timeout=TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None, None
    if not json_answer:
        return r.returncode == 0, None
    try:
        doc = json.loads((r.stdout or "")[:_MAX])
    except ValueError:
        return None, None
    if not isinstance(doc, dict):
        return None, None
    works = doc.get(recipe["works"])
    return (works if isinstance(works, bool) else None), _end(doc.get(recipe.get("ends") or ""))


def state(works: bool | None, ends_at: str | None, now: datetime | None = None) -> str:
    """works | soon | renew | unreachable."""
    now = now or datetime.now(UTC)
    if works is False:
        return "renew"
    if ends_at:
        end = datetime.strptime(ends_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if end <= now:
            return "renew"
        if end - now <= timedelta(days=WARN_DAYS):
            return "soon"
    return "unreachable" if works is None else "works"


def stops(root: Path, adapter: str | None) -> list[dict]:
    """Tickets a helper works on right now with this tool: [{id, key, title}]. Only a helper tool's own runs
    are known to need it; a workspace recipe names none."""
    if not adapter:
        return []
    out = []
    for rec in runs_live.records(root):
        tid = rec.get("ticket")
        try:
            if runs.state(rec) != "alive" or tickets.is_general(root, tid):
                continue
            if adapters.load(str(rec.get("agent") or ""), root)["adapter"] != adapter:
                continue
            t = tickets.load(root, tid)
        except Exception:  # noqa: BLE001  a broken record or ticket never hides the warning
            continue
        out.append({"id": tid, "key": t.get("key") or tid, "title": t.get("title") or ""})
    return out


# ------------------------------------------------------------------------------------------------ all of them


def overview(root: Path, now: datetime | None = None) -> list[dict]:
    """One row per thing set here: {name, label, kind, state, ends_at, helper, chosen, stops}. A helper tool
    that is not installed is not set here and is left out; a workspace recipe whose command is missing
    is unreachable."""
    try:
        chosen = adapters.load(adapters.chosen(root), root)["adapter"]
    except Exception:  # noqa: BLE001  no agent chosen or found: nothing is "the helper here"
        chosen = None
    rows = []
    for r in recipes(root):
        binary = shutil.which(r["command"][0])
        if not binary and r["helper"]:
            continue
        works, ends_at = ask(binary, r) if binary else (None, None)
        rows.append(
            {
                "name": r["name"],
                "label": r["label"],
                "kind": r["kind"],
                "state": state(works, ends_at, now),
                "ends_at": ends_at,
                "helper": r["helper"],
                "chosen": bool(r["helper"]) and r["helper"] == chosen,
                "stops": stops(root, r["helper"]),
            }
        )
    return rows


def _path(root: Path) -> Path:
    return runs.run_dir(Path(root)) / "health.json"


def save(root: Path, rows: list[dict], now: datetime | None = None) -> dict:
    doc = {
        "schema": "orch.health/1",
        "checked_at": (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": rows,
    }
    net.write_json(_path(root), doc)
    return doc


def last(root: Path) -> dict | None:
    """The last saved result, or None (never checked, or the file is not one)."""
    doc = net.read_json(_path(root), None)
    if not (
        isinstance(doc, dict) and doc.get("schema") == "orch.health/1" and isinstance(doc.get("items"), list)
    ):
        return None
    return doc


def check(root: Path, now: datetime | None = None) -> dict:
    """Run every check now and keep the result."""
    return save(root, overview(root, now), now)


# ------------------------------------------------------------------------------------------------ by itself

CHECK_EVERY = 15 * 60  # seconds a result stays fresh
ASK_EVERY = 60  # seconds between two background checks


def due(root: Path, now: float | None = None) -> bool:
    """True when there is no result yet or the last one is older than CHECK_EVERY."""
    doc = last(root)
    if not doc:
        return True
    try:
        at = datetime.strptime(doc["checked_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    except (KeyError, TypeError, ValueError):
        return True
    return (now if now is not None else time.time()) - at >= CHECK_EVERY


def soon(root: Path, *, force: bool = False, now: float | None = None) -> bool:
    """Start one background `orch logins` when the result is stale (or force: a helper just failed for lack
    of a login), at most once per ASK_EVERY. Never waits, never raises. True when one was started."""
    try:
        if os.environ.get("ORCH_NO_HEALTH_CHECK"):  # tests: never the real tools
            return False
        now = now if now is not None else time.time()
        if not (force or due(root, now)):
            return False
        mark = runs.run_dir(Path(root)) / "health-asked"
        try:
            if now - mark.stat().st_mtime < ASK_EVERY:
                return False
        except OSError:
            pass
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.touch()
        os.utime(mark, (now, now))
        from orch import procs

        subprocess.Popen(
            procs.orch_python_argv("logins", "--json"),
            cwd=Path(os.path.realpath(tempfile.gettempdir())),
            env={**os.environ, "ORCH_ROOT": str(root)},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name != "nt",
        )
        return True
    except Exception:  # noqa: BLE001  a check that cannot start never holds up a helper or a page
        return False

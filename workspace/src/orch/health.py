"""Does everything a helper needs here still work? One generic check, a small recipe per thing.

A recipe says which command to run and how to read its answer:
  - a helper tool (built-in adapter with a `login` part, agents/login.json): the tool's own status
    command, which prints one JSON object. orch keeps exactly two facts from it: works or not, and the
    end time (re-written as a UTC time); without `logged_in` the exit code alone answers. The
    helpers it stops are the live runs on that tool.
  - a known tool (known_checks.json: GitHub, Databricks, ...): the same entry as a workspace recipe, used
    only when the tool is installed and set up on this computer.
  - an outside connection set in this workspace (inventory.connections): asked through the chosen helper's
    own list command (adapter `connection_check`); only each connection's state word is read.
  - a workspace recipe, written by a person on this computer into the guarded orch home (key folder record
    `checks`, keystore.RECORDS): never in the project folder, so a cloned project cannot bring commands that
    run by themselves:
    {"checks": {name: {"label", "command", "works"?, "ends"?, "kind"?, "key"?, "how"?}}} (`orch logins add`).
    Without "works" the exit code alone answers: 0 = works, anything else = needs renewing; "works" and
    "ends" may be a short path ('profiles.*.valid': every item must be true).
    "kind" says what it is for the person:
    login (the default), connection or key; a helper tool is always a login. "key" names the key (keystore)
    this check tests: when it fails, the person replaces that key from the warning (renew.replace_key).
    "how" is the one plain step the person takes to renew when orch cannot start it (shown on the warning).

States: works | soon (runs out within WARN_DAYS) | renew (stopped working, a person renews it) |
unreachable (the command could not run or gave no readable answer). Nothing else the command prints is
kept, shown or logged, so no key and no account detail can leave through here (R5.2). The last result
is kept in the guarded orch home (key folder, health.json) for the dashboard and the phone, never in .orch/run
where a helper could write it; it holds the same few facts.
"""

from __future__ import annotations

import contextlib
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
from orch.errors import Refused

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
# a field of the JSON answer: a name, or a short dotted path; '*' walks every item of a list (all must work)
_FIELD = re.compile(r"[A-Za-z_]{1,32}(\.(\*|[A-Za-z_]{1,32})){0,3}")
_HOW = re.compile(r"[^\x00-\x1f\x7f<>]{1,160}")  # what the person does when orch cannot renew it
_LABEL = re.compile(r"[^\x00-\x1f\x7f]{1,40}")
KINDS = ("login", "connection", "key")
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")  # keystore.NAME_RE


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
    works, ends, key = doc.get("works"), doc.get("ends"), doc.get("key")
    if key is not None and not (isinstance(key, str) and _KEY.fullmatch(key)):
        return None
    for f in (works, ends):
        if f is not None and not (isinstance(f, str) and _FIELD.fullmatch(f)):
            return None
    if ends and not works:
        return None
    kind, how = doc.get("kind", "login"), doc.get("how")
    if kind not in KINDS:
        return None
    if how is not None and not (isinstance(how, str) and _HOW.fullmatch(how)):
        return None
    return {
        "name": name,
        "label": label.strip(),
        "command": cmd,
        "works": works,
        "ends": ends,
        "kind": kind,
        "helper": None,
        "key": key,
        "how": how.strip() if how else None,
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


BAD_CHECK = (
    "That check cannot be kept: give a short name (small letters, digits, dash), a label of at most 40 "
    "characters and the tool's own status command with plain arguments (no shell, script or general tool)."
)


def add_recipe(root: Path, name: str, doc: dict) -> dict:
    """Keep one workspace recipe (the person's own check, `orch logins add`) in the guarded orch home and
    return it. Refused when it is not a recipe or names a built-in check."""
    from orch import keystore
    from orch.errors import Refused

    doc = {k: v for k, v in doc.items() if v not in (None, "")}
    r = _recipe(name, doc)
    if not r:
        raise Refused(BAD_CHECK)
    if name in {x["name"] for x in helper_recipes()} or name in _known_names():
        raise Refused(f"orch already checks {name} by itself; pick another name.")
    have = keystore.record_read(Path(root), "checks") or {}
    items = have.get("checks") if isinstance(have.get("checks"), dict) else {}
    items[name] = doc
    keystore.record_write(Path(root), "checks", {**have, "checks": items})
    return r


def remove_recipe(root: Path, name: str) -> bool:
    """Forget one workspace recipe; False when there was none by that name."""
    from orch import keystore

    have = keystore.record_read(Path(root), "checks") or {}
    items = have.get("checks") if isinstance(have.get("checks"), dict) else {}
    if name not in items:
        return False
    del items[name]
    keystore.record_write(Path(root), "checks", {**have, "checks": items})
    return True


def _known_names() -> set[str]:
    try:
        doc = json.loads(Path(__file__).with_name("known_checks.json").read_text(encoding="utf-8"))
        return set(doc.get("checks") or {})
    except (OSError, ValueError):
        return set()


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
                    "works": spec.get("logged_in"),  # absent: the exit code answers (0 = works)
                    "ends": spec.get("ends"),
                    "kind": "login",
                    "helper": name,
                    "renew": bool(spec.get("renew") and spec.get("links")),
                    "how": spec.get("how"),
                }
            )
    return out


def _home() -> Path:
    return Path(os.environ.get("HOME") or os.environ.get("USERPROFILE") or Path.home())


def _set_here(doc: dict) -> bool:
    """A known tool counts as set on this computer when one of its environment names is set or one of its
    settings files exists ({home}; {config} = XDG_CONFIG_HOME or ~/.config; {appdata} = %APPDATA%)."""
    home = _home()
    places = {
        "home": str(home),
        "config": os.environ.get("XDG_CONFIG_HOME") or str(home / ".config"),
        "appdata": os.environ.get("APPDATA") or "",
    }
    if any(os.environ.get(env) for env in doc.get("env_if") or ()):
        return True
    for f in doc.get("set_if") or ():
        where = Path(f.format(**places))
        if (
            where.is_absolute() and where.is_file()
        ):  # an unset place ({appdata} off Windows) is never relative
            return True
    return False


def known_recipes() -> list[dict]:
    """Other tools a helper often needs (known_checks.json: GitHub, Databricks, ...), each only when it
    is installed and set up on this computer, so a tool nobody uses here never warns."""
    try:
        doc = json.loads(Path(__file__).with_name("known_checks.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for name, d in (doc.get("checks") or {}).items():
        r = _recipe(name, d)
        if r and shutil.which(r["command"][0]) and _set_here(d):
            out.append(r)
    return out


def recipes(root: Path) -> list[dict]:
    """Helper tools first, then the known tools, then the workspace's own; a later name never replaces an
    earlier one."""
    out, taken = [], set()
    for r in helper_recipes() + known_recipes() + workspace_recipes(root):
        if r["name"] not in taken:
            taken.add(r["name"])
            out.append(r)
    return out


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
    found = _values(doc, recipe["works"])
    works = None
    if found and all(isinstance(v, bool) for v in found):
        works = all(found)
    ends = [e for e in (_end(v) for v in _values(doc, recipe.get("ends") or "")) if e]
    return works, (min(ends) if ends else None)


def _values(doc, path: str) -> list:
    """Every value at a field path ('a', 'a.b', 'items.*.valid'); [] when the path leads nowhere."""
    if not path:
        return []
    found = [doc]
    for part in path.split("."):
        nxt = []
        for v in found:
            if part == "*" and isinstance(v, list):
                nxt.extend(v)
            elif part != "*" and isinstance(v, dict) and part in v:
                nxt.append(v[part])
        found = nxt
    return found[:64]


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
    """One row per thing set here: {name, label, kind, state, ends_at, helper, chosen, stops, renew, key}. A
    helper tool that is not installed is not set here and is left out; a workspace recipe whose command is
    missing is unreachable."""
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
                "renew": bool(r.get("renew")),  # orch can start the tool's own sign-in (ORCH-46)
                "key": r.get("key"),  # the key a person replaces when this check fails (name only)
                "how": r.get("how"),  # what the person does when orch cannot renew it (ORCH-48)
            }
        )
    return rows + connection_rows(root, chosen, now)


# ------------------------------------------------------------------------------------------------ connections

CONN_TIMEOUT = 60  # seconds: the helper starts every connection once to see whether it answers
# the helper's own word for each state of a connection (its list command prints one line per connection)
_CONN_SAYS = (("needs authentication", False), ("failed", False), ("connected", True))


def _conn_name(name: str, taken: set[str]) -> str:
    base = "connection-" + (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:20] or "x")
    out, n = base, 2
    while out in taken:
        out, n = f"{base}-{n}", n + 1
    return out


def connection_rows(root: Path, adapter: str | None, now: datetime | None = None) -> list[dict]:
    """One row per outside connection set in this workspace (inventory.connections: the workspace's own,
    the admin's and the helper's settings), asked through the chosen helper's own list command (adapter
    `connection_check`, agents/connections.json). Only each connection's state word is read; what it points
    to and anything else the helper prints is dropped."""
    if not adapter:
        return []
    try:
        spec = adapters.load(adapter).get("connection_check") or {}
        binary = shutil.which((adapters.load(adapter).get("detect") or {}).get("binary") or "")
        from orch import inventory

        items, _ = inventory.connections(Path(root))
    except Exception:  # noqa: BLE001  no inventory, no check: nothing to show
        return []
    names = sorted({i["name"] for i in items if not i.get("shadowed")})
    if not (names and binary and spec.get("list")):
        return []
    says = _conn_states(root, binary, spec["list"], names)
    rows, taken = [], set()
    for name in names:
        word = says.get(name)
        works = None if word is None else dict(_CONN_SAYS)[word]
        how = spec.get("sign_in", "").format(name=name) if word == "needs authentication" else None
        row_name = _conn_name(name, taken)
        taken.add(row_name)
        rows.append(
            {
                "name": row_name,
                "label": name[:40],
                "kind": "connection",
                "state": state(works, None, now),
                "ends_at": None,
                "helper": None,
                "chosen": False,
                "stops": [],
                "renew": False,
                "key": None,
                "how": how or None,
            }
        )
    return rows


def _conn_states(root: Path, binary: str, argv: list[str], names: list[str]) -> dict[str, str]:
    """{connection name: state word} from lines like '<name>: <where> - <mark> <state>'."""
    try:
        r = subprocess.run(
            [binary, *argv],
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            errors="replace",
            timeout=CONN_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    wanted, out = set(names), {}
    for line in (r.stdout or "")[: _MAX * 4].splitlines():
        name, sep, rest = line.partition(": ")
        if not sep or name not in wanted or " - " not in rest:
            continue
        tail = rest.rsplit(" - ", 1)[1].lower()
        word = next((w for w, _ in _CONN_SAYS if w in tail), None)
        if word:
            out[name] = word
    return out


def _path(root: Path) -> Path:
    """In the guarded orch home, never .orch/run: the dashboard and the phone show these rows (a name, a
    state, a Renew or Replace button), so a helper must not be able to write them (security review, ORCH-46).
    Refused when this workspace has no guarded home."""
    from orch import home as orch_home

    return orch_home.key_dir(Path(root)) / "health.json"


def save(root: Path, rows: list[dict], now: datetime | None = None) -> dict:
    doc = {
        "schema": "orch.health/1",
        "checked_at": (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": rows,
    }
    try:
        path = _path(root)
    except Refused:  # no guarded home here: nothing is kept, so nothing is shown
        return doc
    net.write_json(path, doc)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
    with contextlib.suppress(OSError):  # the place before ORCH-46's review; never read again
        (runs.run_dir(Path(root)) / "health.json").unlink()
    return doc


def last(root: Path) -> dict | None:
    """The last saved result, or None (never checked, no guarded home, or the file is not one)."""
    try:
        doc = net.read_json(_path(root), None)
    except Refused:
        return None
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
        mark = _path(root).with_name("health-asked")  # guarded too: a helper cannot hold the checks back
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

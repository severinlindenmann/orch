"""Agent tool adapters: the only code (with agents/) that knows tool names and how a tool is run.

agents/ holds the built-in adapters (contracts/agent-adapter.schema.json). A user entry in
.orch/config.toml ([agents.<name>] with adapter, command, interactive) picks one of them; the generic
adapter turns any command line into an agent. Callers ask for argv and capabilities, never for a name.
"""

from __future__ import annotations

import copy
import functools
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Mapping
from pathlib import Path

from orch import agentsdata, config
from orch.errors import Refused

SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
_SESSION_ARG = re.compile(r"^(\{session\}|--[a-z][a-z0-9-]*=\{session\})$")
_PLACEHOLDER = re.compile(r"\{(prompt|session|new_session|orch_hooks_file|allow)\}")
_VERSION = re.compile(r"\d+(?:\.\d+)+\S*")


# ---------------------------------------------------------------- the registry


def argv_errors(doc: Mapping) -> list[str]:
    """Order rules JSON Schema cannot express: {prompt} is a whole item after '--', {session} a whole item
    or --flag={session} (same rules as contracts/validate.py)."""
    out = []
    for name, a in (doc.get("adapters") or {}).items():
        for mode in ("oneshot", "live"):
            for key, argv in (a.get(mode) or {}).items():
                if not isinstance(argv, list):
                    continue
                for i, item in enumerate(argv):
                    where = f"{name}.{mode}.{key}[{i}]"
                    if "{prompt}" in item and (item != "{prompt}" or "--" not in argv[:i]):
                        out.append(f"{where}: {{prompt}} must be a whole item after '--'")
                    if "{session}" in item and not _SESSION_ARG.match(item):
                        out.append(f"{where}: {{session}} must be a whole item or --flag={{session}}")
    return out


@functools.cache
def _registry() -> dict:
    doc = agentsdata.load()
    errs = argv_errors(doc)
    if errs:
        raise RuntimeError("agents/: " + "; ".join(errs))
    return doc["adapters"]


_warned: set[str] = set()


def builtin_names() -> list[str]:
    return list(_registry())


def load(name: str, root: Path | None = None) -> dict:
    """The adapter for an agent name: the built-in one, or the one a [agents.<name>] entry picks, with the
    user's command and interactive command added."""
    entry = config.agent_entries(root).get(name) if root is not None else None
    if entry and name in _registry():
        if name not in _warned:
            _warned.add(name)
            print(
                f"This folder's settings define an agent called '{name}'; pick another name. "
                "Using the built-in one.",
                file=sys.stderr,
            )
        entry = None
    base = entry["adapter"] if entry else name
    reg = _registry()
    if base not in reg:
        raise Refused(f"No agent called '{name}'. See what is available: orch agents")
    a = copy.deepcopy(reg[base])
    a["name"], a["adapter"] = name, base
    a["label"] = a["label"].replace("{name}", name)
    a["command"] = (entry or {}).get("command")
    a["interactive"] = (entry or {}).get("interactive")
    if (entry or {}).get("prompt") in ("arg", "stdin") and base == "generic":
        a["prompt_via"] = entry["prompt"]
    a["from_settings"] = bool(entry and (entry.get("command") or entry.get("interactive")))
    if base == "generic":
        a["capabilities"]["interactive_tmux"] = bool(a["interactive"])
    return a


def caps(name: str, root: Path | None = None) -> dict:
    return load(name, root)["capabilities"]


def chosen(root: Path) -> str:
    """The agent that does the work here: [workspace] agent, else the first agent found on this machine."""
    name = config.agent_name(root)
    if name:
        load(name, root)
        return name
    for row in detect():
        if row["found"]:
            return row["name"]
    raise Refused("No agent found; set one later: orch config set workspace.agent <name>")


# ---------------------------------------------------------------- argv


def _split(cmd: str) -> list[str]:
    if os.name == "nt":
        return [
            t[1:-1] if len(t) > 1 and t[0] == t[-1] and t[0] in "\"'" else t
            for t in shlex.split(cmd, posix=False)
        ]
    return shlex.split(cmd)


def allow_patterns(patterns) -> list[str]:
    out = []
    for p in patterns or []:
        if not isinstance(p, str) or not p.strip() or p.startswith("-") or any(c in p for c in "\r\n\0,"):
            raise Refused(f"'{p}' is not a tool pattern orch can pass on.")
        out.append(p.strip())
    return out


def render(name: str, kind: str, mode: str, v: Mapping, root: Path | None = None) -> list[str] | None:
    """The argv for kind fresh|resume in mode oneshot|live, or None when this agent cannot do it.

    v: prompt, session, new_session, orch_hooks_file, allow (list of tool patterns), stream (bool),
    permissions (ask|auto|full; default: the workspace's setting).
    A oneshot argv without {prompt} gets the prompt appended (prompt_via arg); with stdin the caller sends it.
    """
    a = load(name, root)
    sect = a.get(mode)
    if not sect:
        return None
    if mode == "live" and not a["capabilities"]["interactive_tmux"]:
        return None
    if kind == "resume" and not a["capabilities"]["resume"]:
        return None
    tpl = sect.get(kind)
    if tpl is None:
        return None
    user = isinstance(tpl, str)
    if user:
        cmd = a["command"] if tpl == "{command}" else a["interactive"]
        if not cmd:
            raise Refused(f"'{name}' has no command yet. Add it: orch config agent add {name} --command ...")
        items = _split(cmd)
    else:
        items = list(tpl)
    has_prompt = any("{prompt}" in i for i in items)
    sid = v.get("session")
    if sid is not None and not SESSION_RE.match(str(sid)):
        raise Refused("That session id cannot be passed to an agent.")

    def fill(item: str) -> str:
        def sub(m):
            key = m.group(1)
            if user and key != "prompt":
                return m.group(0)  # the user's own text is theirs
            val = v.get(key)
            if val is None:
                raise Refused(f"orch cannot start '{name}' this way: {key} is missing.")
            return str(val)

        return _PLACEHOLDER.sub(sub, item)

    out = [fill(i) for i in items]
    extra: list[str] = permission_args(name, root, v.get("permissions"), v.get("person"))
    if mode == "oneshot":
        if v.get("stream") and sect.get("stream_args"):
            extra += sect["stream_args"]
        pats = allow_patterns(v.get("allow"))
        if pats and a["capabilities"]["permission_retry"] and sect.get("allow_args"):
            extra += [x.replace("{allow}", ",".join(pats)) for x in sect["allow_args"]]
    if extra:
        at = out.index("--") if "--" in out else len(out)
        out[at:at] = extra
    if mode == "oneshot" and not has_prompt and a["prompt_via"] == "arg" and v.get("prompt") is not None:
        if "--" not in out:
            out.append("--")
        out.append(str(v["prompt"]))
    return out


@functools.cache
def _help_text(binary: str) -> str:
    try:
        r = subprocess.run(
            [binary, "--help"], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (r.stdout or "") + (r.stderr or "")


def permission_args(
    name: str, root: Path | None = None, mode: str | None = None, person: Mapping | None = None
) -> list[str]:
    """The tool's flags for the workspace's permission mode (ask | auto | full), from the adapter's
    `permissions`. An agent without that data (a generic command) gets none: it ignores the mode.
    Codex maps every mode to workspace-write + approval never (exec cannot ask): ask/auto/full never widen it
    beyond that. orch only narrows: a personal config (CODEX_HOME or ~/.codex config.toml, active profile)
    that sets read-only, or cannot be read safely, gets no flags; a personal approval_policy other than
    never is kept. System/managed config and a project .codex/config.toml are not read: codex applies
    them itself.
    person: the result of person_state (read once per start); read here when left out.
    An entry may depend on the installed tool: `if_help_has` (its --help text), else `else`."""
    a = load(name, root)
    table = a.get("permissions")
    if not table:
        return []
    entry = table.get(mode or config.permissions(root))
    if entry is None:
        return []
    if isinstance(entry, list):
        return list(entry)
    st = person if person is not None else person_state(entry.get("unless_config"))
    if st["strict"]:
        return []  # never lift a stricter personal setting
    if "if_help_has" in entry:
        binary = (a.get("detect") or {}).get("binary")
        path = shutil.which(binary) if binary else None
        if not (path and entry["if_help_has"] in _help_text(path)):
            return list(entry.get("else") or [])
    return list(entry["args"]) + ([] if st["approval"] else list(entry.get("approval_args") or []))


_MAX_CONFIG = 1 << 20


def person_state(rule) -> dict:
    """What the person's own tool config says, read once: {strict, approval}. strict = it sets rule key to
    rule value (read-only), or the file cannot be trusted (fail closed: not a regular file, over 1 MiB,
    unreadable or malformed). Only a missing file means "not set". approval = it sets approval_key to
    anything but approval_value (that setting is kept, not overridden)."""
    st = {"strict": False, "approval": False}
    if not rule:
        return st
    closed = {"strict": True, "approval": True}
    home, file = str(rule["home"]), str(rule["file"])
    if any(Path(x).is_absolute() or ".." in Path(x).parts for x in (home, file)):
        return closed
    base = Path(os.environ.get(rule.get("home_env") or "") or Path.home() / home)
    path = base / file
    try:
        info = path.stat()
    except FileNotFoundError:
        return st
    except OSError:
        return closed
    if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_CONFIG:
        return closed
    try:
        with open(path, "rb") as f:
            doc = tomllib.loads(f.read(_MAX_CONFIG + 1).decode("utf-8"))
    except (OSError, ValueError):
        return closed
    tables = [doc]
    prof = doc.get(rule.get("profile_key") or "")
    profiles = doc.get(rule.get("profiles") or "")
    sub = profiles.get(prof) if isinstance(prof, str) and isinstance(profiles, dict) else None
    if isinstance(sub, dict):
        tables.insert(0, sub)  # the profile wins over the top level
    for t in tables:
        if rule["key"] in t:
            st["strict"] = t[rule["key"]] == rule["value"]
            break
    ak = rule.get("approval_key")
    for t in tables:
        if ak and ak in t:
            st["approval"] = t[ak] != rule.get("approval_value")
            break
    return st


def permission_note(
    name: str, root: Path | None = None, mode: str | None = None, person: Mapping | None = None
):
    """One line for the run start when the person's own setting keeps the tool stricter than orch's mode."""
    table = load(name, root).get("permissions") or {}
    entry = table.get(mode or config.permissions(root))
    if not (isinstance(entry, dict) and entry.get("say")):
        return None
    st = person if person is not None else person_state(entry.get("unless_config"))
    return entry["say"] if st["strict"] else None


def person_for(name: str, root: Path | None = None, mode: str | None = None) -> dict | None:
    """person_state for this agent and mode (None when the adapter has no such rule): read once per start."""
    entry = (load(name, root).get("permissions") or {}).get(mode or config.permissions(root))
    return person_state(entry.get("unless_config")) if isinstance(entry, dict) else None


def _inside(inner: Path, outer: Path) -> bool:
    """inner is outer or below it (same file, so case-insensitive filesystems and links cannot hide it)."""
    for p in (inner, *inner.parents):
        try:
            if os.path.samefile(p, outer):
                return True
        except OSError:
            continue
    return False


def check_start_folder(name: str, root: Path, person: Mapping | None = None) -> None:
    """A start whose flags include workspace-write (code, not data: no adapter can drop it) is refused when
    ORCH_HOME is inside the start folder or a temporary folder the sandbox may write: the agent could then
    write permissions.json, add-ons and the human-choice markers. Fails closed when ORCH_HOME is unknown."""
    if not any("workspace-write" in x for x in permission_args(name, root, None, person)):
        return
    from orch import addons

    label = load(name, root)["label"]
    try:
        h = addons.home(root).resolve()
    except Refused:
        raise Refused(f"orch cannot tell where its own folder is, so {label} was not started.") from None
    r = root.resolve()
    if _inside(h, r):
        raise Refused(
            f"{label} could write orch's own settings if it started here "
            "(orch's folder is inside this one). Start it from a smaller folder. Nothing was started."
        )
    temps = {Path(tempfile.gettempdir()), Path("/tmp")} if os.name != "nt" else {Path(tempfile.gettempdir())}
    if any(t.exists() and _inside(h, t.resolve()) for t in temps):
        raise Refused(
            f"{label} could write orch's own settings (orch's folder is in a temporary folder). "
            "Move it to your home folder. Nothing was started."
        )


def permission_line(root: Path) -> str:
    """One plain line saying what agents may do without asking here."""
    mode = config.permissions(root)
    words = {
        "ask": "agents ask before editing files or running commands",
        "auto": "agents work on their own and the tool checks risky steps",
        "full": "agents never ask, even for risky steps",
    }
    return f"Permissions {mode}: {words[mode]} (change: orch config set workspace.permissions ask|auto|full)"


def command_notice(name: str, mode: str = "oneshot", root: Path | None = None) -> str | None:
    """The one-time line for a command that comes from this folder's settings: names the command that will
    run. None for built-in adapters, or when this machine has seen that command before."""
    a = load(name, root)
    cmd = a["interactive"] if mode == "live" else a["command"]
    if not a["from_settings"] or not cmd or a["adapter"] != "generic":
        return None
    return config.first_use_notice(cmd)


def prompt_via_stdin(name: str, root: Path | None = None) -> bool:
    return load(name, root)["prompt_via"] == "stdin"


def permission_retry(name: str, root: Path | None = None) -> bool:
    return bool(load(name, root)["capabilities"]["permission_retry"])


def hooks_doc(name: str, run_id: str, root: Path | None = None) -> dict | None:
    """The tool's hook settings for one live run (for .orch/run/hooks-<run>.json)."""
    hooks = load(name, root).get("hooks")
    if not hooks:
        return None
    return {
        "hooks": {
            event: [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": cmd.replace("orch run event", f"orch run event --run {run_id}", 1),
                        }
                    ]
                }
            ]
            for event, cmd in hooks.items()
        }
    }


def trust_folder(name: str, root: Path, environ: Mapping[str, str] | None = None) -> str:
    """Before a live start: tell the tool this folder is trusted, when its adapter declares how (live.trust).
    Returns "set", "already", "none" (nothing declared) or "skipped" (file missing, unreadable or changing).

    Only the one key is set. The file belongs to the tool, which may write it at the same moment: read it,
    merge, re-read just before an atomic replace and give up (never clobber) when it changed meanwhile."""
    t = ((load(name, root).get("live") or {}).get("trust")) if name else None
    if not t:
        return "none"
    # only the workspace the person set up with `orch init` (its consent), never any other folder
    if not orch_folder(root):
        return "skipped"
    env = os.environ if environ is None else environ
    base = Path(env.get(t.get("dir_env") or "", "") or env.get("HOME") or Path.home())
    f = base / t["file"]
    folder = str(root.resolve())
    keys = [folder if k == "{folder}" else k for k in t["path"]]
    if f.is_symlink():
        return "skipped"  # never replace a link with a file
    for _ in range(3):
        try:
            raw = f.read_bytes()
            doc = json.loads(raw)
        except (OSError, ValueError):
            return "skipped"
        if not isinstance(doc, dict):
            return "skipped"
        node = doc
        for k in keys[:-1]:
            nxt = node.get(k)
            if nxt is None:
                nxt = node[k] = {}
            if not isinstance(nxt, dict):
                return "skipped"
            node = nxt
        if node.get(keys[-1]) is True:
            return "already"
        node[keys[-1]] = True
        tmp = f.with_name(f".{f.name}.orch-{os.getpid()}.tmp")
        try:
            mode = f.stat().st_mode & 0o777
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(doc, out, indent=2, ensure_ascii=False)
            if f.read_bytes() != raw:
                continue  # the tool wrote meanwhile: read again
            os.replace(tmp, f)
            return "set"
        except OSError:
            return "skipped"
        finally:
            tmp.unlink(missing_ok=True)
    return "skipped"


def screen(name: str, root: Path | None, text: str, tid: str) -> dict | None:
    """The first live.screens entry whose match is in the pane text, with its say filled in, or None.
    An entry with answer is a harmless first-run screen the run's wrapper may pass (see runs_live)."""
    a = load(name, root)
    for s in (a.get("live") or {}).get("screens") or []:
        try:
            hit = re.search(s["match"], text, re.IGNORECASE)
        except re.error:
            continue
        if hit:
            return {**s, "say": s["say"].replace("{label}", a["label"]).replace("{ticket}", tid)}
    return None


def orch_folder(root: Path) -> bool:
    """True for a workspace the person set up with `orch init` (its consent that the agent works there)."""
    return (root / ".orch" / "tickets").is_dir() and not (root / ".orch").is_symlink()


def session_mode(name: str, root: Path | None = None) -> str:
    """chosen-by-orch | from-output | none"""
    return load(name, root)["session"]["id"]


def transcript_exists(
    name: str, sid: str, root: Path, environ: Mapping[str, str] | None = None
) -> bool | None:
    """Has the tool saved the conversation of session `sid` for this folder (adapter session.transcript)?
    None = cannot tell (nothing declared, or the tool has no folder for this workspace at all, e.g. a path it
    names differently): orch then trusts the recorded id. False = the folder is there but not this session:
    resuming it would only fail with "no conversation found"."""
    t = (load(name, root).get("session") or {}).get("transcript")
    if not t or not SESSION_RE.match(sid or ""):
        return None
    env = os.environ if environ is None else environ
    base = Path(env.get(t.get("dir_env") or "", "") or Path(env.get("HOME") or Path.home()) / t["home"])
    folder = re.sub(r"[^A-Za-z0-9]", "-", str(root.resolve()))
    parts = [folder if k == "{folder}" else k.replace("{session}", sid) for k in t["path"]]
    f = base.joinpath(*parts)
    if not f.parent.is_dir():
        return None
    return f.is_file()


def session_missing(name: str, output: str, root: Path | None = None) -> bool:
    """True when the output says the resumed session does not exist (the only case for starting fresh)."""
    pat = load(name, root)["session"].get("missing")
    return bool(pat and re.search(pat, output, re.IGNORECASE))


def parse_session(name: str, output: str, root: Path | None = None) -> str | None:
    """The session id a run printed (for tools whose ids come from output)."""
    a = load(name, root)
    if a["session"]["id"] != "from-output":
        return None
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        for key in ("thread_id", "session_id"):
            sid = ev.get(key)
            if isinstance(sid, str) and SESSION_RE.match(sid):
                return sid
    return None


# ---------------------------------------------------------------- what is installed, what runs here


def _version(binary: str) -> str | None:
    try:
        r = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL
        )
    except (OSError, subprocess.SubprocessError):
        return None
    m = _VERSION.search((r.stdout or "") + (r.stderr or ""))
    return m.group(0) if m else None


def detect() -> list[dict]:
    """Built-in agents with a binary to look for: [{name, label, found, version}]."""
    out = []
    for name, a in _registry().items():
        d = a.get("detect") or {}
        binary = d.get("binary")
        if not binary:
            continue
        path = shutil.which(binary)
        out.append(
            {
                "name": name,
                "label": a["label"],
                "found": bool(path),
                "version": _version(path) if path else None,
            }
        )
    return out


RUN_ENV = ("ORCH_AGENT", "ORCH_RUN", "ORCH_TICKET", "ORCH_VIA")


def human_environ(environ: Mapping[str, str]) -> dict:
    """environ without anything that says "an agent is running": every tool's detect variables and the run's
    ORCH_AGENT/RUN/TICKET/VIA. Used for what a person (a page click) or orch itself (a restart) starts, so
    orch never counts it as the agent's. Add-ons call this one helper (no copies that drift apart)."""
    names, prefixes = set(RUN_ENV), []
    for a in _registry().values():
        d = a.get("detect") or {}
        names.update(d.get("env_any") or [])
        if d.get("env_prefix"):
            prefixes.append(d["env_prefix"])
    return {k: v for k, v in environ.items() if k not in names and not k.startswith(tuple(prefixes))}


def detect_env(environ: Mapping[str, str]) -> str | None:
    """The agent tool a process runs under, from its environment (ORCH_AGENT first), else None."""
    if environ.get("ORCH_AGENT"):
        return environ["ORCH_AGENT"]
    for name, a in _registry().items():
        d = a.get("detect") or {}
        if any(environ.get(k) for k in d.get("env_any") or []):
            return name
        prefix = d.get("env_prefix")
        if prefix and any(k.startswith(prefix) for k in environ):
            return name
    return None


_CAP_WORDS = (
    ("resume", "continue"),
    ("interactive_tmux", "live session"),
    ("hooks", "live steps"),
    ("subagents", "helpers"),
    ("usage", "usage"),
)


def describe(name: str, root: Path | None = None) -> str:
    a = load(name, root)
    words = [w for k, w in _CAP_WORDS if a["capabilities"].get(k)]
    if a["adapter"] == "generic":
        words = ["live session"] if a["capabilities"]["interactive_tmux"] else []
        return ", ".join(["fresh each run"] + words)
    return ", ".join(words) or "fresh each run"

"""Agent tool adapters: the only code (with agents.json) that knows tool names and how a tool is run.

agents.json holds the built-in adapters (contracts/agent-adapter.schema.json). A user entry in
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
import subprocess
from collections.abc import Mapping
from pathlib import Path

from orch import config
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
    doc = json.loads(Path(__file__).with_name("agents.json").read_text(encoding="utf-8"))
    errs = argv_errors(doc)
    if errs:
        raise RuntimeError("agents.json: " + "; ".join(errs))
    return doc["adapters"]


def builtin_names() -> list[str]:
    return list(_registry())


def load(name: str, root: Path | None = None) -> dict:
    """The adapter for an agent name: the built-in one, or the one a [agents.<name>] entry picks, with the
    user's command and interactive command added."""
    entry = config.agent_entries(root).get(name) if root is not None else None
    base = entry["adapter"] if entry else name
    reg = _registry()
    if base not in reg:
        raise Refused(f"No agent called '{name}'. See what is available: orch agents")
    a = copy.deepcopy(reg[base])
    a["name"], a["adapter"] = name, base
    a["label"] = a["label"].replace("{name}", name)
    a["command"] = (entry or {}).get("command")
    a["interactive"] = (entry or {}).get("interactive")
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

    v: prompt, session, new_session, orch_hooks_file, allow (list of tool patterns), stream (bool).
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
    extra: list[str] = []
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
        if not user and "--" not in out:
            out.append("--")
        out.append(str(v["prompt"]))
    return out


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


def session_mode(name: str, root: Path | None = None) -> str:
    """chosen-by-orch | from-output | none"""
    return load(name, root)["session"]["id"]


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

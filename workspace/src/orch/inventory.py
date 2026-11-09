"""Read-only inventory of connections (contracts/inventory.md, schema inventory.schema.json $defs/connection).

Three sources, winner first on one name: workspace (.orch/mcp.json), admin (the relay refresh record in the
guarded orch home, `<orch home>/keys/<ws>/connections.json`), harness (the agent tool's own settings, where
agents/connections.json says they are; read only, never changed). Anything unproven is workspace (P1).

Names only: no key, env value, header, URL path/query or argument is ever kept. A connection shows the
program's base name or the http host. Only the version is a hash of the server object
(without env and headers).
Reference functions: inv_conn_version, inv_winners, inv_classify, inv_allowed in contracts/validate.py
(vectors/inventory-v1.json).
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from orch import addons, agentsdata

ORDER = ["workspace", "admin", "harness"]
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
COMMAND_RE = re.compile(r"^[A-Za-z0-9_.+@-]{1,64}$")
HOST_RE = re.compile(r"^[a-z0-9.-]{1,253}(:[0-9]{1,5})?$")
PROFILE_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
LABEL_RE = re.compile(r"^[^\x00-\x1f\x7f<>]{1,64}$")
MAX_BYTES = 32 * 1024 * 1024


# --- small readers: a missing, unreadable or odd file means "nothing there" ---


def _read(path: Path, fmt: str = "json"):
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        text = path.read_text(encoding="utf-8")
        return tomllib.loads(text) if fmt == "toml" else json.loads(text)
    except (OSError, ValueError, UnicodeDecodeError):  # JSONDecodeError and TOMLDecodeError are ValueErrors
        return None


def _dig(doc, path: list[str]) -> dict:
    for key in path:
        if not isinstance(doc, dict):
            return {}
        doc = doc.get(key)
    return doc if isinstance(doc, dict) else {}


def conn_version(server: dict) -> str:
    """Same as inv_conn_version: env and headers are dropped before hashing and never shown."""
    clean = {k: v for k, v in server.items() if k not in ("env", "headers")}
    blob = json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def classify(
    name: str,
    version: str,
    *,
    from_harness_settings: bool,
    refresh_items,
    shipped=None,
    marketplace_index=None,
) -> str:
    """Same as inv_classify (a connection is in practice never builtin or marketplace)."""
    if from_harness_settings:
        return "harness"
    if [name, version] in [list(i) for i in refresh_items]:
        return "admin"
    if (shipped or {}).get(name) == version:
        return "builtin"
    if (marketplace_index or {}).get(name) == version:
        return "marketplace"
    return "workspace"


def winners(entries: list[dict]) -> dict[str, str]:
    """Same as inv_winners for connections: the best source per name."""
    best: dict[str, str] = {}
    for e in entries:
        if e["name"] not in best or ORDER.index(e["source"]) < ORDER.index(best[e["name"]]):
            best[e["name"]] = e["source"]
    return dict(sorted(best.items()))


# --- one server object -> the shown facts ---


def _program(server: dict) -> str | None:
    """Base name of the program only (stdio): never its arguments."""
    cmd = server.get("command")
    if isinstance(cmd, list):
        cmd = cmd[0] if cmd else None
    if not isinstance(cmd, str) or not cmd.strip():
        return None
    base = re.split(r"[\\/]", cmd.strip())[-1]
    return base if COMMAND_RE.match(base) else None


def _host(server: dict) -> str | None:
    """Host (and port) of an http connection: never path, query or credentials."""
    url = server.get("url")
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return None
    if ":" in host:  # an IPv6 literal does not fit the host pattern; show nothing
        return None
    host = f"{host}:{port}" if port else host
    return host if HOST_RE.match(host) else None


def _entry(name: str, server, source: str) -> dict | None:
    if not NAME_RE.match(name or "") or not isinstance(server, dict):
        return None
    http = isinstance(server.get("url"), str) and "command" not in server
    profile, label = server.get("profile"), server.get("label")
    actions = server.get("actions")
    return {
        "name": name,
        "source": source,
        "transport": "http" if http else "stdio",
        "command": None if http else _program(server),
        "host": _host(server) if http else None,
        "profile": profile if isinstance(profile, str) and PROFILE_RE.match(profile) else None,
        "label": label if isinstance(label, str) and LABEL_RE.match(label) else None,
        "version": conn_version(server),
        "_actions": [a for a in actions if isinstance(a, str) and NAME_RE.match(a)]
        if isinstance(actions, list)
        else [],
    }


# --- the three sources ---


def workspace_servers(root: Path) -> dict[str, dict]:
    """.orch/mcp.json servers (orch.mcp/1). Only servers of the right shape; a bad file means no entries."""
    doc = _read(root / ".orch" / "mcp.json")
    if not isinstance(doc, dict) or doc.get("schema") != "orch.mcp/1":
        return {}
    return {k: v for k, v in _dig(doc, ["servers"]).items() if isinstance(v, dict)}


def workspace_allow(root: Path) -> dict:
    doc = _read(root / ".orch" / "mcp.json")
    return _dig(doc, ["allow"]) if isinstance(doc, dict) else {}


def admin_servers(root: Path, orch_home: Path | None = None) -> dict[str, dict]:
    """The last relay refresh as recorded by the core: `<orch home>/keys/<ws>/connections.json`,
    {"mcpServers": {"<name>": {command|url, profile?, label?, actions?[names]}}} (local-files.md, Refresh).
    Missing, no workspace id or a bad file: no admin entries."""
    wid = addons.workspace_id(root)
    if not wid:
        return {}
    home = addons.home(root) if orch_home is None else orch_home
    doc = _read(home / "keys" / wid / "connections.json")
    return {k: v for k, v in _dig(doc, ["mcpServers"]).items() if isinstance(v, dict)}


def harness_servers(root: Path, account_home: Path | None = None) -> dict[str, dict]:
    """Connections the agent tool itself lists, read only; places from agents/connections.json."""
    home = addons.real_home() if account_home is None else account_home
    folder = str(root.resolve())
    out: dict[str, dict] = {}
    for adapter in agentsdata.load()["adapters"].values():
        for loc in adapter.get("mcp_settings", []):
            path = Path(loc["file"].replace("{home}", str(home)).replace("{folder}", folder))
            keys = [folder if k == "{folder}" else k for k in loc["path"]]
            for name, server in _dig(_read(path, loc["format"]), keys).items():
                out.setdefault(name, server)
    return out


def _grants(root: Path, orch_home: Path) -> dict:
    """conn.allow grants recorded with a proof (human-settings.json), by connection name."""
    wid = addons.workspace_id(root)
    doc = _read(orch_home / "human-settings.json")
    ws = _dig(doc, ["workspaces", wid]) if wid else {}
    out = {}
    for key, rec in ws.items():
        if key.startswith("conn.allow.") and isinstance(rec, dict) and "value" in rec:
            out[key[len("conn.allow.") :]] = rec["value"]
    return out


def _expand(x, actions: set[str]) -> set[str]:
    return set(actions) if x == "*" else {a for a in (x if isinstance(x, list) else []) if isinstance(a, str)}


def allowed(entry, grant, actions: list[str]) -> list[str]:
    """Same as inv_allowed: a file entry counts only with a matching proof-made grant."""
    if entry is None or grant is None:
        return []
    known = set(actions)
    return sorted(_expand(entry, known) & _expand(grant, known) & known)


def _profile_state(root: Path, orch_home: Path, profile: str | None) -> str:
    """missing-key when the profile (or a key it names) is not in the key folder; else not-started
    (this slice does not see use, only the files)."""
    if not profile:
        return "not-started"
    wid = addons.workspace_id(root)
    base = orch_home / "keys" / wid if wid else None
    prof = _dig(_read(base / "profiles.toml", "toml"), ["profile", profile]) if base else {}
    if not prof:
        return "missing-key"
    keys = _dig(_read(base / "keys.json"), ["keys"])
    for field in ("env", "files"):
        names = prof.get(field)
        if isinstance(names, dict) and any(v not in keys for v in names.values()):
            return "missing-key"
    return "not-started"


# --- the list ---


def connections(root: Path, *, orch_home: Path | None = None, account_home: Path | None = None):
    """(items, also_from). items = schema `connection` objects of every source, sorted by name then source;
    the winner of a name has shadowed false, the others true. also_from = {name: [other sources]}."""
    root = Path(root)
    home = addons.home(root) if orch_home is None else orch_home
    admin = admin_servers(root, home)
    refresh = [(n, conn_version(s)) for n, s in admin.items()]
    found: list[dict] = []
    for name, server in workspace_servers(root).items():
        # name and version of a refresh item = that item (P1: otherwise workspace)
        src = classify(name, conn_version(server), from_harness_settings=False, refresh_items=refresh)
        found.append(("admin" if src == "admin" else "workspace", name, server))
    seen = {(s, n, conn_version(sv)) for s, n, sv in found}
    for name, server in admin.items():
        if ("admin", name, conn_version(server)) not in seen:
            found.append(("admin", name, server))
    for name, server in harness_servers(root, account_home).items():
        found.append(("harness", name, server))

    file_allow, grants = workspace_allow(root), _grants(root, home)
    entries = []
    for source, name, server in found:
        e = _entry(name, server, source)
        if e:
            entries.append(e)
    entries.sort(
        key=lambda e: (e["name"], ORDER.index(e["source"]))
    )  # stable: discovery order within a source
    win = winners(entries)
    items, also, first = [], {}, set()
    for e in entries:
        name = e["name"]
        entry, grant = file_allow.get(name), grants.get(name)
        known = sorted(set(e.pop("_actions")) | set(_expand(entry, set())) | set(_expand(grant, set())))
        ok = set(allowed(entry, grant, known))
        is_win = name not in first
        first.add(name)
        if not is_win and e["source"] != win[name] and e["source"] not in also.setdefault(name, []):
            also[name].append(e["source"])
        item = {
            "name": name,
            "source": e["source"],
            "transport": e["transport"],
            "command": e["command"],
            "host": e["host"],
            "profile": e["profile"],
            "actions": [{"name": a, "allowed": a in ok} for a in known],
            "allow_all": entry == "*" and grant == "*",
            "state": "unknown" if e["source"] == "harness" else _profile_state(root, home, e["profile"]),
            "shadowed": not is_win,
            "version": e["version"],
        }
        if e["label"]:
            item["label"] = e["label"]
        items.append(item)
    return items, also

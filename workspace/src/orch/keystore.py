"""The key store (contracts/secrets.md, Level 1): keys live in the guarded orch home, never in the workspace.

    <guarded home>/keys/<workspace local id>/    0700 (humanproof.key_dir: guarded home, local-id binding)
        keys.json      0600  {"schema": "orch.keys/1", "keys": {name: {type, source, value | file, added_at}}}
                             the keys a person added here (source "workspace")
        admin-keys.json 0600 same shape, source "admin": written only by the relay refresh, read-only here
        files/<name>   0600  key-file values (at most 1 MB)
        profiles.toml  0600  names only, never a value
        <record>.json  0600  small records of orch itself (the relay record, written by relay.connect)

WINDOWS FAILS CLOSED: the user-and-SYSTEM ACL of the contract is not implemented yet, so on Windows every
function of this module refuses ("Keys can't be stored safely on Windows yet. Coming soon.") and nothing
secret is written or read. Decided by the platform (os.name), never by an environment variable.

Level 1 stops accidents and leaks (chat, logs, records, git, cloud sync of the workspace), not a hostile
process of the same user; see secrets.md. Rights: POSIX folders 0700 and files 0600, checked on every read (a
wrong owner, a looser mode or a link means Refused).

Every write is a new file plus one rename under keys.lock, so a failed or interrupted write leaves the old
state. No message, error or log line of this module contains a key value; names are validated before use.
There is no CLI here (`orch secret` is slice 1.2) and no value hiding (slice 1.3).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
import tomllib
from pathlib import Path

from orch import humanproof as hp
from orch.errors import Refused

KEYS_SCHEMA = "orch.keys/1"
PROFILES_SCHEMA = "orch.secret-profiles/1"
TYPES = ("token", "password", "key-file", "json")
SOURCES = ("workspace", "admin")
MIN_LEN, MAX_LEN, FILE_MAX = 8, 65536, 1024 * 1024
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
PROFILE_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
SKILL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
ENV_DENY = frozenset(
    "PATH HOME SHELL ENV BASH_ENV IFS NODE_OPTIONS PYTHONPATH PYTHONHOME PYTHONSTARTUP PERL5OPT RUBYOPT "
    "ORCH_BIN "
    "ORCH_EVENTS ORCH_RUN ORCH_JOB ORCH_HOME ORCH_ROOT HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY http_proxy "
    "https_proxy all_proxy SSL_CERT_FILE SSL_CERT_DIR NODE_EXTRA_CA_CERTS REQUESTS_CA_BUNDLE CURL_CA_BUNDLE "
    "JAVA_TOOL_OPTIONS _JAVA_OPTIONS".split()
)
ENV_DENY_PREFIX = ("LD_", "DYLD_", "GIT_", "ORCH_")
RECORDS = frozenset({"relay", "dev"})  # allowlist: the other files of the key folder have other owners

TOO_SHORT = "This key is too short to hide safely in records: at least 8 characters."
BAD_NAME = "A key name uses letters, digits, dot, dash and underscore, and starts with a letter or digit."
READ_ONLY = "This key is managed by your admin and cannot be changed here."


WINDOWS_MSG = "Keys can't be stored safely on Windows yet. Coming soon."


def _windows() -> bool:
    return os.name == "nt"


def unsupported() -> bool:
    """True where the key store refuses everything (Windows, until its ACL slice)."""
    return _windows()


def _guard() -> None:
    if _windows():
        raise Refused(WINDOWS_MSG)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _name(name) -> str:
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise Refused(BAD_NAME)
    return name


# ------------------------------------------------------------------------------------------- keys.json


def _load(d: Path, admin: bool = False) -> dict:
    """The keys of keys.json (workspace) or admin-keys.json (admin), validated. Unreadable or wrong shape or a
    source that does not belong in that file: Refused (fail closed), never a guess."""
    fname, src = ("admin-keys.json", "admin") if admin else ("keys.json", "workspace")
    try:
        hp._check_file(d / fname)
        raw = json.loads((d / fname).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError:
        raise Refused("The key file is damaged.") from None
    keys = raw.get("keys") if isinstance(raw, dict) and raw.get("schema") == KEYS_SCHEMA else None
    if not isinstance(keys, dict):
        raise Refused("The key file is damaged.")
    for n, e in keys.items():
        if not (
            NAME_RE.match(str(n))
            and isinstance(e, dict)
            and e.get("type") in TYPES
            and e.get("source") == src
        ):
            raise Refused("The key file is damaged.")
    return keys


def _store(d: Path, keys: dict, admin: bool = False) -> None:
    hp._write_private(
        d / ("admin-keys.json" if admin else "keys.json"),
        json.dumps({"schema": KEYS_SCHEMA, "keys": keys}, indent=2) + "\n",
    )


def _check_value(type_: str, value) -> None:
    if type_ not in TYPES:
        raise Refused("Unknown key type. Use token, password, key-file or json.")
    if type_ == "key-file":
        if not isinstance(value, (bytes, bytearray)) or not value:
            raise Refused("A key file needs its content.")
        if len(value) > FILE_MAX:
            raise Refused("A key file can be at most 1 MB.")
        return
    if not isinstance(value, str):
        raise Refused("A key value must be text.")
    if len(value) < MIN_LEN:
        raise Refused(TOO_SHORT)
    if len(value) > MAX_LEN:
        raise Refused("A key value can have at most 65536 characters.")
    if type_ in ("token", "password") and ("\n" in value or "\r" in value or "\x00" in value):
        raise Refused("A token or password is one line.")
    if type_ == "json":
        try:
            ok = isinstance(json.loads(value), dict)
        except ValueError:
            ok = False
        if not ok:
            raise Refused("A json key must be a JSON object.")


def _existing_dir(root: Path) -> Path | None:
    """The key folder when this workspace already has one; None when there is none yet (nothing stored). A
    workspace that does not pair with its home, or a folder with wrong rights, still raises."""
    from orch import addons

    ws = addons.workspace_id(root, create=False)
    home = hp.guarded_home(root)  # refuses first: no answer about a home that does not pair
    if ws is None or not (home / "keys" / ws).is_dir():
        return None
    return hp.key_dir(root, create=False)


def _files_dir(d: Path, create: bool) -> Path:
    f = d / "files"
    if create:
        hp._private_dir(f, d.parent)
    return f


def add(root: Path, name: str, type_: str, value, source: str = "workspace") -> None:
    """Create or replace key `name` (a person's action; the proof is the caller's job, slice 1.2). A name an
    admin key holds is allowed: the workspace key is used and the admin key shows as shadowed."""
    _guard()
    _name(name)
    if source != "workspace":
        raise Refused(READ_ONLY)  # admin keys come only from set_admin (the relay refresh)
    _check_value(type_, value)
    d = hp.key_dir(root)
    with hp._key_lock(d):
        keys = _load(d)
        entry: dict = {"type": type_, "source": "workspace", "added_at": _now()}
        old_bytes = None
        fpath = None
        if type_ == "key-file":
            fdir = _files_dir(d, True)
            fpath = fdir / name
            entry["file"] = name
            try:
                hp._check_file(fpath)
                old_bytes = fpath.read_bytes()
            except FileNotFoundError:
                pass
            _write_private_bytes(fpath, bytes(value))
        else:
            entry["value"] = value
        prev = keys.get(name)
        keys[name] = entry
        try:
            _store(d, keys)
            if prev and prev["type"] == "key-file" and type_ != "key-file":  # no stale key file stays behind
                with contextlib.suppress(OSError):
                    (d / "files" / name).unlink()
        except BaseException:
            if fpath is not None:  # rollback: the old file content (or none) stays
                if old_bytes is None:
                    with contextlib.suppress(OSError):
                        fpath.unlink()
                else:
                    with contextlib.suppress(OSError):
                        _write_private_bytes(fpath, old_bytes)
            raise


def _write_private_bytes(path: Path, data: bytes) -> None:
    import secrets as _s

    tmp = path.with_name(f".{path.name}.{_s.token_hex(4)}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def remove(root: Path, name: str) -> None:
    _guard()
    _name(name)
    d = hp.key_dir(root)
    with hp._key_lock(d):
        keys = _load(d)
        e = keys.get(name)
        if e is None:
            if name in _load(d, admin=True):
                raise Refused(READ_ONLY)
            raise Refused("There is no such key.")
        del keys[name]
        _store(d, keys)  # the entry goes first, then its file
        if e["type"] == "key-file":
            with contextlib.suppress(OSError):
                (d / "files" / name).unlink()


def get_value(root: Path, name: str):
    """The value of key `name` (str; bytes for a key-file). The workspace key wins over an admin key of the
    same name (see list_keys: the admin one shows as shadowed). The caller hands it straight to a command and
    never prints it. Refused when there is none."""
    _guard()
    _name(name)
    d = _existing_dir(root)
    e = None
    if d:
        e = _load(d).get(name) or _load(d, admin=True).get(name)
    if e is None:
        raise Refused("There is no such key.")
    if e["type"] == "key-file":
        fpath = d / "files" / name
        hp._check_dir(d / "files")
        try:
            hp._check_file(fpath)
            return fpath.read_bytes()
        except FileNotFoundError:
            raise Refused("The key file is missing.") from None
    v = e.get("value")
    if not isinstance(v, str):
        raise Refused("The key file is damaged.")
    return v


def list_keys(root: Path) -> list[dict]:
    """Names, types, sources and state. Never a value. A workspace key and an admin key of the same name are
    both stored: the workspace key is used (`active`) and the admin one shows as `shadowed`; removing the
    workspace key makes the admin one active again."""
    _guard()
    d = _existing_dir(root)
    mine = _load(d) if d else {}
    theirs = _load(d, admin=True) if d else {}
    out = []
    for n in sorted(set(mine) | set(theirs)):
        for e, state in ((mine.get(n), "active"), (theirs.get(n), "shadowed" if n in mine else "active")):
            if e:
                out.append(
                    {
                        "name": n,
                        "type": e["type"],
                        "source": e["source"],
                        "state": state,
                        "added_at": e.get("added_at"),
                    }
                )
    return out


def preflight(root: Path) -> None:
    """Everything set_admin needs, checked without writing a key: the folder (pairing, binding, rights)
    and both key files readable. Refused means nothing was changed; the relay refresh calls it before it
    replaces anything."""
    _guard()
    d = hp.key_dir(root)
    _load(d)
    _load(d, admin=True)


def set_admin(root: Path, items: dict) -> list[str]:
    """Replace every admin key by `items` ({name: str or json object}) in ONE rename of admin-keys.json (the
    relay refresh, secrets.md "an interrupted refresh keeps the old keys"). Workspace keys are not touched. A
    name or value the store refuses is skipped and reported by name, never by value. Returns plain-words lines
    for the skipped ones. Raises Refused (nothing changed) when the folder is not usable."""
    _guard()
    if not isinstance(items, dict):
        raise Refused("The admin keys are not a list of keys.")
    d = hp.key_dir(root)
    skipped: list[str] = []
    with hp._key_lock(d):
        _load(d)  # a damaged key file refuses here, before anything is written
        _load(d, admin=True)
        merged = {}
        for n, v in items.items():
            if not isinstance(n, str) or not NAME_RE.match(n):
                skipped.append("key with an unusable name")
                continue
            type_ = "json" if isinstance(v, dict) else "token"
            value = json.dumps(v, separators=(",", ":")) if isinstance(v, dict) else v
            try:
                _check_value(type_, value)
            except Refused as e:
                skipped.append(f"key {n}: {e}")
                continue
            merged[n] = {"type": type_, "source": "admin", "value": value, "added_at": _now()}
        _store(d, merged, admin=True)
    return skipped


def admin_names(root: Path) -> list[str]:
    _guard()
    d = _existing_dir(root)
    return sorted(_load(d, admin=True)) if d else []


# ------------------------------------------------------------------------------------------- profiles


def _profile_check(profiles: dict, key_values: set[str]) -> None:
    if not isinstance(profiles, dict) or len(profiles) > 64:
        raise Refused("The profiles are not valid.")
    for pn, p in profiles.items():
        if not isinstance(pn, str) or not PROFILE_RE.match(pn) or not isinstance(p, dict):
            raise Refused("A profile name uses lower-case letters, digits and dashes.")
        if not (p.keys() <= {"env", "files", "set", "run", "allow_get", "skills"}):
            raise Refused(f"The profile {pn} has a setting orch does not know.")
        if not (p.get("env") or p.get("files")):
            raise Refused(f"The profile {pn} needs at least one key.")
        seen = set()
        for sect, cap in (("env", 16), ("files", 8), ("set", 16)):
            m = p.get(sect, {})
            if not isinstance(m, dict) or len(m) > cap:
                raise Refused(f"The profile {pn} has a bad {sect} section.")
            for var, tgt in m.items():
                if not isinstance(var, str) or not ENV_RE.match(var):
                    raise Refused(f"The profile {pn} names an unusable variable.")
                if var in ENV_DENY or var.startswith(ENV_DENY_PREFIX):
                    raise Refused(f"The profile {pn} may not set the variable {var}.")
                if var in seen:
                    raise Refused(f"The profile {pn} uses the variable {var} twice.")
                seen.add(var)
                if sect == "set":
                    if (
                        not isinstance(tgt, str)
                        or len(tgt) > 300
                        or any(ord(c) < 32 or ord(c) == 127 for c in tgt)
                    ):
                        raise Refused(f"The profile {pn} has a bad setting value.")
                    if tgt in key_values:  # names only: a key value pasted into a profile is refused
                        raise Refused(
                            f"The profile {pn} holds a key value. Profiles name keys, never hold them."
                        )
                elif not isinstance(tgt, str) or not NAME_RE.match(tgt):
                    raise Refused(BAD_NAME)
        run = p.get("run")
        if run is not None and (
            not isinstance(run, list)
            or not 1 <= len(run) <= 32
            or not all(isinstance(x, str) and 1 <= len(x) <= 300 for x in run)
        ):
            raise Refused(f"The profile {pn} has a bad command.")
        if "allow_get" in p and not isinstance(p["allow_get"], bool):
            raise Refused(f"The profile {pn} has a bad print setting.")
        sk = p.get("skills", [])
        if (
            not isinstance(sk, list)
            or len(sk) > 16
            or not all(isinstance(x, str) and SKILL_RE.match(x) for x in sk)
        ):
            raise Refused(f"The profile {pn} has a bad skills list.")


def _q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)  # a JSON string is a valid TOML basic string


def _toml(profiles: dict) -> str:
    out = [f"schema = {_q(PROFILES_SCHEMA)}", ""]
    for pn in sorted(profiles):
        p = profiles[pn]
        out.append(f"[profile.{pn}]")
        for sect in ("env", "files", "set"):
            if p.get(sect):
                out.append(f"{sect} = {{ " + ", ".join(f"{k} = {_q(v)}" for k, v in p[sect].items()) + " }")
        if p.get("run"):
            out.append("run = [" + ", ".join(_q(x) for x in p["run"]) + "]")
        if p.get("skills"):
            out.append("skills = [" + ", ".join(_q(x) for x in p["skills"]) + "]")
        if p.get("allow_get"):
            out.append("allow_get = true")
        out.append("")
    return "\n".join(out)


def write_profiles(root: Path, profiles: dict) -> None:
    """Replace profiles.toml (a person's action: the proof is the caller's job, slice 1.2). Names only."""
    _guard()
    d = hp.key_dir(root)
    with hp._key_lock(d):
        values = set()
        for e in [*_load(d).values(), *_load(d, admin=True).values()]:
            if isinstance(e.get("value"), str):
                values.add(e["value"])
        _profile_check(profiles, values)
        hp._write_private(d / "profiles.toml", _toml(profiles))


def read_profiles(root: Path) -> dict:
    """The profiles ({} when none yet). Unreadable or invalid: Refused."""
    _guard()
    d = _existing_dir(root)
    if d is None:
        return {}
    try:
        hp._check_file(d / "profiles.toml")
        raw = tomllib.loads((d / "profiles.toml").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (ValueError, UnicodeDecodeError):
        raise Refused("The profiles file is damaged.") from None
    if raw.get("schema") != PROFILES_SCHEMA or set(raw) - {"schema", "profile"}:
        raise Refused("The profiles file is damaged.")
    profiles = raw.get("profile", {})
    _profile_check(profiles, set())
    return profiles


# ------------------------------------------------------------------------------------------- records


def _record_path(d: Path, record: str) -> Path:
    if record not in RECORDS:
        raise Refused("Unknown record.")
    return d / f"{record}.json"


def record_write(root: Path, record: str, data: dict) -> None:
    """A small record of orch itself in the key folder (e.g. `relay`: {url, workspace, token, ...}, written by
    relay.connect). One file, new file + rename under keys.lock."""
    _guard()
    if not isinstance(data, dict):
        raise Refused("A record is an object.")
    d = hp.key_dir(root)
    path = _record_path(d, record)
    with hp._key_lock(d):
        hp._write_private(path, json.dumps(data, indent=2) + "\n")


def record_read(root: Path, record: str) -> dict | None:
    """The record, or None when there is none. A damaged one is Refused, never guessed."""
    _guard()
    d = _existing_dir(root)
    if d is None:
        return None
    data = hp._read_json(_record_path(d, record), None)
    if data is not None and not isinstance(data, dict):
        raise Refused("A record in the orch folder is unreadable.")
    return data

"""The key store (contracts/secrets.md, Level 1): keys live in the guarded orch home, never in the workspace.

    <guarded home>/keys/<workspace local id>/    0700 (humanproof.key_dir: guarded home, local-id binding)
        keys.json      0600  {"schema": "orch.keys/1", "keys": {name: {type, source, value | file, added_at}}}
                             the keys a person added here (source "workspace")
        admin-keys.json 0600 same shape, source "admin": written only by the relay refresh, read-only here
        files/<name>   0600  key-file values (at most 1 MB)
        profiles.toml  0600  names only, never a value
        <record>.json  0600  small records of orch itself (the relay record, written by relay.connect)

WINDOWS: the same rules through orch.winacl (a user-and-SYSTEM-only ACL set before any secret is written, and
checked on every read); loose files are set aside as on POSIX.

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
import logging
import os
import re
import time
import tomllib
from pathlib import Path

from orch import humanproof as hp
from orch import saferead
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
    "JAVA_TOOL_OPTIONS _JAVA_OPTIONS GCONV_PATH GLIBC_TUNABLES LOCPATH LUA_INIT LUA_PATH PERLLIB ZDOTDIR "
    "DOTNET_STARTUP_HOOKS NPM_CONFIG_SCRIPT_SHELL RUSTC_WRAPPER SYSTEMROOT USERPROFILE APPDATA EDITOR PAGER "
    "BROWSER LESSOPEN".split()
)
ENV_DENY_PREFIX = (
    "LD_", "DYLD_", "PATH", "GIT_", "ORCH_", "PYTHON", "PERL", "RUBY", "NODE_", "BASH", "XDG_",
    "LUA_", "GCONV", "GLIBC", "COR_", "CORECLR", "DOTNET", "RUSTC", "CARGO_", "SSH_", "GPG_", "SUDO_",
    "PSMODULEPATH", "NPM_CONFIG", "GNUPG", "PHPRC", "TCLLIBPATH", "R_PROFILE", "CLASSPATH", "RSYNC_",
)  # fmt: skip
ENV_DENY_SUFFIX = ("_OPTIONS",)
ENV_DENY_CONTAINS = ("ASKPASS",)
_ENV_DENY_UP = frozenset(
    {
        *(v.upper() for v in ENV_DENY),
        "SHELLOPTS", "PS4", "PATHEXT", "COMSPEC", "PROMPT_COMMAND", "VISUAL", "MANPAGER", "LOCPATH",
        "TMPDIR", "TEMP", "TMP", "NPM_TOKEN", "DEVELOPER_DIR", "SDKROOT", "TOOLCHAINS",
        "LESS", "LESSOPEN", "LESSCLOSE", "LESSKEY", "LESSHISTFILE",
        "LESSKEYIN", "LESSKEYIN_SYSTEM", "LESSKEY_SYSTEM", "LESSKEY_CONTENT", "LESSEDIT", "LESSSECURE",
    }
)  # fmt: skip
SET_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


# Ordinary secret variable names that look like control prefixes: allowed in `env` ONLY (they carry a key's
# value; a person's `set` and `files` never get them).
ENV_SECRET_NAMES = re.compile(
    r"^(NPM_TOKEN|NODE_AUTH_TOKEN|CARGO_REGISTRY_TOKEN|CARGO_REGISTRIES_[A-Z0-9_]+_TOKEN|GPG_PASSPHRASE)$"
)


def env_denied(var: str, sect: str = "set") -> bool:
    """Control variables a profile may never name in env, files or set (case-insensitive: Windows folds
    names): loader, interpreter, shell, git, ssh, editor, proxy, home/config locations. The ONE hard-deny,
    at profile set AND on every read and run."""
    if sect == "env" and ENV_SECRET_NAMES.fullmatch(var):
        return False
    up = var.upper()
    return (
        up in _ENV_DENY_UP
        or up.startswith(ENV_DENY_PREFIX)
        or up.endswith(ENV_DENY_SUFFIX)
        or any(x in up for x in ENV_DENY_CONTAINS)
    )


def set_name_ok(var: str) -> bool:
    """A plain `set` variable: structural (upper-case letters, digits, underscore, starting with a letter) AND
    not a control variable. Follow-up: only names the profile declares or a person approves (`extra`)."""
    return isinstance(var, str) and bool(SET_NAME_RE.fullmatch(var)) and not env_denied(var)


RECORDS = frozenset({"relay", "dev"})  # allowlist: the other files of the key folder have other owners

TOO_SHORT = "This key is too short to hide safely in records: at least 8 characters."
BAD_NAME = "A key name uses letters, digits, dot, dash and underscore, and starts with a letter or digit."
NEEDS_REENTRY = "needs-reentry"
REENTER = "This key must be entered again."
_log = logging.getLogger("orch.keystore")
READ_ONLY = "This key is managed by your admin and cannot be changed here."


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
        _check_file(d / fname)
        raw = json.loads(_read(d / fname).decode("utf-8"))
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


# ------------------------------------------------------------------------------------ loose files
# A key file that is wider than 0600 or has another owner may have been read or changed by someone else, so
# its VALUES are never used again. It is renamed (under keys.lock) to <name>.loose-<UTC time>, set to 0600
# and kept only so the key NAMES can be listed ("This key must be entered again"). Never chmod'ed and trusted.
# Re-entry (add by a person, the next relay refresh for admin keys) writes a fresh 0600 entry; the set-aside
# file is deleted by exact path when no name in it still needs re-entry, or when the key is removed.


def _read(path: Path, limit: int = 8 * 1024 * 1024) -> bytes:
    """The bytes of a guarded key-store file: the rights check, then saferead.read_private (a link, FIFO, hard
    link, swap or oversize file is refused). FileNotFoundError when it is not there."""
    _check_file(path)
    base, rel = hp._home_of(path)
    data = saferead.read_private(base, rel, limit)
    if data is None:
        raise Refused(hp.WRONG_RIGHTS)
    return data


def _check_file(p: Path) -> None:
    """humanproof's rights check, with the key store's own plain words (a loose file was set aside before this
    is reached; what is left here is a link or a non-file)."""
    try:
        hp._check_file(p)
    except hp.LooseFile:
        raise Refused(hp.WRONG_RIGHTS) from None


def _is_loose(p: Path) -> bool:
    """Loose = wider than 0600, another owner, or (Windows) an ACL beyond user and SYSTEM: the verdict is
    humanproof.file_problem, so its platform hook applies here too. A link or a non-file is not "loose":
    it stays refused. "unknown" (Windows could not tell) raises winacl.Unknown: refuse, set nothing aside."""
    try:
        why = hp.file_problem(p)
    except OSError:
        return False
    if why == "unknown":  # Windows could not tell: refuse this call only, never set a key aside for it
        raise hp.winacl.Unknown("Windows would not tell the rights of a key file. Try again.")
    return why is not None and why != "type"


def _quarantine(path: Path) -> None:
    """Set a loose key file aside (caller holds keys.lock): a NAMES-ONLY copy `<name>.loose-<UTC time>` is
    written with the proper rights and the original is deleted by exact path, so no value stays anywhere under
    loose rights (a rename would keep the values and, on Windows, the loose ACL). Logs the file name, never a
    value."""
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dst = path.with_name(f"{path.name}.loose-{ts}")
    n = 0
    while dst.exists() or dst.is_symlink():
        n += 1
        dst = path.with_name(f"{path.name}.loose-{ts}-{n}")
    if path.parent.name == "files":  # a key-file value: nothing but the fact that it existed is kept
        hp._write_private(dst, "")
    else:
        names = sorted(_names_from(path))
        hp._write_private(
            dst, json.dumps({"schema": KEYS_SCHEMA, "keys": {n: {} for n in names}}, indent=2) + "\n"
        )
    path.unlink()
    _log.warning("key file %s had loose rights and was set aside; its keys must be entered again", path.name)


def _tighten_locked(d: Path) -> None:
    for f in ("keys.json", "admin-keys.json"):
        if _is_loose(d / f):
            _quarantine(d / f)


def _tighten(d: Path) -> None:
    if any(_is_loose(d / f) for f in ("keys.json", "admin-keys.json")):
        with hp._key_lock(d):
            _tighten_locked(d)


def _aside(d: Path, fname: str) -> list[Path]:
    """The set-aside copies of fname (or of a key-file value under files/): <fname>.loose-<time>[-n]."""
    base = d / fname
    rx = re.compile(re.escape(base.name) + r"\.loose-\d{8}T\d{6}Z(-\d+)?$")
    out = []
    with contextlib.suppress(OSError):
        out = [p for p in base.parent.iterdir() if rx.match(p.name) and not p.is_symlink() and p.is_file()]
    return sorted(out)


def _names_from(path: Path) -> set[str]:
    """Key NAMES in a set-aside file, for display only. Values are never returned: the names are untrusted
    (validated, plain text) and the rest of the file is dropped here."""
    try:
        base, rel = hp._home_of(path)
        data = saferead.read_private(
            base, rel, 8 * 1024 * 1024
        )  # no rights check: its rights are why it is here
        raw = json.loads(data.decode("utf-8", "replace")) if data is not None else None
    except (OSError, ValueError):
        return set()
    keys = raw.get("keys") if isinstance(raw, dict) else None
    if not isinstance(keys, dict):
        return set()
    return {n for n in keys if isinstance(n, str) and NAME_RE.match(n)}


def _reentry(d: Path, admin: bool, live: dict) -> set[str]:
    """Names that a set-aside key file listed and that nobody has entered again yet."""
    names: set[str] = set()
    for p in _aside(d, "admin-keys.json" if admin else "keys.json"):
        names |= _names_from(p)
    return names - set(live)


def _file_loose_check(d: Path, name: str) -> None:
    """A key-file value that is loose is set aside, under keys.lock, and never read."""
    fp = d / "files" / name
    if _is_loose(fp):
        with hp._key_lock(d):
            if _is_loose(fp):
                _quarantine(fp)


def _file_needs_reentry(d: Path, name: str) -> bool:
    _file_loose_check(d, name)
    fp = d / "files" / name
    return not (fp.exists() or fp.is_symlink()) and bool(_aside(d, f"files/{name}"))


def _dismiss(d: Path, name: str) -> None:
    """The person removed key `name`: it no longer needs re-entry. Set-aside files are rewritten WITHOUT any
    value (names only) and deleted when empty; the set-aside copy of a key-file value is deleted."""
    for p in _aside(d, "keys.json"):
        names = _names_from(p) - {name}
        if names:
            hp._write_private(
                p, json.dumps({"schema": KEYS_SCHEMA, "keys": {n: {} for n in sorted(names)}}) + "\n"
            )
        else:
            p.unlink(missing_ok=True)
    for p in _aside(d, f"files/{name}"):
        p.unlink(missing_ok=True)


def _sweep(d: Path, mine: dict) -> None:
    """Delete set-aside files that nothing needs any more (exact paths). `mine` = the live workspace keys."""
    for p in _aside(d, "keys.json"):
        if _names_from(p) <= set(mine):
            p.unlink(missing_ok=True)
    fdir = d / "files"
    with contextlib.suppress(OSError):
        for p in fdir.iterdir():
            base, sep, _ = p.name.partition(".loose-")
            if sep and p in _aside(d, f"files/{base}") and (base not in mine or (fdir / base).exists()):
                p.unlink(missing_ok=True)


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
    d = hp.key_dir(root, create=False)
    _tighten(d)
    return d


def _files_dir(d: Path, create: bool) -> Path:
    f = d / "files"
    if create:
        hp._private_dir(f, d.parent)
    return f


def add(root: Path, name: str, type_: str, value, source: str = "workspace") -> None:
    """Create or replace key `name` (a person's action; the proof is the caller's job, slice 1.2). A name an
    admin key holds is allowed: the workspace key is used and the admin key shows as shadowed."""
    _name(name)
    if source != "workspace":
        raise Refused(READ_ONLY)  # admin keys come only from set_admin (the relay refresh)
    _check_value(type_, value)
    d = hp.key_dir(root)
    with hp._key_lock(d):
        _tighten_locked(d)
        keys = _load(d)
        entry: dict = {"type": type_, "source": "workspace", "added_at": _now()}
        old_bytes = None
        fpath = None
        if type_ == "key-file":
            fdir = _files_dir(d, True)
            fpath = fdir / name
            entry["file"] = name
            if _is_loose(fpath):
                _quarantine(fpath)
            try:
                _check_file(fpath)
                old_bytes = _read(fpath, FILE_MAX + 1)
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
            _sweep(d, keys)
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
            hp.winacl.set_private(tmp, False)  # before any secret is written (Windows)
            f.write(data)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def remove(root: Path, name: str) -> None:
    _name(name)
    d = hp.key_dir(root)
    with hp._key_lock(d):
        _tighten_locked(d)
        keys = _load(d)
        e = keys.get(name)
        pending = name in _reentry(d, False, keys) or bool(_aside(d, f"files/{name}"))
        if e is None and not pending:
            if name in _load(d, admin=True) or name in _reentry(d, True, _load(d, admin=True)):
                raise Refused(READ_ONLY)
            raise Refused("There is no such key.")
        if e is not None:
            del keys[name]
            _store(d, keys)  # the entry goes first, then its file
            if e["type"] == "key-file":
                with contextlib.suppress(OSError):
                    (d / "files" / name).unlink()
        _dismiss(d, name)
        _sweep(d, keys)


def get_value(root: Path, name: str):
    """The value of key `name` (str; bytes for a key-file). The workspace key wins over an admin key of the
    same name (see list_keys: the admin one shows as shadowed). The caller hands it straight to a command and
    never prints it. Refused when there is none, or when it must be entered again (its file was loose)."""
    _name(name)
    d = _existing_dir(root)
    if d is None:
        raise Refused("There is no such key.")
    mine, theirs = _load(d), _load(d, admin=True)
    gone = Refused(f"Refused: the key {name} can't be used. {REENTER}")
    if name in _reentry(d, False, mine):
        raise gone
    e = mine.get(name) or theirs.get(name)
    if e is None:
        if name in _reentry(d, True, theirs):
            raise gone
        raise Refused("There is no such key.")
    if e["type"] == "key-file":
        hp._check_dir(d / "files")
        if _file_needs_reentry(d, name):
            raise gone
        try:
            return _read(d / "files" / name, FILE_MAX + 1)
        except FileNotFoundError:
            raise Refused("The key file is missing.") from None
    v = e.get("value")
    if not isinstance(v, str):
        raise Refused("The key file is damaged.")
    return v


def list_keys(root: Path) -> list[dict]:
    """Names, types, sources and state. Never a value. A workspace key and an admin key of the same name are
    both stored: the workspace key is used (`active`) and the admin one shows as `shadowed`; removing the
    workspace key makes the admin one active again. A key whose file had loose rights shows as
    `needs-reentry` with the words "This key must be entered again" (its type is not known: None)."""
    d = _existing_dir(root)
    mine = _load(d) if d else {}
    theirs = _load(d, admin=True) if d else {}
    out = []
    for n in sorted(set(mine) | set(theirs)):
        for e, state in ((mine.get(n), "active"), (theirs.get(n), "shadowed" if n in mine else "active")):
            if e:
                if e["type"] == "key-file" and e["source"] == "workspace" and _file_needs_reentry(d, n):
                    state = NEEDS_REENTRY
                out.append(
                    {
                        "name": n,
                        "type": e["type"],
                        "source": e["source"],
                        "state": state,
                        "added_at": e.get("added_at"),
                        **({"note": REENTER} if state == NEEDS_REENTRY else {}),
                    }
                )
    if d:
        for admin, live in ((False, mine), (True, theirs)):
            for n in sorted(_reentry(d, admin, live)):
                out.append(
                    {
                        "name": n,
                        "type": None,
                        "source": "admin" if admin else "workspace",
                        "state": NEEDS_REENTRY,
                        "added_at": None,
                        "note": REENTER,
                    }
                )
    return out


def preflight(root: Path) -> None:
    """Everything set_admin needs, checked without writing a key: the folder (pairing, binding, rights)
    and both key files readable. Refused means nothing was changed; the relay refresh calls it before it
    replaces anything."""
    d = hp.key_dir(root)
    _tighten(d)
    _load(d)
    _load(d, admin=True)


def set_admin(root: Path, items: dict) -> list[str]:
    """Replace every admin key by `items` ({name: str or json object}) in ONE rename of admin-keys.json (the
    relay refresh, secrets.md "an interrupted refresh keeps the old keys"). Workspace keys are not touched. A
    name or value the store refuses is skipped and reported by name, never by value. Returns plain-words lines
    for the skipped ones. Raises Refused (nothing changed) when the folder is not usable."""
    if not isinstance(items, dict):
        raise Refused("The admin keys are not a list of keys.")
    d = hp.key_dir(root)
    skipped: list[str] = []
    with hp._key_lock(d):
        _tighten_locked(d)
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
        for p in _aside(d, "admin-keys.json"):  # the refresh is the whole truth: nothing is left to re-enter
            p.unlink(missing_ok=True)
    return skipped


def admin_names(root: Path) -> list[str]:
    d = _existing_dir(root)
    return sorted(_load(d, admin=True)) if d else []


# ------------------------------------------------------------------------------------------- profiles


def _profile_check(profiles: dict, key_values: set[str]) -> None:
    if not isinstance(profiles, dict) or len(profiles) > 64:
        raise Refused("The profiles are not valid.")
    for pn, p in profiles.items():
        if not isinstance(pn, str) or not PROFILE_RE.match(pn) or not isinstance(p, dict):
            raise Refused("A profile name uses lower-case letters, digits and dashes.")
        if not (
            p.keys()
            <= {
                "env",
                "files",
                "set",
                "run",
                "allow_get",
                "agents_may_env",
                "skills",
                "extra",
                "real_home",
                "kind",
                "any_command",
            }
        ):
            raise Refused(f"The profile {pn} has a setting orch does not know.")
        if not (p.get("env") or p.get("files")):
            raise Refused(f"The profile {pn} needs at least one key.")
        extra = p.get("extra", [])
        if not isinstance(extra, list) or len(extra) > 16 or len(set(extra)) != len(extra):
            raise Refused(f"The profile {pn} has a bad extra list.")
        for x in extra:
            if not set_name_ok(x):
                raise Refused(f"The profile {pn} may not approve the variable {x}.")
        # env names in `approved` are redundant with the duplicate check below (a set/files name equal to an
        # env name is refused as "twice"); kept for clarity: effectively set/files names need `extra`.
        approved = {
            *(p.get("env") or {}),
            *extra,
        }  # the secret variables it declares + person-approved extras
        seen = set()
        for sect, cap in (("env", 16), ("files", 8), ("set", 16)):
            m = p.get(sect, {})
            if not isinstance(m, dict) or len(m) > cap:
                raise Refused(f"The profile {pn} has a bad {sect} section.")
            for var, tgt in m.items():
                if not isinstance(var, str) or not ENV_RE.match(var):
                    raise Refused(f"The profile {pn} names an unusable variable.")
                if env_denied(var, sect) or (sect == "set" and not set_name_ok(var)):
                    raise Refused(f"The profile {pn} may not set the variable {var}.")
                if sect != "env" and var not in approved:
                    raise Refused(
                        f"{var} is not an approved variable for this profile; add it with --extra {var}."
                    )
                if var.upper() in seen:
                    raise Refused(f"The profile {pn} uses the variable {var} twice.")
                seen.add(var.upper())
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
        if "kind" in p and not (isinstance(p["kind"], str) and re.fullmatch(r"[a-z]{1,16}", p["kind"])):
            raise Refused(f"The profile {pn} has a bad command kind.")
        for flag in ("allow_get", "agents_may_env", "real_home", "any_command"):
            if flag in p and not isinstance(p[flag], bool):
                raise Refused(f"The profile {pn} has a bad {flag.replace('_', ' ')} setting.")
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
        if p.get("extra"):
            out.append("extra = [" + ", ".join(_q(x) for x in p["extra"]) + "]")
        if p.get("run"):
            out.append("run = [" + ", ".join(_q(x) for x in p["run"]) + "]")
        if p.get("kind"):
            out.append(f"kind = {_q(p['kind'])}")
        if p.get("skills"):
            out.append("skills = [" + ", ".join(_q(x) for x in p["skills"]) + "]")
        for flag in ("allow_get", "agents_may_env", "real_home", "any_command"):
            if p.get(flag):
                out.append(f"{flag} = true")
        out.append("")
    return "\n".join(out)


def write_profiles(
    root: Path, profiles: dict, *, sign: frozenset = frozenset(), tombstone: frozenset = frozenset()
) -> None:
    """Replace profiles.toml (a person's action: the proof is the caller's job, slice 1.2). Names only.
    ONLY the names in `sign` (the profile the person is setting right now, with proof) get a body MAC in the
    guarded ledger, BEFORE the file is written. Every other profile is written back as it is and its ledger
    entry is left untouched (an edited body stays unverified, a switch change never vouches for it); a
    removed profile (`tombstone`, passed by the caller, whatever the file says) is tombstoned. What to sign is
    never decided from the unverified file. An unreadable old file refuses the save (nothing is signed)."""
    d = hp.key_dir(root)
    with hp._key_lock(d):
        _tighten_locked(d)
        values = set()
        for e in [*_load(d).values(), *_load(d, admin=True).values()]:
            if isinstance(e.get("value"), str):
                values.add(e["value"])
        _profile_check(profiles, values)
        read_profiles(root)  # Refused when damaged: never fall back to {}
        for pn in sign:
            if pn not in profiles:
                raise Refused("The profile to sign is not in the profiles.")
            hp.profile_sign(root, pn, profiles[pn])
        for pn in tombstone:
            hp.profile_sign(root, pn, None)
        hp._write_private(d / "profiles.toml", _toml(profiles))


def read_profiles(root: Path) -> dict:
    """The profiles ({} when none yet). Unreadable or invalid: Refused."""
    d = _existing_dir(root)
    if d is None:
        return {}
    try:
        raw = tomllib.loads(_read(d / "profiles.toml").decode("utf-8"))
    except FileNotFoundError:
        return {}
    except (ValueError, UnicodeDecodeError):
        raise Refused("The profiles file is damaged.") from None
    if raw.get("schema") != PROFILES_SCHEMA or set(raw) - {"schema", "profile"}:
        raise Refused("The profiles file is damaged.")
    profiles = raw.get("profile", {})
    _profile_check(profiles, set())
    return profiles


def read_verified_profiles(root: Path) -> dict:
    """The profiles whose body carries a current MAC of a person (human key, guarded ledger). Any profile
    without one, or with a body edited outside orch, is refused (fail closed, no legacy profiles)."""
    profiles = read_profiles(root)
    for pn, p in profiles.items():
        if not hp.profile_verified(root, pn, p):
            raise Refused("Refused: " + hp.PROFILE_CHANGED + ".")
    return profiles


# ------------------------------------------------------------------------------------------- records


def _record_path(d: Path, record: str) -> Path:
    if record not in RECORDS:
        raise Refused("Unknown record.")
    return d / f"{record}.json"


def record_write(root: Path, record: str, data: dict) -> None:
    """A small record of orch itself in the key folder (e.g. `relay`: {url, workspace, token, ...}, written by
    relay.connect). One file, new file + rename under keys.lock."""
    if not isinstance(data, dict):
        raise Refused("A record is an object.")
    d = hp.key_dir(root)
    path = _record_path(d, record)
    with hp._key_lock(d):
        hp._write_private(path, json.dumps(data, indent=2) + "\n")


def record_read(root: Path, record: str) -> dict | None:
    """The record, or None when there is none. A damaged one is Refused, never guessed."""
    d = _existing_dir(root)
    if d is None:
        return None
    data = hp._read_json(root, _record_path(d, record), None)
    if data is not None and not isinstance(data, dict):
        raise Refused("A record in the orch folder is unreadable.")
    return data


def all_needles(root: Path) -> dict[str, str | dict | list]:
    """Every stored value, including shadowed admin keys, for output hiding."""
    d = _existing_dir(root)
    if d is None:
        return {}
    mine, theirs = _load(d), _load(d, admin=True)
    out = {}
    for entries, admin in ((mine, False), (theirs, True)):
        for name, entry in entries.items():
            label = name + "#admin" if admin and name in mine else name
            if entry["type"] == "key-file":
                try:
                    raw = _read(d / "files" / _name(name), FILE_MAX + 1)
                except FileNotFoundError:
                    continue
                try:
                    value = raw.decode("utf-8")
                except UnicodeDecodeError:  # a binary file: its text encodings are what can show up
                    import base64

                    value = [
                        raw.hex(),
                        base64.b64encode(raw).decode(),
                        base64.urlsafe_b64encode(raw).decode(),
                    ]
            else:
                value = entry.get("value")
                if not isinstance(value, str):
                    raise Refused("The key file is damaged.")
                if entry["type"] == "json":
                    try:
                        value = json.loads(value)
                    except ValueError:
                        raise Refused("The key file is damaged.") from None
                    if not isinstance(value, dict):
                        raise Refused("The key file is damaged.")
            out[label] = value
    return out

"""The guarded orch home: the account's orch folder, the key folder of one workspace path, private files
written and read under the rights rule, and the install kind (normal, dev or test).

An agent that reads the orch home directly is outside this module's promise: it stops flags, environment,
workspace files and copies, not a hostile process of the same user.

Windows: POSIX rights (0700/0600) do not exist there. orch.winacl does the same job: a user+SYSTEM-only ACL
(no inheritance) is set when a folder or file is made and checked on every read, and a link, junction or other
reparse point anywhere on the path is refused (#405).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import stat
import sys
import threading
import time
from pathlib import Path

from orch import saferead, winacl
from orch.errors import Refused

NOT_TOGETHER = "home_pairing"  # the code, for tests and logs; people read the plain texts below
MSG_HOME_PLACE = (
    "orch will not use that folder as its home (it is a shared or system place, or outside your profile). "
    "Use the default orch folder in your own account."
)
MSG_OTHER_HOME = (
    "This workspace uses a different orch folder than your account's. "
    "Start orch normally (without ORCH_HOME) to approve things here."
)
MSG_LINKED_HOME = (
    "orch's folder in your account is a link to somewhere else, so orch won't trust it. "
    "Move the real folder back to {path}."
)
MSG_ENV_CHANGE = (
    "orch is set up to use a different orch folder than your account's, so it will not change its own "
    "install from here. Start orch normally (without ORCH_HOME) to update it or add things."
)
MSG_TEST_WS = "This is a test workspace; start it with its own test orch folder."
MSG_TEST_INSTALL = "This is a test install of orch; it only works in test folders."


class HomeRefused(Refused):
    code = NOT_TOGETHER


WRONG_RIGHTS = "Refused: the key folder has the wrong rights. Fix: orch doctor"
POSIX = os.name == "posix"


# ---------------------------------------- guarded orch home


def account_home() -> Path:
    """The account's home from the account database (never $HOME). Goes through addons.real_home, which the
    test suite fakes, so tests never touch the real orch home."""
    from orch import addons

    return addons.real_home()  # Windows: the profile folder from the process token, never the environment


def _source_tree() -> bool:
    here = Path(__file__).resolve()
    return (here.parents[2] / "pyproject.toml").is_file() and here.parent.name == "orch"


INSTALL_KINDS = ("normal", "dev", "test")


def install_record_path() -> Path:
    return Path(os.path.realpath(sys.prefix)) / "orch-install.json"


def read_install_record() -> str | None:
    """The kind the installer wrote into orch's own tool environment, or None. The record counts only when
    it sits in the running interpreter's environment AND its "root" is that environment's real path (an
    old, copied or planted record, or one for another environment, is ignored). No `uv` and no environment
    variable decides."""
    here = Path(os.path.realpath(sys.prefix))
    try:
        raw = saferead.read_private(here, "orch-install.json", 4096)
        data = json.loads(raw) if raw is not None else None
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("kind") not in INSTALL_KINDS:
        return None
    root = data.get("root")
    if not isinstance(root, str) or os.path.realpath(root) != str(here):
        return None
    return data["kind"]


def install_record_text(kind: str, root: str | Path) -> str:
    """The record's text, as install.sh / install.ps1 write it after `uv tool install` (orch.install/1):
    root = the real path of the tool environment at install time."""
    if kind not in INSTALL_KINDS:
        raise ValueError("kind must be normal, dev or test")
    body = {"schema": "orch.install/1", "kind": kind, "root": os.path.realpath(root)}
    return json.dumps(body, sort_keys=True) + "\n"


def write_install_record(env_dir: Path, kind: str) -> None:
    """Only for the update that reinstalls the tool environment (which drops the record): it carries over the
    kind the installer wrote, never a new one. No orch command takes a kind from its caller."""
    # Not a secret (the installer writes it with a plain write too) and it lives in the uv tool
    # folder, outside every guarded orch home: so NO rights change here (the scope guard would refuse it).
    _write_private(Path(env_dir) / "orch-install.json", install_record_text(kind, env_dir), private=False)


def install_kind() -> str:
    """normal | dev | test. The installer's record in orch's own tool environment decides; with no record a
    source-tree run (the test suite) is `test` and any other install is `normal`."""
    kind = read_install_record()
    if kind:
        return kind
    return "test" if _source_tree() else "normal"


def _is_windows() -> bool:
    return os.name == "nt"


def _parts(path: str) -> list[str]:
    """Path components for comparing. Windows: both separators, and case-insensitive (the file system is)."""
    if _is_windows():
        return [x.lower() for x in str(path).replace("\\", "/").split("/") if x]
    return [x for x in str(path).split("/") if x]


def _same(a: str, b: str) -> bool:
    return _parts(a) == _parts(b)


def _under(path: str, prefix: str) -> bool:
    """Component-wise: is `path` inside `prefix` (absolute paths; the prefix itself is not inside itself)?"""
    pp, xp = _parts(path), _parts(prefix)
    return len(pp) > len(xp) and pp[: len(xp)] == xp


def _join(account, name: str) -> str:
    return str(account).rstrip("/\\") + "/" + name


def home_ok(
    account: str, install: str, prefix_real_dir: bool, workspace_realpath: str, home_realpath: str
) -> bool:
    """Reference `home_ok` (secrets.md, vectors `home`): a real workspace pairs only with the default home, a
    test workspace (dev/test install, realpath under the literal <account home>/.orch-test) only with a
    test home. On Windows the account home is the profile folder and components compare case-insensitively."""
    prefix = _join(account, ".orch-test")
    active = install in ("dev", "test") and prefix_real_dir
    ws_test = active and _under(workspace_realpath, prefix)
    if _same(home_realpath, _join(account, ".orch-tool")):
        home = "default"
    elif active and _under(home_realpath, prefix):
        home = "test"
    else:
        home = "other"
    return (not ws_test and home == "default") or (ws_test and home == "test")


REPARSE = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT: a junction or symlink


def _lstat(p: Path):
    return p.lstat()


def _prefix_is_real_dir(account: Path) -> bool:
    """<account home>/.orch-test lstat's as a real folder (no link, no reparse point) owned by the user."""
    try:
        st = _lstat(Path(account) / ".orch-test")
    except OSError:
        return False
    if not stat.S_ISDIR(st.st_mode):
        return False
    if _is_windows():
        return not getattr(st, "st_file_attributes", 0) & REPARSE
    return st.st_uid == os.getuid()


def guarded_home(root: Path) -> Path:
    """The orch home that guards this workspace, or Refused. A real workspace uses only <account>/.orch-tool;
    a test workspace (dev/test install, under ~/.orch-test) only the test home from ORCH_HOME (else
    HOME/.orch-tool). Any other pairing is refused, with no fallback in either direction."""
    account = account_home()
    acct = str(account)
    install = install_kind()
    real_dir = _prefix_is_real_dir(account)
    ws_real = os.path.realpath(root)
    ws_test = install in ("dev", "test") and real_dir and _under(ws_real, _join(acct, ".orch-test"))
    if ws_test:
        env = os.environ.get("ORCH_HOME")
        cand = Path(env) if env else Path(os.environ.get("HOME", "")) / ".orch-tool"
        home_real = os.path.realpath(cand)
    else:
        if install == "test":
            # A source-tree/test run never touches the account's real orch home (owner rule). Children of the
            # test suite (subprocess tests) reach here with the real pwd home, so this must refuse, not fake.
            raise HomeRefused(MSG_TEST_INSTALL)
        cand = account / ".orch-tool"
        home_real = _join(acct, ".orch-tool")
        env = os.environ.get("ORCH_HOME")
        # a real workspace pairs only with the default home: another home refuses, never a fallback
        if env and not _same(os.path.realpath(env), home_real):
            raise HomeRefused(MSG_OTHER_HOME)
        if cand.is_symlink():  # the default folder is a link: never followed
            raise HomeRefused(MSG_LINKED_HOME.format(path=cand))
    if not home_ok(acct, install, real_dir, ws_real, home_real):
        raise HomeRefused(MSG_TEST_WS if ws_test else MSG_OTHER_HOME)
    try:
        winacl.allow_home(cand)  # Windows: rights are written only inside this home (not cwd, Public)
    except Refused:
        raise HomeRefused(MSG_HOME_PLACE) from None
    return cand


# ---------------------------------------- folders, files, lock


class LooseFile(Refused):
    """A secret or integrity file with wider rights than 0600, another owner, or not a plain file. Its
    content is never trusted: callers answer with reset_protection()."""


# Extra per-platform checks (Windows ACL: user + SYSTEM only, from the winacl hook): path -> reason|None.
FILE_CHECKS: list = [winacl.file_check]


def _check_dir(p: Path) -> None:
    """A folder must be a real folder of ours. Loose rights are tightened to 0700 (no friction); a link or
    another owner cannot be fixed and is refused."""
    try:
        st = p.lstat()
    except OSError as e:
        raise Refused(WRONG_RIGHTS) from e
    if not stat.S_ISDIR(st.st_mode):
        raise Refused(WRONG_RIGHTS)
    if POSIX:
        if st.st_uid != os.getuid():
            raise Refused(WRONG_RIGHTS)
        if st.st_mode & 0o077:
            p.chmod(0o700)
    winacl.ensure_private(p)  # Windows only: a folder of this user is tightened, else refused


def file_problem(p: Path) -> str | None:
    """Why a secret/integrity file is loose (mode | owner | type | acl), or None. FileNotFoundError passes."""
    st = p.lstat()
    if not stat.S_ISREG(st.st_mode):
        return "type"
    if POSIX and st.st_uid != os.getuid():
        return "owner"
    if POSIX and st.st_mode & 0o077:
        return "mode"
    for chk in FILE_CHECKS:
        why = chk(p)
        if why:
            return why
    return None


def _check_file(p: Path) -> None:
    why = file_problem(p)
    if why == "unknown":  # Windows could not tell: refuse this call, reset nothing
        raise Refused("Windows would not tell the rights of a protected file. Try again.")
    if why:
        raise LooseFile(f"{p.name}:{why}")


def _home_of(path: Path) -> tuple[Path, str]:
    """(guarded home, relative path) of a file in the guarded home: keys/<id>/x."""
    parts = path.parts
    i = parts.index("keys") if "keys" in parts else len(parts) - 1
    return Path(os.path.realpath(Path(*parts[:i]))), "/".join(parts[i:])


MAX_READ = 1 << 20


def _read_guarded(path: Path) -> bytes:
    """The bytes of a secret or integrity file. FileNotFoundError when it is not there; LooseFile when its
    rights, owner or type are wrong, or saferead.read_private refuses it (link, FIFO, hard link, swap)."""
    _check_file(path)
    base, rel = _home_of(path)
    data = saferead.read_private(base, rel, MAX_READ)
    if data is None:
        _read_refused(path)
    return data


def _read_refused(path: Path) -> None:
    """read_private said None. A real finding (loose rights, a link, a special file, a second name, too big)
    is a LooseFile: the caller resets the protection. On Windows, when the file passes every check and still
    could not be read (a transient error), refuse this call only: winacl.Unknown, no reset."""
    why = file_problem(path)
    if why == "unknown":
        raise winacl.Unknown("Windows would not tell the rights of a protected file. Try again.")
    if why is None and winacl._windows():
        st = path.lstat()
        if stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_size <= MAX_READ:
            raise winacl.Unknown("Windows would not let orch read a protected file. Try again.")
    raise LooseFile(f"{path.name}:{why or 'read'}")


def _private_dir(p: Path, stop: Path) -> None:
    """Create p (and parents below `stop`) with 0700, then check each; a link anywhere below `stop` is
    refused."""
    chain = [c for c in [p, *p.parents] if c != stop and stop in c.parents][::-1]
    for c in chain:
        if not c.exists() and not c.is_symlink():
            c.mkdir(mode=0o700)
            if POSIX:
                c.chmod(0o700)
            winacl.set_private(c, True)
        _check_dir(c)


def _decide(home: Path, ws: str | None, bound: list[str]) -> tuple[str | None, bool]:
    """(id to use, healed) from the .local-id `ws` (valid or None) and the folders bound to this path.
    A valid id is kept unless it names no existing folder while exactly ONE other folder is bound (then the
    bound id is put back). Refused: two or more bound folders, or an id naming a DIFFERENT EXISTING folder."""
    others = [n for n in bound if n != ws]
    if ws is None:
        if len(bound) > 1:
            raise Refused(SECOND_FOLDER)
        return (bound[0], True) if bound else (None, False)
    if not others:
        return ws, False
    keys = home / "keys" / ws
    if len(others) == 1 and ws not in bound and not keys.exists() and not keys.is_symlink():
        return others[0], True
    raise Refused(SECOND_FOLDER)


def _resolve(root: Path, home: Path) -> tuple[str | None, list[str]]:
    """The workspace id and the bound folders, healing a lost, damaged or stale .local-id from the trusted
    home. Creates no folder and no fresh id."""
    from orch import addons

    own = addons.read_local_id(root)
    bound = _bound_folders(root, home, own)
    ws, healed = _decide(home, own, bound)
    if healed:
        addons.put_local_id(root, ws, replace=True)
    return ws, bound


def key_dir(root: Path, create: bool = True) -> Path:
    """<guarded home>/keys/<workspace local id>/ (0700). A real path has exactly one key folder."""
    from orch import addons

    home = guarded_home(root)
    winacl.no_reparse(home)  # a symlink or junction below the profile folder (Windows)
    ws, bound = _resolve(root, home)
    if ws is None and not create:
        raise Refused("This folder has no local id yet.")
    if create:
        fresh = not home.exists()
        home.mkdir(parents=True, exist_ok=True)
        if fresh:
            winacl.set_private(home, True)
        _check_dir(home)
        _private_dir(home / "keys", home)
        with _folders_lock(home / "keys"):  # id, check, mkdir and bind are one step: two first starts cannot
            ws, bound = _resolve(root, home)  # both bind (read again under the lock)
            if ws is None:
                ws = addons.put_local_id(root, secrets.token_hex(16))
            d = home / "keys" / ws
            try:
                d.mkdir(mode=0o700)
                if POSIX:
                    d.chmod(0o700)
                fresh = True
            except FileExistsError:
                fresh = False
            _check_dir(d)
            if fresh or not any(d.iterdir()):  # the binding is made only while the folder is new or empty
                _bind_new(root, d)
    else:
        d = home / "keys" / ws
        _check_dir(home)
        _check_dir(home / "keys")  # no link or loose rights anywhere on the path
        _check_dir(d)
    _check_binding(root, d)
    return d


def _healed_id(root: Path, create: bool) -> str:
    """The workspace id as healed and bound by key_dir (the name of its key folder). A MAC uses this id, never
    the raw .local-id read before healing. Refused when there is none."""
    return key_dir(root, create=create).name


BINDING_MISMATCH = (
    "Refused: this folder's key id belongs to another folder (it was copied or moved). "
    "Its keys stay where they are."
)
SECOND_FOLDER = (
    "Refused: this workspace's id was changed; its keys are in another key folder. "
    "Put back the workspace id, or ask the owner."
)
TRY_AGAIN = "orch could not check the key folders just now. Try again; if it keeps happening, ask the owner."


def _try_again(name: str) -> str:
    return (
        f"orch could not read the binding of key folder {name} just now. "
        "Try again; if it keeps happening, ask the owner."
    )


_BINDINGS: dict = {}  # per process: binding.json path -> (file identity, the realpath it names)


def _binding_realpath(f: Path):
    """The `realpath` a binding.json names. Read again only when the file's identity (device, inode, times,
    size, mode, owner, links) changed, so a swapped or edited file is always read afresh; every failure path
    is the uncached one (never cached)."""
    st = f.lstat()
    if not POSIX:  # file ids are not reliable on Windows: always read afresh
        return json.loads(_read_guarded(f).decode("utf-8")).get("realpath")
    ident = (
        st.st_dev,
        st.st_ino,
        st.st_mtime_ns,
        st.st_ctime_ns,
        st.st_size,
        st.st_mode,
        st.st_uid,
        st.st_nlink,
    )
    hit = _BINDINGS.get(str(f))
    if hit is not None and hit[0] == ident:
        return hit[1]
    stored = json.loads(_read_guarded(f).decode("utf-8")).get("realpath")
    if len(_BINDINGS) > 512:
        _BINDINGS.clear()
    _BINDINGS[str(f)] = (ident, stored)
    return stored


def _bound_folders(root: Path, home: Path, own: str | None = None) -> list[str]:
    """Names of the key folders in `home` whose binding.json names this workspace's real path (identity by
    samefile where both exist, else equal real paths). A folder with no or a damaged binding names nothing."""
    keys = home / "keys"
    here = os.path.realpath(root)
    out: list[str] = []
    if keys.is_symlink() or keys.exists():
        _check_dir(keys)  # a link or a foreign keys/ is refused here, before anything is listed through it
    try:
        names = sorted(os.listdir(keys))
    except FileNotFoundError:
        return out
    except OSError:
        raise Refused(TRY_AGAIN) from None
    for name in names:
        try:
            if not stat.S_ISDIR((keys / name).lstat().st_mode):  # keys.lock and the like
                continue
            stored = _binding_realpath(keys / name / "binding.json")
        except FileNotFoundError:  # no binding.json: bound to nothing
            continue
        except (ValueError, AttributeError):  # garbage JSON: bound to nothing
            continue
        except (winacl.Unknown, OSError, Refused):  # cannot be told: fail closed, never "not bound"
            if name == own:
                continue  # this workspace's own folder: _check_binding refuses it with its own words below
            raise Refused(_try_again(name)) from None
        if not isinstance(stored, str):
            continue
        try:
            same = stored == here or os.path.samefile(stored, here)
        except OSError:
            same = os.path.realpath(stored) == here
        if same:
            out.append(name)
    return out


def _bind_new(root: Path, d: Path) -> None:
    """Record the workspace's real path as binding.json in the new key folder: written to a temp file and
    linked into place, so it appears whole and only if none exists (the first writer wins)."""
    f = d / "binding.json"
    tmp = d / f".binding.{secrets.token_hex(4)}.tmp"
    try:
        _write_private(
            tmp, json.dumps({"schema": "orch.binding/1", "realpath": os.path.realpath(root)}) + "\n"
        )
        with contextlib.suppress(FileExistsError):
            os.link(tmp, f)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def _check_binding(root: Path, d: Path) -> None:
    """The workspace's local id (workspace-writable, so not trusted alone) must be bound to this workspace's
    real path in the guarded home (binding.json, 0600): a mismatch is refused (N17). A key folder WITHOUT a
    binding is refused too: orch never binds a folder that already exists (no trust on first use); a person
    reconnects the workspace instead. The stored folder is compared by identity (samefile), so a case change
    on macOS is the same folder, while a copy (another folder, same id) or a move is refused."""
    f = d / "binding.json"
    here = os.path.realpath(root)
    try:
        stored = json.loads(_read_guarded(f).decode("utf-8")).get("realpath")
    except FileNotFoundError:
        raise Refused(BINDING_MISMATCH) from None
    except (LooseFile, winacl.Unknown):
        # a loose or unreadable binding refuses: a reset cannot repair it (the folder is not re-bound),
        # so there is no reset and nothing is written; the person reconnects the workspace
        raise Refused(BINDING_MISMATCH) from None
    except (ValueError, AttributeError):
        raise Refused("A record in the orch folder is unreadable.") from None
    if not isinstance(stored, str):
        raise Refused("A record in the orch folder is unreadable.")
    if stored == here:
        return
    try:
        same = os.path.samefile(stored, here)
    except OSError:
        same = False
    if not same:
        raise Refused(BINDING_MISMATCH)


def _write_private(path: Path, text: str, *, private: bool = True) -> None:
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            if private:
                winacl.set_private(tmp, False)  # before any secret is written (Windows)
            f.write(text)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


_LOCKS = threading.local()


def _lock_held(d: Path, name: str = "keys.lock") -> bool:
    return getattr(_LOCKS, "held", {}).get((str(d), name), 0) > 0


@contextlib.contextmanager
def _key_lock(d: Path):
    """keys.lock (O_EXCL) around read-modify-write of the nonce store, delivered ids, settings and resets.
    Re-entrant in the same thread (reset_protection runs inside readers that already hold it)."""
    with _file_lock(d, "keys.lock"):
        yield


@contextlib.contextmanager
def _folders_lock(keys: Path):
    """folders.lock in keys/ around "one key folder per path": id, check, mkdir and bind are one step, so two
    first starts cannot both bind. A different lock from a key folder's own keys.lock."""
    with _file_lock(keys, "folders.lock"):
        yield


@contextlib.contextmanager
def _file_lock(d: Path, name: str):
    """The O_EXCL lock file `name` in `d`, re-entrant in the same thread."""
    held = _LOCKS.__dict__.setdefault("held", {})
    k = (str(d), name)
    if held.get(k, 0) > 0:
        held[k] += 1
        try:
            yield
        finally:
            held[k] -= 1
        return
    lock = d / name
    end = time.monotonic() + 10
    while True:
        try:
            os.close(os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            break
        except FileExistsError:
            with contextlib.suppress(OSError):
                if time.time() - lock.stat().st_mtime > 30:  # a crashed holder
                    lock.unlink()
                    continue
            if time.monotonic() > end:
                raise Refused("The key store is busy. Try again.") from None
            time.sleep(0.02)
    held[k] = 1
    try:
        yield
    finally:
        held.pop(k, None)
        with contextlib.suppress(OSError):
            lock.unlink()


def _read_json(root: Path, path: Path, default):
    try:
        return json.loads(_read_guarded(path))
    except FileNotFoundError:
        return default
    except LooseFile as e:  # never trusted: reset the protection, the store starts empty
        reset_protection(root, str(e))
        return default
    except ValueError as e:
        raise Refused("A record in the orch folder is unreadable.") from e


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def reset_protection(root: Path, reason: str) -> None:
    """The response to a loose secret or integrity file: log a line with no secret (a file name and a kind,
    never a value). Never a silent chmod of a secret file. Takes keys.lock itself (re-entrant)."""
    home = guarded_home(root)
    d = key_dir(root)  # never a folder of its own: one key folder per real path
    ws = d.name
    with _key_lock(d):
        safe = re.sub(r"[^A-Za-z0-9_.:-]", "_", reason)[:80]
        with contextlib.suppress(OSError):
            fd = os.open(home / "protection-reset.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(f"{_now()} workspace={ws} reset: {safe}\n")


# The relay ALLOW BINDING (guarded home): keys/<ws>/relay-allow.json holds, per "<ticket>:<question>", the
# allow_message id this core asked about when it made the relay:allow question HERE, and whether that answer
# was applied. The ticket's ext.relay (allow_message, allow_applied) is synced, so a peer can swap the message
# or reset "applied"; only this binding decides which message an answer allows, and only once. A plain file:
# an older entry's extra fields (a mac) are ignored.
RELAY_ALLOW = "relay-allow.json"


def _entries_load(root: Path, name: str) -> dict | None:
    """The entries of store file `name`: {} when there is none yet, None when it cannot be trusted (damaged
    or loose). A reader never resets protection (no DoS by chmod)."""
    try:
        d = key_dir(root, create=False)
        try:
            data = json.loads(_read_guarded(d / name))
        except FileNotFoundError:
            data = {"entries": {}}
    except (Refused, OSError, ValueError):  # incl. LooseFile
        return None
    ent = data.get("entries") if isinstance(data, dict) else None
    return ent if isinstance(ent, dict) else None


def relay_allow_get(root: Path, ticket: str, question: str) -> dict | None:
    """{"message", "applied"} recorded here for this question, or None (none, or it cannot be told)."""
    ent = _entries_load(root, RELAY_ALLOW)
    e = ent.get(f"{ticket}:{question}") if ent is not None else None
    if not isinstance(e, dict) or not isinstance(e.get("message"), str):
        return None
    return e if isinstance(e.get("applied"), bool) else None


def relay_allow_set(root: Path, ticket: str, question: str, message: str, applied: bool = False) -> bool:
    """Record the question's message (when asked) or mark it applied. A recorded message is never replaced by
    another one and "applied" never goes back. False when it could not be written."""
    if not all(isinstance(x, str) and x for x in (ticket, question, message)):
        return False
    try:
        d = key_dir(root)
        with _key_lock(d):
            ent = _entries_load(root, RELAY_ALLOW)
            if ent is None:
                return False
            key = f"{ticket}:{question}"
            old = ent.get(key)
            if isinstance(old, dict):
                if old.get("message") != message:
                    return False
                applied = applied or old.get("applied") is True
            ent[key] = {"message": message, "applied": applied}
            _write_private(d / RELAY_ALLOW, json.dumps({"schema": "orch.relay-allow/1", "entries": ent}))
        return True
    except (Refused, OSError):
        return False

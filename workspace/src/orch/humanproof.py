"""Human proof (invariant H1, contracts/human-proof.md): the guarded orch home, the human key, hp1 proofs,
widening-settings records, pending-input MACs and the won't-do MAC.

Level 1 (owner decision R1): an agent that reads the orch home directly is outside this module's promise.
It stops
flags, environment, workspace files and copies, not a hostile process of the same user.

Windows: POSIX rights (0700/0600) do not exist there. orch.winacl does the same job: a user+SYSTEM-only ACL
(no inheritance) is set when a folder or file is made and checked on every read, and a link, junction or other
reparse point anywhere on the path is refused (#405).
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import sys
import threading
import time
from pathlib import Path

from orch import saferead, term, winacl, winfinish
from orch.errors import Refused

# Switch for the read-back rule in runs.human_waiting (supervisor 9 Nov): OFF = a line counts as a person's by
# the old by/via allowlist; ON (since 1.0a-2) = only with a valid pending MAC.
# A module constant on purpose: not an env var, not a workspace file.
ENFORCE_PENDING_MAC = True

HP_MAX_LIFE = 60
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

OPS = frozenset(
    "run.takeover run.type run.release focus.settings insights.settings record.delete_detail secret.add "
    "secret.remove secret.profile conn.allow checkup.accept checkup.rollback checkup.send_to_admin "
    "checkup.reject ticket.verdict ticket.answer relay.connect private.allow private.move config.agent_add "
    "check.wont_do check.wont_do_undo chat.make_ticket chat.send chat.sync chat.contacts chat.thread_sync "
    "update run.stop relay.allow group.remove_member group.write_as_person group.share_file "
    "group.readd_member config.share config.agents_may_finish look.shared_pages ticket.finish "
    "run.human_input addon.act addon.add_local config.permissions look.icon config.copy_setup "
    "copy.remove_orphaned copy.retry".split()
)
SETTING_DEFAULTS = {
    "focus.live_session": True,
    "focus.session_typing": False,
    "insights.share_counts": True,
    "insights.share_names": False,
    "secret.allow_get": False,
    "conn.allow": False,
    "workflow.agents_may_finish": False,
}
_TARGET_RE = re.compile(r"[A-Za-z0-9_.:@-]+")
_BY_RE = re.compile(r"human:[^\x00-\x1f]{1,58}")
_NONCE_RE = re.compile(r"[A-Za-z0-9_-]{22}")
PENDING_MAC_KINDS = ("answer", "message", "text")


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


# ---------------------------------------- guarded orch home


def account_home() -> Path:
    """The account's home from the account database (never $HOME). Goes through addons.real_home, which the
    test suite fakes, so tests never touch the real orch home."""
    from orch import addons

    if _is_windows():  # the profile folder from the process token (winacl), never the environment
        try:
            return Path(winacl.profile_dir())
        except (ImportError, AttributeError, OSError, Refused):
            pass
    return addons.real_home()


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
SAFE_DEFAULTS = {
    "focus.session_typing": False,
    "insights.share_names": False,
    "secret.allow_get": False,
    "conn.allow": False,
}  # live_session and share_counts stay at the owner defaults (3C, I5): their records are dropped
RESET_NOTICE = "orch reset its protection on this computer; please turn on again what you need."
_SECRET_FILES = (
    "proofs-used.json",
    "delivered.json",
    "handoffs.json",
    "wont.json",
    "verdict.json",
)  # the ledgers go with the key they were signed with


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
    """(guarded home, relative path) of a file in the guarded home: keys/<id>/x or human-settings.json."""
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


def key_dir(root: Path, create: bool = True) -> Path:
    """<guarded home>/keys/<workspace local id>/ (0700)."""
    from orch import addons

    home = guarded_home(root)
    winacl.no_reparse(home)  # a symlink or junction below the profile folder (Windows)
    ws = addons.workspace_id(root, create=create)
    if ws is None:
        raise Refused("This folder has no local id yet.")
    d = home / "keys" / ws
    if create:
        fresh = not home.exists()
        home.mkdir(parents=True, exist_ok=True)
        if fresh:
            winacl.set_private(home, True)
        _check_dir(home)
        _private_dir(d.parent, home)
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
        _check_dir(home)
        _check_dir(home / "keys")  # no link or loose rights anywhere on the path
        _check_dir(d)
    _check_binding(root, d)
    return d


BINDING_MISMATCH = (
    "Refused: this folder's key id belongs to another folder (it was copied or moved). "
    "Its keys stay where they are."
)


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
_RESETS = 0  # count of reset_protection runs in this process: a verify that saw one is refused


def _lock_held(d: Path) -> bool:
    return getattr(_LOCKS, "held", {}).get(str(d), 0) > 0


@contextlib.contextmanager
def _key_lock(d: Path):
    """keys.lock (O_EXCL) around read-modify-write of the nonce store, delivered ids, settings and resets.
    Re-entrant in the same thread (reset_protection runs inside readers that already hold it)."""
    held = _LOCKS.__dict__.setdefault("held", {})
    if held.get(str(d), 0) > 0:
        held[str(d)] += 1
        try:
            yield
        finally:
            held[str(d)] -= 1
        return
    lock = d / "keys.lock"
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
    held[str(d)] = 1
    try:
        yield
    finally:
        held.pop(str(d), None)
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


# ------------------------------------------------------------------------------------------- human key


def human_key(root: Path, create: bool = True) -> bytes:
    """The workspace's human key (32 random bytes, hex in the file, 0600). Created on first use. Never put in
    argv, environment, the workspace or a log."""
    d = key_dir(root, create=create)
    f = d / "human.key"
    with _key_lock(d) if create else contextlib.nullcontext():
        try:
            try:
                raw = _read_guarded(f)
            except (
                LooseFile
            ) as e:  # a loose key is never read: rotate it (old proofs and MACs stop verifying)
                reset_protection(root, str(e))
                raw = _read_guarded(f)
            hexkey = raw.decode("utf-8", "replace").strip()
        except FileNotFoundError:
            if not create:
                raise Refused("There is no human key here yet.") from None
            hexkey = secrets.token_hex(32)
            _write_private(f, hexkey + "\n")
    try:
        key = bytes.fromhex(hexkey)
    except ValueError as e:
        raise Refused("The human key file is damaged.") from e
    if len(key) != 32:
        raise Refused("The human key file is damaged.")
    return key


# ------------------------------------------------------------------------------------------- hp1 proofs


def mint(key: bytes, payload: dict) -> str:
    body = "hp1." + _b64u(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    return body + "." + _b64u(hmac.new(key, body.encode(), hashlib.sha256).digest())


def new_payload(op: str, target: str, by: str, now: int | None = None, life: int = 30) -> dict:
    now = int(time.time()) if now is None else now
    return {
        "op": op,
        "target": target,
        "by": by,
        "iat": now,
        "exp": now + min(life, HP_MAX_LIFE),
        "nonce": _b64u(secrets.token_bytes(16)),
    }


def _payload_ok(p) -> bool:
    if not isinstance(p, dict):
        return False
    req = {"op", "target", "by", "iat", "exp", "nonce"}
    if not req <= set(p) or not set(p) <= req | {"dev"}:
        return False
    if "dev" in p and p["dev"] is not True:
        return False
    return (
        p["op"] in OPS
        and isinstance(p["target"], str)
        and 1 <= len(p["target"]) <= 128
        and _TARGET_RE.fullmatch(p["target"]) is not None
        and isinstance(p["by"], str)
        and _BY_RE.fullmatch(p["by"]) is not None
        and all(isinstance(p[k], int) and not isinstance(p[k], bool) and p[k] >= 0 for k in ("iat", "exp"))
        and isinstance(p["nonce"], str)
        and _NONCE_RE.fullmatch(p["nonce"]) is not None
    )


def _decode(part: str):
    try:
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except ValueError:
        return None


def check_proof(
    proof,
    *,
    key_hex: str | None,
    op: str,
    target: str,
    now: int,
    by_flag: str | None = None,
    agent_env: bool = False,
    used_nonces=(),
    home_trusted: bool = True,
    dev_record: bool = False,
    dev_key: str | None = None,
) -> str:
    """Pure check (reference hp_verify). Returns ok | agent_env | forged | missing | dev_on_real | wrong_op |
    wrong_target | expired | replayed. Flags and the environment are never trusted."""
    if agent_env:
        return "agent_env"
    if not home_trusted:
        return "forged"
    if not proof or not isinstance(proof, str):
        return "missing"
    parts = proof.split(".")
    if len(parts) != 3 or parts[0] != "hp1":
        return "forged"
    p = _decode(parts[1])
    if not _payload_ok(p):
        return "forged"
    if p.get("dev"):
        if not dev_record:
            return "dev_on_real"
        key = dev_key
        if not key or p["by"] != "human:test-human":
            return "forged"
    else:
        key = key_hex
    try:
        kb = bytes.fromhex(key or "")
    except ValueError:
        return "forged"
    if not kb:
        return "forged"
    want = _b64u(hmac.new(kb, f"hp1.{parts[1]}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(want, parts[2]):
        return "forged"
    if by_flag is not None and by_flag != p["by"]:
        return "forged"
    if p["op"] != op:
        return "wrong_op"
    if p["target"] != target:
        return "wrong_target"
    if p["exp"] - p["iat"] > HP_MAX_LIFE or not p["iat"] <= now < p["exp"]:
        return "expired"
    if p["nonce"] in used_nonces:
        return "replayed"
    return "ok"


def verify_and_consume(root: Path, proof, op: str, target: str, by_flag: str | None = None) -> str:
    """Verify a proof against this workspace's key, spend its nonce (single use), return `by` FROM THE PROOF.
    The key and the nonce store are loaded together under keys.lock; if a protection reset happens while they
    are read, the proof is refused (a reset never accepts a proof). Raises
    Refused("Do this in the dashboard on this computer.") on any failure."""
    from orch import tickets

    msg = "Do this in the dashboard on this computer."
    try:
        d = key_dir(root, create=False)
        with _key_lock(d):
            resets = _RESETS
            try:
                key = human_key(root, create=False).hex()
            except (Refused, OSError):
                key = (
                    None  # a dev demo workspace has only the dev key; check_proof refuses non-dev proofs then
                )
            store = d / "proofs-used.json"
            used = _read_json(root, store, {})
            if _RESETS != resets:
                raise Refused(msg)
            if not isinstance(used, dict):
                raise Refused(msg)
            now = int(time.time())
            used = {n: e for n, e in used.items() if isinstance(e, int) and e > now}
            res = check_proof(
                proof,
                key_hex=key,
                op=op,
                target=target,
                now=now,
                by_flag=by_flag,
                agent_env=bool(tickets.agent_tool()),
                used_nonces=used,
                dev_record=dev_workspace(root),
                dev_key=_dev_key_hex(d),
            )
            if res != "ok":
                raise Refused(msg)
            p = _decode(proof.split(".")[1])
            used[p["nonce"]] = p["exp"]
            _write_private(store, json.dumps(used))
    except (Refused, OSError):
        raise Refused(msg) from None
    return p["by"]


# ------------------------------------------------------------------------------------------- settings


def settle(setting: str, events: list[dict]) -> list[bool]:
    """Reference hp_settle. file:v = someone edited the file; proof:v = a person set it with a proof. Lowering
    in the file writes a tombstone (false). Effective = file AND (record, or the default when none
    existed)."""
    default = SETTING_DEFAULTS[setting]
    file_val, record, out = default, None, []
    for ev in events:
        if ev["by"] == "proof":
            file_val = record = ev["value"]
        else:
            file_val = ev["value"]
            if ev["value"] is False:
                record = False
        out.append(bool(file_val and (record if record is not None else default)))
    return out


def _settings_path(root: Path) -> tuple[Path, str]:
    home = guarded_home(root)
    return home / "human-settings.json", hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:32]


def _settings_load(root: Path, path: Path):
    """None when the file never existed; raises Refused when unreadable or damaged (N12: every widening
    off). A loose file is reset (reset_protection) and read again."""
    try:
        try:
            raw = _read_guarded(path)
        except LooseFile as e:
            reset_protection(root, str(e))
            raw = _read_guarded(path)
        data = json.loads(raw)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, Refused) as e:
        raise Refused("The settings record is unreadable.") from e
    if (
        not isinstance(data, dict)
        or data.get("schema") != "orch.human-settings/1"
        or not isinstance(data.get("workspaces"), dict)
    ):
        raise Refused("The settings record is unreadable.")
    return data


def _settings_write(root: Path, setting: str, value, by: str) -> None:
    path, wkey = _settings_path(root)
    d = key_dir(root)  # creates the home; the lock lives in the workspace's key folder
    with _key_lock(d):
        data = _settings_load(root, path) or {"schema": "orch.human-settings/1", "workspaces": {}}
        data["workspaces"].setdefault(wkey, {})[setting] = {
            "value": value,
            "by": by,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _write_private(path, json.dumps(data, indent=2, sort_keys=True))


_CONN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")  # same shape as inventory.NAME_RE


def is_conn_grant_key(setting) -> bool:
    """Exactly `conn.allow.<connection name>` with a well-formed name (no arbitrary suffix)."""
    if not isinstance(setting, str) or not setting.startswith("conn.allow."):
        return False
    return _CONN_NAME_RE.fullmatch(setting[len("conn.allow.") :]) is not None


def is_secret_get_key(setting) -> bool:
    """Exactly a per-profile secret switch (allow_get, agents_may_env)."""
    return (
        isinstance(setting, str)
        and re.fullmatch(r"secret\.(allow_get|agents_may_env)\.[a-z][a-z0-9-]{0,31}", setting) is not None
    )


def record_set(root: Path, setting: str, value, by: str) -> None:
    """THE one writer of a widening setting's record, for every key in SETTING_DEFAULTS. A grant (any value
    but False) needs a person (`by` = the verified human:...); every lowering writes the False tombstone, so
    an old "on" record can never come back. The caller writes this BEFORE the config file, so there is no
    moment where the file says on and the record is stale."""
    if setting not in SETTING_DEFAULTS and not is_conn_grant_key(setting) and not is_secret_get_key(setting):
        raise Refused("That is not a setting a person has to allow.")
    if value is not False and not str(by).startswith("human:"):
        raise Refused(AGENT_REFUSED)
    if value is False and not str(by).startswith("human:"):
        by = "reset"  # a lowering by anyone else: the tombstone names no person
    _settings_write(root, setting, value, by)


def conn_grants(root: Path) -> dict:
    """conn.allow grants recorded with a proof, by connection name ("*" or a list of actions). Unreadable
    record or home = no grants (fail closed)."""
    try:
        path, wkey = _settings_path(root)
        data = _settings_load(root, path)
    except (Refused, OSError):
        return {}
    out = {}
    for key, rec in ((data or {}).get("workspaces", {}).get(wkey) or {}).items():
        if not (key.startswith("conn.allow.") and isinstance(rec, dict)):
            continue
        val = rec.get("value")
        # only "*" or a list of action names is a grant; a tombstone (False) or any other type is none
        if val == "*" or (isinstance(val, list) and all(isinstance(a, str) for a in val)):
            out[key[len("conn.allow.") :]] = val
    return out


def effective(root: Path, setting: str, file_value: bool) -> bool:
    """Effective value of a widening switch: file AND (record, or the owner default when no record ever
    existed). A False in the file writes the tombstone at once. An unreadable home or record = off (N12)."""
    default = SETTING_DEFAULTS.get(setting, False)
    try:
        path, wkey = _settings_path(root)
        data = _settings_load(root, path)
        rec = ((data or {}).get("workspaces", {}).get(wkey) or {}).get(setting)
        rec_val = rec.get("value") if isinstance(rec, dict) else None
        if file_value is False and rec_val is not False:
            _settings_write(root, setting, False, "file")
            rec_val = False
    except (Refused, OSError):
        return False
    return bool(file_value and (rec_val if rec_val is not None else default))


# ------------------------------------------------------------------------------------------- launch token

LAUNCH_SERVERS = ("focus", "dashboard")


def is_test_workspace(root: Path) -> bool:
    """A test install AND a workspace whose realpath is under the literal <account home>/.orch-test (Windows:
    <profile folder>\\.orch-test, case-insensitive)."""
    account = account_home()
    return (
        install_kind() == "test"
        and _prefix_is_real_dir(account)
        and _under(os.path.realpath(root), _join(account, ".orch-test"))
    )


def printable_launch_url(root: Path, server: str, base_url: str) -> str:
    """TEST-ONLY exception to "the launch token is never printed" (human-proof.md): `orch start --no-open
    --print-launch-url`, on a test install and a test workspace only, so the Playwright lane can open a page
    session. Refused everywhere else."""
    if not is_test_workspace(root):
        raise Refused("Printing a launch link works only on a test install, in a test folder.")
    token = write_launch_token(root, server)  # the ONE writer (below): same file, format, 30 s, single use
    if token is None:
        raise Refused("A launch link could not be made.")
    return f"{base_url.rstrip('/')}/#launch={token}"


# ------------------------------------------------------------------------------------------- reset


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def reset_protection(root: Path, reason: str) -> None:
    """ONE response to a loose secret or integrity file (human.key, human-settings.json, proofs-used,
    delivered, handoffs, the dev record): tighten the folders, rotate human.key (old proofs and MACs stop
    verifying), empty the nonce/delivered/handoffs stores, put the widening settings at the safest defaults,
    log a line with no secret and queue a one-time notice for the dashboard. Never a silent chmod of a
    secret file. Takes keys.lock itself (re-entrant: callers may already hold it). A reset never widens
    and never accepts a proof."""
    from orch import addons

    global _RESETS
    home = guarded_home(root)
    ws = addons.workspace_id(root, create=True)
    home.mkdir(parents=True, exist_ok=True)
    _check_dir(home)
    d = home / "keys" / ws
    _private_dir(d, home)
    with _key_lock(d):
        _RESETS += 1
        _write_private(d / "human.key", secrets.token_hex(32) + "\n")  # replaces whatever was there
        for name in _SECRET_FILES:
            with contextlib.suppress(OSError):
                (d / name).unlink()
        _reset_settings(root, home)
        if reason.startswith("dev-workspaces"):
            with contextlib.suppress(OSError):
                (home / "dev-workspaces.json").unlink()
        safe = re.sub(r"[^A-Za-z0-9_.:-]", "_", reason)[:80]  # a file name and a kind, never a value
        with contextlib.suppress(OSError):
            fd = os.open(home / "protection-reset.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(f"{_now()} workspace={ws} reset: {safe}\n")
        with contextlib.suppress(OSError, ValueError):
            nf = d / "notices.json"
            try:
                notes = json.loads(_read_guarded(nf))
            except (FileNotFoundError, LooseFile, ValueError):
                notes = []
            if not any(isinstance(n, dict) and n.get("kind") == "protection_reset" for n in notes):
                at = _now()
                notes.append(
                    {"id": _notice_id("protection_reset", at, RESET_NOTICE), "kind": "protection_reset",
                     "at": at, "text": RESET_NOTICE}
                )  # fmt: skip
                _write_private(nf, json.dumps(notes))


def _reset_settings(root: Path, home: Path) -> None:
    """A reset only ever LOWERS: every record whose value is False (a tombstone, in any workspace) is kept
    whatever the file's rights, anything else is dropped, and the opening settings are written False. A
    record file that exists but cannot be read also closes live_session and share_counts (unreadable=off)."""
    path, wkey = _settings_path(root)
    readable, prior = True, {}
    try:
        os.lstat(path)  # FileNotFoundError: the record never existed
        base, rel = _home_of(path)
        raw = saferead.read_private(base, rel, MAX_READ)  # whatever its rights: only False values are kept
        if raw is None:
            raise ValueError("unreadable")
        data = json.loads(raw)
        if (
            not isinstance(data, dict)
            or data.get("schema") != "orch.human-settings/1"
            or not isinstance(data.get("workspaces"), dict)
        ):
            raise ValueError("shape")
        prior = data["workspaces"]
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        readable = False
    out: dict = {}
    for wk, recs in prior.items():
        if isinstance(recs, dict):
            keep = {k: v for k, v in recs.items() if isinstance(v, dict) and v.get("value") is False}
            if keep:
                out[wk] = keep
    mine = out.setdefault(wkey, {})
    closing = dict(SAFE_DEFAULTS)
    if not readable:
        closing.update({"focus.live_session": False, "insights.share_counts": False})
    for k in closing:
        mine.setdefault(k, {"value": False, "by": "reset", "at": _now()})
    _write_private(
        path, json.dumps({"schema": "orch.human-settings/1", "workspaces": out}, indent=2, sort_keys=True)
    )


def _notice_id(kind: str, at: str, text: str) -> str:
    return hashlib.sha256(f"{kind}|{at}|{text}".encode()).hexdigest()[:12]


def _notices_load(root: Path) -> tuple[Path, list[dict]]:
    nf = key_dir(root, create=False) / "notices.json"
    notes = json.loads(_read_guarded(nf))
    return nf, [n for n in notes if isinstance(n, dict)] if isinstance(notes, list) else []


def read_notices(root: Path) -> list[dict]:
    """The notices for the person (dashboard). Reading NEVER clears them: only the person's "Got it"
    (ack_notice) does, so a page that is reloaded or left before it showed the notice loses nothing."""
    try:
        _, notes = _notices_load(root)
    except (OSError, ValueError, Refused):
        return []
    return [
        {
            "id": n.get("id") or _notice_id(str(n.get("kind")), str(n.get("at")), str(n.get("text"))),
            "kind": str(n.get("kind"))[:40],
            "text": str(n.get("text"))[:600],
        }
        for n in notes
    ]


def ack_notice(root: Path, nid: str) -> bool:
    """The person pressed "Got it": remove that notice (session-only on the page)."""
    try:
        d = key_dir(root, create=False)
        with _key_lock(d):
            nf, notes = _notices_load(root)
            keep = [
                n
                for n in notes
                if (n.get("id") or _notice_id(str(n.get("kind")), str(n.get("at")), str(n.get("text"))))
                != nid
            ]
            if len(keep) == len(notes):
                return False
            if keep:
                _write_private(nf, json.dumps(keep))
            else:
                with contextlib.suppress(OSError):
                    nf.unlink()
            return True
    except (OSError, ValueError, Refused):
        return False


def cli_notices(root: Path) -> list[str]:
    """The texts of notices the CLI has not shown yet, each marked shown (cli_shown) so a command says it
    ONCE. The notice itself stays for the page until "Got it"."""
    try:
        d = key_dir(root, create=False)
        with _key_lock(d):
            nf, notes = _notices_load(root)
            fresh = [n for n in notes if not n.get("cli_shown")]
            if not fresh:
                return []
            for n in fresh:
                n["cli_shown"] = True
            _write_private(nf, json.dumps(notes))
            return [str(n.get("text"))[:600] for n in fresh]
    except (OSError, ValueError, Refused):
        return []


def take_notices(root: Path) -> list[dict]:
    """The one-time notices for the person (dashboard), cleared when read."""
    try:
        nf = key_dir(root, create=False) / "notices.json"
        notes = json.loads(_read_guarded(nf))
        nf.unlink()
    except (OSError, ValueError, Refused):
        return []
    return [n for n in notes if isinstance(n, dict)]


def private_json(root: Path, name: str, default):
    """Read a JSON store in the workspace's key folder (handoffs.json, ...) under the rights rule: a loose
    file resets the protection and reads as `default`."""
    return _read_json(root, key_dir(root, create=False) / name, default)


# ------------------------------------------------------------------------------------------- pending MAC


def _canon(obj, drop=()) -> str:
    if isinstance(obj, dict):
        obj = {k: v for k, v in obj.items() if k not in drop}
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def pending_mac(key: bytes, workspace: str, ticket: str, line: dict) -> str:
    canon = _canon(line, ("mac", "delivered_at", "human"))
    return _b64u(hmac.new(key, f"pending1.{workspace}.{ticket}.{canon}".encode(), hashlib.sha256).digest())


def pending_is_human(key: bytes, workspace: str, ticket: str, line: dict, ignore=()) -> bool:
    """A pending line is a person's only with a valid MAC bound to this workspace and ticket; by/via/human are
    informational. `ignore`: extra core-owned bookkeeping fields (live_retry) left out of the MAC check."""
    mac = line.get("mac")
    if not isinstance(mac, str) or not mac or line.get("kind") not in PENDING_MAC_KINDS:
        return False
    rest = {k: v for k, v in line.items() if k not in ignore}
    return hmac.compare_digest(pending_mac(key, workspace, ticket, rest), mac)


def pending_deliver(line: dict, delivered) -> bool:
    return line["id"] not in delivered


def delivered_ids(root: Path) -> set[str]:
    d = key_dir(root, create=False)
    data = _read_json(root, d / "delivered.json", {"ids": []})
    ids = data.get("ids") if isinstance(data, dict) else None
    if not isinstance(ids, list):
        raise Refused("The delivered record is unreadable.")
    return {i for i in ids if isinstance(i, str)}


def consume(root: Path, ids: list[str]) -> list[str]:
    """Record ids as delivered, atomically under the key lock. Returns the ids NOT delivered before. Only the
    newest 5000 ids are kept; an input older than that is no longer remembered."""
    d = key_dir(root)
    with _key_lock(d):
        data = _read_json(root, d / "delivered.json", {"ids": []})
        have = list(data.get("ids") or []) if isinstance(data, dict) else []
        new = [i for i in dict.fromkeys(ids) if i not in have]
        if new:
            _write_private(d / "delivered.json", json.dumps({"ids": (have + new)[-5000:]}))
        return new


def unconsume(root: Path, ids: list[str]) -> None:
    """The core took delivery back (a start hung before the agent read the input). Core-only."""
    d = key_dir(root)
    with _key_lock(d):
        data = _read_json(root, d / "delivered.json", {"ids": []})
        have = list(data.get("ids") or []) if isinstance(data, dict) else []
        _write_private(d / "delivered.json", json.dumps({"ids": [i for i in have if i not in ids]}))


# ------------------------------------------------------------------------------------------- won't do


def wontdo_mac(key: bytes, workspace: str, ticket: str, decision: dict) -> str:
    """wontdo1.<workspace id>.<ticket id>.<canonical decision {check, wont_do, reason, text, covers, nonce}>:
    binds WHERE the decision belongs (another ticket or step) and WHAT it is about (the step's text and
    covers); the nonce makes equal decisions differ. An undo is the same record with wont_do false and
    reason null. FRESHNESS comes from the ledger (see below), not from the MAC."""
    return _b64u(
        hmac.new(key, f"wontdo1.{workspace}.{ticket}.{_canon(decision)}".encode(), hashlib.sha256).digest()
    )


def wontdo_is_human(
    key: bytes, workspace: str, ticket: str, decision: dict, mac, relay_authenticated_sender: bool
) -> bool:
    if relay_authenticated_sender:
        return True
    return (
        isinstance(mac, str)
        and bool(mac)
        and hmac.compare_digest(mac, wontdo_mac(key, workspace, ticket, decision))
    )


# The step fields the signed decision record is built from. ONE source of truth: wont_decision() reads exactly
# these, and the sync merge pins exactly these (+ the MAC itself) while a verified decision is held
# (orch_sync.merge._SIGNED; a test fails if the two drift apart).
SIGNED_STEP_FIELDS = ("wont_do", "reason", "text", "covers", "wont_nonce")


def wont_decision(step: dict) -> dict:
    """The step's decision record, the thing the MAC covers: which step, the decision and its reason, a random
    `nonce` (equal decisions get different MACs) and, ONLY for an "on" record, WHAT the person decided about
    (the step's text and `covers`: rewriting the step needs the person again). An undo record carries no text
    or covers, so a later rename of the reopened step cannot make the undo stop verifying."""
    on = step.get("wont_do") is True
    return {
        "check": step.get("id"),
        "wont_do": on,
        "reason": (step.get("reason") if on else None),
        "text": (step.get("text") if on else None),
        "covers": (step.get("covers") if on else None),
        "nonce": step.get("wont_nonce"),
    }


# The LEDGER (guarded home, next to human.key): keys/<ws>/wont.json holds, per "<ticket>:<check>", the CURRENT
# wontdo1 MAC of that step's decision (null = tombstone, the step was removed). A MAC is accepted only when it
# IS the current entry, so replaying an older signed "on" or "undo", or reusing the id of a removed step, does
# not verify. A missing, loose or damaged ledger vouches for nobody (fail closed).
LEDGER = "wont.json"


LEDGER_DAMAGED = (
    "orch's record of your Won't do decisions is damaged, so this was not saved. Nothing was changed. "
    "Close orch and start it again; orch then resets its protection and you can decide again."
)


def _ledger_load(root: Path, name: str) -> dict | None:
    """The entries of ledger file `name`: {} when there is none yet, None when it cannot be trusted (damaged
    or loose). ONE reader for every ledger (wont.json, verdict.json)."""
    try:
        d = key_dir(root, create=False)
        try:
            data = json.loads(_read_guarded(d / name))
        except FileNotFoundError:
            data = {"entries": {}}
    except (Refused, OSError, ValueError):  # incl. LooseFile: a loose or damaged ledger vouches for nobody,
        return None  # and a reader never resets protection (no DoS by chmod)
    ent = data.get("entries") if isinstance(data, dict) else None
    return ent if isinstance(ent, dict) else None


def _ledger_put(root: Path, name: str, schema: str, key: str, mac: str | None) -> bool:
    """Make `mac` the current entry of `key` in ledger file `name`. A damaged ledger is NEVER
    overwritten (that
    would wipe every other entry): returns False and keeps the file. ONE writer for every ledger."""
    try:
        d = key_dir(root)
        with _key_lock(d):
            ent = _ledger_load(root, name)
            if ent is None:
                return False
            ent[key] = mac
            _write_private(d / name, json.dumps({"schema": schema, "entries": ent}))
        return True
    except (Refused, OSError):
        return False


def _ledger_read(root: Path) -> dict | None:
    return _ledger_load(root, LEDGER)


def _ledger_set(root: Path, ticket: str, check: str, mac: str | None) -> bool:
    return _ledger_put(root, LEDGER, "orch.wont-ledger/1", f"{ticket}:{check}", mac)


def wont_sign(root: Path, ticket: str, step: dict) -> str | None:
    """The receiving core's own wontdo1 MAC for this step's decision, recorded as the CURRENT entry of the
    ledger (None when there is no usable key or ledger). The step must already carry a fresh `wont_nonce`."""
    from orch import addons

    try:
        ws = addons.workspace_id(root, create=False)
        if not ws or not isinstance(step.get("wont_nonce"), str):
            return None
        mac = wontdo_mac(human_key(root, create=False), ws, ticket, wont_decision(step))
    except (Refused, OSError):
        return None
    if not _ledger_set(root, ticket, str(step.get("id")), mac):
        raise Refused(LEDGER_DAMAGED)  # visible: the decision is not saved half-signed
    return mac


def wont_forget(root: Path, ticket: str, check: str) -> None:
    """A step was removed (a proven removal): tombstone its ledger entry (whatever the step file still says),
    so no old MAC verifies on a new step that reuses the id. Nothing to do when the ledger has no entry for
    it; a damaged ledger is left as it is (it vouches for nobody anyway)."""
    ent = _ledger_read(root)
    if ent and ent.get(f"{ticket}:{check}") is not None:
        _ledger_set(root, ticket, check, None)


def wont_verifier(root: Path, relay_ok=None):
    """`person(step, ticket_id) -> bool` for the sync merge: True only for a decision whose MAC is valid for
    the step's content AND is the CURRENT ledger entry for that step (or one the relay client recorded from an
    authenticated sender: `relay_ok(step, ticket_id, decision)` must compare the FULL decision record against
    what the relay recorded, never "this step was touched by a relay sender"). The ledger is read at each
    call, so the sync caller must read, merge and write under the ticket's apply_op lock (the ledger cannot
    move between the merge and the write). The text `by: human:` is never
    looked at. Fails closed: no key, no workspace id, no readable ledger = nobody."""
    from orch import addons

    try:
        ws = addons.workspace_id(root, create=False)
        key = human_key(root, create=False)
    except (Refused, OSError):
        return lambda step, ticket: False
    if not ws:
        return lambda step, ticket: False

    def person(step, ticket) -> bool:
        if not isinstance(step, dict) or not isinstance(ticket, str):
            return False
        decision = wont_decision(step)
        if relay_ok and relay_ok(step, ticket, decision):
            return True
        ledger = _ledger_read(root)  # read at the moment of asking, never a snapshot taken earlier
        if ledger is None:
            return False  # damaged / loose: nobody
        mac = step.get("wont_mac")
        current = ledger.get(f"{ticket}:{step.get('id')}")
        if not isinstance(mac, str) or not mac or not isinstance(current, str):
            return False
        return hmac.compare_digest(mac, current) and wontdo_is_human(key, ws, ticket, decision, mac, False)

    return person


# ------------------------------------------------------------------------------------------- signed verdict

# A ticket counts as Done on this machine only when it carries a verdict entry whose MAC is this core's own
# verdict1 MAC over the ticket's current state AND is the CURRENT entry of this core's verdict ledger
# (keys/<ws>/verdict.json, per ticket id the current MAC, null = tombstone). Every other raw "done" is Review.
# Decided here (verdict_ok), applied in ONE read path (tickets._effective) and ONE write guard
# (tickets._write).
# Leaving Done needs no proof (more work, never less): the core tombstones the entry on every non-done write
# and whenever it reads a non-done ticket.
VERDICT_LEDGER = "verdict.json"
VERDICT_MAX = 8  # verdict entries kept on one ticket
# What a stored entry holds. ONE source of truth: the sync merge imports it (a test fails if it keeps a copy).
VERDICT_FIELDS = ("kind", "nonce", "mac")
VERDICT_KINDS = ("person", "agent")

VERDICT_LEDGER_DAMAGED = (
    "orch's record of your Done decisions is damaged, so this was not saved. Nothing was changed. "
    "Ask your admin to reset orch's protection on this computer, then decide again."
)
VERDICT_NEEDED = "Done needs your OK. Click Looks good in the dashboard."


def verdict_checks(ticket: dict) -> str:
    """sha256 hex of WHAT was accepted: every step's id, text, done and won't-do flags. A later change of the
    checklist makes an old verdict stop verifying. Title, note, summary, outcome, history, evidence are not
    bound (a person may rename a Done ticket; the agent writes its summary after finishing)."""
    rows = [
        [c.get("id"), c.get("text"), c.get("done") is True, c.get("wont_do") is True]
        for c in ticket.get("checklist") or []
    ]
    return hashlib.sha256(_canon(rows).encode()).hexdigest()


def verdict_record(ticket: dict, entry: dict) -> dict:
    """The record the MAC covers. `status` is always "done" (domain separation: a future signed status gets
    its own prefix)."""
    return {
        "status": "done",
        "kind": entry.get("kind"),
        "checks": verdict_checks(ticket),
        "nonce": entry.get("nonce"),
    }


def verdict_mac(key: bytes, workspace: str, ticket: str, record: dict) -> str:
    """verdict1.<workspace id>.<ticket id>.<canonical record {status, kind, checks, nonce}>. Binds WHERE it
    belongs (another ticket or workspace) and WHAT was accepted (the checklist); the nonce makes equal
    decisions differ. FRESHNESS comes from the ledger, not from the MAC."""
    return _b64u(
        hmac.new(key, f"verdict1.{workspace}.{ticket}.{_canon(record)}".encode(), hashlib.sha256).digest()
    )


def verdict_is_human(
    key: bytes, workspace: str, ticket_id: str, ticket: dict, entry, ledger_current
) -> str | None:
    """ "current" when `entry` carries this key's MAC over the ticket's state AND that MAC is the
    current ledger
    entry; "stale" when the MAC is ours but no longer current (replayed, tombstoned, superseded); None when it
    is not ours at all (another machine, forged, the checklist changed). Never raises."""
    try:
        if not isinstance(entry, dict) or entry.get("kind") not in VERDICT_KINDS:
            return None
        mac, nonce = entry.get("mac"), entry.get("nonce")
        if not (isinstance(mac, str) and mac and isinstance(nonce, str) and nonce):
            return None
        mine = hmac.compare_digest(mac, verdict_mac(key, workspace, ticket_id, verdict_record(ticket, entry)))
        if not mine:
            return None
        if isinstance(ledger_current, str) and hmac.compare_digest(mac, ledger_current):
            return "current"
        return "stale"
    except Exception:  # noqa: BLE001 - a malformed ticket is nobody's verdict (fail closed)
        return None


def verdict_ledger(root: Path) -> dict | None:
    """The verdict ledger entries ({} when none yet, None when damaged or loose)."""
    return _ledger_load(root, VERDICT_LEDGER)


def _verdict_ledger_put(root: Path, tid: str, mac: str | None) -> bool:
    return _ledger_put(root, VERDICT_LEDGER, "orch.verdict-ledger/1", tid, mac)


def verdict_sign(root: Path, ticket: dict, kind: str) -> dict:
    """A fresh verdict entry for the ticket as it is NOW (its checklist must be final), recorded as the
    CURRENT ledger entry. No key, no workspace id or a damaged ledger = Refused: never a half-signed Done."""
    from orch import addons

    if kind not in VERDICT_KINDS:
        raise Refused(VERDICT_NEEDED)
    tid = ticket.get("id")
    try:
        ws = addons.workspace_id(root, create=False)
        key = human_key(root, create=False)
    except (Refused, OSError):
        raise Refused(VERDICT_LEDGER_DAMAGED) from None
    if not ws or not isinstance(tid, str):
        raise Refused(VERDICT_LEDGER_DAMAGED)
    entry = {"kind": kind, "nonce": secrets.token_hex(8)}
    entry["mac"] = verdict_mac(key, ws, tid, verdict_record(ticket, entry))
    if not _verdict_ledger_put(root, tid, entry["mac"]):
        raise Refused(VERDICT_LEDGER_DAMAGED)
    return entry


def verdict_forget(root: Path, tid: str, ledger: dict | None = None) -> bool:
    """Tombstone this ticket's ledger entry (it left Done, or the file was deleted). Nothing to do when there
    is no live entry; a damaged ledger is left alone (it vouches for nobody). True when it wrote one."""
    ent = verdict_ledger(root) if ledger is None else ledger
    if ent and ent.get(tid) is not None:
        return _verdict_ledger_put(root, tid, None)
    return False


class VerdictChecker:
    """Asks "does this raw done ticket carry a current verdict?" The workspace id and key are read once; the
    ledger is read at each ask (a fresh read), or once when `snapshot` (one listing)."""

    def __init__(self, root: Path, snapshot: bool = False):
        from orch import addons

        self.root = root
        self._ctx = None
        self._tried = False
        self._snapshot = snapshot
        self._ledger = None
        self._have_ledger = False
        self._addons = addons

    def _context(self):
        if not self._tried:
            self._tried = True
            try:
                ws = self._addons.workspace_id(self.root, create=False)
                self._ctx = (ws, human_key(self.root, create=False)) if ws else None
            except (Refused, OSError):
                self._ctx = None
        return self._ctx

    def ledger(self) -> dict | None:
        if self._snapshot and self._have_ledger:
            return self._ledger
        led = verdict_ledger(self.root)
        if self._snapshot:
            self._ledger, self._have_ledger = led, True
        return led

    def state(self, entry, ticket: dict) -> str | None:
        """ "current" | "stale" | None for one entry of `ticket` (see verdict_is_human)."""
        ctx = self._context()
        tid = ticket.get("id") if isinstance(ticket, dict) else None
        if ctx is None or not isinstance(tid, str):
            return None
        led = self.ledger()
        if led is None:
            return (
                None  # damaged or loose ledger: nobody is vouched for, and nothing is judged "stale" either
            )
        return verdict_is_human(ctx[1], ctx[0], tid, ticket, entry, led.get(tid))

    def ok(self, ticket: dict) -> bool:
        """True only when some entry is current. Missing, loose or damaged ledger, no key, no workspace id, a
        non-list `verdicts`, any error = False."""
        try:
            entries = ticket.get("verdicts")
            if not isinstance(entries, list) or not entries:
                return False
            return any(self.state(e, ticket) == "current" for e in entries)
        except Exception:  # noqa: BLE001 - fail closed
            return False


def verdict_ok(root: Path, ticket: dict) -> bool:
    return VerdictChecker(root).ok(ticket)


def verdict_verifier(root: Path):
    """`verdict(entry, ticket) -> "current" | "stale" | None` for the sync merge: the ledger is read at
    each call,
    so the sync caller must read, merge and write under the ticket's lock. Fails closed (no key, no workspace
    id, no readable ledger = None for everything)."""
    return VerdictChecker(root).state


def dev_can_mark(install_dev: bool, creating: bool, has_human_key: bool) -> bool:
    return bool(install_dev and creating and not has_human_key)


# ------------------------------------------------------------------------------------------- dev test human


def _dev_path(root: Path) -> Path:
    return guarded_home(root) / "dev-workspaces.json"


def dev_workspace(root: Path) -> bool:
    """Is this workspace a dev demo workspace? ONLY the record in the guarded orch home counts (written by the
    dev installer when it creates the workspace); no workspace file, state dir file or environment is read."""
    try:
        data = _read_json(root, _dev_path(root), {})
    except (Refused, OSError):
        return False
    ws = data.get("workspaces") if isinstance(data, dict) else None
    return isinstance(ws, dict) and os.path.realpath(root) in ws and install_kind() in ("dev", "test")


def _dev_key_hex(d: Path) -> str | None:
    try:
        return _read_guarded(d / "dev-human.key").decode("utf-8").strip()
    except (OSError, Refused, ValueError):
        return None


def dev_mark(root: Path) -> None:
    """Called only by the dev installer when it CREATES a demo workspace (reference dev_can_mark): record the
    workspace as dev and make its dev key. A workspace that already has a human.key never becomes dev."""
    d = key_dir(root)
    if not dev_can_mark(install_kind() in ("dev", "test"), True, (d / "human.key").exists()):
        raise Refused("This workspace cannot be a dev workspace.")
    path = _dev_path(root)
    with _key_lock(d):
        data = _read_json(root, path, {"workspaces": {}})
        data.setdefault("workspaces", {})[os.path.realpath(root)] = {"at": int(time.time())}
        _write_private(path, json.dumps(data, indent=2, sort_keys=True))
        if not (d / "dev-human.key").exists():
            _write_private(d / "dev-human.key", secrets.token_hex(32) + "\n")


def mint_dev(root: Path, op: str, target: str, life: int = 30) -> str:
    """The scripted test human's proof (e2e only). Refused unless this is a dev workspace."""
    if not dev_workspace(root):
        raise Refused("This is not a dev workspace.")
    key = _dev_key_hex(key_dir(root, create=False))
    if not key:
        raise Refused("This is not a dev workspace.")
    p = new_payload(op, target, "human:test-human", life=life)
    p["dev"] = True
    return mint(bytes.fromhex(key), p)


# ------------------------------------------------------------------------------------------- CLI gate

HANDOFF = "Do this in the dashboard on this computer."


class HandOffPending(Refused):
    """Raised ONLY where person_by has written (or found) the hand-off card: the person is to click on the
    page. A Refused for anything else (an agent, a bad value, no card) is not this."""


AGENT_REFUSED = "Only a human can do this. Ask the human to run it themselves."
HANDOFF_PER_OP = 3


def read_proof_line() -> str:
    """The proof is the FIRST line of stdin (--proof-stdin). Never argv, never env."""
    try:
        return sys.stdin.readline().strip()
    except (OSError, ValueError):
        return ""


# The command a hand-off runs once the person clicks (set by cli.main; no --by / --proof-stdin in it).
CURRENT_ARGV: list[str] | None = None
# What a page may run for a hand-off: the command words an op may start with (the proof binds op + target).
HANDOFF_HEADS = {
    "ticket.answer": (("answer",),),
    "run.human_input": (("run", "send"),),
    "ticket.verdict": (("ticket", "changes"), ("ticket", "patch"), ("ticket", "status")),
    "relay.allow": (("relay", "allow"),),
    "relay.connect": (("relay", "connect"),),
    "update": (("update",),),
    "addon.add_local": (("addon", "add"),),
    "chat.send": (("chat", "say"), ("chat", "send")),
    "check.wont_do": (("check", "wont-do"),),
    "check.wont_do_undo": (("check", "reopen"), ("check", "edit"), ("check", "remove")),
    "chat.make_ticket": (("chat", "make-ticket"),),
    "config.agents_may_finish": (("config", "set"),),
    "config.copy_setup": (("config", "set"),),
    "copy.remove_orphaned": (("copy", "remove-orphaned"),),
    "copy.retry": (("copy", "retry"),),
    "config.permissions": (("config", "set"),),
    "config.agent_add": (("config", "agent", "add"),),
    "private.allow": (("private", "allow"),),
    "private.move": (("private", "move"),),
    "config.share": (("share", "on"),),
    "look.shared_pages": (("look", "shared-pages"),),
    "look.icon": (("look", "set"),),
    "group.write_as_person": (("relay", "group", "say"), ("relay", "group", "reply")),
    "group.remove_member": (("relay", "group", "remove"),),
    "group.share_file": (("relay", "group", "share"), ("relay", "group", "send-file")),
}


def agent_add_target(
    name: str, command: str, interactive: str | None = None, prompt: str | None = None
) -> str:
    """The proof target of config.agent_add: the name AND a digest of every value that gets saved, so a
    proof for one command (or live command, or prompt mode) can never save another. Same in the dashboard."""
    doc = json.dumps([command, interactive or "", prompt or ""])
    return f"{name}:{hashlib.sha256(doc.encode('utf-8')).hexdigest()}"


def entry_exact(entry: dict) -> str:
    """Every field a private.allow key approves (adapter, command, live command, prompt), one per line."""
    rows = [
        ("Adapter", entry.get("adapter")),
        ("Command", entry.get("command")),
        ("Live command", entry.get("interactive")),
        ("Prompt via", entry.get("prompt")),
    ]
    return "\n".join(f"{k}: {v}" for k, v in rows if v)


def allow_card_is_current(root: Path, target: str) -> bool:
    """private.allow takes its values from the settings file, not argv: the card's target is name:key, so the
    card is only good while the entry still hashes to that key."""
    from orch import config

    name, _, key = str(target).partition(":")
    e = config._raw_entries(root).get(name)
    return e is not None and config._entry_key(root, name, e) == key


def agent_add_exact(command: str, interactive: str | None = None, prompt: str | None = None) -> str:
    """Every value config.agent_add saves, one per line, for the card's exact block."""
    rows = [("Command", command), ("Live command", interactive), ("Prompt via", prompt)]
    return "\n".join(f"{k}: {v}" for k, v in rows if v)


def exact_in_argv(op: str, exact: str, argv) -> bool:
    """The full value(s) shown in the card's exact block must be part of the command that runs."""
    if op in ("relay.connect", "addon.add_local", "group.share_file"):
        return exact in " ".join(argv)
    if op == "config.agent_add":
        words = list(argv)
        vals = [ln.split(": ", 1)[1] for ln in exact.splitlines() if ": " in ln]
        return (
            bool(vals)
            and len(vals) == len(exact.splitlines())
            and all(
                v in words or any(w.startswith("--") and w.endswith("=" + v) for w in words) for v in vals
            )
        )
    return True


EXACT_OPS = ("relay.connect", "addon.add_local", "group.share_file", "config.agent_add", "private.allow")


def _clean_argv(argv) -> list[str] | None:
    out, skip = [], False
    for a in argv or []:
        if skip:
            skip = False
            continue
        if a == "--by":
            skip = True
            continue
        if a.startswith("--by=") or a in ("--proof-stdin", "--unchecked-ok"):
            continue  # --unchecked-ok skips the password check: a hand-off refuses in words, the page asks
        out.append(a)
    return out if all(isinstance(x, str) and len(x) <= 4000 for x in out) and len(out) <= 20 else None


VALUE_MAX = 4000  # the exact text a person approves is shown whole; longer is not queued


def group_target(root: Path, host: str, group: str) -> str:
    """The proof target for an act in a joined group: `<host workspace id>:<group id>`. A group id
    is only unique per host, so the host is part of what the person approves. The CLI and the dashboard both
    build it here (one place), so a proof for host A is never good for host B."""
    from orch import relay

    try:
        host = relay.resolve(root, host) if root is not None else host
    except Refused:
        pass  # the command itself refuses an unknown host in words
    return f"{host}:{group}"


def plain_ticket(root: Path, tid: str, qid: str | None = None) -> str:
    """The ticket (and question) in plain words for the hand-off card: title, never a raw id."""
    from orch import tickets

    try:
        t = tickets.load(root, tid)
        text = f"\u201c{t.get('title', '')}\u201d"
        q = next((x for x in t.get("questions") or [] if qid and x.get("id") == qid), None)
        return text + (f", question: {q.get('text', '')}" if q else "")
    except (Refused, OSError, ValueError, AttributeError):
        return "a ticket"


PART_MAX = 120


def part(text) -> str:
    """One untrusted fragment (a title, a question, a task, a path) for the card: one line, quotes normalised
    so it cannot fake the quotes around it, at most 120 characters with an ellipsis. The page shows it as
    plain text in its own element; `{value}` and the like stay literal."""
    t = " ".join(str(text if text is not None else "").split())
    t = t.translate({ord(c): "'" for c in '"\u201c\u201d\u201e\u2033\u00ab\u00bb'})
    return t[:PART_MAX] + "\u2026" if len(t) > PART_MAX else t


def tail(text, n: int = 60) -> str:
    """A long path for the sentence: its END ("\u2026/real/folder"), never its head. The full value is
    always in the card's exact block."""
    t = " ".join(str(text if text is not None else "").split())
    return t if len(t) <= n else "\u2026" + t[-n:]


NO_USERINFO = "This address contains a name or password. Use just the server address."


def server_address(url: str) -> str:
    """hostname[:port] of a server URL, built from urlsplit; a URL with userinfo (user@ / user:pass@) is
    refused, so what the card shows is what is connected to."""
    from urllib.parse import urlsplit

    try:
        u = urlsplit(url.strip())
        host, port = u.hostname, u.port
    except ValueError:
        raise Refused("That is not a server address.") from None
    if u.username is not None or u.password is not None or "@" in u.netloc:
        raise Refused(NO_USERINFO)
    if not host:
        raise Refused("That is not a server address.")
    return f"{host}:{port}" if port else host


def ticket_name(root: Path, tid: str) -> str:
    """The ticket's title (never its id), as one safe fragment."""
    from orch import tickets

    try:
        t = str(tickets.load(root, tid).get("title", ""))
    except (Refused, OSError, ValueError, AttributeError):
        t = ""
    return part(t) or "this ticket"


def question_text(root: Path, tid: str, qid: str) -> str:
    from orch import tickets

    try:
        q = next((x for x in tickets.load(root, tid).get("questions") or [] if x.get("id") == qid), None)
        t = str((q or {}).get("text", ""))
    except (Refused, OSError, ValueError, AttributeError):
        t = ""
    return part(t.rstrip("?! ")) or "the question"


def step_text(root: Path, tid: str, cid: str) -> str:
    """The step's text (never its id) as one safe fragment."""
    from orch import tickets

    try:
        t = tickets.load(root, tid)
        item = next((c for c in t.get("checklist") or [] if c.get("id") == cid), None)
        text = str((item or {}).get("text", ""))
    except (Refused, OSError, ValueError, AttributeError):
        text = ""
    return part(text) or "this step"


def step_number(root: Path, tid: str, cid: str) -> int:
    """The step's place in the ticket's list (1, 2, 3 ...): shown next to its (agent-written) text."""
    from orch import tickets

    try:
        ids = [c.get("id") for c in tickets.load(root, tid).get("checklist") or []]
        return ids.index(cid) + 1
    except (Refused, OSError, ValueError, AttributeError):
        return 0


def step_parts(root: Path, tid: str, cid: str, **more) -> dict:
    return {
        "title": ticket_name(root, tid),
        "step": step_text(root, tid, cid),
        "n": step_number(root, tid, cid),
        **more,
    }


def status_parts(root: Path, tid: str, data: str) -> dict:
    """A person's ticket patch as fields: {title, status, also: [other keys]} (never the JSON)."""
    try:
        obj = json.loads(data)
    except ValueError:
        obj = {}
    obj = obj if isinstance(obj, dict) else {}
    st = obj.get("status")
    return {
        "title": ticket_name(root, tid),
        "status": st if st in ("done", "review") else "back",
        "also": [part(k) for k in list(obj)[:6] if k != "status"],
    }


SECRET_MARK = "@secret"


def _split_token(argv: list[str]) -> tuple[list[str], str | None]:
    """A relay token never goes into handoffs.json: it is replaced by a mark and kept apart."""
    out, token = list(argv), None
    for i, a in enumerate(out):
        if a == "--token" and i + 1 < len(out):
            token, out[i + 1] = out[i + 1], SECRET_MARK
        elif a.startswith("--token="):
            token, out[i] = a[len("--token=") :], "--token=" + SECRET_MARK
    return out, token


def _join_token(argv: list[str], token: str) -> list[str]:
    return [
        token if a == SECRET_MARK else "--token=" + token if a == "--token=" + SECRET_MARK else a
        for a in argv
    ]


def request_handoff(
    root: Path, op: str, target: str, label: str = "", value: str = "", argv=None, parts=None, exact=None
) -> bool:
    """A command asked for a human-only action without a proof: leave a pending item on the page ("Requested
    by a command"). At most 3 per op; a NEW request is dropped when full (N18), never evicting an older one.
    The item holds the command to run once the person clicks. Best effort: a failure here only means the item
    is missing. Returns True when newly queued, "dup" when the same request already waits, False when not
    queued. The exact value the person will see is the value that runs: it must
    be one of the command's own words (checked here and again when the page takes the item)."""
    heads = HANDOFF_HEADS.get(op, ())
    if not isinstance(argv, list) or not any(argv[: len(h)] == list(h) for h in heads):
        return False  # never queue what the page could not run
    if len(value) > VALUE_MAX or (value and value not in argv):
        return False
    exact = str(exact)[:2000] if exact else ""
    if exact and op in EXACT_OPS and not exact_in_argv(op, exact, argv):
        return False  # the shown full target must be part of the command that runs
    try:
        d = key_dir(root)
        path = d / "handoffs.json"
        now = int(time.time())
        with _key_lock(d):
            items = [i for i in _read_json(root, path, []) if isinstance(i, dict) and i.get("exp", 0) > now]
            argv, token = _split_token(argv)
            same = [
                i for i in items if i.get("op") == op and i.get("target") == target and i.get("argv") == argv
            ]
            if same:
                return "dup"  # already waiting: the FIRST request stays (its token too); no new browser
            if sum(1 for i in items if i.get("op") == op) >= HANDOFF_PER_OP:
                return False
            hid = _b64u(secrets.token_bytes(9))
            if token is not None:
                _write_private(d / f"handoff-{hid}.secret", token)
            for f in d.glob("handoff-*.secret"):  # a secret whose request is gone or expired
                if f.name != f"handoff-{hid}.secret" and f.name[8:-7] not in {i.get("id") for i in items}:
                    with contextlib.suppress(OSError):
                        f.unlink()
            items.append(
                {
                    "id": hid,
                    "op": op,
                    "target": target,
                    "label": label[:400],
                    "exact": exact,
                    "parts": {k: v for k, v in (parts or {}).items() if isinstance(k, str)},
                    "value": value,
                    "argv": argv,
                    "at": now,
                    "exp": now + 600,
                }
            )
            _write_private(path, json.dumps(items))
        return True
    except (Refused, OSError, ValueError):
        return False


def handoffs(root: Path) -> list[dict]:
    """The pending command requests for the page to show (core-written, read by the page servers)."""
    try:
        d = key_dir(root, create=False)
        now = int(time.time())
        with _key_lock(d):  # a secret is written under this lock just before its item
            items = _read_json(root, d / "handoffs.json", [])
            live = [i for i in items if isinstance(i, dict) and i.get("exp", 0) > now]
            ids = {i.get("id") for i in live}
            for f in d.glob("handoff-*.secret"):  # a secret whose request expired or is gone
                if f.name[8:-7] not in ids:
                    with contextlib.suppress(OSError):
                        f.unlink()
        return live
    except (Refused, OSError, ValueError):
        return []


def handoff_take(root: Path, hid: str) -> dict | None:
    """The item with this id, removed from the list (single click, single run). The command must start with
    the words its op allows, else None."""
    try:
        d = key_dir(root, create=False)
        with _key_lock(d):
            items = [i for i in _read_json(root, d / "handoffs.json", []) if isinstance(i, dict)]
            hit = next((i for i in items if i.get("id") == hid and i.get("exp", 0) > time.time()), None)
            if hit is None:
                return None
            _write_private(d / "handoffs.json", json.dumps([i for i in items if i is not hit]))
            secret = d / f"handoff-{hid}.secret"
            token = None
            if SECRET_MARK in json.dumps(hit.get("argv")):
                token = _read_guarded(secret).decode("utf-8").strip()
            with contextlib.suppress(OSError):
                secret.unlink()
    except (Refused, OSError, ValueError):
        return None
    argv = hit.get("argv")
    if token is not None and isinstance(argv, list):
        hit = {**hit, "argv": _join_token(argv, token)}
        argv = hit["argv"]
    heads = HANDOFF_HEADS.get(hit.get("op"), ())
    if not isinstance(argv, list) or not any(argv[: len(h)] == list(h) for h in heads):
        return None
    if hit.get("value") and hit["value"] not in argv:  # only the STORED, shown value may run
        return None
    if hit.get("op") == "private.allow" and not allow_card_is_current(root, hit.get("target")):
        return None  # the entry changed after the card was made: the person never saw this one
    if hit.get("exact") and hit.get("op") in EXACT_OPS:
        if not exact_in_argv(hit["op"], hit["exact"], argv):  # the full target shown must be what runs
            return None
    return hit


def handoff_drop(root: Path, hid: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", str(hid)):
        return
    try:
        d = key_dir(root, create=False)
        with _key_lock(d):
            items = [
                i
                for i in _read_json(root, d / "handoffs.json", [])
                if isinstance(i, dict) and i.get("id") != hid
            ]
            _write_private(d / "handoffs.json", json.dumps(items))
            with contextlib.suppress(OSError):
                (d / f"handoff-{hid}.secret").unlink()
    except (Refused, OSError, ValueError):
        pass


OPEN_EVERY = 30  # seconds: the browser is opened at most this often for hand-offs


def _may_open(root: Path) -> bool:
    """Rate limit for opening the browser: one stamp file in the key folder, by its modification time."""
    try:
        stamp = key_dir(root) / "handoff-open.stamp"
        now = time.time()
        with contextlib.suppress(OSError):
            if now - stamp.stat().st_mtime < OPEN_EVERY:
                return False
        _write_private(stamp, "x")
        return True
    except (Refused, OSError):
        return False


def _dashboard_note(root: Path, open_ok: bool = True) -> str:
    """After a hand-off: open the dashboard on a desktop (launch token in the URL
    fragment, never printed) and say in plain words what to click. No token is ever returned or printed."""
    url = None
    try:
        from orch import services

        row = next((r for r in services.workspace_rows(root) if r.get("addon") == "dashboard"), None)
        url = services.local_url(row.get("url")) if row else None
    except Exception:  # noqa: BLE001 - the note is best effort
        url = None
    if url and open_ok and term.is_terminal(sys.stdout) and _may_open(root):
        open_browser(launch_url(root, "dashboard", url))
        return f"Opened the dashboard ({url}): press Continue to send this to the agent."
    if url:
        return f"Waiting for your click: open the dashboard ({url}) and press Continue to send this."
    return "Waiting for your click: open the dashboard on this computer and press Continue."


def person_by(
    root: Path,
    args,
    op: str,
    target: str,
    *,
    label: str = "",
    value: str = "",
    argv=None,
    no_handoff=None,
    parts=None,
    exact=None,
) -> str:
    """Who acts for a human-only op (invariant H1). With --proof-stdin: the person in a verified proof (`by`
    comes from the proof, --by must agree). An agent (agent tool in the environment, or --by agent:...) keeps
    its own, unprivileged, identity. Anything claiming to be a person without a proof is refused and handed
    off to the page."""
    if getattr(args, "proof_stdin", False):
        return verify_and_consume(root, read_proof_line(), op, target, getattr(args, "by", None))
    tool = None
    from orch import tickets

    tool = tickets.agent_tool()
    if tool:
        return "agent:" + str(tool)
    explicit = getattr(args, "by", None)
    if explicit and explicit.startswith("agent:"):
        return tickets.current_actor(explicit)
    if no_handoff:
        raise Refused(no_handoff)  # this command cannot be approved on the page as typed
    clean = _clean_argv(CURRENT_ARGV) if argv is None else argv
    queued = request_handoff(root, op, target, label, value, clean, parts, exact)
    if not queued:
        raise Refused(HANDOFF)
    raise HandOffPending(_dashboard_note(root, open_ok=queued is True))


# ------------------------------------------------------------------------------------------- launch token

LAUNCH_LIFE = 30  # seconds: the token is single use and dies on the first page load


def write_launch_token(root: Path, server: str) -> str | None:
    """The one-time token that bootstraps a page session: <key folder>/launch-<server>.token (0600, once,
    30 s). Returned ONLY to the code that opens the browser at `#launch=<token>` (a URL fragment); never
    printed or logged."""
    if server not in LAUNCH_SERVERS:
        raise Refused("Unknown page server.")  # a local or marketplace add-on never gets a launch token
    try:
        d = key_dir(root)
        token = secrets.token_urlsafe(24)
        _write_private(d / f"launch-{server}.token", f"{token}\n{int(time.time()) + LAUNCH_LIFE}\n")
        return token
    except (Refused, OSError):
        return None


def consume_launch_token(root: Path, server: str, token: str) -> bool:
    """Compare with the file and delete it (single use), whatever the outcome of the comparison."""
    try:
        d = key_dir(root, create=False)
        f = d / f"launch-{server}.token"
        with _key_lock(d):
            try:
                lines = _read_guarded(f).decode("utf-8").split()
            finally:
                with contextlib.suppress(OSError):
                    f.unlink()  # single use, whatever the outcome (a loose file is spent too)
    except (Refused, OSError, ValueError):
        return False
    return (
        len(lines) == 2
        and lines[1].isdigit()
        and int(lines[1]) > time.time()
        and hmac.compare_digest(lines[0], token)
    )


def opener_env() -> dict:
    """The browser opener's environment, built from scratch (never inherited): no BROWSER, no *_BROWSER, no
    GIO_* / XDG_* overrides, no LD_* / DYLD_* / PYTHON*, a fixed PATH. Only what a desktop session needs."""
    if sys.platform == "darwin":
        keep = ("HOME",)
    else:
        keep = ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "HOME", "DBUS_SESSION_BUS_ADDRESS")
    return {"PATH": "/usr/bin:/bin", **{k: os.environ[k] for k in keep if k in os.environ}}


def open_browser(url: str) -> bool:
    """Open `url` (it may hold a launch token in its fragment) in the person's browser by an absolute-path
    helper with a FIXED CLEAN environment and cwd "/", never a bare name from PATH or cwd and never the
    caller's BROWSER/PATH/LD_*: macOS /usr/bin/open, Linux xdg-open from a system folder. Windows os.startfile
    uses the registry's file association, not environment variables. No other process gets the token."""
    import subprocess

    try:
        if sys.platform == "win32":
            os.startfile(url)  # type: ignore[attr-defined]  # noqa: S606
            return True
        if sys.platform == "darwin":
            cmd = ["/usr/bin/open", url]
        else:
            helper = next(
                (p for p in ("/usr/bin/xdg-open", "/usr/local/bin/xdg-open") if os.access(p, os.X_OK)), None
            )
            if helper is None:
                return False
            cmd = [helper, url]
        subprocess.Popen(  # noqa: S603
            cmd,
            cwd="/",
            env=opener_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except OSError:
        return False


def launch_url(root: Path, server: str, url: str) -> str:
    """`url` with a fresh launch token in the fragment, for the code that opens the browser for a person."""
    try:
        token = write_launch_token(root, server)
    except Refused:
        return url  # not a page server: no token
    return f"{url}#launch={token}" if token else url


RESUME_LIFE = (
    900  # seconds a restarting page server may adopt the session cookie of the page that asked for an update
)


def write_resume_cookie(root: Path, server: str, cookie: str) -> bool:
    """Called by a page server just before it lets an update (which restarts it) run: the restarted server
    adopts this cookie once, so the person's open tab keeps its session (no extra click). Narrow on purpose:
    one server, one use, 15 minutes, written only after a person's click."""
    if server not in ("focus", "dashboard") or not isinstance(cookie, str) or not 20 <= len(cookie) <= 80:
        return False
    try:
        _write_private(
            key_dir(root) / f"resume-{server}.cookie", f"{cookie}\n{int(time.time()) + RESUME_LIFE}\n"
        )
        return True
    except (Refused, OSError):
        return False


def take_resume_cookie(root: Path, server: str) -> str | None:
    """The cookie a restarted server may adopt, once; the file is removed whatever it holds."""
    if server not in ("focus", "dashboard"):
        return None
    try:
        d = key_dir(root, create=False)
        f = d / f"resume-{server}.cookie"
        with _key_lock(d):
            try:
                lines = _read_guarded(f).decode("utf-8").split()
            finally:
                with contextlib.suppress(OSError):
                    f.unlink()
    except (Refused, OSError, ValueError):
        return None
    if len(lines) == 2 and lines[1].isdigit() and int(lines[1]) > time.time() and 20 <= len(lines[0]) <= 80:
        return lines[0]
    return None


# ----------------------------------------------------------------------------------- e2e test human (CLI)

# What the e2e scripts need (e2e/scenarios_v2.py, e2e/scenarios_ws.py, e2e/windows/standard-user-flow.ps1 call
# `orch dev-proof update orch`); the rest are the other first-batch ops an e2e driver may script.
DEV_PROOF_OPS = frozenset(
    "update ticket.verdict ticket.answer relay.connect relay.allow run.human_input chat.send "
    "chat.make_ticket".split()
)


def dev_proof_cli(root: Path, op: str, target: str, by_flag: str | None = None) -> str:
    """The proof the scripted test human of the e2e harness hands to `<command> --proof-stdin`. NARROW: a
    TEST install only (not a dev one), a workspace under the literal <account home>/.orch-test, a dev record
    for it, only the ops above, and never from an orch-started agent context (ORCH_RUN / ORCH_TICKET /
    ORCH_VIA, a detected agent tool, `--by agent:`). Defence in depth only: the environment is
    caller-controlled (Level 1), so an agent that scrubs it can still ask; this stops the agents orch
    itself starts in test workspaces from self-approving. Every mint is logged as dev:test-human with the
    op and nothing secret."""
    from orch import tickets

    no = "No test-human proof here."
    if not is_test_workspace(root):
        raise Refused(no)
    if any(os.environ.get(k) for k in ("ORCH_RUN", "ORCH_TICKET", "ORCH_VIA")) or tickets.agent_tool():
        raise Refused(no)
    if by_flag and by_flag.startswith("agent:"):
        raise Refused(no)
    if op not in DEV_PROOF_OPS:
        raise Refused(no)
    if op == "update":  # the target is the resolved source (what this install would update from)
        from orch import addons

        target = update_target(addons.repo(), addons.ref())
    proof = mint_dev(root, op, target)
    with contextlib.suppress(Refused, OSError):
        fd = os.open(key_dir(root) / "dev-proof.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(f"{_now()} dev:test-human minted op={op}\n")
    return proof


def dev_mark_cli(root: Path, by_flag: str | None = None) -> None:
    """`orch dev-mark` (hidden): the e2e harness marks a demo workspace dev, right after creating it. Same
    narrow gate as dev_proof_cli (test install, under ~/.orch-test, no orch-started agent context) and
    dev_can_mark: a workspace with a human.key can never become dev. Defence in depth (Level 1)."""
    from orch import tickets

    no = "This workspace cannot be marked as a dev workspace."
    if not is_test_workspace(root):
        raise Refused(no)
    if any(os.environ.get(k) for k in ("ORCH_RUN", "ORCH_TICKET", "ORCH_VIA")) or tickets.agent_tool():
        raise Refused(no)
    if by_flag and by_flag.startswith("agent:"):
        raise Refused(no)
    dev_mark(root)
    with contextlib.suppress(Refused, OSError):
        fd = os.open(key_dir(root) / "dev-proof.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(f"{_now()} dev:test-human marked this workspace as dev\n")


def update_target(repo: str, ref: str) -> str:
    """The proof target of `update`: the resolved source, hashed (a target is letters, digits and `_.:@-`)."""
    return "orch@" + hashlib.sha256(f"{repo}@{ref}".encode()).hexdigest()[:32]


# ------------------------------------------------------------------------------------------- update status

UPDATE_TIMEOUT = 1800  # seconds: a hung install is stopped after 30 minutes


def write_update_status(
    root: Path, state: str, reason: str = "", *, finish_offset: int | None = None
) -> None:
    """running | finished | failed, with a short plain reason (no secrets): what the page shows afterwards."""
    if state not in ("running", "finished", "failed"):
        return
    with contextlib.suppress(Refused, OSError):
        d = key_dir(root)
        with _key_lock(d):
            _write_private(
                d / "update-status.json",
                json.dumps(
                    {
                        "state": state,
                        "reason": reason[:200],
                        "at": int(time.time()),
                        **({"finish_offset": finish_offset} if finish_offset is not None else {}),
                    }
                ),
            )


def take_update_status(root: Path) -> dict | None:
    """The detached update's result for the page. A finished or failed result is read ONCE (then cleared); a
    running one stays."""
    try:
        d = key_dir(root, create=False)
        with _key_lock(d):
            f = d / "update-status.json"
            data = json.loads(_read_guarded(f).decode("utf-8"))
            if isinstance(data, dict) and "finish_offset" in data:
                from orch import addons

                home = addons.home()
                if winfinish.pending(home) or winfinish.updating(home):
                    return {"state": "running", "reason": ""}
                ok = winfinish.result_ok_since(home, data["finish_offset"])
                data = {
                    "state": "finished" if ok else "failed",
                    "reason": "" if ok else "The background update failed; see finish.log.",
                }
            if isinstance(data, dict) and data.get("state") in ("finished", "failed"):
                with contextlib.suppress(OSError):
                    f.unlink()
    except (Refused, OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("state") not in ("running", "finished", "failed"):
        return None
    return {"state": data["state"], "reason": str(data.get("reason") or "")[:200]}

"""Human proof (invariant H1, contracts/human-proof.md): the guarded orch home, the human key, hp1 proofs,
widening-settings records, pending-input MACs and the won't-do MAC.

Level 1 (owner decision R1): an agent that reads the orch home directly is outside this module's promise.
It stops
flags, environment, workspace files and copies, not a hostile process of the same user.

Windows: POSIX rights (0700/0600) do not exist there. The folder and file are created in the user's profile
(inherits the profile ACL: the user, SYSTEM and administrators); the explicit "user and SYSTEM only" ACL of
secrets.md is a follow-up (slice 1.1, key store). The mode checks below are skipped on Windows.
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
import time
from pathlib import Path

from orch.errors import Refused

# Switch for the read-back rule in runs.human_waiting (supervisor 9 Nov): OFF = a line counts as a person's by
# the old by/via allowlist; ON (since 1.0a-2) = only with a valid pending MAC.
# A module constant on purpose: not an env var, not a workspace file.
ENFORCE_PENDING_MAC = True

HP_MAX_LIFE = 60
NOT_TOGETHER = "Refused: this workspace and this orch home don't belong together."
WRONG_RIGHTS = "Refused: the key folder has the wrong rights. Fix: orch doctor"
POSIX = os.name == "posix"

OPS = frozenset(
    "run.takeover run.type run.release focus.settings insights.settings record.delete_detail secret.add "
    "secret.remove secret.profile conn.allow checkup.accept checkup.rollback checkup.send_to_admin "
    "checkup.reject ticket.verdict ticket.answer relay.connect private.allow private.move config.agent_add "
    "check.wont_do check.wont_do_undo chat.make_ticket chat.send chat.sync chat.contacts chat.thread_sync "
    "update run.stop relay.allow group.remove_member group.write_as_person group.share_file "
    "group.readd_member config.share config.agents_may_finish look.shared_pages ticket.finish "
    "run.human_input addon.act".split()
)
SETTING_DEFAULTS = {
    "focus.live_session": True,
    "focus.session_typing": False,
    "insights.share_counts": True,
    "insights.share_names": False,
    "secret.allow_get": False,
    "conn.allow": False,
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

    return addons.real_home()


def _source_tree() -> bool:
    here = Path(__file__).resolve()
    return (here.parents[2] / "pyproject.toml").is_file() and here.parent.name == "orch"


def install_kind() -> str:
    """normal | dev | test. The install record sits in orch's own tool environment
    (<sys.prefix>/orch-install.json,
    written by the installer). No record: running from the source tree = test, anything else = normal."""
    try:
        data = json.loads((Path(sys.prefix) / "orch-install.json").read_text(encoding="utf-8"))
        kind = data.get("kind") if isinstance(data, dict) else None
        if kind in ("normal", "dev", "test"):
            return kind
    except (OSError, ValueError):
        pass
    return "test" if _source_tree() else "normal"


def _under(path: str, prefix: str) -> bool:
    """Component-wise: is `path` inside the literal `prefix` (both absolute POSIX strings)?"""
    pp, xp = [x for x in path.split("/") if x], [x for x in prefix.split("/") if x]
    return len(pp) > len(xp) and pp[: len(xp)] == xp


def home_ok(
    account: str, install: str, prefix_real_dir: bool, workspace_realpath: str, home_realpath: str
) -> bool:
    """Reference `home_ok` (secrets.md, vectors `home`): a real workspace pairs only with the default home, a
    test workspace (dev/test install, realpath under the literal <account home>/.orch-test) only with a
    test home."""
    prefix = account.rstrip("/") + "/.orch-test"
    active = install in ("dev", "test") and prefix_real_dir
    ws_test = active and _under(workspace_realpath, prefix)
    default_home = account.rstrip("/") + "/.orch-tool"
    if home_realpath == default_home:
        home = "default"
    elif active and _under(home_realpath, prefix):
        home = "test"
    else:
        home = "other"
    return (not ws_test and home == "default") or (ws_test and home == "test")


def _prefix_is_real_dir(account: Path) -> bool:
    p = account / ".orch-test"
    try:
        st = p.lstat()
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and (not POSIX or st.st_uid == os.getuid())


def guarded_home(root: Path) -> Path:
    """The orch home that guards this workspace, or Refused. A real workspace uses only <account>/.orch-tool;
    a test workspace (dev/test install, under ~/.orch-test) only the test home from ORCH_HOME (else
    HOME/.orch-tool). Any other pairing is refused, with no fallback in either direction."""
    account = account_home()
    acct = str(account)
    install = install_kind()
    real_dir = _prefix_is_real_dir(account)
    ws_real = os.path.realpath(root)
    ws_test = install in ("dev", "test") and real_dir and _under(ws_real, acct.rstrip("/") + "/.orch-test")
    if ws_test:
        env = os.environ.get("ORCH_HOME")
        cand = Path(env) if env else Path(os.environ.get("HOME", "")) / ".orch-tool"
        home_real = os.path.realpath(cand)
    else:
        cand = account / ".orch-tool"
        home_real = acct.rstrip("/") + "/.orch-tool"
        if cand.exists() and os.path.realpath(cand) != os.path.realpath(home_real) or cand.is_symlink():
            raise Refused(NOT_TOGETHER)  # the default folder is a link: never followed
    if not home_ok(acct, install, real_dir, ws_real, home_real):
        raise Refused(NOT_TOGETHER)
    return cand


# ---------------------------------------- folders, files, lock


def _check_dir(p: Path) -> None:
    try:
        st = p.lstat()
    except OSError as e:
        raise Refused(WRONG_RIGHTS) from e
    if not stat.S_ISDIR(st.st_mode):
        raise Refused(WRONG_RIGHTS)
    if POSIX and (st.st_uid != os.getuid() or st.st_mode & 0o077):
        raise Refused(WRONG_RIGHTS)


def _check_file(p: Path) -> None:
    st = p.lstat()  # FileNotFoundError passes through: "not there" is not "wrong rights"
    if not stat.S_ISREG(st.st_mode):
        raise Refused(WRONG_RIGHTS)
    if POSIX and (st.st_uid != os.getuid() or st.st_mode & 0o077):
        raise Refused(WRONG_RIGHTS)


def _private_dir(p: Path, stop: Path) -> None:
    """Create p (and parents below `stop`) with 0700, then check each; a link anywhere below `stop` is
    refused."""
    chain = [c for c in [p, *p.parents] if c != stop and stop in c.parents][::-1]
    for c in chain:
        if not c.exists() and not c.is_symlink():
            c.mkdir(mode=0o700)
            if POSIX:
                c.chmod(0o700)
        _check_dir(c)


def key_dir(root: Path, create: bool = True) -> Path:
    """<guarded home>/keys/<workspace local id>/ (0700)."""
    from orch import addons

    home = guarded_home(root)
    ws = addons.workspace_id(root, create=create)
    if ws is None:
        raise Refused("This folder has no local id yet.")
    d = home / "keys" / ws
    if create:
        home.mkdir(parents=True, exist_ok=True)
        _private_dir(d, home)
    else:
        _check_dir(d)
    return d


def _write_private(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


@contextlib.contextmanager
def _key_lock(d: Path):
    """keys.lock (O_EXCL) around read-modify-write of the nonce store, delivered ids and settings."""
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
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()


def _read_json(path: Path, default):
    try:
        _check_file(path)
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
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
            _check_file(f)
            hexkey = f.read_text(encoding="utf-8").strip()
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
    """Verify a proof against this workspace's key, spend its nonce (single use, under the key lock) and
    return
    `by` FROM THE PROOF. Raises Refused("Do this in the dashboard on this computer.") on any failure."""
    from orch import tickets

    msg = "Do this in the dashboard on this computer."
    try:
        d = key_dir(root, create=False)
    except (Refused, OSError):
        raise Refused(msg) from None
    try:
        key = human_key(root, create=False).hex()
    except (Refused, OSError):
        key = None  # a dev demo workspace has only the dev key; check_proof refuses any non-dev proof then
    now = int(time.time())
    store = d / "proofs-used.json"
    with _key_lock(d):
        try:
            used = _read_json(store, {})
        except Refused:
            raise Refused(msg) from None
        if not isinstance(used, dict):
            raise Refused(msg)
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


def _settings_load(path: Path):
    """None when the file never existed; raises Refused when unreadable or damaged (N12: every widening
    off)."""
    try:
        _check_file(path)
        data = json.loads(path.read_text(encoding="utf-8"))
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
        data = _settings_load(path) or {"schema": "orch.human-settings/1", "workspaces": {}}
        data["workspaces"].setdefault(wkey, {})[setting] = {
            "value": value,
            "by": by,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _write_private(path, json.dumps(data, indent=2, sort_keys=True))


def record_set(root: Path, setting: str, value, by: str) -> None:
    """A person set the value with a verified proof: the caller also writes the file. Record = the grant."""
    _settings_write(root, setting, value, by)


def effective(root: Path, setting: str, file_value: bool) -> bool:
    """Effective value of a widening switch: file AND (record, or the owner default when no record ever
    existed). A False in the file writes the tombstone at once. An unreadable home or record = off (N12)."""
    default = SETTING_DEFAULTS[setting]
    try:
        path, wkey = _settings_path(root)
        data = _settings_load(path)
        rec = ((data or {}).get("workspaces", {}).get(wkey) or {}).get(setting)
        rec_val = rec.get("value") if isinstance(rec, dict) else None
        if file_value is False and rec_val is not False:
            _settings_write(root, setting, False, "file")
            rec_val = False
    except (Refused, OSError):
        return False
    return bool(file_value and (rec_val if rec_val is not None else default))


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
    data = _read_json(d / "delivered.json", {"ids": []})
    ids = data.get("ids") if isinstance(data, dict) else None
    if not isinstance(ids, list):
        raise Refused("The delivered record is unreadable.")
    return {i for i in ids if isinstance(i, str)}


def consume(root: Path, ids: list[str]) -> list[str]:
    """Record ids as delivered, atomically under the key lock. Returns the ids NOT delivered before."""
    d = key_dir(root)
    with _key_lock(d):
        data = _read_json(d / "delivered.json", {"ids": []})
        have = list(data.get("ids") or []) if isinstance(data, dict) else []
        new = [i for i in dict.fromkeys(ids) if i not in have]
        if new:
            _write_private(d / "delivered.json", json.dumps({"ids": (have + new)[-5000:]}))
        return new


def unconsume(root: Path, ids: list[str]) -> None:
    """The core took delivery back (a start hung before the agent read the input). Core-only."""
    d = key_dir(root)
    with _key_lock(d):
        data = _read_json(d / "delivered.json", {"ids": []})
        have = list(data.get("ids") or []) if isinstance(data, dict) else []
        _write_private(d / "delivered.json", json.dumps({"ids": [i for i in have if i not in ids]}))


# ------------------------------------------------------------------------------------------- won't do


def wontdo_mac(key: bytes, workspace: str, item: dict) -> str:
    return _b64u(hmac.new(key, f"wontdo1.{workspace}.{_canon(item)}".encode(), hashlib.sha256).digest())


def wontdo_is_human(key: bytes, workspace: str, item: dict, mac, relay_authenticated_sender: bool) -> bool:
    if relay_authenticated_sender:
        return True
    return isinstance(mac, str) and bool(mac) and hmac.compare_digest(mac, wontdo_mac(key, workspace, item))


def dev_can_mark(install_dev: bool, creating: bool, has_human_key: bool) -> bool:
    return bool(install_dev and creating and not has_human_key)


# ------------------------------------------------------------------------------------------- dev test human


def _dev_path(root: Path) -> Path:
    return guarded_home(root) / "dev-workspaces.json"


def dev_workspace(root: Path) -> bool:
    """Is this workspace a dev demo workspace? ONLY the record in the guarded orch home counts (written by the
    dev installer when it creates the workspace); no workspace file, state dir file or environment is read."""
    try:
        data = _read_json(_dev_path(root), {})
    except (Refused, OSError):
        return False
    ws = data.get("workspaces") if isinstance(data, dict) else None
    return isinstance(ws, dict) and os.path.realpath(root) in ws and install_kind() in ("dev", "test")


def _dev_key_hex(d: Path) -> str | None:
    try:
        _check_file(d / "dev-human.key")
        return (d / "dev-human.key").read_text(encoding="utf-8").strip()
    except (OSError, Refused):
        return None


def dev_mark(root: Path) -> None:
    """Called only by the dev installer when it CREATES a demo workspace (reference dev_can_mark): record the
    workspace as dev and make its dev key. A workspace that already has a human.key never becomes dev."""
    d = key_dir(root)
    if not dev_can_mark(install_kind() in ("dev", "test"), True, (d / "human.key").exists()):
        raise Refused("This workspace cannot be a dev workspace.")
    path = _dev_path(root)
    with _key_lock(d):
        data = _read_json(path, {"workspaces": {}})
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
HANDOFF_PER_OP = 3


def read_proof_line() -> str:
    """The proof is the FIRST line of stdin (--proof-stdin). Never argv, never env."""
    try:
        return sys.stdin.readline().strip()
    except (OSError, ValueError):
        return ""


# The command line a hand-off will run once the person clicks (set by cli.main; never contains --by / --proof-stdin).
CURRENT_ARGV: list[str] | None = None
# What a page may run for a hand-off: the command words an op may start with. The proof binds op and target too.
HANDOFF_HEADS = {
    "ticket.answer": (("answer",),),
    "run.human_input": (("run", "send"),),
    "ticket.verdict": (("ticket", "changes"), ("ticket", "patch")),
    "relay.allow": (("relay", "allow"),),
    "update": (("update",),),
    "chat.send": (("chat", "say"),),
}


def _clean_argv(argv) -> list[str] | None:
    out, skip = [], False
    for a in argv or []:
        if skip:
            skip = False
            continue
        if a == "--by":
            skip = True
            continue
        if a.startswith("--by=") or a == "--proof-stdin":
            continue
        out.append(a)
    return out if all(isinstance(x, str) and len(x) <= 4000 for x in out) and len(out) <= 20 else None


def request_handoff(root: Path, op: str, target: str, label: str = "", value: str = "", argv=None) -> bool:
    """A command asked for a human-only action without a proof: leave a pending item on the page ("Requested
    by a command"). At most 3 per op; a NEW request is dropped when full (N18), never evicting an older one.
    The item holds the command to run once the person clicks. Best effort: a failure here only means the item
    is missing. Returns True when queued."""
    try:
        d = key_dir(root)
        path = d / "handoffs.json"
        now = int(time.time())
        with _key_lock(d):
            items = [i for i in _read_json(path, []) if isinstance(i, dict) and i.get("exp", 0) > now]
            if any(i.get("op") == op and i.get("target") == target and i.get("argv") == argv for i in items):
                return True
            if sum(1 for i in items if i.get("op") == op) >= HANDOFF_PER_OP:
                return False
            items.append(
                {
                    "id": _b64u(secrets.token_bytes(9)),
                    "op": op,
                    "target": target,
                    "label": label[:120],
                    "value": value[:300],
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
        items = _read_json(d / "handoffs.json", [])
        return [i for i in items if isinstance(i, dict) and i.get("exp", 0) > now]
    except (Refused, OSError, ValueError):
        return []


def handoff_take(root: Path, hid: str) -> dict | None:
    """The item with this id, removed from the list (single click, single run). The command must start with
    the words its op allows, else None."""
    try:
        d = key_dir(root, create=False)
        with _key_lock(d):
            items = [i for i in _read_json(d / "handoffs.json", []) if isinstance(i, dict)]
            hit = next((i for i in items if i.get("id") == hid and i.get("exp", 0) > time.time()), None)
            if hit is None:
                return None
            _write_private(d / "handoffs.json", json.dumps([i for i in items if i is not hit]))
    except (Refused, OSError, ValueError):
        return None
    argv = hit.get("argv")
    heads = HANDOFF_HEADS.get(hit.get("op"), ())
    if not isinstance(argv, list) or not any(argv[: len(h)] == list(h) for h in heads):
        return None
    return hit


def handoff_drop(root: Path, hid: str) -> None:
    try:
        d = key_dir(root, create=False)
        with _key_lock(d):
            items = [i for i in _read_json(d / "handoffs.json", []) if isinstance(i, dict) and i.get("id") != hid]
            _write_private(d / "handoffs.json", json.dumps(items))
    except (Refused, OSError, ValueError):
        pass


def _dashboard_note(root: Path) -> str:
    """After a hand-off: open the dashboard on a desktop (fresh launch token in the URL fragment, never printed)
    and say in plain words what to click. No token is ever returned or printed."""
    url = None
    try:
        from orch import services

        row = next((r for r in services.workspace_rows(root) if r.get("addon") == "dashboard"), None)
        url = services.local_url(row.get("url")) if row else None
    except Exception:  # noqa: BLE001 - the note is best effort
        url = None
    if url and sys.stdout.isatty():
        import webbrowser

        with contextlib.suppress(Exception):
            webbrowser.open(launch_url(root, "dashboard", url))
        return f"Opened the dashboard ({url}): press Continue to send this to the agent."
    if url:
        return f"Waiting for your click: open the dashboard ({url}) and press Continue to send this to the agent."
    return "Waiting for your click: open the dashboard on this computer and press Continue."


def person_by(root: Path, args, op: str, target: str, *, label: str = "", value: str = "") -> str:
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
    request_handoff(root, op, target, label, value, _clean_argv(CURRENT_ARGV))
    raise Refused(_dashboard_note(root))


# ------------------------------------------------------------------------------------------- launch token

LAUNCH_LIFE = 120


def write_launch_token(root: Path, server: str) -> str | None:
    """The one-time token that bootstraps a page session: <key folder>/launch-<server>.token (0600, once,
    120 s). Returned ONLY to the code that opens the browser at `#launch=<token>` (a URL fragment); never
    printed or logged."""
    if server not in ("focus", "dashboard"):
        return None
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
            _check_file(f)
            lines = f.read_text(encoding="utf-8").split()
            f.unlink()
    except (Refused, OSError):
        return False
    return (
        len(lines) == 2
        and lines[1].isdigit()
        and int(lines[1]) > time.time()
        and hmac.compare_digest(lines[0], token)
    )


def launch_url(root: Path, server: str, url: str) -> str:
    """`url` with a fresh launch token in the fragment, for the code that opens the browser for a person."""
    token = write_launch_token(root, server)
    return f"{url}#launch={token}" if token else url

"""Deliver keys to commands and hide their output (Level 1).

Every use is written to the run's record (`.orch/record`, record.py) as a key.use event BEFORE the command
starts and before any key file is written, without any value; a writer that cannot write (no hider, damaged
record) stops the command. A call outside a run by a PROVEN person (hp1 proof, cli_secret) goes to the
workspace's unattributed run of the day (run r_outside_<yyyymmdd>, ticket t_outside); every other caller
(`agent=True`, the default of the CLI: nothing the caller controls can lower it) outside a run is refused.
set_recorder() replaces the writer (tests).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time

from orch import hider, keystore, launchenv, term
from orch import humanproof as hp
from orch.errors import Refused

_recorder = None
_NAME = re.compile(r"^[A-Za-z0-9_.+-]{1,64}$")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _run_ids():
    run, ticket = os.environ.get("ORCH_RUN"), os.environ.get("ORCH_TICKET")
    return (run, ticket) if run and ticket else None


OUTSIDE_DAY_CAP = 5000  # lines of the unattributed run of one day
NO_RUN = "Refused: an agent can use keys only inside an active orch run, where the use is recorded."
BAD_RUN = "Refused: this run is not active, so the use cannot be recorded."


def require_run(root, agent) -> None:
    """The run a use is recorded in. Every caller not proven as a person (`agent=True`) must have one
    (ORCH_RUN + ORCH_TICKET naming a live claim that belong together, like orch's own runs), or the call is
    refused before any key is read. A proven person without a run is not refused (its uses go to the
    unattributed run of the day); with a run named in its environment the same check applies (nothing is
    written into another run's record)."""
    ids = _run_ids()
    if ids is None:
        if agent:
            raise Refused(NO_RUN)
        return
    check_live_run(root, *ids)


def check_live_run(root, run, ticket) -> dict:
    """run and ticket name a live claim that belong together: the claim, or Refused (BAD_RUN)."""
    from orch import runs

    try:
        rec = runs.read(root, ticket)
        ok = bool(rec) and rec.get("run") == run and runs.state(rec) in ("alive", "maybe-stale")
    except Exception:
        ok = False
    if not ok:
        raise Refused(BAD_RUN)
    return rec


def _record_event(root, ev):
    """The record line for an event of this module, or None when there is no run to write it to."""
    ids = _run_ids() or (f"r_outside_{time.strftime('%Y%m%d', time.gmtime())}", "t_outside")
    from orch import tickets

    tool = tickets.agent_tool()
    harness = tool if isinstance(tool, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,31}", tool) else "generic"
    line = {
        "run": ids[0],
        "session": None,
        "agent": "main",
        "parent": None,
        "at": _now(),
        "ticket": ids[1],
        "harness": harness,
        "coverage": "full",
        "via": "broker",
        "kind": ev["kind"],
        "detail": None,
        "outcome": {"ok": ev["outcome"]["ok"], "error": None, "ms": None},
    }
    if ev["kind"] == "key.use":
        refused = ev.get("refused")
        sources = {r["name"]: r["source"] for r in keystore.list_keys(root) if r["state"] != "shadowed"}
        cmd = ev.get("command")
        data = {
            "profile": ev["profile"],
            "command": cmd if cmd and _NAME.match(cmd) else None,
            "skill": ev.get("skill"),
        }
        if refused:
            data["refused"] = refused
            line["outcome"]["error"] = "Not allowed by this profile"
        line.update(
            text=f"Key {ev['key']} not given: {refused}"
            if refused
            else f"Key {ev['key']} handed to {data['command'] or 'a command'}",
            used={
                "kind": "key",
                "name": ev["key"],
                "action": ev["action"],
                "source": sources.get(ev["key"], "workspace"),
                "version": None,
            },
            data=data,
        )
    else:
        line.update(
            text=f"Profile {ev['profile']}: {ev['action']}",
            used=None,
            data={"action": ev["action"], "profile": ev["profile"], "by": ev["by"]},
        )
    return line


def _write_record(root, ev):
    """The default recorder: the run's record writer with a hider built from THIS workspace's key store."""
    from orch import record

    require_run(root, False)  # a named run must be live and match; no run: the unattributed run of the day
    line = _record_event(root, ev)
    if _run_ids() is None:  # a script cannot grow the unattributed run without bound
        read = record.read_run(root, line["run"], seen_by="writer")
        if read.status == "ok" and len(read.value) >= OUTSIDE_DAY_CAP:
            raise Refused("Refused: too many key uses outside a run today.")
    record_writer(root).append(line)


def record_writer(root):
    """The record writer with a hider built from THIS workspace's key store (the one place that wires it)."""
    from orch import record

    return record.RecordWriter(root, hider=hider.Hider(keystore.all_needles(root)))


def set_recorder(fn):
    global _recorder
    _recorder = fn


class Recorder:
    def __init__(self, root, h, action, profile, command):
        self.root, self.h = root, h
        self.action, self.profile, self.command = action, profile, os.path.basename(command)

    def record(self, key, refused=None):
        skill = os.environ.get("ORCH_SKILL", "")
        event = {
            "kind": "key.use",
            "key": key,
            "action": self.action,
            "profile": self.profile,
            "command": self.command,
            "skill": skill if keystore.SKILL_RE.fullmatch(skill) else None,
            "outcome": {"ok": refused is None},
            "refused": refused,
        }

        def hide(value):
            if isinstance(value, str):
                return self.h.hide_text(value)
            if isinstance(value, dict):
                return {self.h.hide_text(k): hide(v) for k, v in value.items()}
            return value

        try:
            (_recorder or _write_record)(self.root, hide(event))
        except Exception:
            if refused is None:
                raise Refused("Refused: this use could not be recorded.") from None


def resolve_program(root, name):
    """The absolute path of a program, searched once and only in the safe folders (never cwd or the caller's
    unsafe PATH entries); an absolute name must be an executable file. Used when a person saves a profile."""
    if os.path.isabs(name):
        path = name
    else:
        path = next(
            (os.path.join(d, name) for d in safe_path_dirs(root) if os.path.isfile(os.path.join(d, name))),
            None,
        )
    if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
        raise Refused(f"Refused: the program {name} was not found.")
    return path


def record_change(root, action, profile, by):
    """A person's or anyone's change of a profile switch, to the same recorder seam as key.use (best effort:
    a failing recorder never blocks turning a switch off)."""
    try:
        (_recorder or _write_record)(
            root,
            {
                "kind": "secret.change",
                "action": action,
                "profile": profile,
                "by": by,
                "outcome": {"ok": True},
            },
        )
    except Exception:
        pass


# A pinned (user-owned) program must not be an interpreter: its script arguments are not covered by the pin.
# Tests switch this off (and then the hash is only checked, the file is not copied) to use the test
# interpreter, which cannot run from a copy, as the pinned program.
PIN_STRICT = True
PINNED_INTERPRETER = (
    "Refused: this program runs scripts or any code you give it, so pinning its file would not protect "
    "anything. Choose a program that does one fixed job."
)
PIN_TEXT = (
    "The fingerprint covers this program file (and any file you named as an argument), not the libraries or "
    "settings it loads. orch starts a private copy of the approved file."
)
USER_OWNED = (
    "Refused: the program or a folder above it belongs to your own user, so an agent running as you could "
    "replace it. Choose a program in a system folder, or approve this exact file as the person."
)

RISKY_PROGRAMS = re.compile(
    r"^(sh|bash|zsh|dash|ksh|fish|csh|tcsh|env|xargs|python[0-9.]*|node|npx|npm|pip[0-9.]*|perl|ruby|php|lua|"
    r"java|git|osascript|pwsh|powershell|cmd|ssh|curl|wget|psql|mysql|sqlite3|redis-cli|mongosh)(\.exe)?$",
    re.IGNORECASE,
)


def _under(path: str, base: str) -> bool:
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


def approve_program(root, name, *, allow_user_owned=False):
    """What a person approves as a profile's `run` program: (real path, warnings). Refused: a relative path;
    the program or a folder above it inside the workspace, or changeable by others (group/other-writable; the
    root and admin groups of a normal system are fine); unless `allow_user_owned` (a person's override, whose
    sha256 is then checked right before every spawn), also a program or folder above it owned by the current
    non-root user (an agent running as that user can rewrite it).
    Interpreters and tools that run arbitrary code (sh,
    python, node, env, git, npm, curl, and database clients that read commands from stdin or run shell
    escapes: psql, mysql, sqlite3, redis-cli, mongosh) are allowed but warned about: approving one is
    approving anything."""
    if not os.path.isabs(name) and (os.sep in name or (os.altsep and os.altsep in name) or "/" in name):
        raise Refused("Refused: give the program as a full path or a plain name, not a relative path.")
    path = resolve_program(root, name)
    real = os.path.realpath(path)
    ws = os.path.realpath(root)
    here, chain = real, []
    while True:
        chain.append(here)
        up = os.path.dirname(here)
        if up == here:
            break
        here = up
    for p in chain:
        if _under(p, ws):
            raise Refused("Refused: the program lies inside this workspace; an agent could change it.")
        if os.name != "nt":
            st = os.stat(p)
            admin_gid = (0, 80) if sys.platform == "darwin" else (0,)
            if st.st_mode & 0o002 or (st.st_mode & 0o020 and st.st_gid not in admin_gid):
                raise Refused("Refused: the program or a folder above it can be changed by other users.")
    if os.name != "nt" and not allow_user_owned:
        for p in chain:
            uid = os.stat(p).st_uid
            if uid != 0 and uid == os.getuid():
                raise Refused(USER_OWNED)
    if (
        allow_user_owned
        and PIN_STRICT
        and (RISKY_PROGRAMS.match(os.path.basename(real)) or RISKY_PROGRAMS.match(os.path.basename(name)))
    ):
        raise Refused(PINNED_INTERPRETER)
    warnings = []
    if RISKY_PROGRAMS.match(os.path.basename(real)) or RISKY_PROGRAMS.match(os.path.basename(name)):
        warnings.append(
            f"{os.path.basename(real)} can run any code: approving it as this profile's command is the same "
            "as approving any command."
        )
    return real, warnings


def safe_path_dirs(root):
    """The only folders a plain program name is searched in, and the child's PATH: fixed system folders that
    belong to root and nobody else can change. Never the caller's PATH (an agent can prepend to it)."""
    fixed = ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    if os.name == "nt":
        return [
            p
            for p in [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")]
            if os.path.isdir(p)
        ]
    result = []
    for p in fixed:
        try:
            info = os.stat(p)
        except OSError:
            continue
        if info.st_uid == 0 and not info.st_mode & 0o022 and p not in result:
            result.append(p)
    return result


def _environment(dirs, private, real_home=False):
    names = "LANG LC_ALL LC_CTYPE TERM TZ USER LOGNAME".split()
    if os.name == "nt":
        names += "SYSTEMROOT COMSPEC PATHEXT USERPROFILE APPDATA LOCALAPPDATA TEMP TMP".split()
    env = {
        k: os.environ[k]
        for k in names
        if k in os.environ and len(os.environ[k]) <= 200 and "\0" not in os.environ[k]
    }
    env["PATH"] = os.pathsep.join(dirs)
    # H3: the child works in a private empty folder: no planted config, scripts or modules of the caller's
    # cwd or home are loaded. Programs that read their config from the real home are not contained unless a
    # person approved real_home (then HOME is the real one; the cwd stays private).
    home = launchenv.user_home() if real_home else None
    env["HOME"] = str(home if home is not None else private)
    if os.name == "nt":
        env["TEMP"] = env["TMP"] = str(private)
    env["TMPDIR"] = str(private)  # never the caller's (key-bearing temp files land only in our folder)
    return env


def _program(name, dirs, h):
    paths = (
        [os.path.abspath(name)]
        if os.sep in name or (os.altsep and os.altsep in name)
        else [os.path.join(d, name) for d in dirs]
    )
    for path in paths:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    raise Refused(h.hide_text(f"Refused: the program {name} was not found."))


def _pinned_copy(path, want, temp):
    """Read the program once, check its hash, write exactly those bytes to a private file and return it."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        raise Refused("Refused: could not read the program to check it.") from None
    if hashlib.sha256(data).hexdigest() != want:
        raise Refused("Refused: the program is not the one the person approved (it has changed).")
    copy = temp / "~program"
    keystore._write_private_bytes(copy, data)
    os.chmod(copy, 0o700)
    return str(copy)


def _check_sha(path, want, h):
    """The program about to be started is the exact file a person approved (hash of the bytes just read; a
    tiny window between this check and exec remains: documented limit)."""
    try:
        with open(path, "rb") as f:
            got = hashlib.sha256(f.read()).hexdigest()
    except OSError:
        raise Refused(h.hide_text("Refused: could not read the program to check it.")) from None
    if got != want:
        raise Refused("Refused: the program is not the one the person approved (it has changed).")


def _pid_alive(pid: int) -> bool:
    """Is a process with this pid still running? Unsure counts as alive (nothing is deleted)."""
    if os.name == "nt":
        try:
            import ctypes

            kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return kernel.GetLastError() != 87  # 87 = invalid parameter: no such process
            code = ctypes.c_ulong()
            ok = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
            kernel.CloseHandle(handle)
            return not ok or code.value == 259  # STILL_ACTIVE
        except Exception:
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OverflowError):
        return True
    return True


def sweep_tmp(root):
    home = hp.guarded_home(root)
    tmp = home / "keys" / "tmp"
    if not tmp.exists() and not tmp.is_symlink():
        return
    hp._private_dir(tmp, home)
    for p in tmp.iterdir():
        if not re.fullmatch(r"\d+-[0-9a-f]{16}", p.name):
            continue
        info = p.lstat()
        if not stat.S_ISDIR(info.st_mode):
            continue
        if not _pid_alive(int(p.name.split("-", 1)[0])):
            shutil.rmtree(p, ignore_errors=True)  # one undeletable folder must not stop every use


AGENT_COMMAND = (
    "Refused: agents may only run this profile's own command. "
    "Ask the person to allow any command, or use orch secret exec {p}."
)


def _switch_on(root, name, flag) -> bool:
    """A profile switch (allow_get, agents_may_env): the file flag AND the person's record. The file is read
    again under the key lock, the same lock a person's enable holds across record and file, so a reader never
    writes an off record over an enable in progress."""
    with hp._key_lock(hp.key_dir(root)):
        profile = _verified(root, name)
        return hp.effective(root, f"secret.{flag}.{name}", bool(profile and profile.get(flag) is True))


def _agent_may_run(root, name, profile, command) -> bool:
    """The one gate for an agent's env, file AND exec call (`command` is the full argv, for exec the profile's
    `run` plus any extra arguments): any command only with agents_may_env (file flag AND a person's record);
    else exactly the profile's own `run` (same argv, absolute program, no extra arguments)."""
    if _switch_on(root, name, "agents_may_env"):
        return True
    run = profile.get("run")
    return bool(run) and os.path.isabs(run[0]) and list(command) == list(run)


def _verified(root, name):
    """The profile `name` with its body MAC-verified (None when there is no such profile). A body edited
    outside orch, or without a person's MAC, is refused; the variables are re-checked too (a forged file
    cannot inject loader/interpreter variables even if it carried a valid MAC for them)."""
    profile = keystore.read_profiles(root).get(name)
    if profile is None:
        return None
    if not hp.profile_verified(root, name, profile):
        raise Refused("Refused: " + hp.PROFILE_CHANGED + ".")
    keystore._profile_check({name: profile}, set())  # the variable rules again at run time (same code as set)
    for sect in ("env", "files", "set"):
        if any(
            keystore.env_denied(v, sect) or (sect == "set" and not keystore.set_name_ok(v))
            for v in profile.get(sect, {})
        ):
            raise Refused("Refused: this key profile sets a variable orch does not allow.")
    return profile


def _profile(root, name):
    profile = _verified(root, name)
    if profile is None:
        raise Refused(f"Refused: there is no profile named {name}.")
    return profile


def _value(root, name, recorder):
    try:
        return keystore.get_value(root, name)
    except Refused as exc:
        if str(exc) in ("There is no such key.", "The key file is missing."):
            recorder.record(name, "missing")
        raise


def _pump(pipe, out, h, errors):
    stream = hider.HidingStream(h, binary=True)
    try:
        with pipe:
            while chunk := pipe.read1(65536):
                out.write(stream.feed(chunk, now=True))
                out.flush()
            out.write(stream.close())
            out.flush()
    except BaseException:
        errors.append(True)


def _kill_group(pid: int, grace: float = 2.0) -> None:
    """End every process of the child's own session: TERM, then KILL after a short grace. Nothing left holds a
    key or a pipe."""
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 1.0)):
        try:
            os.killpg(pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        end = time.monotonic() + wait
        while time.monotonic() < end:
            try:
                os.killpg(pid, 0)
            except (ProcessLookupError, PermissionError):
                return
            time.sleep(0.02)


def _child(command, env, h, stdout, stderr, cwd=None):
    child = None
    threads, errors = [], []
    main = threading.current_thread() is threading.main_thread()
    sigs = [getattr(signal, n) for n in ("SIGTERM", "SIGHUP", "SIGQUIT") if hasattr(signal, n)]
    old = {s: signal.getsignal(s) for s in sigs} if main else {}
    state = {"spawning": False, "sig": None}
    interactive = term.is_terminal(sys.stdin)
    # Own session when no terminal input is needed, so a hangup of ours does not leave it running with a key
    # (a child can still open /dev/tty: known limit).
    own_session = not interactive and os.name == "posix"

    def stop(signum, frame):
        for s in sigs:  # the first signal wins; the cleanup below is not interrupted by more
            signal.signal(s, signal.SIG_IGN)
        if state["spawning"]:  # between starting the child and knowing it: act on it right after
            state["sig"] = signum
            return
        raise SystemExit(128 + signum)

    try:
        if main:
            for s in sigs:
                signal.signal(s, stop)
        state["spawning"] = True
        try:
            child = subprocess.Popen(
                command,
                env=env,
                cwd=cwd,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=own_session,
            )
        finally:
            state["spawning"] = False
        if state["sig"] is not None:
            raise SystemExit(128 + state["sig"])
        for pipe, out in ((child.stdout, stdout), (child.stderr, stderr)):
            thread = threading.Thread(target=_pump, args=(pipe, out, h, errors), daemon=True)
            thread.start()
            threads.append(thread)
        code = child.wait()
        for thread in threads:
            thread.join(2.0)
        if own_session and any(t.is_alive() for t in threads):
            _kill_group(child.pid)  # something kept the pipes open after the command ended
            for thread in threads:
                thread.join(2.0)
        if errors:
            raise Refused("Refused: could not run the command.")
        return 128 - code if code < 0 else code
    finally:
        if child is not None:
            if own_session:
                _kill_group(child.pid)  # also anything the command left running with the key
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        for s, handler in old.items():
            signal.signal(s, handler)


def run(root, mode, profile_name, argv, *, stdout, stderr, agent) -> int:
    temp = None
    h = None
    try:
        require_run(root, agent)  # before any key or file is touched
        profile = _profile(root, profile_name)
        if mode not in ("env", "file", "exec"):
            raise Refused("Refused: unknown secret command.")
        sweep_tmp(root)
        command = list(argv)
        if mode == "exec":
            if not profile.get("run"):
                raise Refused("Refused: this profile has no command to run.")
            if not os.path.isabs(profile["run"][0]):
                raise Refused(
                    "Refused: this profile's command is not a full path. "
                    "Ask the person to set the profile again."
                )
            command = profile["run"] + command
        if not command:
            raise Refused("Refused: give a command to run.")
        program_sha = None
        run0 = (profile.get("run") or [None])[0]
        if run0 is not None and command[0] == run0:  # the profile's own program, in every mode
            if not os.path.isabs(run0):
                raise Refused(
                    "Refused: this profile's command is not a full path. Ask the person to set it again."
                )
            # still a safe, existing program now; a user-owned one only with the person's stored fingerprint
            approve_program(root, run0, allow_user_owned=bool(profile.get("run_sha256")))
            program_sha = profile.get("run_sha256")
        for path, want in (profile.get("run_pins") or {}).items():  # every file named in the command
            if path in command[1:]:
                _check_sha(path, want, hider.Hider([]))
        if mode == "env" and not profile.get("env") and profile.get("files"):
            raise Refused("Refused: this profile needs files. Use orch secret file.")
        needles = keystore.all_needles(root)
        h = hider.Hider(needles)
        recorder = Recorder(root, h, mode, profile_name, command[0])
        if agent and not _agent_may_run(root, profile_name, profile, command):
            for name in dict.fromkeys([*profile.get("env", {}).values(), *profile.get("files", {}).values()]):
                recorder.record(name, "agent_command")
            raise Refused(AGENT_COMMAND.format(p=profile_name))
        files = profile.get("files", {}) if mode != "env" else {}
        names = list(dict.fromkeys([*profile.get("env", {}).values(), *files.values()]))
        values = {name: _value(root, name, recorder) for name in names}
        if not needles:
            raise Refused("Refused: no keys are available for hiding output.")
        dirs = safe_path_dirs(root)
        command[0] = _program(command[0], dirs, h)
        home = hp.guarded_home(root)
        parent = home / "keys" / "tmp"
        candidate = parent / f"{os.getpid()}-{secrets.token_hex(8)}"
        private = candidate / "~home"  # empty: the child's cwd and HOME (a key name can never be "~home")
        env = _environment(dirs, private, profile.get("real_home") is True)
        env.update(profile.get("set", {}))
        types = {row["name"]: row["type"] for row in keystore.list_keys(root) if row["state"] != "shadowed"}
        for var, name in profile.get("env", {}).items():
            value = values[name]
            if isinstance(value, bytes):
                raise Refused("Refused: a key file goes in the profile's files section.")
            env[var] = (
                json.dumps(json.loads(value), separators=(",", ":"), ensure_ascii=False)
                if types.get(name) == "json"
                else value
            )
        for name in names:  # recorded BEFORE any key file is written (a failing record leaves nothing behind)
            recorder.record(name)
        hp._private_dir(parent, home)
        candidate.mkdir(mode=0o700)
        temp = candidate
        hp.winacl.set_private(temp, True)
        hp._private_dir(temp, parent)
        private.mkdir(mode=0o700)
        if program_sha is not None:  # run a private copy of the exact bytes that were hashed (no swap race)
            if PIN_STRICT:
                command[0] = _pinned_copy(command[0], program_sha, temp)
            else:
                _check_sha(command[0], program_sha, h)
        if files:
            paths = {}
            for var, name in files.items():
                if name not in paths:
                    path = temp / name
                    value = values[name]
                    keystore._write_private_bytes(
                        path, value if isinstance(value, bytes) else value.encode("utf-8")
                    )
                    paths[name] = str(path)
                env[var] = paths[name]
            command = [
                re.sub(
                    r"\{file:([A-Za-z_][A-Za-z0-9_]*)\}", lambda m: env[m[1]] if m[1] in files else m[0], arg
                )
                for arg in command
            ]
        return _child(command, env, h, stdout, stderr, cwd=str(private))
    except Refused as exc:
        raise Refused(h.hide_text(str(exc)) if h else str(exc)) from None
    except Exception:
        raise Refused("Refused: could not run the command.") from None
    finally:
        if temp is not None:
            try:
                shutil.rmtree(temp)
            except OSError:
                raise Refused("Refused: could not remove the temporary key files.") from None


def _get(root, profile_name, key, *, stdout_is_tty, out, agent) -> None:
    require_run(root, agent)
    profile = _profile(root, profile_name)
    h = hider.Hider(keystore.all_needles(root))
    recorder = Recorder(root, h, "get", profile_name, "")

    def refuse(code, message):
        recorder.record(key, code)
        raise Refused(h.hide_text(message))

    if key not in {*profile.get("env", {}).values(), *profile.get("files", {}).values()}:
        refuse("not_in_profile", f'Refused: the profile "{profile_name}" does not hold the key "{key}".')
    if not _switch_on(root, profile_name, "allow_get"):
        refuse(
            "get_off",
            f'Refused: the profile "{profile_name}" does not allow printing keys. '
            f"Use orch secret env {profile_name} -- <command>.",
        )
    if stdout_is_tty:
        refuse("get_to_terminal", "Refused: this would show the key on a screen. Pipe the output.")
    value = _value(root, key, recorder)
    recorder.record(key)
    out.write(value if isinstance(value, bytes) else value.encode("utf-8"))
    out.flush()


def list_answer(root) -> dict:
    try:  # display only: a damaged file lists the keys with no profiles
        profiles = {  # a profile changed outside orch counts for nothing (it cannot run)
            n: v for n, v in keystore.read_profiles(root).items() if hp.profile_verified(root, n, v)
        }
    except Refused:
        profiles = {}
    items = []
    for row in keystore.list_keys(root):
        members = sorted(
            p
            for p, v in profiles.items()
            if row["name"] in {*v.get("env", {}).values(), *v.get("files", {}).values()}
        )
        state = "managed" if row["source"] == "admin" else "ok" if members else "unused"
        if row["state"] == "needs-reentry":
            state = "needs-reentry"
        items.append(
            {
                "name": row["name"],
                "type": row["type"],
                "source": row["source"],
                "profiles": members,
                "state": state,
                "last_used": None,
                "uses_7d": 0,
                "shadowed": row["state"] == "shadowed",
            }
        )
    return {"items": items, "next": None}


def get(root, profile_name, key, *, stdout_is_tty, out, agent) -> None:
    try:
        _get(root, profile_name, key, stdout_is_tty=stdout_is_tty, out=out, agent=agent)
    except Refused:
        raise
    except Exception:
        raise Refused("Refused: could not print the key.") from None

"""Deliver keys to commands and hide their output (Level 1).

The record store is not merged yet: without set_recorder(), calls proceed without
persisting events. A configured recorder must succeed before a command starts.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import threading
import time
from pathlib import Path

from orch import hider, keystore, launchenv
from orch import humanproof as hp
from orch.errors import Refused

_recorder = None


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

        if _recorder is not None:
            try:
                _recorder(self.root, hide(event))
            except Exception:
                if refused is None:
                    raise Refused("Refused: this use could not be recorded.") from None


def safe_path_dirs(root):
    fixed = ["/usr/bin", "/bin", "/usr/local/bin", "/opt/homebrew/bin", "/usr/sbin", "/sbin"]
    if os.name == "nt":
        fixed = [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")]
    result = [p for p in fixed if os.path.isdir(p)]
    workspace = Path(root).resolve()
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if not os.path.isabs(p) or not os.path.isdir(p) or Path(p).resolve().is_relative_to(workspace):
            continue
        try:
            info = os.stat(p)
        except OSError:
            continue
        if os.name != "nt" and (info.st_mode & 0o022 or info.st_uid not in (0, os.getuid())):
            continue
        if p not in result:
            result.append(p)
    return result


def _environment(dirs):
    names = "LANG LC_ALL LC_CTYPE TERM TZ USER LOGNAME TMPDIR".split()
    if os.name == "nt":
        names += "SYSTEMROOT COMSPEC PATHEXT USERPROFILE APPDATA LOCALAPPDATA TEMP TMP".split()
    env = {
        k: os.environ[k]
        for k in names
        if k in os.environ and len(os.environ[k]) <= 200 and "\0" not in os.environ[k]
    }
    env["PATH"] = os.pathsep.join(dirs)
    home = launchenv.user_home()
    if home is not None:
        env["HOME"] = str(home)
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
        if os.name == "nt":
            dead = time.time() - info.st_mtime > 6 * 3600
        else:
            try:
                os.kill(int(p.name.split("-", 1)[0]), 0)
                dead = False
            except ProcessLookupError:
                dead = True
            except (PermissionError, OverflowError):
                dead = False
        if dead:
            shutil.rmtree(p)


def _profile(root, name):
    profile = keystore.read_profiles(root).get(name)
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
                out.write(stream.feed(chunk))
                out.flush()
            out.write(stream.close())
            out.flush()
    except BaseException:
        errors.append(True)


def _child(command, env, h, stdout, stderr):
    child = None
    threads, errors = [], []
    main = threading.current_thread() is threading.main_thread()
    old = signal.getsignal(signal.SIGTERM) if main else None

    def stop(signum, frame):
        raise SystemExit(128 + signum)

    try:
        if main:
            signal.signal(signal.SIGTERM, stop)
        child = subprocess.Popen(
            command, env=env, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        for pipe, out in ((child.stdout, stdout), (child.stderr, stderr)):
            thread = threading.Thread(target=_pump, args=(pipe, out, h, errors), daemon=True)
            thread.start()
            threads.append(thread)
        code = child.wait()
        for thread in threads:
            thread.join()
        if errors:
            raise Refused("Refused: could not run the command.")
        return 128 - code if code < 0 else code
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        if main:
            signal.signal(signal.SIGTERM, old)


def run(root, mode, profile_name, argv, *, stdout, stderr) -> int:
    temp = None
    h = None
    try:
        profile = _profile(root, profile_name)
        if mode not in ("env", "file", "exec"):
            raise Refused("Refused: unknown secret command.")
        if mode in ("file", "exec"):
            sweep_tmp(root)
        command = list(argv)
        if mode == "exec":
            if not profile.get("run"):
                raise Refused("Refused: this profile has no command to run.")
            command = profile["run"] + command
        if not command:
            raise Refused("Refused: give a command to run.")
        if mode == "env" and not profile.get("env") and profile.get("files"):
            raise Refused("Refused: this profile needs files. Use orch secret file.")
        needles = keystore.all_needles(root)
        h = hider.Hider(needles)
        recorder = Recorder(root, h, mode, profile_name, command[0])
        files = profile.get("files", {}) if mode != "env" else {}
        names = list(dict.fromkeys([*profile.get("env", {}).values(), *files.values()]))
        values = {name: _value(root, name, recorder) for name in names}
        if not needles:
            raise Refused("Refused: no keys are available for hiding output.")
        dirs = safe_path_dirs(root)
        command[0] = _program(command[0], dirs, h)
        env = _environment(dirs)
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
        if files:
            home = hp.guarded_home(root)
            parent = home / "keys" / "tmp"
            hp._private_dir(parent, home)
            candidate = parent / f"{os.getpid()}-{secrets.token_hex(8)}"
            candidate.mkdir(mode=0o700)
            temp = candidate
            hp.winacl.set_private(temp, True)
            hp._private_dir(temp, parent)
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
        for name in names:
            recorder.record(name)
        return _child(command, env, h, stdout, stderr)
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


def _get(root, profile_name, key, *, stdout_is_tty, out) -> None:
    profile = _profile(root, profile_name)
    h = hider.Hider(keystore.all_needles(root))
    recorder = Recorder(root, h, "get", profile_name, "")

    def refuse(code, message):
        recorder.record(key, code)
        raise Refused(h.hide_text(message))

    if key not in {*profile.get("env", {}).values(), *profile.get("files", {}).values()}:
        refuse("not_in_profile", f'Refused: the profile "{profile_name}" does not hold the key "{key}".')
    if not (
        profile.get("allow_get") is True and hp.effective(root, f"secret.allow_get.{profile_name}", True)
    ):
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
    profiles = keystore.read_profiles(root)
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


def get(root, profile_name, key, *, stdout_is_tty, out) -> None:
    try:
        _get(root, profile_name, key, stdout_is_tty=stdout_is_tty, out=out)
    except Refused:
        raise
    except Exception:
        raise Refused("Refused: could not print the key.") from None

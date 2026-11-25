"""Windows: reinstall orch after this orch has exited.

Windows does not let a program delete (or even rename) the files it runs from. `uv tool install --reinstall`
replaces orch's own tool folder, so when orch ran it, uv stopped halfway ("Access is denied") and left orch
broken (`No module named 'orch'`). On Windows orch therefore hands the reinstall to a small finisher: a
standalone script run by the base Python (outside the tool folder, it imports nothing from orch). It waits
until orch has exited and the folder is free, runs uv, saves the add-on list and runs the follow-up step
(e.g. turning the add-on on in the workspace). Its log: <orch home>/finish.log. While the dashboard is off it
serves the "orch is updating" page on the dashboard's address(es) (orch_ui/static/updating.html, copied with the
master stylesheets to <orch home>/finish/page before orch is replaced; ORCH-1794).

The entry guard reads <orch home>/finish.updating (a decimal owner PID), beside finish.pending and
finish/job.json. The finisher holds it from before the folder probe/reinstall through RESULT ok/fail,
and removes it in finally. Dead owners or markers older than 15 minutes are ignored. POSIX holds the
same marker around its in-place package reinstall. The top-level orch_entry checks both ORCH_HOME and
the account's ~/.orch-tool (orch may reject an untrusted override). Internal `python -m orch` follow-up
commands deliberately remain usable while the finisher owns the marker."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from orch import keepold
from orch.keepold import STILL_OLD, backup_tool, discard_backup, plain_reason, restore_tool  # noqa: F401
from orch_entry import marker_path, step_path, updating

# The finisher. Kept free of orch imports: it runs while orch's own files are being replaced.
FINISHER = r'''
import json, os, subprocess, sys, time

job = json.load(open(sys.argv[1], encoding="utf-8"))
job.setdefault("updating", os.path.join(os.path.dirname(job["pending"]), "finish.updating"))
job.setdefault("step", os.path.join(os.path.dirname(job["updating"]), "finish.step"))
job.setdefault("took", os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), "took.json"))
log = open(job["log"], "a", encoding="utf-8")
registry_written = False
registry_before = None
final_line = None
stopped = []  # workspaces whose services this finisher stopped: they are started again at the end


NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW: a child never opens a console window


def say(text):
    log.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
    log.flush()


began = time.time()
now_step = {"n": 0, "of": 0, "label": None, "since": began}
# For the updating page (ORCH-1794): the plain name of every step, the seconds each finished step took and
# what each took last time (finish/took.json, written after an update that worked).
names = []
spent = {}
usual = {}


def took(seconds):
    return "%d s" % seconds if seconds < 90 else "%d min" % round(seconds / 60)


def end_step():
    if now_step["label"]:
        seconds = time.time() - now_step["since"]
        spent[now_step["n"]] = round(seconds, 1)
        say("step %d of %d done (%s)" % (now_step["n"], now_step["of"], took(seconds)))
        now_step["label"] = None


def step(label, n=None):
    """A progress line per step in the log, and the step in finish.step: `orch` says it while this runs."""
    end_step()
    now_step.update(n=n or now_step["n"] + 1, label=label, since=time.time())
    now_step["of"] = max(now_step["of"], now_step["n"])
    say("step %d of %d: %s" % (now_step["n"], now_step["of"], label))
    try:
        tmp = job["step"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({**now_step, "began": began, "names": names,
                       "took": [spent.get(k) for k in range(1, now_step["n"])],
                       "usual": [usual.get(x) for x in names]}, f)
        os.replace(tmp, job["step"])
    except OSError:
        pass


def plan_names():
    out = ["Stopping the dashboard"] if job.get("services") else []
    out.append("Getting the new orch")
    out += [cmd.get("name") or "Updating this workspace" for cmd in job["then"]]
    if job.get("services"):
        out.append("Starting the dashboard again")
    return out


def load_usual():
    try:
        with open(job["took"], encoding="utf-8") as f:
            data = json.load(f)
        usual.update({k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, (int, float))})
    except Exception:
        pass


def save_usual():
    try:
        tmp = job["took"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({names[k - 1]: v for k, v in spent.items() if 0 < k <= len(names)}, f)
        os.replace(tmp, job["took"])
    except Exception:
        pass


# ---- the "orch is updating" page (ORCH-1794): on the dashboard's addresses while the dashboard is off

PAGE_PREFIX = "/orch-updating/"
PAGE_FILES = {"tokens.css": "text/css", "components.css": "text/css", "motion.css": "text/css",
              "widgets.css": "text/css", "updating.js": "text/javascript"}
page_servers = []
page_end = {"result": None, "bad": None, "reason": None}


def page_state():
    """What the page shows: finish.step as this finisher wrote it, plus how it ended (once it has)."""
    try:
        with open(job["step"], "rb") as f:
            data = json.loads(f.read(65536).decode("utf-8"))
    except (OSError, ValueError):
        data = {}
    keep = ("n", "of", "since", "began", "names", "took", "usual")
    out = {k: data[k] for k in keep if k in data}
    out.update(page_end, orch_updating=True, now=time.time())
    return out


def serve_page():
    page = job.get("page")
    if not page:
        return
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    def read(name):
        with open(os.path.join(page["dir"], name), "rb") as f:
            return f.read()

    class Page(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body, kind):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
            if code == 503:
                self.send_header("Retry-After", "5")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            name = path[len(PAGE_PREFIX):] if path.startswith(PAGE_PREFIX) else ""
            try:
                if name == "state":
                    return self.send(200, json.dumps(page_state()).encode("utf-8"), "application/json")
                if name in PAGE_FILES:
                    return self.send(200, read(name), PAGE_FILES[name] + "; charset=utf-8")
                self.send(503, read("updating.html"), "text/html; charset=utf-8")
            except OSError:
                self.send(503, b"orch is updating. Try again in a few minutes.", "text/plain; charset=utf-8")

        do_HEAD = do_GET

        def do_POST(self):
            self.send(503, b'{"error": "orch is updating. Try again in a few minutes."}', "application/json")

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = os.name != "nt"  # Windows: it would let two servers share a port

    for host, port in page.get("at") or []:
        server = None
        for _ in range(int(job.get("page_tries", 20))):  # the dashboard has just stopped: its port frees soon
            try:
                server = Server((host, int(port)), Page)
                break
            except OSError:
                time.sleep(0.25)
        if server is None:
            say("could not show the updating page on port %s (it is still in use)" % port)
            continue
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()
        page_servers.append(server)
        say("the updating page is on port %s" % port)


def stop_page():
    """Free the dashboard's port before it starts again; an open page first sees how the update ended."""
    if not page_servers:
        return
    if final_line and final_line.startswith("RESULT fail"):
        why = final_line[len("RESULT fail: "):].strip()
        page_end.update(result="fail", bad=page_end["bad"],
                        reason=why if why and "\n" not in why and len(why) <= 200 else None)
    else:
        page_end["result"] = "ok"
    time.sleep(job.get("page_linger", 2.5))  # the page asks every second
    for server in page_servers:
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
    del page_servers[:]


IN_USE_SUFFIXES = (".exe", ".pyd", ".dll")


def _held(path):
    """Windows: a running program or a loaded module can not be opened for writing with no sharing."""
    if os.name != "nt":  # tests on POSIX name the held paths in the job
        return path in (job.get("test_held") or ())
    import ctypes
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    d = wintypes.DWORD
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, d, d, ctypes.c_void_p, d, d, ctypes.c_void_p]
    k.CreateFileW.restype = ctypes.c_void_p
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k.CreateFileW(path, 0x40000000, 0, None, 3, 0x80, None)  # GENERIC_WRITE, no sharing, OPEN_EXISTING
    if h is None or h == ctypes.c_void_p(-1).value:
        return ctypes.get_last_error() not in (2, 3)  # gone is not held
    k.CloseHandle(h)
    return False


def free(path):
    """Nothing runs from `path` any more. Windows: no program or module under it is held open; checked without
    renaming anything (a rename made a starting orch miss its own files). Elsewhere: nothing to wait for."""
    if not os.path.exists(path):
        return True
    if os.path.isfile(path) or os.name != "nt":
        return not _held(path)
    for top, _dirs, files in os.walk(path):
        for name in files:
            if name.lower().endswith(IN_USE_SUFFIXES) and _held(os.path.join(top, name)):
                return False
    return True


def busy():
    """Keep the pending mark fresh while this finisher works (orch refuses a second job meanwhile)."""
    try:
        os.utime(job["pending"])
    except OSError:
        pass


def result(text):
    """The RESULT line is written last, after the services are back (the page waits for it)."""
    global final_line
    final_line = "RESULT " + text
    if text.startswith("fail") and page_end["bad"] is None:
        page_end["bad"] = now_step["n"]  # the step the updating page marks as failed


def orch(verb, *args, cwd=None):
    r = subprocess.run([job["py"], "-I", "-P", "-m", "orch", verb, *args], cwd=cwd, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=120, creationflags=NO_WINDOW)
    return r


def stop_services():
    """The dashboard and the other add-on services run from the tool folder: stop them like `orch stop`."""
    for ws in job.get("services") or []:
        try:
            r = orch("stop", ws, cwd=ws)
            say("stopped the services in " + ws + (" (exit %d)" % r.returncode if r.returncode else ""))
            stopped.append(ws)
        except Exception as e:  # keep going: the folder check below says if something still runs
            say("could not stop the services in " + ws + ": " + str(e)[:200])
            stopped.append(ws)


def start_services():
    if stopped:
        step("starting the dashboard and the other services again", now_step["of"])
    stop_page()
    for ws in stopped:
        try:
            r = orch("start", "--no-open", cwd=ws)
            say("started the services in " + ws + " again" if r.returncode == 0
                else "could not start the services in " + ws + ": " + (r.stderr or r.stdout).strip()[-300:])
        except Exception as e:
            say("could not start the services in " + ws + ": " + str(e)[:200])


def wait_free():
    deadline = time.time() + job["wait"]
    while True:
        busy_paths = [p for p in job["free"] if not free(p)]
        if not busy_paths:
            return []
        if time.time() > deadline:
            return busy_paths
        busy()
        time.sleep(0.5)


def reinstall_once(last):
    """None: uv succeeded. "again": orch held its files while uv replaced them (the old one is back). Else the
    exit code, with the RESULT line set."""
    busy_paths = wait_free()
    if busy_paths:
        result("fail: still in use after %ds: %s. Nothing was changed. Run the command again."
               % (job["wait"], ", ".join(busy_paths)))
        return 1
    busy()
    kept = None
    if job.get("backup"):
        try:
            kept = backup_tool(job["backup"]["env"], job["backup"].get("bins"))
        except Exception as e:
            say("could not keep a copy of orch: " + str(e)[:300])
            result("fail: could not keep a copy of orch, so nothing was changed. Try again later.")
            return 1
    busy()
    try:
        env = dict(os.environ)
        env.update(job.get("env") or {})  # e.g. UV_TOOL_DIR pinned to where the person installed orch
        r = subprocess.run(job["uv"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=job["uv_timeout"], env=env, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        restored = restore_tool(kept, job.get("restore_wait", 60)) if kept else not job.get("backup")
        result("fail: " + plain_reason("took too long", restored))
        return 1
    busy()
    if r.returncode == 0:
        discard_backup(kept)
        return None
    detail = (r.stderr or r.stdout).strip()[-1500:]
    say("uv failed: " + detail)
    restored = restore_tool(kept, job.get("restore_wait", 60)) if kept else not job.get("backup")
    say("the old orch was put back" if restored else "the old orch could NOT be put back")
    if restored and not last and locked_failure(detail):
        return "again"
    result("fail: " + plain_reason(detail, restored))
    return 1


def main():
    global registry_written, registry_before
    try:
        os.remove(job["step"])  # left by a finisher that was killed
    except OSError:
        pass
    with open(job["updating"], "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    busy()
    names[:] = plan_names()
    now_step["of"] = len(names)
    load_usual()
    if job.get("services"):
        time.sleep(job.get("stop_delay", 3))  # the update that started us is just ending
        step("stopping the dashboard and the other services")
        stop_services()
        serve_page()
    step("replacing orch: download and install (often 1 to 2 min)")
    say("waiting for orch to exit (finisher pid %d; folders: %s)" % (os.getpid(), ", ".join(job["free"])))
    tries = job.get("tries", 3)
    for attempt in range(1, tries + 1):
        code = reinstall_once(attempt == tries)
        if code is None:
            break
        if code != "again":
            return code
        say("orch was started while it was being replaced; trying again (%d of %d)" % (attempt + 1, tries))
    if job.get("record"):  # the reinstall drops the install record: put it back
        rpath, rtext = job["record"]
        with open(rpath, "w", encoding="utf-8", newline="\n") as f:
            f.write(rtext)
    if job.get("registry"):
        path, data = job["registry"]
        if os.path.exists(path):
            with open(path, "rb") as f:
                registry_before = f.read()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, path)
        registry_written = True
    for cmd in job["then"]:
        step("running orch " + " ".join(cmd["argv"][5:]) + " (can take several minutes)")
        r = subprocess.run(cmd["argv"], cwd=cmd["cwd"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", creationflags=NO_WINDOW)
        say((r.stdout + r.stderr).strip())
        if r.returncode != 0:
            result("fail: " + " ".join(cmd["argv"][3:]) + " failed (see above)")
            return 1
    end_step()
    result("ok: " + job["done"])
    return 0


code = 1
try:
    code = main()
except Exception:
    import traceback

    result("fail: " + traceback.format_exc())
finally:
    try:
        os.remove(job["updating"])
    except OSError:
        pass
    if code != 0 and registry_written:
        path = job["registry"][0]
        if registry_before is None:
            os.remove(path)
        else:
            with open(path, "wb") as f:
                f.write(registry_before)
    if code != 0 and job.get("consents"):  # the consents this install recorded turn nothing on later
        try:
            cpath, wid, names = job["consents"]
            with open(cpath, encoding="utf-8") as f:
                items = json.load(f)
            items = [e for e in items if not (e.get("workspace_id") == wid and e.get("name") in names)]
            with open(cpath + ".tmp", "w", encoding="utf-8") as f:
                f.write(json.dumps(items, indent=2))
            os.replace(cpath + ".tmp", cpath)
        except Exception:
            say("could not drop the consents: " + str(job["consents"]))
    try:
        start_services()  # also after a failure: what ran before runs again
        end_step()
    except Exception:
        pass
    try:
        stop_page()  # no services to start: the page still must not outlive the finisher
    except Exception:
        pass
    if code == 0:
        save_usual()
    try:
        os.remove(job["step"])
    except OSError:
        pass
    if final_line:
        say(final_line)
    try:
        os.remove(job["pending"])
    except OSError:
        pass
sys.exit(code)
'''
# The finisher carries keepold's code (one copy, no orch imports) in front of its own.
FINISHER = FINISHER.replace(
    "\njob = json.load", Path(keepold.__file__).read_text(encoding="utf-8") + "\njob = json.load", 1
)


PENDING_MAX_AGE = 600  # seconds without a sign of life: the finisher has died
UV_TIMEOUT = 480  # below PENDING_MAX_AGE: the mark is refreshed right before uv starts


class Busy(RuntimeError):
    """Another finisher is still at work."""


def needed() -> bool:
    """A reinstall must wait until orch has exited (only on Windows)."""
    return sys.platform == "win32"


def result_ok_since(home: Path, offset: object) -> bool:
    """Did the finisher log `RESULT ok` (and no `RESULT fail`) after byte `offset` of finish.log?
    Bounded read; a bad offset or an unreadable log counts as not ok."""
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return False
    try:
        with log_path(home).open("rb") as log:
            log.seek(offset)
            result = log.read(1_000_000).decode("utf-8", "replace")
    except (OSError, ValueError):
        return False
    return "RESULT ok:" in result and "RESULT fail:" not in result


def fail_reason_since(home: Path, offset: object) -> str:
    """A plain reason for the page, from the `RESULT fail:` line the finisher logged after `offset`."""
    default = "The background update failed. Run it again."
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return default
    try:
        with log_path(home).open("rb") as log:
            log.seek(offset)
            text = log.read(1_000_000).decode("utf-8", "replace")
    except (OSError, ValueError):
        return default
    line = next((x for x in text.splitlines() if "RESULT fail:" in x), "")
    why = line.split("RESULT fail:", 1)[-1].strip()
    if STILL_OLD in why or "could not be put back" in why or "could not keep a copy" in why:
        return why[:200]
    if "still in use" in why:
        return "orch was still running, so nothing was changed. Run the update again."
    if "took too long" in why:
        return "The reinstall took too long. Run the update again."
    if "reinstall failed" in why:
        return "The reinstall failed. Run the update again."
    if why:
        # The last line of what the finisher logged (a traceback ends in the real error): the person sees it
        # on screen when the log cannot be sent. Paths are cut out, the rest stays short.
        import re

        tail = text.split("RESULT fail:", 1)[-1].strip().splitlines()
        last = re.sub(r"[A-Za-z]:\\[^\s'\"]*", "<path>", tail[-1].strip())[:140] if tail else ""
        more = f" Reason: {last}." if last else ""
        return "The background update failed; nothing more was changed." + more + " Run it again."
    return default


def log_path(home: Path) -> Path:
    return home / "finish.log"


def pending(home: Path) -> bool:
    """A finisher is still at work. Each job carries the whole add-on list, so a second one started now
    would undo the first (e.g. bring back an add-on that was just removed). The mark holds the finisher's
    process id: a finisher that died (e.g. ended with the SSH session that started it) does not block."""
    import time

    mark = home / "finish.pending"
    try:
        fresh = time.time() - mark.stat().st_mtime < PENDING_MAX_AGE
        text = mark.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not fresh:
        return False
    return not text.isdigit() or _alive(int(text))


def _alive(pid: int) -> bool:
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True
    import ctypes

    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def start(home: Path, uv_argv: list[str], then: list[list[str]], cwd: Path, done: str,
          registry: tuple[Path, str] | None = None, extra: dict | None = None) -> Path:  # fmt: skip
    """Start the finisher detached and return its log. `then`: orch commands run afterwards (in `cwd`)."""
    base = getattr(sys, "_base_executable", None)
    if not base or Path(base).resolve().is_relative_to(Path(sys.prefix).resolve()):
        # the finisher must not run from orch's own folder: it would keep that folder locked
        raise RuntimeError("no Python outside orch's tool folder to finish the install with")
    env_dir = Path(sys.prefix)  # the uv tool folder this orch runs from
    py = env_dir / "Scripts" / "python.exe"
    free = [str(env_dir)]
    launcher = Path(sys.argv[0])
    if launcher.suffix.lower() == ".exe" and launcher.is_file():
        free.append(str(launcher))  # orch.exe in uv's bin folder: uv replaces it too
    job = {
        "uv": uv_argv,
        "free": free,
        "wait": 120,
        "uv_timeout": UV_TIMEOUT,
        "registry": [str(registry[0]), registry[1]] if registry else None,
        "env": (extra or {}).get("env"),
        "record": (extra or {}).get("record"),
        "consents": (extra or {}).get("consents"),  # [consent.json, workspace id, names]: dropped on failure
        "backup": {"env": str(env_dir), "bins": (extra or {}).get("bins") or []},
        "then": [
            {"argv": [str(py), "-I", "-P", "-m", "orch", *t], "cwd": str(cwd), "name": _then_name(t)}
            for t in then
        ],
        "py": str(py),
        "services": [str(w) for w in (extra or {}).get("services") or []],
        "log": str(log_path(home)),
        "done": done,
        "pending": str(home / "finish.pending"),
        "updating": str(marker_path(home)),
        "step": str(step_path(home)),
    }
    # In orch's own folder, not %TEMP% (which can be shared, e.g. C:\Windows\Temp for tasks).
    d = home / "finish"
    d.mkdir(parents=True, exist_ok=True)
    job["took"] = str(d / "took.json")
    job["page"] = _copy_page(d / "page", (extra or {}).get("page"))
    (d / "finish.py").write_text(FINISHER, encoding="utf-8")
    (d / "job.json").write_text(json.dumps(job), encoding="utf-8")
    # NOT DETACHED_PROCESS: with no console at all, every program the finisher runs (uv, orch stop/start)
    # opens its own visible, empty console window. CREATE_NO_WINDOW gives it a hidden console
    # that its children inherit.
    flags = 0x00000200 | 0x08000000  # NEW_PROCESS_GROUP, NO_WINDOW
    breakaway = (
        0x01000000  # CREATE_BREAKAWAY_FROM_JOB: outlive the job (e.g. an SSH session) that started orch
    )
    kw = dict(
        cwd=str(d),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        env={k: v for k, v in os.environ.items() if not k.startswith("PYTHON")},
    )
    argv = [base, "-I", str(d / "finish.py"), str(d / "job.json")]
    mark = home / "finish.pending"
    _claim(home, mark)  # no second job from here on
    try:
        try:
            pid = _popen(argv, creationflags=flags | breakaway, **kw)
        except OSError:  # the job does not allow breaking away: start it inside the job
            pid = _popen(argv, creationflags=flags, **kw)
        mark.write_text(str(pid), encoding="utf-8")
    except Exception as e:  # any failure: free the mark, or it would block installs for 10 minutes
        mark.unlink(missing_ok=True)
        raise RuntimeError(f"could not start the finisher: {e}") from e
    return log_path(home)


def _then_name(argv: list[str]) -> str:
    """The plain name of a follow-up step on the updating page."""
    if argv[:2] == ["addon", "add"] and len(argv) > 2:
        return f"Turning on {argv[2]}"
    return "Updating this workspace"


PAGE_FILES = ("updating.html", "updating.js", "tokens.css", "components.css", "motion.css", "widgets.css")


def _copy_page(d: Path, at: object) -> dict | None:
    """The updating page and the master files it needs, copied next to the finisher now: the finisher
    serves them while orch's own folder is being replaced. `at`: the dashboard's [host, port] pairs.
    None: no page."""
    if not isinstance(at, list) or not at:
        return None
    import orch

    # found by path: the core never imports orch_ui
    kit = Path(orch.__file__).resolve().parent.parent / "orch_ui" / "static"
    try:
        d.mkdir(parents=True, exist_ok=True)
        for name in PAGE_FILES:
            shutil.copyfile(kit / name, d / name)
    except OSError:
        return None  # the update goes on without the page
    return {"dir": str(d), "at": [[str(h), int(p)] for h, p in at]}


def _claim(home: Path, mark: Path) -> None:
    """Create the pending mark atomically (two orch commands at the same moment: only one gets it). A mark
    left by a finisher that is gone is taken over."""
    for _ in range(2):
        try:
            fd = os.open(mark, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if pending(home):
                raise Busy("an add-on install or update is still finishing in the background") from None
            mark.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("starting")
        return
    raise Busy("an add-on install or update is still finishing in the background")


def _popen(argv: list[str], **kw) -> int:
    """Start the finisher; its process id. Tests replace this."""
    return subprocess.Popen(argv, **kw).pid


@contextlib.contextmanager
def replacing(home: Path):
    """POSIX in-place reinstall: same PID marker and RESULT-before-release as Windows."""
    home.mkdir(parents=True, exist_ok=True)
    mark = marker_path(home)
    if updating(home):
        raise Busy("orch is still updating, try again in a moment.")
    mark.write_text(str(os.getpid()), encoding="utf-8")
    result = "fail: package reinstall"
    detail = ""
    try:
        yield
        result = "ok: package reinstall"
    except BaseException as e:  # the reason goes into finish.log (a detached update has no terminal)
        cause = e.__cause__ or e
        detail = " ".join(str(cause).split()).removeprefix("uv failed: ")[-1500:]
        result = "fail: package reinstall: " + " ".join(str(e).split())[:300]
        raise
    finally:
        try:
            with log_path(home).open("a", encoding="utf-8") as log:
                if detail:
                    log.write(f"uv failed: {detail}\n")
                log.write(f"RESULT {result}\n")
        finally:
            mark.unlink(missing_ok=True)

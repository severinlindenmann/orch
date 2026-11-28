"""`orch doctor` and `orch uninstall`: install and leave (R8.5).

`doctor` only reads. `uninstall` undoes what `orch init` and the add-ons wrote in this folder and in the
person's orch home, newest first, and keeps the person's data (tickets, settings, secrets).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from orch import adapters, addons, harness, history, nextstep, procs, reminder_settings, services, skills
from orch.errors import Refused

TOOL = "orch-workspace"  # the uv tool the installers make (install.sh, install.ps1)
KEPT = (".orch/tickets", ".orch/config.toml", ".orch/secrets")  # the person's data


def _out(args, data, text: str) -> None:
    if args.json:
        data = history.shown_json(history.args_root(args), data)
    nextstep.remember(args, data)
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def add_parsers(sub, common) -> None:
    d = sub.add_parser("doctor", parents=[common], help="show what is wrong with orch here (read-only)")
    dsub = d.add_subparsers(dest="doctor_cmd", metavar="<command>")
    p = dsub.add_parser(
        "pass", parents=[common], help="the scheduled health checks and clean-up, once now (makes tickets)"
    )
    p.add_argument("--dry-run", action="store_true", help="only say what it would clean up and open")
    p.add_argument("--no-cleanup", action="store_true", help="checks only")
    p.add_argument("--simulate", help=argparse.SUPPRESS)  # tests: a JSON file of probe results
    dsub.add_parser("soon", parents=[common], help="start a pass in the background when one is due")
    p = dsub.add_parser("setup", parents=[common], help="turn the scheduled checks on here from a JSON file")
    p.add_argument("file", nargs="?", help="the setup (JSON); without it: show the one in use")
    p.add_argument("--off", action="store_true", help="turn the scheduled checks off on this computer")
    p = dsub.add_parser(
        "clean", parents=[common], help="list (or with --apply remove) finished copies and old test folders"
    )
    p.add_argument("--apply", action="store_true")
    p = dsub.add_parser("remove-temp", parents=[common], help="delete temp folders your own mktemp made")
    p.add_argument("paths", nargs="+")
    p = dsub.add_parser(
        "stop-pids", parents=[common], help="stop exactly these processes and prove they are gone"
    )
    p.add_argument("pids", nargs="+")
    sub.add_parser("uninstall", parents=[common], help="take orch out of this folder (your tickets stay)")


# ------------------------------------------------------------------ doctor


def _row(name: str, ok: bool, fact: str, nxt: str | None = None) -> dict:
    return {"name": name, "ok": ok, "fact": fact, "next": None if ok else nxt}


def _all_agent_files(key: str) -> list[str]:
    out = []
    for n in adapters.builtin_names():
        files = adapters.load(n).get("files") or {}
        v = files.get(key)
        for item in list(v) if isinstance(v, dict) else [v] if v else []:
            if item not in out:
                out.append(item)
    return out


def _skill_linked(root: Path, where: str, name: str) -> bool:
    return (root / where / name / "SKILL.md").is_file()


def _launcher_row() -> dict:
    """orch on the PATH. On Windows also whether orch.exe starts: a company rule may block it, and orch then
    still works through Python (ORCH-2138)."""
    problem = procs.launcher_problem()
    if problem is None:
        found = bool(shutil.which("orch"))
        return _row(
            "orch on the PATH",
            found,
            "orch is on your PATH." if found else "orch is not on your PATH.",
            "Open a new terminal window, or run the install line again.",
        )
    py = procs.python_command_line()
    fact = (
        "orch.exe is blocked on this computer (a company rule may block .exe files)."
        if problem == "blocked"
        else "orch.exe is not on your PATH."
    )
    return _row(
        "orch on the PATH",
        False,
        f"{fact} orch still works through Python: the dashboard, add-ons and helpers do not need orch.exe.",
        f"Type {py} instead of orch, for example: {py} doctor"
        if problem == "blocked"
        else f"Open a new terminal window or run the install line again; until then type {py} for orch.",
    )


def install_checks(root: Path) -> list[dict]:
    rows = [_launcher_row()]
    if (root / ".git").exists():
        from orch import safegit

        ok = safegit.have_git(root)
        rows.append(
            _row(
                "git",
                ok,
                "git is found." if ok else "git was not found.",
                "Install git, then run orch doctor again.",
            )
        )
    uv = addons._which_uv()
    uv_err = _uv_fails(uv) if uv else None
    rows.append(
        _row(
            "uv",
            bool(uv) and not uv_err,
            "uv is found."
            if uv and not uv_err
            else f"uv at {uv} does not run ({uv_err})."
            if uv
            else "uv was not found (orch update needs it).",
            "Run the install line again; it installs uv.",
        )
    )
    if not (root / ".orch").is_dir():
        rows.append(_row("this folder", False, "orch is not set up in this folder.", "Run: orch init"))
        return rows
    rows.append(_row("this folder", True, "orch is set up in this folder."))
    linked = _skill_linked(root, ".agents/skills", "orch")
    rows.append(
        _row(
            "skill link",
            linked,
            "The orch skill is in place." if linked else "The orch skill is not linked in .agents/skills.",
            "Run: orch init",
        )
    )
    agents = skills.detected_agents(root)
    for fn in skills.local_instruction_files(agents):
        text = _read_quiet(root / fn)
        has = harness.LOCAL_MARK[0] in text
        left = None if has else harness.local_file_left(root, fn)
        if left:  # the team's file (or one git would show): left alone on purpose, nothing to fix
            rows.append(_row(f"{fn}", True, left))
            continue
        rows.append(
            _row(
                f"{fn}",
                has,
                f"{fn} points your agent at orch." if has else f"{fn} does not point your agent at orch.",
                "Run: orch init",
            )
        )
    for rel in reminder_settings.settings_files(root, agents):
        has = reminder_settings.has_ours(_json_quiet(root / rel))
        rows.append(
            _row(
                f"reminder in {rel}",
                has,
                f"{rel} has the reminder." if has else f"{rel} has no work reminder.",
                "Run: orch init",
            )
        )
    return rows


def _read_quiet(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8") if p.is_file() else ""
    except (OSError, UnicodeDecodeError):
        return ""


def _json_quiet(p: Path):
    try:
        return json.loads(_read_quiet(p).removeprefix("\ufeff"))  # a BOM from a Windows editor
    except ValueError:
        return None


def _uv_fails(uv: str) -> str | None:
    """Why the uv on the PATH does not run (a broken link, a deleted tool folder), or None when it does."""
    try:
        r = subprocess.run(
            [uv, "--version"], capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL
        )
    except (OSError, subprocess.SubprocessError) as e:
        return type(e).__name__
    return None if r.returncode == 0 else f"exit {r.returncode}"


LOCK_OLD_S = 60  # a ticket write holds its lock for milliseconds; tickets._locked waits 5 s at most


def ticket_file_checks(root: Path, now: float | None = None) -> list[dict]:
    """Ticket files orch cannot read (a listing silently leaves them out) and ticket locks left behind."""
    from orch import tickets

    d = tickets.tickets_dir(root)
    if not d.is_dir():
        return []
    now = time.time() if now is None else now
    bad, old = [], []
    for p in sorted(d.glob("t_*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
            ok = isinstance(t, dict) and t.get("id") == p.stem
        except (OSError, ValueError):
            ok = False
        if not ok:
            bad.append(p.name)
    for p in sorted(d.glob(".lock-*")):
        if p.name.count(".") > 1:  # .lock-<id>.<random>: a waiter breaking a stale lock right now
            continue
        try:
            age = now - p.stat().st_mtime
        except OSError:
            continue
        if age > LOCK_OLD_S:
            old.append((p.name, int(age // 60)))
    rows = []
    if bad:
        names = ", ".join(bad[:3]) + (f" and {len(bad) - 3} more" if len(bad) > 3 else "")
        rows.append(
            _row(
                "ticket files",
                False,
                f"orch cannot read {len(bad)} ticket file{'' if len(bad) == 1 else 's'} in .orch/tickets"
                f" ({names}), so {'it is' if len(bad) == 1 else 'they are'} left out of every list.",
                "Open the file in a text editor and fix the JSON (or take it back from git or a backup).",
            )
        )
    else:
        rows.append(_row("ticket files", True, "Every ticket file can be read."))
    if old:
        name, mins = old[0]
        more = f" (and {len(old) - 1} more)" if len(old) > 1 else ""
        rows.append(
            _row(
                "ticket locks",
                False,
                f"The lock file .orch/tickets/{name}{more} is {mins} min old: an orch command stopped"
                " half way, so a ticket may stay busy.",
                f"If no orch command is running, delete .orch/tickets/{name}{more and ' and the others'}.",
            )
        )
    return rows


def addon_checks(root: Path) -> list[dict]:
    """Add-ons turned on here whose package cannot be found or imported, and a background add-on whose last
    port another program now holds (it then starts on another port and old links stop working)."""
    try:
        on = [n for n in addons.active(root) if n not in addons.CORE_ADDONS]
    except (Refused, OSError, ValueError):
        return []
    if not on:
        return []
    found = addons.discover()
    rows = []
    for name in on:
        m = found.get(name)
        err = "its package is not installed" if m is None else _import_fails(root, m["run"])
        if err:
            rows.append(
                _row(
                    f"add-on {name}",
                    False,
                    f"The add-on {name} is on here but cannot be loaded ({err}).",
                    f"Run: orch addon add {name} (it installs it again).",
                )
            )
            continue
        port = services.last_port(root, name) if m["background"] else None
        if port and not _runs_here(root, name) and _port_taken(port):
            rows.append(
                _row(
                    f"port of {name}",
                    False,
                    f"Port {port} of the add-on {name} is used by another program,"
                    " so it starts on another port and old links to it stop working.",
                    f"Close the program that uses port {port}, then run: orch start",
                )
            )
    return rows


def _import_fails(root: Path, module: str) -> str | None:
    """Import the add-on's package the way orch starts it (own process, -P), or None when it loads."""
    try:
        r = subprocess.run(
            [sys.executable, "-P", "-c", f"import {module}"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return type(e).__name__
    if r.returncode == 0:
        return None
    last = (r.stderr.strip().splitlines() or [f"exit {r.returncode}"])[-1]
    return last[:200]


def _runs_here(root: Path, name: str) -> bool:
    ws = str(root.resolve())
    return any(
        e["workspace"] == ws and e["addon"] == name and services.pid_alive(e["pid"]) for e in services._load()
    )


def _port_taken(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def doctor(root: Path) -> dict:
    if not root.is_dir():
        raise Refused(f"{root} cannot be read. Open a terminal in your project folder and try again.")
    rows = install_checks(root)
    if (root / ".orch").is_dir():
        rows += ticket_file_checks(root)
        rows += addon_checks(root)
    run_checks = []
    if (root / ".orch").is_dir():
        from orch import cli_diag

        try:
            run_checks = cli_diag.inspect(root)["checks"]
        except (Refused, OSError, ValueError) as e:
            rows.append(
                _row(
                    "run health", False, f"The run checks could not be read ({e}).", "Run: orch diag inspect"
                )
            )
    fixes = _diag_fixes() if any(c["verdict"] == "problem" for c in run_checks) else {}
    for c in run_checks:
        if c["verdict"] == "problem":
            fix = fixes.get(c["name"])
            fact = c["fact"][:1].upper() + c["fact"][1:]
            if fix and c["evidence"]:  # with a fix of its own: say exactly what was found
                fact += f": {c['evidence'][0]}"
            rows.append(_row(c["name"], False, fact + ".", fix or "Run: orch diag inspect"))
    from orch import doctorpass

    late = doctorpass.overdue_row(root)  # once, after the run checks (it sat inside their loop: ORCH-104)
    if late:
        rows.append(late)
    if (root / ".orch").is_dir():
        from orch import procs

        rows.append(_row("background work", True, procs.power_words(root)))  # ORCH-2407: the limits, in words
    from orch import macfolders

    try:
        services_on = "services" in addons.active(root)
    except (Refused, OSError, ValueError):
        services_on = False
    mac = macfolders.doctor_row(root, services_on)  # report r-1119-1255-ws-6: launchd jobs die in Documents
    if mac:
        rows.append(mac)
    if (root / ".orch").is_dir():
        from orch import ticketindex, tickets

        with ticketindex.no_write():  # doctor only reads
            for name in ticketindex.broken(root):
                rows.append(
                    _row(
                        f"ticket file {name}",
                        False,
                        f"The ticket file .orch/tickets/{name} is broken (not valid JSON).",
                        tickets.BROKEN_FIX[:1].upper() + tickets.BROKEN_FIX[1:] + ".",
                    )
                )
    problems = [r for r in rows if not r["ok"]]
    return {"ok": not problems, "problems": len(problems), "checks": rows}


def _diag_fixes() -> dict[str, str]:
    """The one-sentence fix a diag check names (its FIX), by check name."""
    from orch import diag_checks

    return {m.NAME: m.FIX for m in diag_checks.modules() if isinstance(getattr(m, "FIX", None), str)}


def _doctor_text(res: dict) -> str:
    out = ["orch doctor"]
    for r in res["checks"]:
        out.append(f"  ok       {r['fact']}" if r["ok"] else f"  problem  {r['fact']} {r['next']}")
    n = res["problems"]
    out.append("Nothing wrong." if not n else f"{n} thing{'' if n == 1 else 's'} to fix.")
    return "\n".join(out)


# ------------------------------------------------------------------ uninstall


def _drop_local_block(root: Path, fn: str) -> str | None:
    path = root / fn
    if harness.is_link(path) or not path.is_file():
        return None
    text = harness._read(path)
    rx = re.compile(
        re.escape(harness.LOCAL_MARK[0]) + r".*?" + re.escape(harness.LOCAL_MARK[1]) + r"\n?", re.S
    )
    if not rx.search(text):
        return None
    new = rx.sub("", text, count=1).rstrip("\n")
    if not new.strip():
        path.unlink()  # orch made the file, nothing else is in it
        return "deleted"
    harness.write_text(path, new + "\n")
    return "removed"


def _home_keys(root: Path) -> list[str]:
    """Remove this folder's keys from the per-person files in the orch home. Returns the files changed."""
    from orch import config

    try:
        home = addons.home()
    except Refused:
        return []
    done = []
    key = config._perm_key(root)
    for fn in ("permissions.json", "copies.json"):
        if adapters._drop_json_key(home / fn, [], key):
            done.append(fn)
    ports = home / "ports.json"
    prefix = f"{root.resolve()}\t"
    keys = []
    try:
        data = json.loads(ports.read_text(encoding="utf-8"))
        keys = (
            [k for k in data if isinstance(k, str) and k.startswith(prefix)] if isinstance(data, dict) else []
        )
    except (OSError, ValueError):
        pass
    if any([adapters._drop_json_key(ports, [], k) for k in keys]):
        done.append("ports.json")
    return done


def _rmdir_if_empty(p: Path) -> None:
    try:
        if p.is_dir() and not harness.is_link(p) and not any(p.iterdir()):
            p.rmdir()
    except OSError:
        pass


def _exclude_tags(root: Path) -> list[str]:
    found = harness._git_exclude(root)
    if found is None or not found[0].is_file():
        return []
    b = harness.EXCLUDE_MARK[0] + " "
    rows = found[0].read_text(encoding="utf-8").splitlines()
    return [r[len(b) :] for r in rows if r.startswith(b)]


def is_set_up(root: Path) -> bool:
    return (root / ".orch").is_dir()


def uninstall(root: Path) -> dict:
    """Undo what init and the add-ons wrote. Returns {"removed": [...], "kept": [...]}."""
    if not is_set_up(root):
        raise Refused("orch is not set up in this folder, so there is nothing to remove.")
    removed: list[str] = []
    harness.check_harness(root)
    # 0. everything orch started here (ORCH-2299): helper sessions and runs, then the helpers' separate copies
    from orch import runs_live, worktrees

    stopped = runs_live.stop_all(root)
    for name in stopped:
        removed.append(f"Stopped the helper session of {name}")
    copies = worktrees.leave(root)
    removed += copies["removed"]
    # 1. background services, then every add-on, newest first
    try:
        for row in services.stop(root):
            if row.get("stopped"):
                removed.append(f"Stopped the background process of {row['addon']}")
    except (Refused, OSError):
        pass
    for name in reversed(list(addons.listed(root))):
        addons.remove(root, name)
        removed.append(f"Add-on {name}")
    # 2. skills and their links (every place any agent looks, found or not)
    names = skills._harness_skill_names(root)
    places = [".agents/skills", *[w for w in _all_agent_files("skills_link") if w != ".agents/skills"]]
    for n in names:
        for where in places:
            harness.unlink_skill(root, where, n)
        removed.append(f"Skill {n}")
    # 3. the agents' local instruction files
    for fn in _all_agent_files("instructions_link"):
        done = _drop_local_block(root, fn)
        if done:
            removed.append(f"{fn} ({'deleted' if done == 'deleted' else 'orch lines removed'})")
    # 4. the reminder hooks
    for rel, done in reminder_settings.remove_each(root):
        removed.append(f"{rel} ({'deleted' if done == 'deleted' else 'orch reminder removed'})")
    # 5. git exclude blocks
    tags = _exclude_tags(root)
    for tag in tags:
        harness.exclude_set(root, tag, [])
    if tags:
        removed.append(".git/info/exclude (orch lines removed)")
    # 6. this folder's keys in the orch home
    for fn in _home_keys(root):
        removed.append(f"{fn} in your orch home (this folder's entry)")
    # 7. orch's own files in .orch
    orch = root / ".orch"
    for rel in ("harness", "run"):
        p = orch / rel
        if p.is_dir() and not harness.is_link(p):
            shutil.rmtree(p)
            removed.append(f".orch/{rel}/")
    from orch import checkfiles

    if checkfiles.drop_untouched_template(root):  # the template `orch init` wrote, unchanged
        removed.append(".orch/checks/_template.json")
    gi = orch / ".gitignore"
    # R5.2: whatever stays in .orch (tickets, chat, local files, config, secrets) keeps its ignore rules, so a
    # later `git add -A` commits nothing private; the file goes only when nothing else is left (or never when
    # the team owns it)
    left = list(orch.iterdir()) if orch.is_dir() else []
    kept_data = any(p.name not in (".gitignore", "addons.json") for p in left)
    if (
        gi.is_file()
        and not harness.is_link(gi)
        and not kept_data
        and not harness._tracked(root, ".orch/.gitignore")
    ):
        gi.unlink()
        removed.append(".orch/.gitignore")
    act = orch / "addons.json"
    if act.is_file() and not harness.is_link(act) and not addons.listed(root):
        act.unlink()
        removed.append(".orch/addons.json")
    for place in [*skills._skills_link_paths(), ".agents/skills"]:  # the skill folders, then their parents
        _rmdir_if_empty(root / place)
        if (root / place).parent != root:
            _rmdir_if_empty((root / place).parent)
    kept = [k for k in KEPT if (root / k).exists()]
    return {"removed": removed, "kept": kept, "stopped": stopped, "left": copies["kept"]}


def _uninstall_text(root: Path, res: dict) -> str:
    out = ["Removed:", *[f"  {r}" for r in res["removed"]]] if res["removed"] else ["Nothing to remove."]
    if res.get("left"):  # ORCH-2299: what stays outside .orch is named, with the command that removes it
        out.append("Still there, because it holds work that is not in your project:")
        for k in res["left"]:
            where = f" ({k['path']})" if k.get("path") else ""
            out.append(f"  {k['why'][0].upper()}{k['why'][1:]}{where}.")
            if k.get("command"):
                out.append(f"    To remove it, in this folder: {k['command']}")
            else:
                out.append("    Delete that folder when you no longer need the work in it.")
    out.append(
        f"Kept your tickets and settings in {root / '.orch'}. "
        f"To uninstall orch itself: uv tool uninstall {TOOL}"
    )
    return "\n".join(out)


def _pass_text(res: dict) -> str:
    out = [*res["cleaned"]]
    for o in res["opened"]:
        out.append(f"opened {o['ticket']}: {o['title']}" if o["ticket"] else f"would open: {o['title']}")
    if res["hold"]:
        out.append(f"automatic helper starts {res['hold']} (disk {res['disk_free_gb']} GB free)")
    out.append(
        f"{len(res['problems'])} problem(s), {len(res['opened'])} ticket(s) opened, "
        f"{len(res['kept'])} already open; disk {res['disk_free_gb']} GB free"
    )
    return "\n".join(out)


def _doctor_sub(args, root: Path) -> None:
    from orch import doctorpass

    cmd = args.doctor_cmd
    if cmd == "pass":
        sim = None
        if args.simulate:
            sim = json.loads(Path(args.simulate).read_text(encoding="utf-8"))
        res = doctorpass.run_pass(root, sim=sim, apply=not args.dry_run, cleanup=not args.no_cleanup)
        _out(args, res, _pass_text(res))
    elif cmd == "soon":
        started = doctorpass.soon(root)
        _out(
            args, {"started": started}, "A pass started in the background." if started else "No pass is due."
        )
    elif cmd == "setup":
        if args.off or args.file:  # what orch checks and cleans by itself here: a person's choice
            from orch import tickets

            tickets.require_human(
                "Change what the scheduled health checks watch and clean on this computer?",
                "changing the scheduled health checks",
                getattr(args, "by", None),
            )
        if args.off:
            was = doctorpass.remove_setup(root)
            _out(args, {"on": False, "was_on": was}, "The scheduled health checks are off on this computer.")
            return
        if args.file:
            try:
                doc = json.loads(Path(args.file).read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise Refused(f"The setup file cannot be read as JSON ({e}).") from None
            cfg = doctorpass.save_setup(root, doc)
            _out(
                args,
                {"on": True, "setup": cfg},
                f"The scheduled health checks are on: every {cfg['every_min']} minutes while orch runs here.",
            )
            return
        cfg = doctorpass.setup(root)
        _out(
            args,
            {"on": cfg is not None, "setup": cfg},
            json.dumps(cfg, indent=2)
            if cfg
            else "The scheduled health checks are not set up on this computer.",
        )
    elif cmd == "clean":
        cfg = doctorpass.setup(root)
        if cfg is None:
            raise Refused(
                "Nothing to clean: the scheduled checks are not set up here. Run: orch doctor setup <file>"
            )
        lines = doctorpass.clean(cfg, apply=args.apply)
        _out(args, {"cleaned": lines, "applied": args.apply}, "\n".join(lines) or "Nothing to clean up.")
    elif cmd == "remove-temp":
        res = doctorpass.remove_temp(root, args.paths)
        _out(
            args,
            {"items": res},
            "\n".join(
                f"{r['path']}: {r['result']}" + (f" ({r['why']})" if r.get("why") else "") for r in res
            ),
        )
        if any(r["result"] in ("refused", "failed") for r in res):
            args._exit = 1  # some were refused or still run
    elif cmd == "stop-pids":
        res = doctorpass.stop_pids(args.pids)
        _out(
            args,
            {"items": res},
            "\n".join(f"{r['pid']}: {r['result']}" + (f" ({r['why']})" if r.get("why") else "") for r in res),
        )
        if any(r["result"] in ("refused", "STILL RUNNING") for r in res):
            args._exit = 1  # some were refused or still run


def dispatch(args, root: Path) -> bool:
    if args.cmd == "doctor" and getattr(args, "doctor_cmd", None):
        _doctor_sub(args, root)
    elif args.cmd == "doctor":
        res = doctor(root)
        _out(args, res, _doctor_text(res))
    elif args.cmd == "uninstall":
        res = uninstall(root)
        _out(
            args,
            {"ok": True, **res, "root": str(root), "remove_orch": f"uv tool uninstall {TOOL}"},
            _uninstall_text(root, res),
        )
    else:
        return False
    return True

"""`orch doctor` and `orch uninstall`: install and leave (R8.5).

`doctor` only reads. `uninstall` undoes what `orch init` and the add-ons wrote in this folder and in the
person's orch home, newest first, and keeps the person's data (tickets, settings, secrets).
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from orch import adapters, addons, harness, history, reminder_settings, services, skills
from orch.errors import Refused

TOOL = "orch-workspace"  # the uv tool the installers make (install.sh, install.ps1)
KEPT = (".orch/tickets", ".orch/config.toml", ".orch/secrets")  # the person's data


def _out(args, data, text: str) -> None:
    if args.json:
        data = history.shown_json(history.args_root(args), data)
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def add_parsers(sub, common) -> None:
    sub.add_parser("doctor", parents=[common], help="show what is wrong with orch here (read-only)")
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


def install_checks(root: Path) -> list[dict]:
    rows = [
        _row(
            "orch on the PATH",
            bool(shutil.which("orch")),
            "orch is on your PATH." if shutil.which("orch") else "orch is not on your PATH.",
            "Open a new terminal window, or run the install line again.",
        )
    ]
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
    rows.append(
        _row(
            "uv",
            bool(uv),
            "uv is found." if uv else "uv was not found (orch update needs it).",
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
    for fn in _local_files(root):
        text = _read_quiet(root / fn)
        has = harness.LOCAL_MARK[0] in text
        rows.append(
            _row(
                f"{fn}",
                has,
                f"{fn} points your agent at orch." if has else f"{fn} does not point your agent at orch.",
                "Run: orch init",
            )
        )
    for rel in reminder_settings.settings_files(root):
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


def _local_files(root: Path) -> list[str]:
    """The local instruction files of the agents found here (init writes these)."""
    out = []
    for n in skills.detected_agents(root):
        for fn in (adapters.load(n).get("files") or {}).get("instructions_link") or {}:
            if ".local." in fn and fn not in out:
                out.append(fn)
    return out


def _read_quiet(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8") if p.is_file() else ""
    except (OSError, UnicodeDecodeError):
        return ""


def _json_quiet(p: Path):
    try:
        return json.loads(_read_quiet(p))
    except ValueError:
        return None


def doctor(root: Path) -> dict:
    if not root.is_dir():
        raise Refused(f"{root} cannot be read. Open a terminal in your project folder and try again.")
    rows = install_checks(root)
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
    for c in run_checks:
        if c["verdict"] == "problem":
            rows.append(
                _row(
                    c["name"],
                    False,
                    c["fact"][:1].upper() + c["fact"][1:] + ".",
                    "Run: orch diag inspect",
                )
            )
    problems = [r for r in rows if not r["ok"]]
    return {"ok": not problems, "problems": len(problems), "checks": rows}


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
    for d in (".agents/skills", ".agents", ".claude/skills", ".claude"):
        _rmdir_if_empty(root / d)
    kept = [k for k in KEPT if (root / k).exists()]
    return {"removed": removed, "kept": kept}


def _uninstall_text(root: Path, res: dict) -> str:
    out = ["Removed:", *[f"  {r}" for r in res["removed"]]] if res["removed"] else ["Nothing to remove."]
    out.append(
        f"Kept your tickets and settings in {root / '.orch'}. "
        f"To remove orch from this computer: uv tool uninstall {TOOL}"
    )
    return "\n".join(out)


def dispatch(args, root: Path) -> bool:
    if args.cmd == "doctor":
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

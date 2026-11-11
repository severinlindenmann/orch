"""orch init: set up the project folder. Safe to run again."""

from __future__ import annotations

from pathlib import Path

from orch import adapters, reminder_settings, skills
from orch.errors import Refused


def init(root: Path, code: str | None = None) -> list[str]:
    """Returns plain-words lines about what is in place."""
    from orch import config

    if code is not None:
        code = config.clean_code(code)  # refused before anything is written
    (root / ".orch" / "tickets").mkdir(parents=True, exist_ok=True)
    if code is not None or not config.workspace_code(root):
        code = config.set_code(root, code or config.suggest_code(root.resolve().name))
    code = config.workspace_code(root)
    skills.ensure_gitignore(root)  # local files stay out of git before anything else is written
    src = skills.packaged_skills_dir() / "orch"
    skills.install_skill(root, "orch", src)
    skills.set_block(root, "orch", skills.read_block(src, "orch"))
    linked = skills.apply_agent_files(root)
    # the reminder hooks, merged into the agent tool's local settings (only for a tool that has them)
    reminders = reminder_settings.ensure_each(root)
    lines = [
        "Skill       .agents/skills/orch/SKILL.md (local; not part of your team's files)",
    ]
    if linked:
        lines.append("Linked for: " + ", ".join(linked))
    for name, rel, warn in reminders:
        label = adapters.load(name)["label"]
        lines.append(warn or f"Reminder    {rel} (local; {label} is reminded of work with no ticket)")
    lines += [
        "Local only  orch files stay out of git (.git/info/exclude)",
        "Tickets     .orch/tickets/",
        f"Ticket keys {code}-1, {code}-2, ... (change the code: orch config set workspace.code <code>)",
        adapters.permission_line(root),
        "Your agent can now use tickets.",
        "Your agent will be allowed to work in this folder.",  # consent for a live start's folder trust
    ]
    return lines


def has_recommended(root: Path) -> bool:
    from orch import addons

    return any(r["recommended"] and not r["active"] for r in addons.listing(root)) or bool(
        addons.shipped_recommended(fetch=False)
    )


def recommended(root: Path, yes: bool = False, interactive: bool = False) -> list[str]:
    """Turn on the add-ons whose manifest says recommended = true: one prompt lists what each brings, each
    keeps its own consent record. If one fails, none of them stays on. Returns the names turned on."""
    import contextlib
    import io
    import sys

    from orch import addons

    rows = [r for r in addons.listing(root) if r["recommended"] and not r["active"]]
    mans = addons.discover()
    installed = (set(addons.installed_names()) & set(mans)) | set(addons.CORE_ADDONS)
    for name, m in addons.shipped_recommended().items():  # shipped with orch, not installed yet
        mans[name] = m
        rows.append({"name": name})
    if not rows:
        return []
    text = "\n\n".join(addons.consent_text(mans[r["name"]], False) for r in rows)
    if not yes:
        if not interactive:
            err = Refused(f"{text}\n\nTo turn these on, run it again with --yes.")
            err.confirm = True
            raise err
        sys.stderr.write(text + "\nTurn these on? [y/N] ")
        sys.stderr.flush()
        if sys.stdin.readline().strip().lower() not in ("y", "yes"):
            raise Refused("Not confirmed. Nothing was changed.")
    names = [r["name"] for r in rows]
    before = set(addons.active(root))  # whatever is on already stays on, whatever fails
    now: list[str] = []  # turned on at once (already installed); the rest wait for the one reinstall
    out = io.StringIO()
    try:
        # one reinstall for all of them (on Windows a second background install is refused while one runs)
        batch = addons.batch_install(root) if set(names) - installed else contextlib.nullcontext()
        with contextlib.redirect_stdout(out), batch:
            for n in names:
                addons.add(root, n, yes=True)
                if n not in addons.batched(root) and n not in before:
                    now.append(n)
    except Exception as e:
        sys.stderr.write(out.getvalue())
        undone = list(getattr(e, "undone", []))
        for n in reversed(now):
            with contextlib.suppress(Exception):
                addons.remove(root, n)
                undone.append(n)
        left = [n for n in names if n in addons.active(root) and n not in before]
        if left:
            tail = f"Still on: {', '.join(left)}."
        elif undone:
            tail = f"Turned off again: {', '.join(undone)}."
        else:
            tail = "Nothing was changed."
        raise Refused(f"Could not turn on {', '.join(names)}: {e} {tail}") from e
    notice = out.getvalue().strip()
    if notice:  # e.g. "finishes in the background": to stderr, so init --json stays clean
        sys.stderr.write(notice + "\n")
    return names


def choose_agent(root: Path, yes: bool = False, interactive: bool = False) -> str:
    """Which agent does the work here: asked once (found agents + Other); --yes takes the first found.
    Returns one plain line to show."""
    from orch import adapters, config

    cur = config.agent_name(root)
    if cur:
        try:
            adapters.load(cur, root)
            return f"Agent: {adapters.load(cur, root)['label']}."
        except Refused:
            pass  # the saved name no longer exists: ask again
    found = [r for r in adapters.detect() if r["found"]]
    if not found:
        if interactive and not yes:
            return _other(root)
        return "No agent found; set one later: orch config set workspace.agent <name>"
    if yes or not interactive:
        _save(root, found[0]["name"])
        return f"Agent: {found[0]['label']} (found first)."
    print("Which agent does the work?")
    for i, r in enumerate(found, 1):
        print(f"  {i}) {r['label']}  (found{', ' + r['version'] if r['version'] else ''})")
    print(f"  {len(found) + 1}) Other: type its command")
    ans = input("Pick [1]: ").strip() or "1"
    if ans.isdigit() and 1 <= int(ans) <= len(found):
        _save(root, found[int(ans) - 1]["name"])
        return f"Agent: {found[int(ans) - 1]['label']}."
    if ans == str(len(found) + 1):
        return _other(root)
    raise Refused(f"'{ans}' is not on the list. Run orch init again.")


def _save(root: Path, name: str) -> None:
    from orch import config

    config.set_key(root, "workspace", "agent", name)


def _other(root: Path) -> str:
    from orch import adapters, config

    name = input("Name for it [my-agent]: ").strip() or "my-agent"
    if not config.NAME_RE.match(name):
        raise Refused(f"'{name}' is not a name orch can use. Use lowercase letters, digits and '-'.")
    if name in adapters.builtin_names() or name in config.agent_entries(root):
        raise Refused(f"There is already an agent called '{name}'. Pick another name; nothing was changed.")
    cmd = input("Command (use {prompt} where the task goes): ").strip()
    if not cmd:
        return "No agent chosen; set one later: orch config set workspace.agent <name>"
    # a command that will run is a human-only step (invariant H1): an agent in the environment is refused, a
    # person leaves the same config.agent_add hand-off as `orch config agent add` (a click on the page)
    from types import SimpleNamespace

    from orch import humanproof

    if not (1 <= len(cmd) <= 500 and "\n" not in cmd and "\r" not in cmd):
        raise Refused("The command must be one line of at most 500 characters.")
    target = humanproof.agent_add_target(name, cmd)  # computed first: a bad value refuses here (exit 2)
    exact = humanproof.agent_add_exact(cmd)
    try:
        who = humanproof.person_by(
            root,
            SimpleNamespace(proof_stdin=False, by=None),
            "config.agent_add",
            target,
            parts={"name": name, "command": cmd},
            exact=exact,
            argv=["config", "agent", "add", name, "--command", cmd],
        )
    except humanproof.HandOffPending as e:  # a person: the card is on the page; init goes on
        return (
            f"Agent: not set yet. {e} Confirm '{name}' on the page, "
            f"then run: orch config set workspace.agent {name}"
        )
    if not who.startswith("human:"):
        raise Refused(config.ONLY_PERSON_AGENT.format(what="add an agent command"))
    config.add_agent(root, name, cmd, approve=True, by=who)  # a person: approve ONLY what they typed
    _save(root, name)
    return f"Agent: {name} (starts fresh each run; it cannot continue a conversation)."

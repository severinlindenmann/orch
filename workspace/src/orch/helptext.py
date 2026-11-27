"""Every `orch ... --help` ends with 1-2 examples and the next step (R2.7, R7.5).

ONE table (`EXAMPLES`) keyed by the command path, like `nextstep.HINTS`. The next step is the line the
command prints after it runs (`nextstep.HINTS`, R4.3), read with no ticket at hand; `NEXT` only covers the
few commands whose printed line needs a ticket's state. A group without its own examples shows the first
example of its first two commands. A built-in add-on (relay, publish) that is off leaves no trace in any
help (R1.1): an option or a listed command that names one is hidden until it is on.
"""

from __future__ import annotations

import argparse
import re
import textwrap

from orch import addons, nextstep

K = "WEB-12"  # a ticket key as `orch ticket list` shows it

EXAMPLES: dict[str, tuple[str, ...]] = {
    "init": ("orch init", "orch init --code WEB"),
    "work-check": ("orch work-check",),
    "tokens": ("orch tokens", "orch tokens --days 7"),
    "changes": ("orch changes --since 2026-11-01", "orch changes --since v1.0"),
    "triage": ("orch triage", "orch triage --start"),
    "update": ("orch update", "orch update --to release"),
    "start": ("orch start", "orch start --no-open"),
    "stop": ("orch stop", "orch stop --all"),
    "restart": ("orch restart",),
    "status": ("orch status",),
    "pause": ("orch pause", 'orch pause --reason "too many runs today"'),
    "resume": ("orch resume",),
    "addon": ("orch addon list", "orch addon add <name>"),
    "addon add": ("orch addon add <name>",),
    "addon remove": ("orch addon remove <name>",),
    "addon uninstall": ("orch addon uninstall <name>",),
    "addon list": ("orch addon list",),
    "addon check": ("orch addon check <name>", "orch addon check ./my-addon"),
    "diag": ("orch diag inspect", f"orch diag report --ticket {K}"),
    "diag inspect": ("orch diag inspect", f"orch diag inspect --ticket {K}"),
    "diag query": ("orch diag query --since 2h", "orch diag query --lvl error --limit 20"),
    "diag report": ("orch diag report", f'orch diag report --ticket {K} --note "the list stays empty"'),
    "diag tickets": ("orch diag tickets --dry-run", "orch diag tickets"),
    "diag delete": ("orch diag delete reports", "orch diag delete notes"),
    "report": ('orch report problem "The list stays empty"', 'orch report feature "Sort tickets by due day"'),
    "report problem": (
        'orch report problem "The list stays empty"',
        f'orch report problem "Save does nothing" --ticket {K}',
    ),
    "report feature": (
        'orch report feature "Sort tickets by due day"',
        'orch report feature "Dark mode" --why "I work at night"',
    ),
    "doctor": ("orch doctor", "orch doctor pass --dry-run"),
    "doctor pass": ("orch doctor pass --dry-run", "orch doctor pass"),
    "doctor soon": ("orch doctor soon",),
    "doctor setup": ("orch doctor setup", "orch doctor setup checks.json"),
    "doctor clean": ("orch doctor clean", "orch doctor clean --apply"),
    "doctor remove-temp": ("orch doctor remove-temp /tmp/tmp.abc123",),
    "doctor stop-pids": ("orch doctor stop-pids 4242", "orch doctor stop-pids 4242 4243"),
    "uninstall": ("orch uninstall",),
    "checks": ("orch checks list", "orch checks templates"),
    "checks list": ("orch checks list",),
    "checks init": ("orch checks init",),
    "checks templates": ("orch checks templates",),
    "checks add": ("orch checks add <template>", "orch checks add <template> --name github-login"),
    "checks approve": ("orch checks approve github-login",),
    "checks remove": ("orch checks remove github-login",),
    "checks run": ("orch checks run", "orch checks run github-login"),
    "checks show": ("orch checks show github-login",),
    "skill": ("orch skill list", "orch skill check"),
    "skill check": ("orch skill check", "orch skill check <name>"),
    "skill list": ("orch skill list",),
    "skill show": ("orch skill show <name>",),
    "skill credits": ("orch skill credits",),
    "skill review-due": ("orch skill review-due --dry-run", "orch skill review-due"),
    "tools": ("orch tools list", "orch tools notes <name>"),
    "tools list": ("orch tools list", "orch tools list --refresh"),
    "tools notes": ("orch tools notes <name>",),
    "tools update": ("orch tools update <name>",),
    "ticket": ('orch ticket new "Fix the login"', "orch ticket list"),
    "ticket new": ('orch ticket new "Fix the login"', 'orch ticket new "Write the report" --due 2026-12-04'),
    "ticket tree": (f"orch ticket tree {K}",),
    "ticket list": ("orch ticket list", "orch ticket list --status waiting"),
    "ticket show": (f"orch ticket show {K}",),
    "ticket export": (f"orch ticket export {K}",),
    "ticket status": (f"orch ticket status {K} review", f"orch ticket status {K} done"),
    "ticket edit": (
        f'orch ticket edit {K} --title "Fix the login page"',
        f"orch ticket edit {K} --due 18:30",
    ),
    "ticket order": (f"orch ticket order todo {K} WEB-9",),
    "ticket set": (f"orch ticket set {K} marketing.budget 2400",),
    "ticket summary": (f'orch ticket summary {K} "Login fixed; the test is still open"',),
    "ticket outcome": (
        f'orch ticket outcome {K} --changed "Login works again" --why "A cookie was too old"',
    ),
    "ticket artifacts": (f"orch ticket artifacts {K}",),
    "ticket title": (f'orch ticket title {K} "Fix the login"',),
    "ticket tidy": (f'orch ticket tidy {K} "Fix the login" --done-when "A person can sign in"',),
    "ticket found": (f"orch ticket found {K} < found.json",),
    "ticket prepared": (f"orch ticket prepared {K}",),
    "ticket kind": (f"orch ticket kind {K} bug",),
    "ticket model": (
        f"orch ticket model {K} sonnet",
        f'orch ticket model {K} up --why "the test keeps failing"',
    ),
    "ticket plan": (f'orch ticket plan {K} --goal "Sign-in works on small screens"',),
    "ticket attach": (f"orch ticket attach {K} --name notes.txt < notes.txt",),
    "ticket artifacts-dir": (f"orch ticket artifacts-dir {K}",),
    "ticket wait": (
        f"orch ticket wait {K} --on ticket:WEB-9",
        f"orch ticket wait {K} --until 2026-12-04T09:00",
    ),
    "ticket changes": (f'orch ticket changes {K} "The button is still grey"',),
    "ticket patch": (f'orch ticket patch {K} --if-revision 7 \'{{"title": "Fix the login"}}\'',),
    "wait": (f"orch wait {K} --on ticket:WEB-9", f"orch wait {K} --clear"),
    "check": (f'orch check add {K} "Write the test"', f'orch check done {K} c1 --command "pytest"'),
    "check add": (f'orch check add {K} "Write the test"',),
    "check edit": (f'orch check edit {K} c1 "Write two tests"',),
    "check move": (f"orch check move {K} c3 --after c1",),
    "check remove": (f"orch check remove {K} c2",),
    "check reopen": (f"orch check reopen {K} c2",),
    "check start": (f"orch check start {K} c1",),
    "check stop": (f"orch check stop {K} c1",),
    "check wont-do": (f'orch check wont-do {K} c2 --reason "not needed after all"',),
    "check record": (f'orch check record {K} c1 --cmd "pytest" --exit 0',),
    "check done": (f'orch check done {K} c1 --command "pytest"', f"orch check done {K} c2 --file shot.png"),
    "log": (f'orch log {K} "Tried the old browser too"',),
    "ask": (
        f'orch ask {K} "Which colour?" --option blue --option green --recommend blue',
        f'orch ask {K} "Send the offer?" --option yes --option no --recommend yes --because "it is ready"',
    ),
    "answer": (f"orch answer {K} q1 blue",),
    "ref": (f"orch ref add {K} https://example.com/report", f"orch ref list {K}"),
    "ref add": (f"orch ref add {K} https://example.com/report", f'orch ref add {K} notes.md --title "Notes"'),
    "ref list": (f"orch ref list {K}",),
    "ref rm": (f"orch ref rm {K} 2",),
    "ref set": (f"orch ref set {K} 1 --status merged",),
    "ref merge": (f"orch ref merge {K} 1 --head 3f2a1b9",),
    "ref wait": (f"orch ref wait {K}", f"orch ref wait {K} --merge"),
    "ext": (f"orch ext set {K} <add-on> '{{\"budget\": 2400}}'", f"orch ext unset {K} <add-on>"),
    "ext set": (f"orch ext set {K} <add-on> '{{\"budget\": 2400}}'",),
    "ext unset": (f"orch ext unset {K} <add-on>", f"orch ext unset {K} <add-on>.budget"),
    "needs": ("orch needs",),
    "counts": ("orch counts",),
    "review": ("orch review list", "orch review link"),
    "review list": ("orch review list", "orch review list --answered"),
    "review answer": (f"orch review answer {K} q1 --verdict ok",),
    "review run": (f"orch review run {K} q1 --digest <digest>",),
    "review wait": (f"orch review wait {K} q1", f"orch review wait {K} q1 --timeout 600"),
    "review link": ("orch review link",),
    "review tend": ("orch review tend --dry-run", "orch review tend"),
    "review tend-releases": ("orch review tend-releases --dry-run",),
    "review verdict": (f'orch review verdict {K} accept "small and tested"',),
    "review security": ('orch review security 812 ok "no new way in"',),
    "review undo": (f"orch review undo {K}",),
    "review accepted": ("orch review accepted", "orch review accepted --since 2026-12-01"),
    "shot": ("orch shot http://localhost:8000", "orch shot page.html --width 1280,390"),
    "look": ("orch look show", "orch look set --icon none --color auto"),
    "look list": ("orch look list",),
    "look show": ("orch look show",),
    "look shared-pages": ("orch look shared-pages", "orch look shared-pages on"),
    "look set": ("orch look set --icon none", "orch look set --color auto"),
    "manager": ("orch manager start", "orch manager status"),
    "manager start": ("orch manager start", "orch manager start --fresh"),
    "manager stop": ("orch manager stop",),
    "manager status": ("orch manager status",),
    "session": ("orch session new chat", "orch session list"),
    "session new": ("orch session new chat", "orch session new terminal"),
    "session list": ("orch session list",),
    "session stop": ("orch session stop chat",),
    "session end": ("orch session end chat",),
    # helpers' run, settings and tools: shown once they are listed (ORCH-1877)
    "run": (f"orch run start {K}", f"orch run status {K}"),
    "run start": (f"orch run start {K}", f'orch run start {K} --text "Start with the test"'),
    "run status": (f"orch run status {K}",),
    "run list": ("orch run list",),
    "run attach": (f"orch run attach {K}",),
    "run screen": (f"orch run screen {K}",),
    "run send": (f'orch run send {K} "Use the blue button"',),
    "run take-back": (f"orch run take-back {K} 1",),
    "run interrupt": (f"orch run interrupt {K}",),
    "run stop": (f"orch run stop {K}",),
    "run history": (f"orch run history {K}",),
    "run tend": ("orch run tend --dry-run",),
    "config": ("orch config get", "orch config set workflow.reviewer on"),
    "config get": ("orch config get", "orch config get workspace.name"),
    "config set": ('orch config set workspace.name "Web team"',),
    "config propose": ("orch config propose",),
    "config agent": ("orch config agent add <name> --command <command>",),
    "agents": ("orch agents test <name>",),
    "agents test": ("orch agents test <name>",),
    # built-in add-ons: their help is reachable only once they are on
    "publish": ("orch publish list", "orch publish file report.pdf"),
    "publish invite": (
        "orch publish invite web --folder ~/work/web --admin-url https://publish-admin.example.com",
    ),
    "publish connect": ("orch publish connect https://files.example.com --workspace web --token <token>",),
    "publish whoami": ("orch publish whoami",),
    "publish profile": (
        "orch publish profile",
        'orch publish profile --description "Web team" --tags web,design',
    ),
    "publish file": ("orch publish file report.pdf", "orch publish file site/ --days 30"),
    "publish extend": ("orch publish extend f_ab12 --days 30",),
    "publish app": ("orch publish app myapp", "orch publish app myapp --private"),
    "publish new": ("orch publish new static myapp", "orch publish new python myapp --store json"),
    "publish list": ("orch publish list",),
    "publish view": ("orch publish view",),
    "publish restart": ("orch publish restart myapp",),
    "publish stop": ("orch publish stop myapp",),
    "publish delete": ("orch publish delete f_ab12", "orch publish delete myapp"),
    "relay": ('orch relay send Design "The report is ready"', "orch relay inbox"),
    "relay invite": (
        "orch relay invite web --folder ~/work/web --admin-url https://relay-admin.example.com",
    ),
    "relay connect": ("orch relay connect https://relay.example.com --workspace web --token <token>",),
    "relay whoami": ("orch relay whoami",),
    "relay status": ("orch relay status",),
    "relay key": ("orch relay key",),
    "relay view": ("orch relay view",),
    "relay mobile": ("orch relay mobile on", "orch relay mobile status"),
    "relay mobile on": ("orch relay mobile on", "orch relay mobile on --hours 4"),
    "relay mobile off": ("orch relay mobile off",),
    "relay mobile status": ("orch relay mobile status",),
    "relay mobile hours": ("orch relay mobile hours 8",),
    "relay mobile ack": ("orch relay mobile ack",),
    "relay profile": ("orch relay profile", 'orch relay profile --description "Web team" --tags web,design'),
    "relay contacts": ("orch relay contacts list", "orch relay contacts refused"),
    "relay contacts list": ("orch relay contacts list",),
    "relay contacts accept": ("orch relay contacts accept ws_ab12 --fingerprint <fingerprint>",),
    "relay contacts withdraw": ("orch relay contacts withdraw ws_ab12",),
    "relay contacts refused": ("orch relay contacts refused",),
    "relay contacts unsigned": ("orch relay contacts unsigned status", "orch relay contacts unsigned refuse"),
    "relay inbox": ("orch relay inbox", "orch relay inbox --wait 60"),
    "relay needs": ("orch relay needs", "orch relay needs --json"),
    "relay outbox": ("orch relay outbox", "orch relay outbox --resend"),
    "relay done": ("orch relay done m_ab12",),
    "relay pickups": ("orch relay pickups", "orch relay pickups --waiting"),
    "relay send": (
        'orch relay send Design "The report is ready"',
        "orch relay send Design --file report.pdf",
    ),
    "relay topic": ('orch relay topic --from m_ab12 "Plan the launch"',),
    "relay delegate": (
        f'orch relay delegate Design "Draw the logo" --ticket {K} --dry-run',
        f'orch relay delegate Design "Draw the logo" --ticket {K}',
    ),
    "relay start": (
        "orch relay start Design weekly-report --dry-run",
        "orch relay start Design weekly-report",
    ),
    "relay allow": ("orch relay allow m_ab12 --once", "orch relay allow m_ab12 --permanent"),
    "relay refresh": ("orch relay refresh",),
    "relay download": ("orch relay download m_ab12",),
    "relay group": ("orch relay group list", f'orch relay group say {K} "The draft is ready"'),
    "relay group list": ("orch relay group list",),
    "relay group say": (f'orch relay group say {K} "The draft is ready"',),
    "relay group add": (f"orch relay group add {K} Design",),
    "relay group ask-add": (f"orch relay group ask-add {K} Design",),
    "relay group remove": (f"orch relay group remove {K} Design",),
    "relay group ask": (f'orch relay group ask {K} Design "Which logo size?"',),
    "relay group share": (f"orch relay group share {K} report.pdf",),
    "relay group reply": ('orch relay group reply Sales g_ab12 "Looks good"',),
    "relay group answer": ('orch relay group answer m_ab12 "200 px wide"',),
    "relay group send-file": ("orch relay group send-file Sales g_ab12 logo.png",),
    "relay group leave": ("orch relay group leave Sales g_ab12",),
    "relay problem": ("orch relay problem list", "orch relay problem share <report>"),
    "relay problem share": (
        "orch relay problem share <report> --dry-run",
        "orch relay problem share <report>",
    ),
    "relay problem list": ("orch relay problem list", "orch relay problem list --status all"),
    "relay problem get": ("orch relay problem get p_ab12",),
    "relay problem done": ("orch relay problem done p_ab12",),
    "relay problem back": ("orch relay problem back p_ab12",),
    "relay webhook": ("orch relay webhook list", f"orch relay webhook new --ticket {K} --once"),
    "relay webhook new": (
        f"orch relay webhook new --ticket {K} --once",
        "orch relay webhook new --permanent",
    ),
    "relay webhook list": ("orch relay webhook list",),
    "relay webhook delete": ("orch relay webhook delete h_ab12",),
}

# The next step for commands whose printed `Next:` line reads a ticket or the run's result.
NEXT = {
    "": 'orch init  (in a new folder), then orch ticket new "<title>"',
    "init": 'orch ticket new "<title>"',
    "work-check": 'orch ticket new "<title>"  (when it says files changed without a ticket)',
    "uninstall": "orch init  (to set this folder up again later)",
    "ticket artifacts-dir": "save the files there, then: orch check done <ticket> <task> --file <file>",
    "publish new": "orch publish app <folder>",
    "publish invite": "open the folder in your helper; it is connected to publish.",
    "relay invite": "open the folder in your helper; it is connected to the relay.",
    "addon check": "fix what it lists, then: orch addon add <name>",
    "config get": "change one: orch config set <key> <value>",
    "ticket status": "orch ticket list",
    "ticket show": 'orch check add <ticket> "<step>"  (one task per step)',
    "ticket tree": "orch ticket show <ticket>",
    "check done": 'orch ticket summary <ticket> "<where things stand>"  (when every task is done)',
    "github expert": "orch ticket list",
    "github release": "orch review list  (what still waits for the owner)",
    "ref wait": "orch ticket show <ticket>",
    "relay problem get": "read .agents/skills/orch-diagnose/SKILL.md, then investigate the report",
}

_CORE_ADDON = re.compile(r"(?<![A-Za-z_-])(" + "|".join(addons.CORE_ADDONS) + r")(?![A-Za-z_])", re.I)


def next_line(path: str) -> str | None:
    """The next step for a command path, as its help shows it: the same line the command prints."""
    if path in NEXT:
        return NEXT[path]
    if path in nextstep.EXEMPT:
        return None
    return nextstep.hint(path, None, argparse.Namespace(orch_root=None))


def _subparsers(p: argparse.ArgumentParser):
    return next((a for a in p._actions if isinstance(a, argparse._SubParsersAction)), None)


def _children(p: argparse.ArgumentParser, path: str):
    sp = _subparsers(p)
    if sp is None:
        return []
    shown = [a.dest for a in sp._choices_actions]
    return [(f"{path} {n}".strip(), sp.choices[n]) for n in shown if n in sp.choices]


def examples(path: str, p: argparse.ArgumentParser) -> tuple[str, ...]:
    if path in EXAMPLES:
        return EXAMPLES[path]
    out: list[str] = []
    for child_path, _ in _children(p, path)[:2]:
        out += EXAMPLES.get(child_path, ())[:1]
    return tuple(out)


def _wrap(label: str, text: str) -> str:
    return textwrap.fill(
        text,
        78,
        initial_indent=label,
        subsequent_indent="  ",
        break_long_words=False,
        break_on_hyphens=False,
    )


def _hide_off_addons(p: argparse.ArgumentParser, off: set[str]) -> None:
    """R1.1: an option or a listed command that names a built-in add-on that is off is not shown."""
    for a in p._actions:
        if a.option_strings and a.help not in (None, argparse.SUPPRESS):
            if any(m.lower() in off for m in _CORE_ADDON.findall(a.help)):
                a.help = argparse.SUPPRESS
    sp = _subparsers(p)
    if sp is not None:
        sp._choices_actions[:] = [
            c
            for c in sp._choices_actions
            if not any(m.lower() in off for m in _CORE_ADDON.findall(c.help or ""))
        ]


def apply(parser: argparse.ArgumentParser, on: frozenset[str] | set[str] = frozenset()) -> None:
    """Give every help screen its examples and next step; hide what names a built-in add-on that is off."""
    off = {a for a in addons.CORE_ADDONS if a not in on}

    def walk(p: argparse.ArgumentParser, path: str) -> None:
        if path.split(" ")[0] not in addons.CORE_ADDONS:
            _hide_off_addons(p, off)
        sp = _subparsers(p)
        if sp is not None and sp.metavar is None:
            sp.metavar = "<command>"
        notes = [p.epilog] if p.epilog else []
        ex = examples(path, p) if path else ()
        if ex:
            notes.append("Examples:\n" + "\n".join(f"  {e}" for e in ex))
        nxt = next_line(path) if (sp is None or not path) else f"orch {path} <command> --help  (its examples)"
        if nxt:
            notes.append(_wrap("Next step: ", nxt))
        p.epilog = "\n\n".join(notes) or None
        p.formatter_class = argparse.RawDescriptionHelpFormatter
        if sp is not None:
            seen: set[int] = set()
            for name, child in sp.choices.items():  # an alias is the same parser: walked once
                if id(child) not in seen:
                    seen.add(id(child))
                    walk(child, f"{path} {name}".strip())

    walk(parser, "")

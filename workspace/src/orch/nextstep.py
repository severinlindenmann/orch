"""R2.7: every `orch` command ends with one `Next:` line, so any agent stays on track without vendor tricks.

ONE table (`HINTS`) keyed by the command path ("ticket new", "check done", ...). A path ending in `*` covers
every command below it ("relay *"). An entry is a plain line or a function `(data, args) -> str | None`.
`data` is what the command gave `_out` (None when it printed itself); `args.orch_root` is the workspace.

Printing happens once, in `cli.main`, after the command: text mode only. `--json` shapes never change
(`ticket status` keeps its own `next_step` key). A hint names relay, publish, a phone or an add-on only
when the command itself belongs to that part (R1.1).
"""

from __future__ import annotations

import argparse

from orch import tickets

# Commands whose whole stdout is read by a program or a hook, so a trailing line would corrupt it.
EXEMPT = {
    "work-check": "silent unless files changed, and it speaks a tool's hook protocol",
    "uninstall": "its last line already says how to remove orch itself",
    "ticket artifacts-dir": "its only output is a folder path that scripts capture",
}


def remember(args, data) -> None:
    """Each command's result, kept for its hint (the printed shapes are not touched)."""
    args._next_data = data


def leaf_path(parser: argparse.ArgumentParser, args) -> str:
    """The command path of a parsed command ("ticket new"), found by walking the parser's own sub-commands."""
    words: list[str] = []
    cur = parser
    while True:
        sp = next((a for a in cur._actions if isinstance(a, argparse._SubParsersAction)), None)
        word = getattr(args, sp.dest, None) if sp else None
        if not word or word not in sp.choices:
            break
        words.append(word)
        cur = sp.choices[word]
    return " ".join(words)


def _tid(args) -> str:
    return getattr(args, "id", None) or getattr(args, "ticket", None) or "<ticket>"


def _load(args, tid: str | None = None):
    try:
        return tickets.load(args.orch_root, tid or _tid(args))
    except Exception:  # a hint must never break the command it follows
        return None


def _name(t: dict, fallback: str) -> str:
    return t.get("key") or t.get("id") or fallback


def work_on(t: dict | None, fallback: str = "<ticket>") -> str:
    """The one most useful next command for a ticket, from what it holds now."""
    if not t:
        return f"orch ticket show {fallback}"
    n = _name(t, fallback)
    if t.get("status") in ("done", "dropped"):
        return "orch ticket list"
    if t.get("status") == "review":
        return "a person looks at it and marks it Done: orch needs"
    checks = t.get("checklist") or []
    if not checks:
        return f'add one task per step: orch check add {n} "<step>"'
    open_ = [c for c in checks if not c.get("done") and not c.get("wont_do")]
    if open_:
        c = open_[0]["id"]
        return f'do {c}, then record its evidence: orch check done {n} {c} --note "<evidence>"'
    if not t.get("summary"):
        return f'orch ticket summary {n} "<where things stand>"'
    return f"orch ticket status {n} done"


def _on_ticket(data, args) -> str:
    return work_on(_load(args), _tid(args))


def _new(data, args) -> str:
    n = (data or {}).get("key") or (data or {}).get("id") or "<ticket>"
    return f'add one task per step: orch check add {n} "<step>"'


def _check_add(data, args) -> str:
    c = (data or {}).get("id", "<task>")
    return f'do the step, then record its evidence: orch check done {_tid(args)} {c} --note "<evidence>"'


def _start_task(data, args) -> str:
    c = getattr(args, "check", "<task>")
    return f'do the step, then record its evidence: orch check done {_tid(args)} {c} --note "<evidence>"'


def _record(data, args) -> str:
    c = getattr(args, "check", "<task>")
    return f'if that is the evidence, close the task: orch check done {_tid(args)} {c} --note "<evidence>"'


def _init(data, args) -> str:
    from orch import init as init_mod

    if not getattr(args, "recommended", False) and init_mod.has_recommended(args.orch_root):
        return "orch init --recommended"
    if (data or {}).get("starter"):  # a person starts it (dashboard Start, or their helper)
        return f"start the starter task {data['starter']} to fill in the workspace profile"
    return 'orch ticket new "<title>"'


def _status(data, args) -> str:
    if (data or {}).get("next_step"):
        return data["next_step"]
    t = _load(args)
    return work_on(t, _tid(args)) if t and t.get("status") != "done" else "orch ticket list"


def _list(data, args) -> str:
    rows = [t for t in (data or []) if t.get("status") not in ("done", "dropped")]
    if not rows:
        return 'create one: orch ticket new "<title>"'
    return work_on(rows[0] if "checklist" in rows[0] else _load(args, rows[0]["id"]), rows[0]["id"])


def _ask(data, args) -> str:
    if (data or {}).get("taken_back"):
        return "keep working on the ticket."
    return "keep working on the steps that do not need the answer."


def _update(data, args) -> str | None:
    if getattr(args, "project_only", False) or getattr(args, "after_install", False):
        return None  # the installer's own internal runs: nothing for a person or agent to follow
    return "orch ticket list"


def _doctor(data, args) -> str:
    if (data or {}).get("problems"):
        return "fix the first problem above, then run orch doctor again"
    return "orch ticket list"


def _logins(data, args) -> str:
    if any(r.get("state") == "renew" for r in (data or {}).get("items") or []):
        return "renew it with the tool's own login, then run orch logins again"
    return "orch ticket list"


def _status_cmd(data, args) -> str:
    return "orch stop  (when you are done)" if data else "orch ticket list"


HINTS = {
    "init": _init,
    "update": _update,
    "start": "keep working; the dashboard link is above. orch ticket list",
    "stop": "orch ticket list",
    "status": _status_cmd,
    "addon add": "orch addon list",
    "addon remove": "orch addon list",
    "addon uninstall": "orch addon list",
    "addon list": "turn one on with: orch addon add <name>",
    "diag inspect": "orch diag query",
    "diag query": "orch diag report",
    "diag report": "share the report with whoever is helping you, then keep working: orch ticket list",
    "diag delete": "orch ticket list",
    "report problem": "carry on with your ticket: orch ticket list",
    "report feature": "carry on with your ticket: orch ticket list",
    "ticket new": _new,
    "ticket tree": _on_ticket,
    "ticket list": _list,
    "ticket show": _on_ticket,
    "ticket status": _status,
    "ticket edit": _on_ticket,
    "ticket set": _on_ticket,
    "ticket summary": _on_ticket,
    "ticket outcome": _on_ticket,
    "ticket artifacts": _on_ticket,
    "ticket title": _on_ticket,
    "ticket tidy": _on_ticket,
    "ticket plan": _on_ticket,
    "ticket attach": _on_ticket,
    "ticket wait": "keep working on other tickets: orch ticket list",
    "ticket changes": _on_ticket,
    "ticket patch": _on_ticket,
    "doctor": _doctor,
    "logins": _logins,
    "pause": "turn it back on with: orch resume",
    "resume": "orch needs",
    "wait": "keep working on other tickets: orch ticket list",
    "check add": _check_add,
    "check edit": _on_ticket,
    "check move": _on_ticket,
    "check remove": _on_ticket,
    "check reopen": _start_task,
    "check start": _start_task,
    "check stop": _on_ticket,
    "check wont-do": _on_ticket,
    "ticket model": _on_ticket,
    "check record": _record,
    "check done": _on_ticket,
    "log": _on_ticket,
    "ask": _ask,
    "answer": "the agent picks the answer up on its next run: orch ticket list",
    "ref add": _on_ticket,
    "ref list": _on_ticket,
    "ref rm": _on_ticket,
    "ref set": _on_ticket,
    "ref merge": _on_ticket,
    "ext set": _on_ticket,
    "ext unset": _on_ticket,
    "needs": "keep working on what does not wait: orch ticket list",
    "usage": "keep working: orch ticket list",
    "review list": "orch review link  (the page where a person answers)",
    "review answer": "orch needs",
    "review wait": _on_ticket,
    "review link": "orch needs",
    "review tend": "orch review accepted  (what was accepted for you today)",
    "review accepted": "orch needs",
    "look *": "orch ticket list",
    "publish connect": 'describe this workspace: orch publish profile --description "..." --tags a,b',
    "publish new": lambda d, a: f"orch publish app {a.folder}",
    "publish *": "carry on with your ticket: orch ticket list",
    "relay connect": 'describe this workspace: orch relay profile --description "..." --tags a,b',
    "relay problem share": "carry on with your ticket: orch ticket list",
    "relay problem list": lambda d, a: (
        "take one: orch relay problem get <id>" if d else "nothing to pick up; carry on with your ticket."
    ),
    "relay problem get": lambda d, a: (
        f"read .agents/skills/orch-diagnose/SKILL.md, then investigate orch report {d.get('ref')}"
        if isinstance(d, dict)
        else None
    ),
    "relay problem done": "orch relay problem list",
    "relay problem back": "orch relay problem list",
    "relay *": "carry on; a reply comes in on your next run.",
}


def entry(path: str):
    """The table entry for a command path: the exact one, else the longest `<prefix> *`."""
    if path in HINTS:
        return HINTS[path]
    words = path.split()
    for i in range(len(words) - 1, 0, -1):
        key = " ".join(words[:i]) + " *"
        if key in HINTS:
            return HINTS[key]
    return None


def hint(path: str, data, args) -> str | None:
    """The one next-step line for a command path, or None (exempt, unknown, or nothing sensible to say)."""
    if path in EXEMPT:
        return None
    e = entry(path)
    if e is None:
        return None
    try:
        return e(data, args) if callable(e) else e
    except Exception:  # a hint must never break the command it follows
        return None

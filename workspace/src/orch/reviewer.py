"""The Reviewer (`orch review tend`, ORCH-77): accepts small finished work for the owner.

Owner rule (16 Nov 2026): bugs and small changes are accepted for him; bigger changes (look, words, workflow,
concept, technical) wait for his answer. A program decides from facts, never a model:

- **Accept for you** (Review -> Done) when every task is done with evidence, every part of Done when has a
  task, no question waits, every linked pull request is merged with its checks green, and the change is
  small by its files (`size_reasons`).
- **Leave it for you** when the change is not small, there is no pull request to check, or it was already sent
  back once. One line in the history says why.
- **Send it back to the helper** when work is missing (a pull request not merged, checks not green, a task
  without evidence). Once per ticket: reviews never loop (R4.5).

Off until the owner turns it on (`orch config set workflow.reviewer on`). Nothing happens while automation is
paused. Each ticket is decided once per change: the state file remembers the ticket's revision after the
decision, so a quiet ticket gets no second line. No AI call: a repeating automation script runs the pass.
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

from orch import brake, config, ghmerge, history, runs, tickets
from orch.errors import Refused

BY = tickets.REVIEWER
MAX_FILES = 10  # changed files, tests not counted
MAX_LINES = 300  # changed lines, tests not counted
STATE_MAX = 256 * 1024
DIFF_MAX = 2 * 1024 * 1024

# What a changed file is, by its path (the first match wins in this order: a test is never "look").
# Tests: only real test folders (at the top, or one or two levels down).
TEST = re.compile(r"^(e2e|tests?|[^/]+/tests?|[^/]+/[^/]+/tests?)/")  # a test name in a source folder is code
# What may leave the machine (manager, 16 Nov: a green PR still let a password in a picture through): the
# secret check and scan and what they read with, sign-in and session code, sync, the contracts. Never small.
SECURITY = re.compile(
    r"^contracts/|(^|/)(secretscan|secretrun|cli_secret|keystore|phone_view|phone_results|pagelaunch)\.py$"
    r"|(^|/)[^/]*(session|signin|sign_in|login|auth)[^/]*\.py$|(^|/)orch_ui/origin\.py$"
    r"|(^|/)sync[^/]*\.py$|^workspace-addons/sync/"
)
STRUCTURE = re.compile(
    r"^\.github/|^[A-Z][A-Z_]*\.md$|(^|/)AGENTS\.md$|\.schema\.json$|^(relay|publish)/"
    r"|(^|/)(relay|publish)[^/]*\.py$|(^|/)install\.(sh|ps1)$|(^|/)(pyproject\.toml|uv\.lock|Cargo\.(toml|lock)"
    r"|package(-lock)?\.json|Dockerfile)$|\.ya?ml$"
)
LOOK = re.compile(
    r"\.(css|html?|png|jpe?g|gif|svg|webp|ico|[cm]?js|jsx|tsx|vue|swift|kt|xib|storyboard)$"
    r"|(^|/)(static|mockup|web|templates|mobile|assets)/"
)
WORDS = re.compile(r"\.(md|txt|rst)$|(^|/)(skills|docs)/|wording")
# In an added line of code (not a test): a new command or setting, or words a person reads.
NEW_CONCEPT = re.compile(r"\b(add_parser|add_argument|set_key|file_switch)\(")
WORDS_IN_CODE = re.compile(r"""(["'])(?=[^"'\n]*[A-Za-z]+ [A-Za-z]+ [A-Za-z]+)[^"'\n]*\1""")
KIND_TEXT = {
    "security": "security: needs a second look",
    "structure": "changes rules, checks, relay, publish or how orch is installed",
    "look": "changes how a page looks",
    "words": "changes words people read",
    "concept": "adds a command or a setting",
    "other": "changes code the Reviewer cannot read (not Python)",
}


def kind_of(path: str) -> str:
    """security | test | structure | look | words | code."""
    for name, rx in (
        ("security", SECURITY),  # first: a security file never hides as a test
        ("test", TEST),
        ("structure", STRUCTURE),
        ("look", LOOK),
        ("words", WORDS),
    ):
        if rx.search(path):
            return name
    return "code"


def _diff_added(diff: str) -> dict[str, list[str]]:
    """Added lines per file from a unified diff."""
    out: dict[str, list[str]] = {}
    path = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            p = line[4:].strip()
            path = p[2:] if p.startswith("b/") else None
        elif path and line.startswith("+") and not line.startswith("+++"):
            out.setdefault(path, []).append(line[1:])
    return out


def _words_line(line: str) -> bool:
    s = line.strip()
    if not s or s.startswith(("#", '"""', "'''", 'r"""')):
        return False
    return WORDS_IN_CODE.search(s) is not None


def size_reasons(files: list[dict], added: dict[str, list[str]] | None = None) -> tuple[list[str], dict]:
    """Why a change is NOT small ([] = small), and the counts {files, lines} without tests. files: [{path,
    additions, deletions}]; added: the added lines per file (from the diff), for words and new commands in
    code."""
    counts = {"security": 0, "look": 0, "words": 0, "structure": 0, "concept": 0, "other": 0}
    n_files = n_lines = 0
    for f in files:
        path = str(f.get("path") or "")
        kind = kind_of(path)
        if kind == "test":
            continue
        n_files += 1
        n_lines += int(f.get("additions") or 0) + int(f.get("deletions") or 0)
        if kind in counts:
            counts[kind] += 1
        elif not path.endswith(".py"):
            counts["other"] += 1  # only Python is read line by line; anything else waits for the owner
        elif added is not None:
            lines = added.get(path, [])
            if any(NEW_CONCEPT.search(x) for x in lines):
                counts["concept"] += 1
            elif any(_words_line(x) for x in lines):
                counts["words"] += 1
    why = [f"{KIND_TEXT[k]} ({n} {'file' if n == 1 else 'files'})" for k, n in counts.items() if n]
    if n_files > MAX_FILES or n_lines > MAX_LINES:
        why.append(
            f"too big for a small fix ({n_files} files, {n_lines} lines; "
            f"small is {MAX_FILES} and {MAX_LINES})"
        )
    return why, {"files": n_files, "lines": n_lines}


# ------------------------------------------------------------------ facts


def pr_urls(root: Path, ticket: dict) -> list[str]:
    """Every pull request linked to the ticket: references and evidence, in order, once each."""
    from orch import refs

    seen: list[str] = []
    found = [refs.target(r) for _, r in refs.all_refs(root, ticket)]
    for c in ticket.get("checklist") or []:
        for e in c.get("evidence") or [] if isinstance(c, dict) else []:
            if isinstance(e, dict) and e.get("type") in ("pr", "url"):
                found.append(str(e.get("ref") or ""))
    for u in found:
        m = ghmerge.PR_URL.search(str(u or ""))
        if m and m.group(0) not in seen:
            seen.append(m.group(0))
    return seen


def pr_facts(url: str) -> dict | None:
    """What GitHub says about a pull request, read-only: {url, number, state, green, checks, failed, files,
    added}. None when it cannot be read (no gh, not signed in, no network): the ticket is looked at again
    on the next pass."""
    gh = shutil.which("gh")
    if gh is None:
        return None
    try:
        v = ghmerge._gh_plain(
            gh, ["pr", "view", url, "--json", "number,state,statusCheckRollup,files,mergedAt"], 30
        )
        data = json.loads(v.stdout) if v.returncode == 0 else None
    except (Refused, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("state"), str):
        return None
    rollup = data.get("statusCheckRollup") if isinstance(data.get("statusCheckRollup"), list) else []
    newest = ghmerge._newest(rollup) if rollup else []
    files = [f for f in data.get("files") or [] if isinstance(f, dict)]
    facts = {
        "url": url,
        "number": data.get("number"),
        "state": data["state"],
        "green": ghmerge.passed(rollup),
        "checks": len(newest),
        "failed": sum(1 for c in newest if not ghmerge.passed([c])),
        "files": files,
        "merged_at": data.get("mergedAt") if isinstance(data.get("mergedAt"), str) else None,
        "added": None,
    }
    code = [f for f in files if str(f.get("path", "")).endswith(".py") and kind_of(str(f["path"])) == "code"]
    if data["state"] == "MERGED" and code:
        try:
            d = ghmerge._gh_plain(gh, ["pr", "diff", url], 30)
        except Refused:
            return None
        if d.returncode != 0 or len(d.stdout) > DIFF_MAX:
            return None
        facts["added"] = _diff_added(d.stdout)
    return facts


# ------------------------------------------------------------------ the rule


def _n(text: str, n: int) -> str:
    return f"{n} {text}" if n == 1 else f"{n} {text}s"


_SKIP = {
    "with",
    "that",
    "this",
    "from",
    "when",
    "have",
    "does",
    "must",
    "only",
    "then",
    "them",
    "into",
    "also",
}


def _words(text: str) -> list[str]:
    return list(dict.fromkeys(w for w in tickets._norm_words(text).split() if len(w) >= 4 and w not in _SKIP))


def decide(root: Path, ticket: dict, facts: list[dict | None], sent_back: int = 0) -> dict:
    """{"verdict": accept | leave | back | wait, "why": one line}. `facts`: pr_facts per linked pull request
    (None = could not be read: wait, look again next pass). Pure apart from reading the ticket's evidence."""
    items = [c for c in ticket.get("checklist") or [] if isinstance(c, dict) and not c.get("wont_do")]
    proof = tickets.proof_state(ticket, root)
    if tickets._open_questions(ticket):
        return {"verdict": "leave", "why": "a question on this ticket waits for your answer."}
    gaps = [c["text"] for c in items if not c.get("done") or not c.get("evidence")]
    # a part no task links to is sent back with the words looked for and the question which task proves it
    for p in proof["uncovered"]:
        looked = ", ".join(_words(p)[:6]) or "none"
        gaps.append(
            f"Done when part '{p}' has no task (looked for: {looked}; "
            'which task proves it? orch check done <ticket> <task> --proves "<part>")'
        )
    gaps += [
        f"the check on '{c['text']}' failed" for c in items if proof["per_item"].get(c["id"]) == "failed"
    ]
    missing = []
    if gaps:
        missing.append(gaps[0] if len(gaps) == 1 else f"{gaps[0]} (and {len(gaps) - 1} more)")
    if not facts:
        if missing:
            return _back_or_leave("work is missing: " + missing[0], sent_back)
        return {"verdict": "leave", "why": "no pull request to check, so you look at it yourself."}
    if any(f is None for f in facts):
        return {"verdict": "wait", "why": "GitHub could not be read; looked at again next time."}
    for f in facts:
        num = f"#{f['number']}"
        made, merged = _at(ticket.get("created_at")), _at(f.get("merged_at"))
        if f["state"] == "MERGED" and made is not None and (merged is None or merged < made):
            return {"verdict": "leave", "why": f"pull request {num} was merged before this ticket was made."}
        if f["state"] == "CLOSED":
            return {"verdict": "leave", "why": f"pull request {num} was closed without merging."}
        if f["state"] != "MERGED":
            missing.append(f"pull request {num} is not merged yet")
        elif not f["green"]:
            bad = f"{f['failed']} of {f['checks']}" if f["checks"] else "no"
            missing.append(f"checks of pull request {num} were not green when it was merged ({bad} failed)")
    if missing:
        return _back_or_leave("; ".join(missing[:2]), sent_back)
    why: list[str] = []
    files = lines = 0
    for f in facts:
        reasons, counts = size_reasons(f["files"], f["added"])
        why += reasons
        files += counts["files"]
        lines += counts["lines"]
    if not why and (files > MAX_FILES or lines > MAX_LINES):
        why.append(f"too big for a small fix ({files} files, {lines} lines)")
    if why:
        return {"verdict": "leave", "why": "; ".join(dict.fromkeys(why)) + "."}
    prs = ", ".join(f"#{f['number']}" for f in facts)
    checks = sum(f["checks"] for f in facts)
    done = sum(1 for c in items if c.get("done") and c.get("evidence"))
    return {
        "verdict": "accept",
        "why": (
            f"{'pull request' if len(facts) == 1 else 'pull requests'} {prs} merged, "
            f"{_n('check', checks)} green, {done} of {len(items)} tasks with evidence, "
            f"small fix ({_n('file', files)}, {_n('line', lines)})."
        ),
    }


def _back_or_leave(why: str, sent_back: int) -> dict:
    if sent_back:
        return {"verdict": "leave", "why": f"sent back once already and still: {why}."}
    return {"verdict": "back", "why": why}


# ------------------------------------------------------------------ the pass


def _state_path(root: Path) -> Path:
    return runs.run_dir(root) / "reviewer.json"


def _read_state(root: Path) -> dict:
    try:
        p = _state_path(root)
        if p.stat().st_size > STATE_MAX:
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def _write_state(root: Path, state: dict) -> None:
    with contextlib.suppress(OSError):
        runs.run_dir(root).mkdir(parents=True, exist_ok=True)
        runs._atomic(_state_path(root), json.dumps(state, indent=1) + "\n")


def _send_back(root: Path, tid: str, why: str) -> dict:
    if "which task proves it?" in why:  # a question, not missing work: name the task, then send it again
        note = f"The Reviewer has a question: {why}. Answer it and send the ticket to Review again."
    else:
        note = f"The Reviewer found work missing: {why}. Finish it and send the ticket to Review again."
    t = tickets.ask_for_changes(root, tid, note, BY)
    from orch import runs_live

    with contextlib.suppress(Exception):  # Busy (no free slot) or a start problem: the ticket waits in line
        runs.start(root, tid, runs_live.AUTOMATION_BY)
    return t


def run(root: Path, dry_run: bool = False, facts_of=None) -> dict:
    """One pass: {"off", "paused", "actions": [{ticket, key, verdict, why, done}]}. dry_run only says it."""
    facts_of = facts_of or pr_facts
    if not config.reviewer_on(root):
        return {"off": True, "paused": False, "actions": []}
    if brake.paused(root) is not None:
        return {"off": False, "paused": True, "actions": []}
    state = _read_state(root)
    actions = []
    in_review = set()
    for t in tickets.list_all(root):
        if t.get("status") != "review":
            continue
        tid = t["id"]
        in_review.add(tid)
        mine = state.get(tid, {})
        if mine.get("rev") == t.get("revision"):
            continue  # decided already and nothing changed since
        res = decide(root, t, [facts_of(u) for u in pr_urls(root, t)], int(mine.get("back") or 0))
        row = {"ticket": tid, "key": t.get("key") or tid, **res, "done": False}
        if res["verdict"] == "wait" or dry_run:
            actions.append(row)
            continue
        try:
            if res["verdict"] == "accept":
                after = tickets.accept_for_owner(root, tid, res["why"])
            elif res["verdict"] == "back":
                after = _send_back(root, tid, res["why"])
                mine["back"] = int(mine.get("back") or 0) + 1
            else:
                after = tickets.log(root, tid, "Left for you by the Reviewer: " + res["why"], BY)
        except Refused as e:  # changed under us (moved, answered): look again next pass
            row["why"] = str(e)
            actions.append(row)
            continue
        mine["rev"] = after.get("revision")
        state[tid] = mine
        row["done"] = True
        actions.append(row)
    if not dry_run:
        for tid in list(state):  # keep "sent back once" while the ticket is worked on; forget finished ones
            if tid not in in_review:
                with contextlib.suppress(Refused, OSError, ValueError):
                    if tickets.load(root, tid).get("status") in ("done", "dropped"):
                        state.pop(tid)
                        continue
                state[tid].pop("rev", None)
        _write_state(root, state)
    return {"off": False, "paused": False, "actions": actions}


VERDICT_WORDS = {
    "accept": "accepted for you",
    "leave": "left for you",
    "back": "sent back",
    "wait": "not yet",
}


def text(result: dict, dry_run: bool = False) -> str:
    if result.get("off"):
        return "The Reviewer is off here. Turn it on: orch config set workflow.reviewer on"
    if result.get("paused"):
        return "Automation is paused here: the Reviewer did nothing. Turn it back on: orch resume."
    lines = []
    for a in result["actions"]:
        word = VERDICT_WORDS[a["verdict"]]
        lines.append(f"{a['key']}: {'would be ' if dry_run else ''}{word}: {a['why']}")
    return "\n".join(lines) or "Nothing in Review to look at."


# ------------------------------------------------------------------ what was accepted for the owner


def since_time(word: str | None, now: float | None = None) -> str:
    """today (default) | yesterday | YYYY-MM-DD -> the ISO time it starts (local midnight, as UTC)."""
    now = time.time() if now is None else now
    local = datetime.fromtimestamp(now).astimezone()
    w = (word or "today").strip().lower()
    if w == "today":
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    elif w == "yesterday":
        start = (local - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", w):
        try:
            start = datetime.strptime(w, "%Y-%m-%d").astimezone()
        except ValueError:
            raise Refused("Give today, yesterday or a date like 2026-11-16.") from None
    else:
        raise Refused("Give today, yesterday or a date like 2026-11-16.")
    return start.isoformat(timespec="seconds")


def _at(iso) -> float | None:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def accepted(root: Path, since: str) -> list[dict]:
    """Tickets the Reviewer accepted for the owner since `since` (ISO), newest first: {ticket, key, title, at,
    why, sent_back} (sent_back: the owner sent it back since)."""
    start = _at(since)
    out = []
    for t in tickets.list_all(root):
        for h in history.lines(root, t):
            if not isinstance(h, dict) or h.get("by") != BY:
                continue
            txt = str(h.get("text") or "")
            at = _at(h.get("at"))
            if txt.startswith(tickets.ACCEPTED_LINE) and at is not None and (start is None or at >= start):
                out.append(
                    {
                        "ticket": t["id"],
                        "key": t.get("key") or t["id"],
                        "title": t.get("title") or "",
                        "at": h.get("at"),
                        "why": txt[len(tickets.ACCEPTED_LINE) :],
                        "sent_back": not tickets.accepted_by_reviewer(root, t),
                    }
                )
    out.sort(key=lambda r: str(r["at"]), reverse=True)
    return out


def accepted_text(rows: list[dict], word: str = "today") -> str:
    if not rows:
        return f"Nothing was accepted for you {word}."
    head = f"Accepted for you {word}: {_n('ticket', len(rows))}"
    lines = [
        f"- {r['key']} {r['title']}: {r['why']}" + (" (you sent it back)" if r["sent_back"] else "")
        for r in rows
    ]
    return "\n".join([head, *lines])

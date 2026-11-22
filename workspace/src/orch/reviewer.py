"""The Reviewer (`orch review tend`, ORCH-77): accepts small finished work for the owner.

Owner rule (16 Nov 2026): bugs and small changes are accepted for him; bigger changes (look, words, workflow,
concept, technical) wait for his answer. A program decides from facts, never a model:

- **Accept for you** (Review -> Done) when every task is done with evidence, every part of Done when has a
  task, no question waits, every linked pull request is merged with its checks green, and the change is
  small by its files (`size_reasons`), and the ticket's kind is one the workspace lists
  (`workflow.reviewer_kinds`, default bugs; ORCH-645). A ticket without a kind (made before kinds)
  counts as a small bug.
- **Leave it for you** when a ticket is a draft, mockup or design (kind `draft`, never accepted), its kind
  is not listed, or when the change is not small, there is no pull request to check, a part of Done when
  has no task (ORCH-220: a missing link is a question for you, not work for a helper), or it was already sent
  back once. One line in the history says why.
- **Send it back to the helper** when work is missing (a pull request not merged, checks not green, a task
  without evidence). Once per ticket: reviews never loop (R4.5).

It also answers small, routine questions for the owner (ORCH-176, `answer_routine`): a plain question with
the helper's recommended option, open 30 minutes, that names no concept, words, look, money, production or
anything that cannot be undone. A word hit leaves it for the owner (fail safe). Its own switch, which only a
person turns on: `workflow.reviewer_answers`.

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
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

from orch import brake, config, ghmerge, history, ownerpick, runs, tickets
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
    n_files = n_lines = all_files = all_lines = 0
    for f in files:
        path = str(f.get("path") or "")
        kind = kind_of(path)
        all_files += 1
        all_lines += int(f.get("additions") or 0) + int(f.get("deletions") or 0)
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
    return why, {"files": n_files, "lines": n_lines, "all_files": all_files, "all_lines": all_lines}


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


def part_match(part: str, items: list[dict]) -> tuple[list[str], list[str]]:
    """(words looked for, words found) for one Done when part: its longer words against the title, covers,
    proofs and one-line results of the finished tasks."""
    seen: set[str] = set()
    for c in items:
        if c.get("done") and c.get("evidence"):
            bits = [c.get("text"), c.get("covers"), *(c.get("proves") or [])]
            for e in c["evidence"]:
                if isinstance(e, dict):
                    bits += [
                        e.get("summary"),
                        e.get("title"),
                        e.get("ref") if e.get("type") == "note" else None,
                    ]
            seen.update(_words(" ".join(b for b in bits if isinstance(b, str))))
    want = _words(part)
    return want, [w for w in want if w in seen]


def review_result(root: Path | None, ticket: dict) -> dict | None:
    """ORCH-826 (owner: "they should rather highlight if something is not good for me to check and not what
    is good"): the result of a review ticket orch made itself (a security review of a pull request, the
    Reviewer's second look), {"ok", "line", "what"}, or None (not one, or no result yet). An ok is accepted
    for the owner like a small fix; a problem stays on the owner's list and its card leads with it."""
    from orch import lookreview, secreview  # here: both read run files, and lookreview imports this module

    for get in (secreview.ticket_result, lookreview.ticket_result):
        try:
            got = get(root, ticket)
        except (OSError, ValueError, KeyError, TypeError, Refused):
            got = None
        if got is not None:
            got["line"] = " ".join(str(got.get("line") or "").split())[:300] or "no details given"
            return got


def kind_block(root: Path, ticket: dict) -> str | None:
    """ORCH-645: why no automation may accept this ticket by its kind (a draft, an empty list, a kind the
    workspace does not list; no kind counts as a small bug), or None. One check for the Reviewer and its
    second look."""
    kind = tickets.kind(ticket)
    if kind == "draft":
        return "drafts, mockups and designs are only accepted by you."
    allowed = config.reviewer_kinds(root)
    if not allowed:
        return "this workspace lets the Reviewer accept no kind of work by itself."
    if (kind or "small_bug") not in allowed:
        return f"{tickets.KINDS[kind or 'small_bug'].lower()} work is not accepted by itself here (Settings)."
    return None


def decide(root: Path, ticket: dict, facts: list[dict | None], sent_back: int = 0) -> dict:
    """The verdict below, marked kind_block when the ticket's kind keeps every automation away (the second
    look then leaves it too, whatever the verdict's reason)."""
    res = _decide(root, ticket, facts, sent_back)
    if res.get("verdict") == "leave" and kind_block(root, ticket):
        res["kind_block"] = True
    return res


def _decide(root: Path, ticket: dict, facts: list[dict | None], sent_back: int = 0) -> dict:
    """{"verdict": accept | leave | back | wait, "why": one line}. `facts`: pr_facts per linked pull request
    (None = could not be read: wait, look again next pass). Pure apart from reading the ticket's evidence."""
    items = [c for c in ticket.get("checklist") or [] if isinstance(c, dict) and not c.get("wont_do")]
    proof = tickets.proof_state(ticket, root)
    if ownerpick.carries_draft(ticket):  # ORCH-582: never accepted, sent back or put in line by the Reviewer
        return {"verdict": "leave", "why": ownerpick.LEFT_WHY, "owner": True}
    if tickets.kind(ticket) == "draft":  # ORCH-645: never accepted by an automation, never sent back
        return {"verdict": "leave", "why": kind_block(root, ticket), "owner": True}
    if tickets._open_questions(ticket):
        return {"verdict": "leave", "why": "a question on this ticket waits for your answer."}
    gaps = [c["text"] for c in items if not c.get("done") or not c.get("evidence")]
    # a part no task links to: with related work in the finished tasks it only gets a note on the accept; with
    # none the ticket is left for the owner with the words looked for (ORCH-220: never sent back for it, a
    # helper run cannot answer whether the work is missing; the owner sends it back when it is).
    unmatched, uncovered = [], []
    for p in proof["uncovered"]:
        want, found = part_match(p, items)
        if want and len(found) * 5 >= len(want) * 2:
            unmatched.append(p)
            continue
        looked = ", ".join(want[:6]) or "none"
        uncovered.append(f"Done when part '{p}' has no task (looked for: {looked})")
    gaps += [
        f"the check on '{c['text']}' failed" for c in items if proof["per_item"].get(c["id"]) == "failed"
    ]
    missing = []
    if gaps:
        missing.append(gaps[0] if len(gaps) == 1 else f"{gaps[0]} (and {len(gaps) - 1} more)")
    found = review_result(root, ticket)
    if found is not None and not missing:  # ORCH-826: orch's own review: only a problem is the owner's
        what = found["what"][:1].upper() + found["what"][1:]
        if found["ok"]:
            return {"verdict": "accept", "why": f"{what} found nothing for you: {found['line']}"}
        return {"verdict": "leave", "why": f"{found['what']} found a problem: {found['line']}", "owner": True}
    if not facts:
        if missing:
            return _back_or_leave("work is missing: " + missing[0], sent_back)
        return {"verdict": "leave", "why": "no pull request to check, so you look at it yourself."}
    open_part = None
    if uncovered:
        more = f" (and {len(uncovered) - 1} more)" if len(uncovered) > 1 else ""
        open_part = f"{uncovered[0]}{more}; send it back if that work is missing."
    if any(f is None for f in facts):
        return {"verdict": "wait", "why": "GitHub could not be read; looked at again next time."}
    for f in facts:
        num = f"#{f['number']}"
        made, merged = _at(ticket.get("created_at")), _at(f.get("merged_at"))
        if f["state"] == "MERGED" and made is not None and (merged is None or merged < made):
            return {"verdict": "leave", "why": f"pull request {num} was merged before this ticket was made."}
        if f["state"] == "CLOSED":
            return {"verdict": "leave", "why": f"pull request {num} was closed without merging."}
        if f["state"] != "MERGED" and tickets.in_merge_queue(root, [f.get("url")]):
            # ORCH-815: sending it back only starts a helper that can do nothing but wait; the queue merges it
            # or wakes the helper with its reason
            return {
                "verdict": "wait",
                "why": f"pull request {num} is in the merge queue; looked at again later.",
            }
        if f["state"] != "MERGED":
            missing.append(f"pull request {num} is not merged yet")
        elif not f["green"]:
            bad = f"{f['failed']} of {f['checks']}" if f["checks"] else "no"
            missing.append(f"checks of pull request {num} were not green when it was merged ({bad} failed)")
    if missing:
        return _back_or_leave("; ".join(missing[:2]), sent_back)
    if open_part:
        return {"verdict": "leave", "why": open_part}
    blocked = kind_block(root, ticket)  # ORCH-645: which kinds this workspace lets the Reviewer accept
    if blocked:
        return {"verdict": "leave", "why": blocked}
    why: list[str] = []
    files = lines = all_files = all_lines = 0
    for f in facts:
        reasons, counts = size_reasons(f["files"], f["added"])
        why += reasons
        files += counts["files"]
        lines += counts["lines"]
        all_files += counts["all_files"]
        all_lines += counts["all_lines"]
    if not why and (files > MAX_FILES or lines > MAX_LINES):
        why.append(f"too big for a small fix ({files} files, {lines} lines)")
    if why:
        return {"verdict": "leave", "why": "; ".join(dict.fromkeys(why)) + "."}
    prs = ", ".join(f"#{f['number']}" for f in facts)
    done = _first_sentence(ticket.get("summary"))
    what = f"{done} " if done else ""
    return {
        "verdict": "accept",
        "why": (
            f"{what}{'Pull request' if len(facts) == 1 else 'Pull requests'} {prs} "
            f"merged with all checks green, every task has evidence and the change is small "
            f"({_n('file', all_files)}, {_n('line', all_lines)} changed)."
        ),
    }


def _first_sentence(text) -> str:
    t = " ".join(str(text or "").split())
    if not t:
        return ""
    i = t.find(". ")
    t = t[: i + 1] if i > 0 else t
    t = t[:160].rstrip()
    return t if t.endswith((".", "!", "?")) else t + "."


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


LEFT_MAX = 300


def remember_left(mine: dict, verdict: str, why: str) -> None:
    """Keep why the Reviewer left a ticket for the person (the Reviewer was not sure), so Needs you can list
    it as stuck (stuck.py, ORCH-426); any other verdict forgets it."""
    if verdict == "leave":
        mine["left"] = " ".join(str(why or "").split())[:LEFT_MAX]
    else:
        mine.pop("left", None)


def _send_back(root: Path, tid: str, why: str) -> dict:
    note = f"The Reviewer found work missing: {why}. Finish it and send the ticket to Review again."
    t = tickets.ask_for_changes(root, tid, note, BY)
    from orch import runs_live

    with contextlib.suppress(Exception):  # Busy (no free slot) or a start problem: the ticket waits in line
        runs.start(root, tid, runs_live.AUTOMATION_BY)
    return t


def run(root: Path, dry_run: bool = False, facts_of=None) -> dict:
    """One pass: {"off", "paused", "actions": [{ticket, key, verdict, why, done}]}. dry_run only says it."""
    from orch import autoreview

    facts_of = facts_of or pr_facts
    answers_on = config.reviewer_answers_on(root)
    plain, auto, away = config.reviewer_on(root), autoreview.active(root), autoreview.away(root)
    if not plain and not answers_on and not auto:
        return {"off": True, "paused": False, "actions": [], "answers": []}
    if brake.paused(root) is not None:
        return {"off": False, "paused": True, "actions": [], "answers": []}
    answers = autoreview.answer_away(root, dry_run) if away else []  # Away first: at once, no wait
    if answers_on:
        answers += answer_routine(root, dry_run)
    if not plain and not auto:
        return {"off": False, "paused": False, "actions": [], "answers": answers}
    from orch import lookreview

    now_mode = autoreview.mode(root)
    look = plain and lookreview.on(root)
    own = lookreview.own(root) if look else set()
    state = _read_state(root)
    actions = []
    in_review = set()
    kinds = config.reviewer_kinds(root)  # a changed list decides every waiting ticket again (ORCH-645)
    for t in tickets.list_all(root):
        if t.get("status") != "review":
            continue
        tid = t["id"]
        in_review.add(tid)
        mine = state.get(tid, {})
        ok_now = bool((review_result(root, t) or {}).get("ok"))
        if (
            mine.get("rev") == t.get("revision")
            and mine.get("kinds", kinds) == kinds
            and mine.get("mode", now_mode) == now_mode
            and not (ok_now and not mine.get("ok"))
        ):
            continue  # nothing changed since (ticket, kinds, switches); an ok since: look again
        if autoreview.held(root, t):  # the owner undid a Reviewer verdict: theirs now, not even a line
            if not dry_run:
                state[tid] = {**mine, "rev": t.get("revision"), "kinds": kinds, "mode": now_mode}
            continue
        facts = [facts_of(u) for u in pr_urls(root, t)]
        back = int(mine.get("back") or 0)
        res = decide(root, t, facts, back) if plain else None
        if auto and tid not in own and (res is None or (res["verdict"] == "leave" and not res.get("owner"))):
            mine_auto = autoreview.decide(root, t, facts, back)  # None: Human review needed on, or a draft
            if mine_auto is not None:
                res = {**mine_auto, "auto": True}
        if res is None:  # not the Auto Reviewer's and the plain Reviewer is off: untouched, not even a line
            if not dry_run:
                state[tid] = {**mine, "rev": t.get("revision"), "kinds": kinds, "mode": now_mode}
            continue
        if (
            look
            and res["verdict"] == "leave"
            and tid not in own
            and not res.get("owner")
            and not res.get("auto")
        ):  # second look (ORCH-175)
            res = lookreview.triage(t, facts, res, back) or res
        row = {"ticket": tid, "key": t.get("key") or tid, **res, "done": False}
        if res["verdict"] == "wait" or dry_run:
            actions.append(row)
            continue
        try:
            if res.get("auto"):
                after = autoreview.act(root, t, res)
                if res["verdict"] == "back":
                    mine["back"] = back + 1
            elif res["verdict"] == "accept":
                after = tickets.accept_for_owner(root, tid, res["why"])
            elif res["verdict"] == "back":
                after = _send_back(root, tid, res["why"])
                mine["back"] = int(mine.get("back") or 0) + 1
            elif res["verdict"] == "queue":
                after = lookreview.queue(root, tid, res["why"])
            else:
                after = tickets.log(root, tid, "Left for you by the Reviewer: " + res["why"], BY)
        except Refused as e:  # changed under us (moved, answered): look again next pass
            row["why"] = str(e)
            actions.append(row)
            continue
        mine["rev"], mine["mode"] = after.get("revision"), now_mode
        if ok_now:
            mine["ok"] = True
        mine["kinds"] = kinds
        remember_left(mine, res["verdict"], res["why"])
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
    second = lookreview.tend(root, dry_run) if look else []
    return {"off": False, "paused": False, "actions": actions, "answers": answers, "second_look": second}


VERDICT_WORDS = {
    "accept": "accepted for you",
    "leave": "left for you",
    "back": "sent back",
    "wait": "not yet",
    "queue": "in line for a second look",
}


def text(result: dict, dry_run: bool = False) -> str:
    if result.get("off"):
        return ("The Reviewer is off here. Turn it on: orch config set workflow.reviewer on "
                "(or the Auto Reviewer on the Review page)")  # fmt: skip
    if result.get("paused"):
        return "Automation is paused here: the Reviewer did nothing. Turn it back on: orch resume."
    lines = []
    for a in result["actions"]:
        word = VERDICT_WORDS[a["verdict"]]
        who = f"Auto Reviewer ({a['kind']}): " if a.get("auto") else ""
        lines.append(f"{a['key']}: {who}{'would be ' if dry_run else ''}{word}: {a['why']}")
    lines += [f"Second look: {x}" for x in result.get("second_look") or []]
    for a in result.get("answers") or []:
        if a["routine"]:
            word = "would be answered for you" if dry_run or not a["done"] else "answered for you"
            word += " in Away mode" if a.get("away") else ""
            lines.append(f"{a['key']} {a['question']}: {word}: {a['answer']}")
        elif dry_run:
            lines.append(f"{a['key']} {a['question']}: left for you: {a['why']}")
    return "\n".join(lines) or "Nothing in Review to look at."


# ------------------------------------------------------------------ routine questions (ORCH-176)

ROUTINE_WAIT = 30 * 60  # seconds open before the Reviewer answers (the owner, when awake, sees it first)
# What stays with the owner (owner, ORCH-176: "Not included: concept, words, money, production"), by words in
# the question, its options or the ticket title. A hit only leaves the question for the owner (fails safe).
STAYS = {  # words split by spaces; each one is a regular expression
    "concept": "concepts? commands? settings? features? options? workflows? rules? roles? plans? designs?"
    r" approach(es)? behaviou?rs? should\s(a|the)\s(person|user|owner)",
    "words": "word(s|ing)? texts? names? renamed? labels? titles? messages? copy phrases? terms? nouns?",
    "look": "looks? pictures? screenshots? layouts? pages? screens? colou?rs? visual ui ux 1280 390 1920"
    " mockups? style icons? cards? show(s|n|ing)? boards? columns? buttons? dialogs? tabs? menus? lists?"
    " filters? panels? widths? dashboard phone",
    "money": "costs? prices? pay paid money budget credits? subscriptions? accounts? billing invoices?",
    "production": "production prod deploy(s|ed|ment)? releases? servers? relay publish(ed|ing)? main"
    " customers? public outside users? send email vps",
    "cannot be undone": "delete[sd]? remov(e|es|ed|ing) drop(s|ped)? irreversible undo(ne)? force secrets?"
    " passwords? tokens? keys? security merge[sd]? wipe reset migrat(e|ion)",
}
STAYS_RE = {k: re.compile(rf"(?<![\w-])({'|'.join(v.split())})(?![\w-])", re.I) for k, v in STAYS.items()}
MONEY_MARK = re.compile(r"[$€£]")
ROUTINE_TEXT_MAX = 2000
PLAIN_TEXT = re.compile(r"[\x20-\x7e\n\t]*")  # printable ASCII only
ROUTINE_WHY = (
    "routine: a plain question with the helper's recommendation, no concept, words, look, money or production"
)


def routine(root: Path, ticket: dict, q: dict, now: float | None = None) -> tuple[bool, str]:
    """(True, why) when the Reviewer may answer this question for the owner, else (False, why it stays)."""
    now = time.time() if now is None else now
    if ticket.get("general") is True:
        return False, "a Chat question"
    if q.get("answer") is not None or q.get("taken_back") is not None:
        return False, "already settled"
    if q.get("owner_only"):  # ORCH-425: the owner undid the Reviewer's answer
        return False, "you took it back from the Reviewer"
    if ownerpick.is_draft_card(q):  # ORCH-582
        return False, "a draft for you to pick"
    if q.get("card") is not None or q.get("action") is not None:
        return False, "a card for you to see"
    if q.get("kind") not in (None, "plain"):
        return False, "an add-on's own question"
    opts = q.get("options") or []
    if len(opts) < 2 or q.get("recommended") not in opts:
        return False, "no recommended option"
    asked = _at(q.get("asked_at")) if q.get("asked_at") else None  # older questions: left for the owner
    if asked is None or now - asked < ROUTINE_WAIT:
        return False, "asked less than 30 minutes ago"
    text = " ".join([str(q.get("text") or ""), *map(str, opts), str(ticket.get("title") or "")])
    text = unicodedata.normalize("NFKC", text)
    if not PLAIN_TEXT.fullmatch(text) or len(text) > ROUTINE_TEXT_MAX:  # look-alikes, hidden marks: fail safe
        return False, "not plain short text"
    hits = [k for k, rx in STAYS_RE.items() if rx.search(text) or (k == "money" and MONEY_MARK.search(text))]
    if hits:
        return False, "names " + ", ".join(hits)
    return True, ROUTINE_WHY


def answer_routine(root: Path, dry_run: bool = False, now: float | None = None) -> list[dict]:
    """Every open question on a working ticket: answer the routine ones for the owner. Returns
    [{ticket, key, question, routine, why, answer, done}]."""
    out = []
    for t in tickets.list_all(root):
        if t.get("status") in ("done", "dropped"):
            continue
        for q in t.get("questions") or []:
            if q.get("answer") is not None:
                continue
            ok, why = routine(root, t, q, now)
            row = {"ticket": t["id"], "key": t.get("key") or t["id"], "question": q["id"], "routine": ok,
                   "why": why, "answer": q.get("recommended") if ok else None, "done": False}  # fmt: skip
            if ok and not dry_run:
                try:
                    tickets.answer_for_owner(root, t["id"], q["id"], tickets.question_digest(q), why)
                    row["done"] = True
                except Refused as e:  # changed under us: look again next pass
                    row["routine"], row["why"], row["answer"] = False, str(e), None
            out.append(row)
    return out


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


_ANSWERED_RAW = re.compile(r"q\d+ = (?P<ans>.*?)(?: \(routine: [^()]*\))?\s*", re.S)


def _answered_words(raw: str) -> str:
    """The history line 'q3 = Morning (routine: ...)' as plain words: 'answered "Morning"'."""
    m = _ANSWERED_RAW.fullmatch(raw.strip())
    return f'answered "{m.group("ans")}"' if m and m.group("ans") else "answered " + raw


def accepted(root: Path, since: str) -> list[dict]:
    """What the Reviewer, the Auto Reviewer and Away mode did for the owner since `since` (ISO), newest first:
    {ticket, key, title, at, why, sent_back, auto, undo, undone} plus `answer` + `question` for an answer and
    `back` for a send-back (sent_back: the owner sent an accepted ticket back since; undo: what Undo would
    take
    back now, None when it cannot any more; undone: the owner undid it)."""
    from orch import autoreview

    start = _at(since)
    out = []
    acc_lines = (tickets.ACCEPTED_LINE, autoreview.AUTO_ACCEPTED_LINE)
    ans_lines = (tickets.ANSWERED_LINE, autoreview.AUTO_ANSWERED_LINE)
    back_lines = (tickets.SENT_BACK_LINE, autoreview.AUTO_SENT_BACK_LINE)
    for t in tickets.list_all(root):
        lines = [h for h in history.lines(root, t) if isinstance(h, dict)]
        undone = [
            str(h.get("text") or "")
            for h in lines
            if str(h.get("text") or "").startswith(autoreview.UNDONE_LINE)
        ]
        newest = {}
        for h in lines:
            txt = str(h.get("text") or "")
            if h.get("by") == BY and txt.startswith((*acc_lines, *back_lines)):
                newest["ticket"] = h
        base = {"ticket": t["id"], "key": t.get("key") or t["id"], "title": t.get("title") or ""}
        for h in lines:
            if h.get("by") != BY:
                continue
            txt = str(h.get("text") or "")
            at = _at(h.get("at"))
            if at is None or (start is not None and at < start):
                continue
            prefix = next((p for p in (*acc_lines, *ans_lines, *back_lines) if txt.startswith(p)), None)
            if prefix is None:
                continue
            auto = prefix in (
                autoreview.AUTO_ACCEPTED_LINE,
                autoreview.AUTO_ANSWERED_LINE,
                autoreview.AUTO_SENT_BACK_LINE,
            )
            row = {**base, "at": h.get("at"), "auto": auto, "sent_back": False, "undo": None, "undone": False}
            if prefix in ans_lines:
                qid = txt[len(prefix) :].split(" ", 1)[0]
                shown = history.shown_ticket(root, t)  # person fields only as shown here (history.md)
                q = next((x for x in shown.get("questions") or [] if x.get("id") == qid), None)
                row.update(answer=True, question=qid, why=_answered_words(txt[len(prefix) :]))
                row["undone"] = any(f" on {qid} (" in u for u in undone) and not (
                    q and q.get("answered_by") == BY
                )
                if (
                    q is not None
                    and q.get("answered_by") == BY
                    and q.get("answer") is not None
                    and not q.get("taken_back")
                ):
                    row["undo"] = "answer"
            elif prefix in acc_lines:
                row["why"] = txt[len(prefix) :]
                now_done = tickets.accepted_by_reviewer(root, t)
                row["sent_back"] = not now_done
                last = newest.get("ticket") is h
                if last and now_done:
                    row["undo"] = "accept"
                row["undone"] = last and not now_done and any("accept" in u for u in undone)
            else:
                row.update(back=True, why=txt[len(prefix) :])
                last = newest.get("ticket") is h
                if last and t.get("status") in ("ready", "open") and not runs.running(root, t["id"]):
                    row["undo"] = "back"
                row["undone"] = last and t.get("status") == "review" and any("send-back" in u for u in undone)
            out.append(row)
    out.sort(key=lambda r: str(r["at"]), reverse=True)
    return out


def picks_text(picks: list[dict]) -> list[str]:
    """The morning list's own part for drafts (ORCH-582): what waits for the owner's pick, never mixed with
    what the Reviewer did."""
    if not picks:
        return []
    out = [f"Waiting for your pick: {_n('draft', len(picks))}"]
    out += [f"- {r['key']} {r['title']}: {r['card']}" for r in picks]
    return out


def accepted_text(rows: list[dict], word: str = "today", picks: list[dict] | None = None) -> str:
    tail = picks_text(picks or [])
    if not rows:
        return "\n".join([f"Nothing was accepted for you {word}.", *tail])
    acc = [r for r in rows if not r.get("answer") and not r.get("back")]
    ans = [r for r in rows if r.get("answer")]
    back = [r for r in rows if r.get("back")]
    out = []
    if acc:
        out.append(f"Accepted for you {word}: {_n('ticket', len(acc))}")
        out += [
            f"- {r['key']} {r['title']}: {r['why']}"
            + (" (you undid it)" if r.get("undone") else " (you sent it back)" if r["sent_back"] else "")
            for r in acc
        ]
    if ans:
        out.append(f"Answered for you {word}: {_n('question', len(ans))}")
        out += [f"- {r['key']} {r['title']}: {r['why']}" + (" (Away mode)" if r.get("auto") else "")
                + (" (you undid it)" if r.get("undone") else "") for r in ans]  # fmt: skip
    if back:
        out.append(f"Sent back to the helper {word}: {_n('ticket', len(back))}")
        out += [f"- {r['key']} {r['title']}: {r['why']}" + (" (you undid it)" if r.get("undone") else "")
                for r in back]  # fmt: skip
    if any(r.get("undo") for r in rows):
        out.append("Undo one: orch review undo <ticket> (an answer: orch review undo <ticket> <question>)")
    return "\n".join(out + tail)

"""`orch ticket export <id>`: the ticket as a short markdown handover to paste into any agent (R2.3).

A view of the ticket, never a new object: what it is, where it stands, the open steps and questions, the
evidence and the links. No copies of files. The whole text goes through the one secret scan (R5.2) before it
is printed: a hit prints nothing and names the kind and the line, never the value."""

from __future__ import annotations

from pathlib import Path

from orch import history, refs, secretscan, tickets
from orch.errors import Refused

RECENT = 5  # history lines in the handover: enough to see the last moves, not the whole log


def _one(text) -> str:
    return " ".join(str(text or "").split())


def _evidence(ev: dict) -> str:
    t, ref = ev.get("type"), str(ev.get("ref", ""))
    if t == "commit":
        label = f"commit {ref[:12]}" + (f" · {ev['text']}" if ev.get("text") else "")
    elif t == "file" or ev.get("title"):
        label = tickets.proof_label(ev)
    else:
        label = f"{t}: {ref}" if t and t not in ("note", "url") else ref
        if ev.get("text") and t != "note":
            label += f" · {ev['text']}"
    return refs.one_line(_one(label), 300)


def _step(c: dict) -> list[str]:
    if c.get("wont_do"):
        mark, tail = "[-]", " (won't do" + (f": {_one(c.get('reason'))}" if c.get("reason") else "") + ")"
    elif c.get("done"):
        mark, tail = "[x]", ""
    else:
        mark, tail = "[ ]", " (in progress)" if c.get("state") == "doing" else ""
    out = [f"- {mark} {c['id']} {_one(c.get('text'))}{tail}"]
    out += [f"  - evidence: {_evidence(ev)}" for ev in c.get("evidence") or []]
    return out


def _waiting(w: dict) -> str:
    if w.get("kind") == "time":
        return f"until {w.get('until', '')}"
    if w.get("kind") == "question":
        return "an answer to a question"
    return f"{w.get('kind')} {w.get('ref', '')}".strip()


def markdown(root: Path, t: dict) -> str:
    t = history.shown_ticket(root, t)
    name = t.get("key") or t["id"]
    out = [f"# {name}: {_one(t['title'])}", ""]
    out.append(
        f"- Status: {tickets.status_word(t)}" + (f" ({tickets.progress_text(t)})" if t["checklist"] else "")
    )
    for label, key in (("Owner", "owner"), ("Due", "due")):
        if t.get(key):
            out.append(f"- {label}: {_one(t[key])}")
    if t.get("parent"):
        out.append(f"- Sub-ticket of: {t['parent']}")
    if t.get("waiting_on"):
        out.append(f"- Waiting on: {_waiting(t['waiting_on'])}")
    out.append(f"- Ticket id: {t['id']} (continue there with: orch ticket show {name})")

    def section(title: str, lines: list[str]) -> None:
        if lines:
            out.extend(["", f"## {title}", "", *lines])

    plan = t.get("plan") or {}
    outcome = (t.get("outcome") or {}) if t.get("status") == "done" else {}
    section("Where it stands", [_one(t["summary"])] if t.get("summary") else [])
    section(
        "What it is about",
        [
            f"- {label}: {_one(v)}"
            for label, v in (
                ("Description", t.get("description")),
                ("Note", t.get("note")),
                ("Done when", t.get("done_when")),
                ("Goal", plan.get("goal")),
                ("Not included", plan.get("not_included")),
                ("Changed", outcome.get("changed")),
                ("Why", outcome.get("why")),
            )
            if v
        ],
    )
    section("Steps", [ln for c in t["checklist"] for ln in _step(c)])
    open_q, answered = [], []
    for q in t["questions"]:
        if q.get("answer") is None:
            opts = f" Options: {' / '.join(map(_one, q['options']))}." if q.get("options") else ""
            rec = f" Suggested: {_one(q['recommended'])}." if q.get("recommended") else ""
            open_q.append(f"- {q['id']}: {_one(q['text'])}{opts}{rec}")
        else:
            answered.append(f"- {q['id']}: {_one(q['text'])} Answer: {_one(q['answer'])}")
    section("Open questions", open_q)
    section("Answered", answered)
    section(
        "Links",
        [
            f"- {refs.one_line(_one(ln.get('title') or 'link'), 120)}: {refs.one_line(refs.target(ln), 300)}"
            for _, ln in refs.all_refs(root, t)
        ],
    )
    section(
        "Recent",
        [
            f"- {h.get('at', '')[:16].replace('T', ' ')} UTC {h.get('by', '')}: "
            f"{refs.one_line(_one(tickets.history_line(h['text'], t['checklist'])), 200)}"
            for h in history.lines(root, t)[-RECENT:]
        ],
    )
    return "\n".join(out) + "\n"


def export(root: Path, tid: str) -> str:
    """The handover text, or Refused when it holds a secret (R5.2): nothing is printed then."""
    text = markdown(root, tickets.load(root, tid))
    try:
        found = secretscan.find(text, root, strict=False)
    except Exception:  # noqa: BLE001 - a scan that cannot run is never a pass
        raise Refused(
            "orch could not check the handover for secrets, so nothing was shown. Try again."
        ) from None
    if found:
        first = found[0]
        kind = secretscan.WORDS.get(first["kind"], "a secret")
        more = f" (and {len(found) - 1} more)" if len(found) > 1 else ""
        raise Refused(
            f"The handover has {kind} on line {first['line']}{more}, so nothing was shown. "
            "Remove it from the ticket and export again."
        )
    return text

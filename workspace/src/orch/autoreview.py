"""The Auto Reviewer and Away mode (ORCH-425, Away from ORCH-428): finished work in Review on a ticket without
Human review needed is checked by the kind of work, gets a written verdict point by point, and is accepted
for the owner or sent back to its helper once, without a person in between. A program decides, no AI call:
it runs inside the Reviewer's pass (`orch review tend`).

- **Kinds of work** (`kind_of_work`): screen, campaign, data or code, from the linked pull requests' files
  and, for work without a pull request, from the evidence files and the ticket's own words. Anything else is
  "other" and stays with the owner (fail safe).
- **Points** per kind: every task done with evidence and a green check, every part of Done when linked to a
  task, and the kind's own points: code = every pull request merged after the ticket was made with green
  checks; screen = pictures at 1280, 1920 and 390 px wide (and the pull request, when there is one);
  campaign = the campaign itself is on the ticket and nothing says it went out; data = a data file or a
  passing check.
- **Verdict**: every point shown -> accepted for the owner; a point missing -> sent back once; anything the
  owner keeps (a security or rules file, relay or publish, a pull request closed or merged before the ticket,
  a part of Done when without a task, a waiting question, an unknown kind, sent back once already) -> left
  for the owner with one line why.
- **Never touched**: a ticket with Human review needed on or with a draft (`ownerpick.refuse_auto`, checked
  again inside the locked write of every accept, send-back and answer). Not even a history line.
- **Undo** (`undo`): only a person. An accept goes back to Review, a send-back goes back to Review while no
  helper took it yet, an answer opens again. Each undo also turns Human review needed on for that ticket (or
  marks that question as the owner's), so the next pass never does the same thing again.

Away mode (`workflow.away`, one switch for the night): the Auto Reviewer works as above, and plain questions
and choice or plan cards with a recommended option are answered at once (no 30-minute wait), on tickets
without Human review needed, unless they name what the owner keeps (`AWAY_STAYS`: words or names, money,
production, deploy or sending, deleting or anything that cannot be undone, logins or keys). Never a Merge
card, a link card, a draft or an add-on's own question. Everything it did shows in the morning list
(`orch review accepted`) with an Undo.

Off until a person turns it on: `orch config set workflow.auto_reviewer on` or `orch config set
workflow.away on`.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from orch import config, ownerpick, runs, tickets
from orch.errors import Refused

BY = tickets.REVIEWER
KINDS = ("screen", "campaign", "data", "code")
PICTURE = (".png", ".jpg", ".jpeg", ".webp", ".gif")
DATA_EXT = (".csv", ".tsv", ".xlsx", ".xls", ".json", ".jsonl", ".parquet", ".sql", ".db", ".sqlite", ".ods")
WIDTHS = ("1280", "1920", "390")
POINTS_MAX = 20
LINE_MAX = 1500

CAMPAIGN_WORDS = re.compile(
    r"\b(campaigns?|newsletters?|mailings?|social|linkedin|instagram|ads?|adverts?|announcements?"
    r"|press release|outreach|blog posts?)\b",
    re.I,
)
DATA_WORDS = re.compile(
    r"\b(data|datasets?|reports?|exports?|imports?|csv|spreadsheets?|tables?|analysis|metrics|kpis?|figures)\b",
    re.I,
)
SCREEN_WORDS = re.compile(
    r"\b(screens?|pages?|layouts?|dashboard|ui|ux|mockups?|dialogs?|buttons?|views?)\b", re.I
)
WENT_OUT = re.compile(
    r"\b(was|were|been|got|is|are) (sent|published|posted|scheduled|live)\b|\bwent (out|live)\b", re.I
)

AUTO_POINTS_LINE = "Auto Reviewer, point by point ({kind}): "
AUTO_ACCEPTED_LINE = "Accepted for you by the Auto Reviewer: "
AUTO_SENT_BACK_LINE = "Sent back by the Auto Reviewer: "
AUTO_LEFT_LINE = "Left for you by the Auto Reviewer: "
AUTO_ANSWERED_LINE = "Answered for you in Away mode: "
UNDONE_LINE = "Undone by you: "
REVIEWER_TASKS = ("The Auto Reviewer found work missing", "The Reviewer found work missing")
OWNER_ONLY = "owner_only"  # a question the owner took back from Away mode: never answered for them again

# What Away mode never answers (owner 18 Nov on ORCH-428): words or new names, money, production, deploy or
# sending out, deleting or anything that cannot be undone, logins and keys. Words split by spaces; each one is
# a regular expression. A hit leaves the question for the owner (fails safe).
AWAY_STAYS = {
    "words or names": "word(s|ing)? texts? names? nam(e|ed|ing) renam(e|ed|es|ing) labels? titles? copy"
    " phrases? terms? nouns? slogans? taglines? wording",
    "money": "costs? prices? pay(s|ing|ment|ments)? paid money budget credits? subscriptions? billing"
    " invoices?"
    " purchases? buy(s|ing)? orders?",
    "production": "production prod deploy(s|ed|ing|ment)? releases? servers? relay publish(es|ed|ing)? main"
    " customers? public outside send(s|ing)? sent emails? mail(s|ing)? post(s|ed|ing)? go\\slive vps",
    "cannot be undone": "delet(e|es|ed|ing) remov(e|es|ed|ing) drop(s|ped)? irreversible undo(ne)? force"
    " merge[sd]? wipe reset migrat(e|es|ion|ions) destroy purge overwrite push(es|ed|ing)? truncat\\w* rm",
    "logins or keys": "logins? log\\s?in sig[n][-\\s]?in passwords? tokens? keys? secrets? credentials?"
    " accounts?"
    " auth\\w* ssh oauth api",
    # security review of #1646 (ORCH-1375): what others can see or reach is sending out too
    "outside-visible": "shar(e|es|ed|ing) links? urls? https? www invit\\w* expos\\w* grant\\w* access\\w*"
    " permission\\w* ports? network\\w* export\\w* external\\w* upload\\w* download\\w* open\\sto"
    " webhooks? domains? dns firewall\\w* clients? users? guests? members? teams? visible online internet"
    " phones? tunnel\\w* forward\\w* broadcast\\w* announc\\w* notif(y|ies|ied|ying|ication|ications)"
    " messag(e|es|ed|ing) tweets? social let(\\s\\w+){1,4}\\s(see|view|read|edit|open|use|join|in|into|have)"
    " give\\w* gave rights views? viewers? editors? roles? others? anyone everyone people person someone"
    " colleagues? partners? vendors? third\\sparty",
    # a go-ahead that points at steps it does not show: what would happen is not in the words, so it stays
    "a go-ahead without the steps": "proceed\\w* go\\s?ahead carry\\son continu(e|es|ed|ing) as\\splanned"
    " as\\sdiscussed as\\sproposed as\\sabove as\\sbefore as\\sagreed as\\sdescribed the\\splan"
    " planned next\\ssteps? steps?\\s?\\d+ c\\d+ do\\sit run\\sit start\\sit ship\\w* go\\sfor\\sit"
    " all\\sof\\sit everything the\\srest good\\sto\\sgo ready sounds\\sgood lgtm approv\\w* confirm\\w*"
    " fine\\sby",
}
# no boundary in front: a word with any prefix still counts (redeploy, pre-delete, unpublish); a hit only ever
# leaves the question for the owner, so a word that merely contains one fails safe
AWAY_RE = {k: re.compile(rf"({'|'.join(v.split())})(?![a-z0-9_])", re.I) for k, v in AWAY_STAYS.items()}
MONEY_MARK = re.compile(r"[$€£]")
# any other mark reads as one space: 'go-ahead', 'go.ahead' and 'do  it' are 'go ahead' and 'do it'
GAPS = re.compile(r"[^a-z0-9$€£]+", re.I)
AWAY_MIN_WORDS = 4  # 'Is that OK?' or 'Ready?' does not say what the yes does: it stays
LONG_WORD = re.compile(r"[a-z]{3,}", re.I)
PLAIN_TEXT = re.compile(r"[\x20-\x7e\n\t]*")
AWAY_TEXT_MAX = 2000
AWAY_CARDS = ("choice",)  # a plan or link card is approve/don't: always the owner's
AWAY_WHY = (
    "Away mode: the helper's recommendation, nothing you keep (words, names, money, production, delete, keys)"
)


def active(root: Path) -> bool:
    """The Auto Reviewer checks finished work: its own switch or Away mode is on."""
    return config.auto_reviewer_on(root) or config.away_on(root)


def away(root: Path) -> bool:
    return config.away_on(root)


def mode(root: Path) -> str:
    """What decides tickets now, so a ticket decided under another mode is looked at again."""
    return ("away" if away(root) else "auto" if active(root) else "") + (
        "+r" if config.reviewer_on(root) else ""
    )


# ------------------------------------------------------------------ the kind of work


def _evidence(ticket: dict) -> list[dict]:
    out = []
    for c in ticket.get("checklist") or []:
        if isinstance(c, dict) and not c.get("wont_do"):
            out += [e for e in c.get("evidence") or [] if isinstance(e, dict)]
    return out


def _files(ticket: dict) -> list[str]:
    return [str(e.get("ref") or "").lower() for e in _evidence(ticket) if e.get("type") == "file"]


def _words_of(ticket: dict) -> str:
    return " ".join(str(ticket.get(k) or "") for k in ("title", "note", "done_when", "description"))


def kind_of_work(ticket: dict, facts: list[dict | None]) -> str:
    """screen | campaign | data | code | other. With pull requests: a page, style or picture file -> screen,
    else code. Without: the ticket's words and its evidence files."""
    from orch import reviewer

    prs = [f for f in facts if isinstance(f, dict)]
    if prs:
        kinds = {reviewer.kind_of(str(x.get("path") or "")) for f in prs for x in f.get("files") or []}
        return "screen" if "look" in kinds else "code"
    words, files = _words_of(ticket), _files(ticket)
    if CAMPAIGN_WORDS.search(words):
        return "campaign"
    if any(f.endswith(DATA_EXT) for f in files) or DATA_WORDS.search(words):
        return "data"
    if any(f.endswith(PICTURE) for f in files) or SCREEN_WORDS.search(words):
        return "screen"
    return "other"


# ------------------------------------------------------------------ the points


def _short(text, n: int = 60) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _pictures(ticket: dict) -> tuple[bool, list[str]]:
    """(any picture, the widths 1280/1920/390 that no picture names)."""
    pics = [
        e
        for e in _evidence(ticket)
        if e.get("type") == "file" and str(e.get("ref") or "").lower().endswith(PICTURE)
    ]
    said = " ".join(" ".join(str(e.get(k) or "") for k in ("ref", "title", "summary")) for e in pics)
    return bool(pics), [w for w in WIDTHS if not re.search(rf"(?<!\d){w}(?!\d)", said)]


def _passed_check(ticket: dict) -> bool:
    return any(
        e.get("type") == "command" and type(e.get("exit")) is int and e["exit"] == 0
        for e in _evidence(ticket)
    )


def decide(root: Path, ticket: dict, facts: list[dict | None], sent_back: int = 0) -> dict | None:
    """The Auto Reviewer's verdict on a ticket in Review: None when the ticket is not its to touch (Human
    review
    needed on, a draft), else {"verdict": accept | back | leave | wait, "kind", "points": [...], "why"}."""
    from orch import reviewer

    try:
        ownerpick.refuse_auto(ticket)
    except Refused:
        return None
    if ticket.get("status") != "review":
        return None
    kind = kind_of_work(ticket, facts)
    res = {"kind": kind, "points": []}
    if tickets._open_questions(ticket):
        return {**res, "verdict": "leave", "why": "a question on this ticket waits for your answer."}
    if any(f is None for f in facts):
        return {**res, "verdict": "wait", "why": "GitHub could not be read; looked at again next time."}
    prs = [f for f in facts if isinstance(f, dict)]
    # what the owner keeps, over every pull request before anything else (a security file next to a page is
    # still a security change)
    kinds = {reviewer.kind_of(str(x.get("path") or "")) for f in prs for x in f.get("files") or []}
    if "security" in kinds:
        return {**res, "verdict": "leave", "why": "a security file changed: the security review is yours."}
    if "structure" in kinds:
        return {**res, "verdict": "leave", "why": reviewer.KIND_TEXT["structure"] + ": you look at it."}
    if kind == "other":
        return {**res, "verdict": "leave", "why": "not clear what kind of work this is, so you look at it."}
    points: list[str] = []
    missing: list[str] = []

    def point(name: str, ok: bool, what: str = "") -> None:
        points.append(f"{name}: shown" if ok else f"{name}: missing {what}".rstrip())
        if not ok:
            missing.append(f"{name}: {what}" if what else name)

    proof = tickets.proof_state(ticket, root)
    for c in ticket.get("checklist") or []:
        if not isinstance(c, dict) or c.get("wont_do"):
            continue
        state = proof["per_item"].get(c.get("id"))
        name = f"task '{_short(c.get('text'))}'"
        if not c.get("done"):
            point(name, False, "(not done)")
        elif not c.get("evidence"):
            point(name, False, "(no evidence)")
        elif state == "failed":
            point(name, False, "(its check failed)")
        elif state == "changed":
            point(name, False, "(files changed since its check)")
        else:
            point(name, True)
    if proof["uncovered"]:
        part = proof["uncovered"][0]
        more = f" (and {len(proof['uncovered']) - 1} more)" if len(proof["uncovered"]) > 1 else ""
        return {
            **res,
            "points": points,
            "verdict": "leave",
            "why": f"Done when part '{_short(part, 120)}' has no task{more}; "
            "send it back if that work is missing.",
        }
    for f in prs:
        num = f"pull request #{f.get('number')}"
        made, merged = reviewer._at(ticket.get("created_at")), reviewer._at(f.get("merged_at"))
        if f.get("state") == "CLOSED":
            return {**res, "verdict": "leave", "why": f"{num} was closed without merging."}
        if f.get("state") == "MERGED" and made is not None and (merged is None or merged < made):
            return {**res, "verdict": "leave", "why": f"{num} was merged before this ticket was made."}
        if f.get("state") != "MERGED":
            point(num, False, "(not merged yet)")
        elif not f.get("green"):
            point(num, False, f"(checks not green: {f.get('failed', 0)} of {f.get('checks', 0)} failed)")
        else:
            point(f"{num} merged, checks green", True)
    if kind == "code" and not prs:
        point("a pull request with the code", False, "(none linked)")
    elif kind == "screen":
        any_pic, widths = _pictures(ticket)
        if not any_pic:
            point("pictures of the screen", False, "(none on the ticket)")
        else:
            point(
                "pictures at 1280, 1920 and 390 px wide",
                not widths,
                f"(no picture says {', '.join(widths)} px)",
            )
    elif kind == "campaign":
        material = [e for e in _evidence(ticket) if e.get("type") in ("file", "url")]
        point("the campaign itself on the ticket", bool(material), "(no file or link of it)")
        said = " ".join(
            [
                str(ticket.get("summary") or ""),
                *(str(e.get("summary") or "") for e in _evidence(ticket)),
                *(str(c.get("text") or "") for c in ticket.get("checklist") or [] if isinstance(c, dict)),
            ]
        )
        if WENT_OUT.search(said):
            return {
                **res,
                "points": points,
                "verdict": "leave",
                "why": "it says it went out or is scheduled for people outside: you look at it.",
            }
    elif kind == "data":
        point(
            "a data file or a passing check",
            any(f.endswith(DATA_EXT) for f in _files(ticket)) or _passed_check(ticket),
            "(neither on the ticket)",
        )
    points = points[:POINTS_MAX]
    if missing:
        why = "; ".join(missing[:3]) + (f" (and {len(missing) - 3} more)" if len(missing) > 3 else "")
        if sent_back:
            return {
                **res,
                "points": points,
                "verdict": "leave",
                "why": f"sent back once already and still: {why}.",
            }
        return {**res, "points": points, "verdict": "back", "why": why}
    return {
        **res,
        "points": points,
        "verdict": "accept",
        "why": f"{kind} work, all {len(points)} points shown.",
    }


def points_line(res: dict) -> str:
    return (AUTO_POINTS_LINE.format(kind=res["kind"]) + "; ".join(res.get("points") or []))[:LINE_MAX]


# ------------------------------------------------------------------ acting on it


def act(root: Path, ticket: dict, res: dict) -> dict:
    """Carry out a verdict on exactly the ticket revision that was looked at; the guard runs again inside the
    locked write. Returns the ticket after it. Refused: changed meanwhile, switch turned on, a draft came."""
    tid, rev = ticket["id"], ticket.get("revision")
    word = res["verdict"]
    if word == "accept":
        return tickets.accept_for_owner(root, tid, res["why"], auto=points_line(res), if_revision=rev)
    if word == "back":
        note = (
            f"The Auto Reviewer found work missing ({res['kind']} work): {res['why']}. "
            "Finish it and send the ticket to Review again."
        )
        t = tickets.ask_for_changes(
            root,
            tid,
            note,
            BY,
            guard=_guard,
            if_revision=rev,
            line=AUTO_SENT_BACK_LINE,
            extra=points_line(res),
        )
        from orch import runs_live

        try:  # Busy (no free slot) or a start problem: the ticket waits in line
            runs.start(root, tid, runs_live.AUTOMATION_BY)
        except Exception:  # noqa: BLE001,S110
            pass
        return t
    return tickets.log(root, tid, AUTO_LEFT_LINE + res["why"], BY)


def _guard(ticket: dict) -> None:
    ownerpick.refuse_auto(ticket)


# ------------------------------------------------------------------ Away mode answers


def away_answerable(ticket: dict, q: dict) -> tuple[bool, str]:
    """(True, why) when Away mode may answer this question now, else (False, why it stays with the owner)."""
    if ticket.get("general") is True:
        return False, "a Chat question"
    if ticket.get("status") in ("done", "dropped"):
        return False, "the ticket is finished"
    try:
        ownerpick.refuse_auto(ticket)
    except Refused as e:
        return False, str(e)
    if q.get("answer") is not None or q.get("taken_back") is not None:
        return False, "already settled"
    if q.get(OWNER_ONLY):
        return False, "you took it back from Away mode"
    if q.get("action") is not None:
        return False, "a Merge or action card"
    card = q.get("card")
    if card is not None and (not isinstance(card, dict) or card.get("kind") not in AWAY_CARDS):
        return False, "a card for you to see"
    if q.get("kind") not in (None, "plain"):
        return False, "an add-on's own question"
    opts = q.get("options") or []
    if len(opts) < 2 or q.get("recommended") not in opts:
        return False, "no recommended option"
    bits = [str(q.get("text") or ""), *map(str, opts), str(ticket.get("title") or "")]
    if isinstance(card, dict):
        bits += _strings(
            card
        )  # every word the card shows (headings, options, steps, links), not a chosen few
    bits += _strings(q.get("links"))
    text = unicodedata.normalize("NFKC", " ".join(bits))
    if not PLAIN_TEXT.fullmatch(text) or len(text) > AWAY_TEXT_MAX:
        return False, "not plain short text"
    hits = _away_hits(text)
    if hits:
        return False, "names " + ", ".join(hits)
    if len(LONG_WORD.findall(str(q.get("text") or ""))) < AWAY_MIN_WORDS:
        return False, "too short to say what the yes does"
    # what the yes sets going: the open steps are read too (a short question can stand for a step that
    # sends something out); each step on its own, so a long list does not count against the length rule
    for c in ticket.get("checklist") or []:
        if not isinstance(c, dict) or c.get("done") or c.get("wont_do"):
            continue
        step = unicodedata.normalize("NFKC", str(c.get("text") or ""))
        if not PLAIN_TEXT.fullmatch(step):
            return False, "an open step that is not plain text"
        hits = _away_hits(step)
        if hits:
            return False, "an open step names " + ", ".join(hits)
    return True, AWAY_WHY


def _away_hits(text: str) -> list[str]:
    text = GAPS.sub(" ", text)
    return [k for k, rx in AWAY_RE.items() if rx.search(text) or (k == "money" and MONEY_MARK.search(text))]


def _strings(v, depth: int = 0) -> list[str]:
    if depth > 6:  # too deep to read all of it: a mark that is never plain text, so the question stays
        return ["\x00"]
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [s for x in v.values() for s in _strings(x, depth + 1)]
    if isinstance(v, list):
        return [s for x in v for s in _strings(x, depth + 1)]
    return []


def held(root: Path, ticket: dict) -> bool:
    """The owner undid a Reviewer verdict on this ticket and nothing moved it since: the newest status line is
    the person's own undo (`orch review undo`). No Reviewer, Auto Reviewer or second look touches it then;
    once
    a helper works on it again (a new status), the hold ends by itself."""
    from orch import history

    lines = [h for h in history.lines(root, ticket) if isinstance(h, dict)]
    for i in range(len(lines) - 1, -1, -1):
        if re.fullmatch(r"Status \w+ -> \w+", str(lines[i].get("text") or "")):
            nxt = lines[i + 1] if i + 1 < len(lines) else {}
            return str(nxt.get("text") or "").startswith(UNDONE_LINE) and not str(
                lines[i].get("by")
            ).startswith("agent:")
    return False


def answer_away(root: Path, dry_run: bool = False) -> list[dict]:
    """Every open question on a working ticket: Away mode answers what it may at once. Returns
    [{ticket, key, question, routine, why, answer, done, away}]."""
    out = []
    for t in tickets.list_all(root):
        if t.get("status") in ("done", "dropped"):
            continue
        for q in t.get("questions") or []:
            if q.get("answer") is not None or q.get("taken_back") is not None:
                continue
            ok, why = away_answerable(t, q)
            row = {
                "ticket": t["id"],
                "key": t.get("key") or t["id"],
                "question": q["id"],
                "routine": ok,
                "why": why,
                "answer": q.get("recommended") if ok else None,
                "done": False,
                "away": True,
            }
            if ok and not dry_run:
                try:
                    tickets.answer_for_owner(
                        root, t["id"], q["id"], tickets.question_digest(q), why, away=True
                    )
                    row["done"] = True
                except Refused as e:  # changed under us: look again next pass
                    row["routine"], row["why"], row["answer"] = False, str(e), None
            out.append(row)
    return out


def _away_recheck(ticket: dict, q: dict) -> None:
    """Inside the locked write of an Away answer: the same rules on the fresh ticket."""
    ok, why = away_answerable(ticket, q)
    if not ok:
        raise Refused(f"{q.get('id')} stays with the owner: {why}.")


# ------------------------------------------------------------------ undo (only a person)


def undo(root: Path, tid: str, by: str, question: str | None = None) -> dict:
    """A person undoes what the Reviewer or Away mode did on a ticket: {"ticket", "undone": accept | back |
    answer, "line"}. Also turns Human review needed on (an answer: marks the question as the owner's), so the
    next pass never does it again."""
    if not by.startswith("human:") or tickets.agent_tool():
        raise Refused("Only a person can undo what the Reviewer did.")
    if question:
        t = tickets.undo_reviewer_answer(root, tid, question, by)
        with _quiet():
            runs.pending_add(
                root,
                tid,
                by,
                "event",
                f"The owner undid the answer the Reviewer gave on {question}. It waits for the owner "
                "again: do not act on the old answer; work on what does not depend on it.",
                "reviewer",
            )
        return {"ticket": tid, "key": t.get("key") or tid, "undone": "answer", "question": question}
    t = tickets.load(root, tid)
    if tickets.accepted_by_reviewer(root, t):
        t = tickets.undo_reviewer_accept(root, tid, by)
        return {"ticket": tid, "key": t.get("key") or tid, "undone": "accept"}
    t = _undo_send_back(root, tid, by)
    return {"ticket": tid, "key": t.get("key") or tid, "undone": "back"}


class _quiet:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return exc[0] is not None and issubclass(exc[0], (Refused, OSError, ValueError))


def _undo_send_back(root: Path, tid: str, by: str) -> dict:
    """The Reviewer sent the ticket back and no helper took it yet: its task and its queued note go, the
    ticket
    is in Review again with Human review needed on."""
    t = tickets.load(root, tid)
    item = next(
        (
            c
            for c in reversed(t.get("checklist") or [])
            if isinstance(c, dict) and str(c.get("text") or "").startswith(REVIEWER_TASKS)
        ),
        None,
    )
    if item is None or item.get("done") or t.get("status") not in ("ready", "open"):
        raise Refused("There is nothing of the Reviewer's to undo on this ticket.")
    with runs.locked(root, tid):  # a run that starts meanwhile takes this lock too: checked inside it
        rec = runs.read(root, tid)
        if rec and runs.state(rec) != "dead":
            raise Refused(
                "A helper already works on what the Reviewer asked. Send it a note on the ticket instead."
            )
        items = runs._pending_read(root, tid)  # noqa: SLF001 - the one reader, inside its own lock
        mine = [
            i for i in items if i.get("by") == BY and i.get("kind") == "event" and not i.get("delivered_at")
        ]
        if not mine:
            raise Refused(
                "The helper already read what the Reviewer asked. Send it a note on the ticket instead."
            )
        # the ticket first, still inside the run lock (no helper can start in between); a refusal keeps the
        # note
        after = tickets.undo_reviewer_send_back(root, tid, item["id"], by)
        keep = [i for i in items if i not in mine]
        runs._pending_write(root, tid, keep)  # noqa: SLF001
        if rec is not None and rec.get("pending") and not any(not i.get("delivered_at") for i in keep):
            rec["pending"] = False
            runs._write(root, rec)  # noqa: SLF001
    return after

"""`orch review`: the Review stack from a terminal. A helper puts a card in with `orch ask
--draft/--choose/...` (ask_card below) and waits for the answer (`wait`); a person answers
(`answer`) as the person chosen in orch. No subcommand starts the page."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from orch import ghmerge, history, nextstep, review, review_server, runs_live, safefile, tickets
from orch.errors import Refused

SUBS = ("list", "answer", "wait", "link")
CARD_KINDS = ("draft", "link", "plan", "choose")
SUGGEST_VERDICTS = ("ok", "no")
LINKS_MAX = 5  # what a card without options can suggest: approve or don't do
KEY_RE = re.compile(r"review|q[0-9]+")


class ReviewError(Refused):
    """A refusal with a contract error code (`{"error", "code"}`, exit 2)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.extra = {"code": code}


def add_parsers(sub, common) -> None:
    r = sub.add_parser(
        "review", parents=[common], help="the page where you answer what waits for you (list, answer, link)"
    )
    r.add_argument(
        "--port", type=int, default=review_server.DEFAULT_PORT, help="the page's port (default 8432)"
    )
    r.add_argument("--until", metavar="HH:MM", help="stop the page at this time of day (default 23:59)")
    r.add_argument("--no-open", action="store_true", help="do not open the browser")
    s = r.add_subparsers(dest="sub", metavar="<command>")
    x = s.add_parser("list", parents=[common], help="what waits for an answer (or --answered)")
    x.add_argument("--answered", action="store_true", help="the answers already given, newest first")

    x = s.add_parser("answer", parents=[common], help="answer one card")
    x.add_argument("ticket")
    x.add_argument("key", help="the question (q3) or 'review' for a ticket in Review")
    x.add_argument("--verdict", required=True, choices=review.VERDICTS, help="ok, no or talk (with a note)")
    x.add_argument("--picked", metavar="ID")
    x.add_argument("--note", metavar="JSON", help="changes, words, pins (JSON, at most 8 KB)")
    x.add_argument("--digest", metavar="D", help="the card as it was shown")
    x.add_argument("--via", default="cli", metavar="WORD")

    x = s.add_parser("wait", parents=[common], help="wait until a card is answered")
    x.add_argument("ticket")
    x.add_argument("question", nargs="?", help="the question (default: the latest card)")
    x.add_argument("--timeout", type=int, default=600, metavar="SECONDS")
    s.add_parser("link", parents=[common], help="the address of the review page")


def _ticket(root: Path, args) -> dict:
    try:
        return tickets.load(root, tickets.resolve_cli(root, args.ticket, json_output=args.json))
    except Refused as e:
        raise ReviewError("not_found", str(e)) from None


def _guard(fn, *a, **kw):
    """Plain Refused from the core becomes code `refused`."""
    try:
        return fn(*a, **kw)
    except ReviewError:
        raise
    except Refused as e:
        if getattr(e, "extra", None):
            raise
        raise ReviewError("refused", str(e)) from None


def _out(args, data, text: str) -> None:
    if args.json:
        data = history.shown_json(history.args_root(args), data)
    nextstep.remember(args, data)
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def _when(at) -> str:
    return review._when(at)


# ------------------------------------------------------------------ cards for `orch ask`


def _file_preview(root: Path, src: str, where: str) -> dict:
    ext = Path(src).suffix.lower()
    kind = review.FILE_TYPES.get(ext)
    if kind in ("img", "page"):
        return {"type": kind, "src": src}
    if ext in (".md", ".txt"):
        data = safefile.open_file_ref(root, src, 64 * 1024) if not src.startswith("artifacts/") else None
        if data is None:
            raise Refused(f"{where}: '{src}' was not found or is too large for a text card.")
        text = data.decode("utf-8", "replace")
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()][:50]
        return {"type": "doc", "heading": Path(src).name, "paras": [p[:2000] for p in paras]}
    raise Refused(f"{where}: show an image, a page (.html) or a text file (.md, .txt).")


def _option(root: Path, spec: str) -> dict:
    ident, eq, rest = spec.partition("=")
    if not eq or not ident.strip() or not rest.strip():
        raise Refused(f'An option is "ID=Title" or "ID=Title:file", got "{spec[:40]}".')
    title, _, tail = rest.rpartition(":")
    if title and Path(tail).suffix.lower() in review.FILE_TYPES and " " not in tail.strip():
        out = {
            "id": ident.strip(),
            "title": title.strip(),
            "preview": _file_preview(root, tail.strip(), "option"),
        }
    else:
        out = {"id": ident.strip(), "title": rest.strip()}
    return out


def _describe(specs: list[str], ids: list[str]) -> dict[str, str]:
    """--describe "A=text": a description under one option."""
    out: dict[str, str] = {}
    for spec in specs:
        ident, eq, text = spec.partition("=")
        ident, text = ident.strip(), " ".join(text.split())
        if not eq or ident not in ids or not text:
            raise Refused(f'--describe is "ID=Text" with one of the option ids, got "{spec[:40]}".')
        if len(text) > 500:
            raise Refused("An option description is at most 500 characters.")
        out[ident] = text
    return out


def links_of(specs: list[str]) -> list[dict] | None:
    """--ref "Label=https://...": links shown beside the card (a mockup, a reference). At most 5."""
    if not specs:
        return None
    if len(specs) > LINKS_MAX:
        raise Refused(f"A card takes at most {LINKS_MAX} --ref links.")
    out = []
    for spec in specs:
        label, eq, url = spec.partition("=")
        label, url = " ".join(label.split()), url.strip()
        if not eq or not label or len(label) > 60 or not review.is_plain_url(url):
            raise Refused(f'--ref is "Label=https://address" (label up to 60 characters), got "{spec[:40]}".')
        out.append({"label": label, "url": url})
    return out


def build_card(root: Path, args) -> tuple[dict, list[str], str | None, str]:
    kind, title = next((k, getattr(args, k)) for k in CARD_KINDS if getattr(args, k, None) is not None)
    kind = "choice" if kind == "choose" else kind
    card: dict = {"kind": kind, "title": title, "then": args.then}
    for k, v in (("why", args.why), ("need", args.need), ("ok_label", args.ok), ("open", args.open)):
        if v:
            card[k] = v
    options: list[str] = []
    if kind == "choice":
        opts = [_option(root, o) for o in args.option]
        if len(opts) < 2:
            raise Refused('A choice needs at least two --option "ID=Title[:file]".')
        if args.after or args.file:
            raise Refused("A choice shows its options; add how it is today with --before FILE.")
        about = _describe(getattr(args, "describe", None) or [], [o["id"] for o in opts])
        for o in opts:
            if o["id"] in about:
                o["text"] = about[o["id"]]
        card["preview"] = {"type": "options", "options": opts}
        if args.before:  # how it is today, beside the options (the person compares, then picks one)
            card["preview"]["before"] = _file_preview(root, args.before, "before")
        options = [o["id"] for o in opts]
    elif args.option:
        raise Refused("A card takes --option only with --choose.")
    elif getattr(args, "describe", None):
        raise Refused("--describe goes with the options of --choose.")
    elif bool(args.before) != bool(args.after):
        raise Refused("--before and --after go together.")
    elif args.before and args.file:
        raise Refused("Use --before/--after or --file, not both.")
    elif args.before:
        card["preview"] = {
            "type": "compare",
            "before": _file_preview(root, args.before, "before"),
            "after": _file_preview(root, args.after, "after"),
        }
    elif args.file:
        card["preview"] = _file_preview(root, args.file, "file")
    elif kind == "link":
        if not args.open:
            raise Refused("A link card needs --open URL (or --file).")
        card["preview"] = {"type": "doc", "heading": "Link", "paras": [args.open]}
    if getattr(args, "merge", False):
        if kind != "link" or not ghmerge.is_pr_url(args.open):
            raise Refused(
                "--merge goes with --link and --open <GitHub pull request address>, "
                "e.g. --open https://github.com/owner/repo/pull/12."
            )
        head = args.merge_head = ghmerge.head_of(args.open)  # the click merges exactly this commit
        card["preview"] = {
            "type": "doc",
            "heading": "Pull request",
            "paras": [args.open, f"Commit {head[:7]}"],
        }
        card["ok_label"] = "Merge"  # the button says what the click does (review.merge_url checks it)
        card.setdefault("why", "Your click merges it on GitHub with your own GitHub login.")
    if args.suggest is not None and kind == "choice" and args.suggest not in options:
        raise Refused("--suggest must be one of the --option ids.")
    if args.suggest is not None and kind != "choice" and args.suggest not in SUGGEST_VERDICTS:
        raise Refused("On this card --suggest is ok (approve) or no (don't do).")
    return card, options, args.suggest, title


def has_card_flags(args) -> bool:
    return any(getattr(args, k, None) is not None for k in CARD_KINDS)


def ask_card(args, root: Path, tid: str, by: str) -> tuple[dict, dict]:
    """`orch ask TICKET TEXT --draft|--link|--plan|--choose TITLE ...`: the question with a card on it."""
    if not args.then:
        raise Refused("A card needs --then: what happens after the answer.")
    card, options, suggest, _title = _guard(build_card, root, args)
    links = _guard(links_of, getattr(args, "ref", None) or [])
    card, shown = _guard(review.prepare_card, root, tid, card)
    action = None
    if getattr(args, "merge", False):
        action = json.dumps({"merge": args.open, "head": args.merge_head})
    return _guard(
        tickets.ask,
        root,
        tid,
        args.text,
        options,
        suggest or args.recommend,
        by,
        action=action,
        card=card,
        shown=shown,
        group=getattr(args, "group", None),
        links=links,
    )


# ------------------------------------------------------------------ list


def _answered(root: Path) -> list[dict]:
    out = []
    for t in history.shown_json(root, tickets.list_all(root)):
        if t.get("general") is True or not isinstance(t.get("id"), str):
            continue
        for q in t.get("questions") or []:
            if q.get("answer") is None or not isinstance(q.get("decision"), dict):
                continue
            out.append(
                {
                    "id": f"core:q:{t['id']}:{q['id']}",
                    "ticket": t["id"],
                    "ticket_key": t.get("key"),
                    "key": q["id"],
                    "by": q.get("answered_by"),
                    "via": q.get("via"),
                    "at": q.get("at"),
                    "card": q.get("card") or {},
                    "shown": q.get("shown"),
                    "decision": q["decision"],
                }
            )
    out.sort(key=lambda e: (e["at"] or "", e["id"]), reverse=True)
    return out


def _list(args, root: Path) -> None:
    if args.answered:
        rows = _answered(root)
        lines = [
            f"  {e['ticket_key'] or e['ticket']}  {e['key']}  {e['decision'].get('summary', '')}"
            f"  ({re.sub(r'^(human|agent):', '', e['by'] or 'someone')}, {e['via']}, {_when(e['at'])})"
            for e in rows
        ]
        _out(args, rows, "\n".join(["Answered (newest first)", *lines]) if rows else "Nothing answered yet.")
        return
    cards = review.stack(root)
    n = len(cards)
    lines = [
        f"  {c['ticket_key'] or c['ticket']}  {c['key']}  [{c['kind']}]  {c['card'].get('title', '')}"
        for c in cards
    ]
    text = (
        "\n".join([f"{n} thing{'' if n == 1 else 's'} wait{'s' if n == 1 else ''} on you.", *lines])
        if cards
        else "Nothing waits for you."
    )
    _out(args, {"workspace": root.name, "cards": cards}, text)


# ------------------------------------------------------------------ answer


def _answer(args, root: Path) -> None:
    t = _ticket(root, args)
    tid, key = t["id"], args.key
    if not KEY_RE.fullmatch(key):
        raise ReviewError("not_found", f"'{key[:20]}' is not a question of {tid}. Use q3 or review.")
    if args.note is not None and len(args.note.encode("utf-8")) > review.MAX_NOTE_BYTES:
        raise ReviewError("too_large", "A note is at most 8 KB.")
    if key == "review":
        q = None
        current = review.check_digest(t)
    else:
        q = next((x for x in t.get("questions") or [] if x.get("id") == key), None)
        if q is None:
            raise ReviewError("not_found", f"{tid} has no question {key}.")
        _guard(tickets.refuse_if_taken_back, q)  # said first, before anything is asked of the person
        current = tickets.question_digest(q)
    given = args.digest
    if given is not None and not re.fullmatch(r"[0-9a-f]{64}", given):
        raise ReviewError("changed", "This card changed or can't be checked. Look at it again.")
    if given is not None and given != current:
        raise ReviewError("changed", f"{key} changed after it was shown. Look at it again, then answer.")
    if tickets.agent_tool() or (args.by or "").startswith(
        "agent:"
    ):  # an answer on a card is a person's, never an agent's (a label check)
        raise ReviewError("needs_person", review_server.AGENT_REFUSED)
    who = tickets.current_actor(
        args.by
    )  # the person chosen in orch (--by human:<name>), else the computer's user
    digest = given or current
    fn = review.change if q is not None and q.get("answer") is not None else review.decide
    entry = _guard(
        fn, root, tid, key, args.verdict, args.picked, args.note, by=who, via=args.via, digest=digest
    )
    import contextlib

    with contextlib.suppress(Refused):  # saved; a busy run only delays it reaching the agent
        runs_live.pass_answer(root, tid, entry, who)
    _out(args, entry, f"Answered {entry['id']}: {entry.get('answer')}")


# ------------------------------------------------------------------ show, wait, link


def _wait(args, root: Path) -> None:
    t = _ticket(root, args)
    tid = t["id"]
    qs = t.get("questions") or []
    if args.question:
        q0 = next((x for x in qs if x.get("id") == args.question), None)
    else:
        q0 = next((x for x in reversed(qs) if isinstance(x.get("card"), dict)), None)
    if q0 is None:
        raise ReviewError("not_found", f"{t.get('key') or tid} has no such card to wait for.")
    end = time.monotonic() + max(args.timeout, 0)
    while True:
        q = next(
            x for x in history.shown_ticket(root, tickets.load(root, tid))["questions"] if x["id"] == q0["id"]
        )
        if q.get("answer") is not None:
            break
        if time.monotonic() >= end:
            raise ReviewError("busy", f"No answer yet on {q0['id']}. Try again later.")
        time.sleep(1)
    who = re.sub(r"^human:", "", q.get("answered_by") or "someone")
    _out(args, q, f"{q['answer']} ({who}, {q.get('via')}, {_when(q.get('at'))})")


def _link(args, root: Path) -> None:
    now = review_server.running(root)
    if now:
        data = {"running": True, "url": now["url"], "until": now["until"], "tunnel": now["tunnel"]}
        text = (
            f"The review page runs: {now['url']}   until {now['until']}\n"
            f"On a server? From your laptop: {now['tunnel']}"
        )
        _out(args, data, text)
        return
    data = {"running": False, "url": None, "until": None, "tunnel": None}
    _out(args, data, "No review page runs. Start it in your terminal: orch review")


def dispatch(args, root: Path) -> bool:
    if args.cmd != "review":
        return False
    if args.sub is None:
        rc = review_server.serve(args)
        if rc:
            raise SystemExit(rc)
        return True
    {"list": _list, "answer": _answer, "wait": _wait, "link": _link}[args.sub](args, root)
    return True

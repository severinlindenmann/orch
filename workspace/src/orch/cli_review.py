"""`orch review`: the Review stack from a terminal. A helper puts a card in with `orch ask
--draft/--choose/...` (ask_card below) and waits for the answer (`wait`); a person answers
(`answer`) as the person chosen in orch. No subcommand starts the page."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from orch import (
    attention,
    cardkinds,
    dashshots,
    ghmerge,
    history,
    nextstep,
    ownerpick,
    review,
    review_server,
    runs_live,
    safefile,
    tickets,
)
from orch.errors import Refused

SUBS = ("list", "answer", "wait", "link", "tend", "tend-releases", "accepted", "verdict", "security", "undo")
CARD_KINDS = ("draft", "link", "plan", "choose", "run")
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
    x.add_argument(
        "--group",
        choices=("quick", "short", "time"),
        help="only Quick look, Short decision or Take your time",
    )
    x.add_argument(
        "--week",
        action="store_true",
        help="this week's undos, work sent back after an accept and missed deadlines",
    )

    x = s.add_parser("answer", parents=[common], help="answer one card")
    x.add_argument("ticket")
    x.add_argument("key", help="the question (q3) or 'review' for a ticket in Review")
    x.add_argument("--verdict", required=True, choices=review.VERDICTS, help="ok, no or talk (with a note)")
    x.add_argument("--picked", metavar="ID")
    x.add_argument("--note", metavar="JSON", help="changes, words, pins (JSON, at most 8 KB)")
    x.add_argument("--digest", metavar="D", help="the card as it was shown")
    x.add_argument("--via", default="cli", metavar="WORD")

    x = s.add_parser("run", parents=[common], help="run a run card's command (the signed-in person's click)")
    x.add_argument("ticket")
    x.add_argument("key", help="the question (q3)")
    x.add_argument("--digest", metavar="D", required=True, help="the card as it was shown")
    x.add_argument("--confirmed", action="store_true", help="the person confirmed a command not orch's")
    x.add_argument("--via", default="cli", metavar="WORD", help="where the click comes from")

    # ORCH-865: what the terminal window Run it now opened runs (its one-time code is in ORCH_SIGNIN)
    x = s.add_parser("signin", parents=[common], help=argparse.SUPPRESS)
    x.add_argument("ticket")
    x.add_argument("key")

    x = s.add_parser("wait", parents=[common], help="wait until a card is answered")
    x.add_argument("ticket")
    x.add_argument("question", nargs="?", help="the question (default: the latest card)")
    x.add_argument("--timeout", type=int, default=600, metavar="SECONDS")
    s.add_parser("link", parents=[common], help="the address of the review page")
    x = s.add_parser(
        "tend", parents=[common], help="the Reviewer's pass: accept small finished work for the owner"
    )
    x.add_argument("--dry-run", action="store_true", help="only say what it would do")
    x = s.add_parser(
        "tend-releases",
        parents=[common],
        help="merge green release cards for the owner when Settings allow it (workflow.release_merge)",
    )
    x.add_argument("--dry-run", action="store_true", help="only say what it would do")
    x = s.add_parser(
        "verdict",
        parents=[common],
        help="the Reviewer's second look decides one ticket (accept, back, leave)",
    )
    x.add_argument("ticket")
    x.add_argument("word", choices=("accept", "back", "leave"), help="accept, back or leave")
    x.add_argument("why", help="one line why")
    x.add_argument(
        "--point", action="append", default=[], metavar="TEXT", help="one point and what you saw (repeat)"
    )
    x = s.add_parser(
        "security",
        parents=[common],
        help="the security review of one pull request records its verdict (ok or problems), or the pull "
        "request that fixes its finding (fixed-by)",
    )
    x.add_argument("pr", type=int, help="the pull request number")
    x.add_argument(
        "word",
        choices=("ok", "problems", "fixed-by"),
        help="ok: nothing High or Medium left; else problems; fixed-by <M>: pull request M fixes the finding",
    )
    x.add_argument(
        "why", help="one line: the worst finding, or what was checked; for fixed-by the fix's number"
    )
    x.add_argument(
        "--sha", metavar="COMMIT", help="the commit you reviewed (from the brief); needed for ok and problems"
    )
    x = s.add_parser(
        "undo", parents=[common], help="undo what the Reviewer, Auto Reviewer or Away mode did on a ticket"
    )
    x.add_argument("ticket")
    x.add_argument("question", nargs="?", help="an answer to undo (q3); without it the accept or send-back")
    x = s.add_parser("accepted", parents=[common], help="what the Reviewer accepted for you")
    x.add_argument(
        "--since", default="today", metavar="WHEN", help="today (default), yesterday or YYYY-MM-DD"
    )
    x.add_argument("--phone", action="store_true", help=argparse.SUPPRESS)  # relay add-on, see its skill


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


TEXT_MAX = 64 * 1024  # a text or glance card shows at most this much of its file


def _read_small(root: Path, tid: str | None, src: str, where: str = "file") -> bytes:
    """A text or card file for a card, at most 64 KB: artifacts/<name> is the ticket's own file (as images
    and pages are), anything else a file in the workspace. The path `orch ticket artifacts-dir` prints
    (.orch/tickets/<this ticket>/artifacts/<name>, also with backslashes) counts as artifacts/<name>
    (ORCH-1777); any other .orch or .git path is refused. Each refusal names its cause and the next step."""
    path = src.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    own = f".orch/tickets/{tid}/artifacts/" if tid else None
    if own and path.startswith(own) and len(path) > len(own):
        path = "artifacts/" + path[len(own) :]
    shown = src[:120]
    parts = safefile._parts(path)
    if parts is None:
        raise Refused(
            f"{where}: '{shown}' is not a plain path inside the workspace; "
            "give it like docs/x.md or artifacts/<name>."
        )
    inside = next(
        (p.rstrip(". ").lower() for p in parts if p.rstrip(". ").lower() in (".orch", ".git")), None
    )
    if inside:
        raise Refused(
            f"{where}: '{shown}' is inside a {inside} folder a card does not read; "
            "give a file of this ticket as artifacts/<name>."
        )
    try:
        if parts[0] == "artifacts" and len(parts) > 1:
            if tid is None:
                raise Refused(f"{where}: artifacts/<name> needs a ticket; give the ticket id to `orch ask`.")
            checked = f".orch/tickets/{tid}/{path}"
            data = safefile.read_ticket_file(root, tid, "artifacts", "/".join(parts[1:]), TEXT_MAX)
        else:
            checked = path
            data = safefile.open_file_ref(root, path, TEXT_MAX)
    except safefile.TooLarge:
        raise Refused(
            f"{where}: '{shown}' is over the {TEXT_MAX // 1024} KB limit for a text card; "
            "shorten it or show it as a page (.html)."
        ) from None
    if data is None:
        raise Refused(
            f"{where}: '{shown}' was not found (checked {checked}); "
            f"put the file there or check the name with `orch ticket artifacts-dir {tid or '<ticket>'}`."
        )
    return data


def _file_preview(root: Path, src: str, where: str, tid: str | None = None) -> dict:
    ext = Path(src).suffix.lower()
    kind = review.FILE_TYPES.get(ext)
    if kind in ("img", "page"):
        return {"type": kind, "src": src}
    if ext in (".md", ".txt"):
        data = _read_small(root, tid, src, where)
        text = data.decode("utf-8", "replace")
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()][:50]
        return {
            "type": "doc",
            "heading": re.split(r"[\\/]", src.strip())[-1],
            "paras": [p[:2000] for p in paras],
        }
    if ext == ".json":  # a glance card (ORCH-329): headline, progress, chips, flow, chart, diff, details
        data = _read_small(root, tid, src, where)
        try:
            pv = json.loads(data.decode("utf-8"))
        except ValueError:
            pv = None
        if not isinstance(pv, dict):
            raise Refused(f"{where}: '{src}' is not a JSON object; a card file holds one {{...}} object.")
        return {"type": "doc", **pv}
    raise Refused(f"{where}: show an image, a page (.html), a text file (.md, .txt) or a card (.json).")


def _option(root: Path, spec: str, tid: str | None = None) -> dict:
    ident, eq, rest = spec.partition("=")
    if not eq or not ident.strip() or not rest.strip():
        raise Refused(f'An option is "ID=Title" or "ID=Title:file", got "{spec[:40]}".')
    title, _, tail = rest.rpartition(":")
    if title and Path(tail).suffix.lower() in review.FILE_TYPES and " " not in tail.strip():
        out = {
            "id": ident.strip(),
            "title": title.strip(),
            "preview": _file_preview(root, tail.strip(), "option", tid),
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


def build_run_card(root: Path, args) -> tuple[dict, list[str], str | None, str]:
    """`orch ask TICKET TEXT --run "<command>" [--changes L] [--undo L] [--login] [--option "Leave it off"]`
    (ORCH-848): the person runs the command with one click. The question text is the card's title."""
    from orch import runcard

    for flag in ("after", "file", "before", "open", "ci_shots", "ok"):
        if getattr(args, flag, None):
            raise Refused("A run card shows its command; it takes no files, address or --ok.")
    if getattr(args, "merge", False) or getattr(args, "describe", None):
        raise Refused("A run card takes no --merge or --describe.")
    spec = runcard.parse(root, args.run, getattr(args, "changes", None), getattr(args, "undo", None),
                         login=bool(getattr(args, "login", False)))  # fmt: skip
    if len(args.option) > 1:
        raise Refused('A run card has one other answer besides I ran it: --option "Leave it off for now".')
    given = " ".join((args.option[0] if args.option else "Not now").split()).casefold()
    no_label = next((x for x in runcard.NO_LABELS if x.casefold() == given), None)
    if no_label is None:
        raise Refused("The other answer is one of: " + ", ".join(runcard.NO_LABELS) + ".")
    if args.suggest is not None and args.suggest not in SUGGEST_VERDICTS:
        raise Refused("On this card --suggest is ok (run it) or no (the other answer).")
    title = args.text.strip().splitlines()[0][:200] if args.text.strip() else "Run this command"
    card = {"kind": "run", "title": title, "then": args.then or "The helper goes on once it ran.",
            "ok_label": runcard.OK_LABEL, "no_label": no_label, "run": spec}  # fmt: skip
    if args.why:
        card["why"] = args.why
    return card, [no_label], args.suggest, title


def build_card(root: Path, args, tid: str | None = None) -> tuple[dict, list[str], str | None, str]:
    if getattr(args, "run", None) is not None:
        return build_run_card(root, args)
    kind, title = next((k, getattr(args, k)) for k in CARD_KINDS if getattr(args, k, None) is not None)
    kind = "choice" if kind == "choose" else kind
    card: dict = {"kind": kind, "title": title, "then": args.then}
    for k, v in (("why", args.why), ("need", args.need), ("ok_label", args.ok), ("open", args.open)):
        if v:
            card[k] = v
    options: list[str] = []
    if kind == "choice":
        opts = [_option(root, o, tid) for o in args.option]
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
            card["preview"]["before"] = _file_preview(root, args.before, "before", tid)
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
            "before": _file_preview(root, args.before, "before", tid),
            "after": _file_preview(root, args.after, "after", tid),
        }
    elif args.file:
        card["preview"] = _file_preview(root, args.file, "file", tid)
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
        # what the person decides on, read for the pinned commit; never a helper's own file in its place
        wf = args.merge_workflow = ghmerge.workflow_check(args.open, head)  # ORCH-305: CI workflow files
        card["preview"] = merge_preview(root, args.open, head, ghmerge.summary(args.open, head), wf)
        card["ok_label"] = "Merge"  # the button says what the click does (review.merge_url checks it)
        card.setdefault(
            "why",
            (
                "It changes a CI workflow, so GitHub waits for you to approve it: your click approves "
                "this exact version and merges it with your own GitHub login."
                if wf
                else "Your click merges it on GitHub with your own GitHub login."
            )
            + (
                " When you allowed it in Settings, it merges by itself once every check is green."
                if getattr(args, "release", False)
                else ""
            ),
        )
    if args.suggest is not None and kind == "choice" and args.suggest not in options:
        raise Refused("--suggest must be one of the --option ids.")
    if args.suggest is not None and kind != "choice" and args.suggest not in SUGGEST_VERDICTS:
        raise Refused("On this card --suggest is ok (approve) or no (don't do).")
    return card, options, args.suggest, title


def _pr_tickets(root: Path, repo_url: str) -> dict[int, list[str]]:
    """{pull request number: [ticket keys]} for this repository's pull requests the tickets link (shown after
    GitHub's own title, never in its place)."""
    out: dict[int, list[str]] = {}
    for t in tickets.list_all(root):
        name = t.get("key") if isinstance(t.get("key"), str) else ""
        for r in t.get("refs") or []:
            url = r.get("url") if isinstance(r, dict) else None
            if isinstance(url, str) and url.startswith(repo_url + "/pull/") and name:
                tail = url[len(repo_url) + 6 :]
                if tail.isdigit():
                    keys = out.setdefault(int(tail), [])
                    if name not in keys:
                        keys.append(name)
    return out


def _with_workflow(pv: dict, wf: dict | None) -> dict:
    """ORCH-305: a pull request that changes a CI workflow says the check of those lines first (the reason
    the owner is asked) and lists the workflow files before any other row."""
    if not wf:
        return pv
    pv["paras"] = [ghmerge.workflow_words(wf), *(pv.get("paras") or [])]
    # ORCH-429: the label a script check gives, and the changed lines themselves with the risky ones marked
    if wf.get("safe"):
        pv["chips"] = [{"text": "Safe to merge", "tone": "ok"}]
    elif any(x.get("risk") for x in wf.get("lines") or []):
        pv["chips"] = [{"text": "Look at the red lines", "tone": "bad"}]
    if wf.get("lines"):
        pv["diff"] = wf["lines"]
        if wf.get("lines_more"):
            n = wf["lines_more"]
            pv["paras"].append(
                f"And {n} more changed line{'' if n == 1 else 's'}: Workflow changes shows all."
            )
    rows = [{"title": f"{f['name']} (+{f['add']} −{f['del']})"[:200]} for f in wf["files"][:5]]
    if len(wf["files"]) > 5:
        rows.append({"title": f"and {len(wf['files']) - 5} more workflow files"})
    pv["rows"] = rows + (pv.get("rows") or [])
    return pv


def merge_preview(root: Path, url: str, head: str, info: dict | None, wf: dict | None = None) -> dict:
    """A merge card's box (ORCH-183, owner 17 Nov, after a design challenge): the checks as a status line,
    "What goes out · N changes" with one row per pull request (GitHub's title first, its ticket key and
    number beside it), the commits that are no pull request merge, and the exact version as a small footer.
    The address itself is the card's Open link, not its content. Without GitHub's answer only the version.
    `wf` (ghmerge.workflow_check): the CI workflow check goes first (_with_workflow)."""
    foot = f"Exact version: {head[:7]}"
    if not info:
        return _with_workflow({"type": "doc", "heading": "Pull request", "foot": foot}, wf)
    when = datetime.now().strftime("%H:%M")
    tone, words = info["checks"]
    names = _pr_tickets(root, url.rsplit("/pull/", 1)[0])
    rows = []
    for i in info["items"]:
        row = {"title": i["title"] or "Pull request", "n": i["pr"]}
        keys = names.get(i["pr"], [])
        if keys:
            row["key"] = " ".join(keys[:2])[:20]
        rows.append(row)
    if info.get("more"):
        rows.append({"title": f"and {info['more']} more"})
    if rows and info.get("other"):
        n = info["other"]
        rows.append({"title": f"and {n} other commit{'' if n == 1 else 's'}"})
    paras = []
    if tone == "working":
        paras.append("Safer to wait: choose Later and this card stays.")
    elif tone == "failed":
        paras.append("Merging now would put work live that failed a check.")
    if tone != "done":
        paras.append(f"Checked at {when}; it may have changed. Open shows the latest.")
    n = len(info["items"]) + info.get("more", 0)
    pv: dict = {
        "type": "doc",
        "heading": (
            f"What goes out · {n} change{'' if n == 1 else 's'}" if n else info.get("title") or "Pull request"
        )[:200],
        "status": {"tone": tone, "text": f"{words} · checked {when}"},
        "foot": foot,
    }
    if paras:
        pv["paras"] = paras
    if rows:
        pv["rows"] = rows
    return _with_workflow(pv, wf)


def has_card_flags(args) -> bool:
    return any(getattr(args, k, None) is not None for k in CARD_KINDS)


def ask_card(args, root: Path, tid: str, by: str) -> tuple[dict, dict]:
    """`orch ask TICKET TEXT --draft|--link|--plan|--choose TITLE ...`: the question with a card on it."""
    if not args.then and getattr(args, "run", None) is None:
        raise Refused("A card needs --then: what happens after the answer.")
    if getattr(args, "ci_shots", None):  # ORCH-312: the pictures CI took, never the helper's own
        if args.file or args.before or args.after or getattr(args, "choose", None) is not None:
            raise Refused(
                "--ci-shots shows the pictures by itself: leave out --file, --before, --after and --choose."
            )
        if getattr(args, "merge", False):
            raise Refused("--ci-shots goes on its own card, not on a Merge card.")
        args.file = _guard(dashshots.card_file, root, tid, args.ci_shots)
        if not args.open:
            args.open = args.ci_shots
    card, options, suggest, _title = _guard(build_card, root, args, tid)
    links = _guard(links_of, getattr(args, "ref", None) or [])
    if getattr(args, "merge_workflow", None) and len(links or []) < LINKS_MAX:  # ORCH-305: the diff itself
        links = [*(links or []), {"label": "Workflow changes", "url": args.open + "/files"}]
    card, shown = _guard(review.prepare_card, root, tid, card)
    action = None
    if getattr(args, "merge", False):
        act = {"merge": args.open, "head": args.merge_head}
        if getattr(args, "release", False):
            act["release"] = True  # review.tend_releases may merge it for the owner (workflow.release_merge)
        action = json.dumps(act)
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
        if_wait=getattr(args, "if_wait", None),
        facts=getattr(args, "fact", None),
        due=getattr(args, "due", None),
        said=getattr(args, "said", None),
    )


# ------------------------------------------------------------------ list


def _answered_tickets(root: Path, limit: int | None, out: list[dict]):
    """The tickets to look in (as stored; the caller shows them), newest change first. With a limit and the
    ticket index (ORCH-521) the walk
    stops once `limit` answers are found and the next ticket changed before the oldest of them: an answer
    changes its ticket, so no older ticket holds a newer answer (ORCH-522: every ticket was read, 1 s at
    10,000)."""
    rows = None
    if limit is not None:
        try:
            from orch import ticketindex

            rows = ticketindex.rows(root)  # hidden tickets left out, as list_all
        except Exception:  # noqa: BLE001 - no index: every ticket
            rows = None
    if rows is None:
        yield from tickets.list_all(root)
        return
    # an index that counts answers names the tickets that hold one and when the newest was given
    by = "answered_at" if rows and all("answered_at" in r for r in rows) else "updated_at"
    if by == "answered_at":
        rows = [r for r in rows if r.get("answers")]
    for r in sorted(rows, key=lambda r: str(r.get(by) or ""), reverse=True):
        if len(out) >= limit:
            oldest = sorted((e["at"] or "" for e in out), reverse=True)[limit - 1]
            if str(r.get(by) or "") < oldest:
                return
        try:
            t = tickets.load(root, r["id"])
        except Exception:  # noqa: BLE001 - a ticket that cannot be read is left out (as list_all skips it)
            continue
        yield t


def _answered(root: Path, limit: int | None = None) -> list[dict]:
    """Every answered card question, newest first; with `limit` only the newest `limit`."""
    out: list[dict] = []
    for stored in _answered_tickets(root, limit, out):
        t = history.shown_json(root, stored)
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
                    "ticket_title": t.get("title") or "",
                    "text": q.get("text") or "",
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
    return out if limit is None else out[:limit]


def _week(args, root: Path) -> None:
    w = attention.week(root)
    _out(
        args,
        w,
        f"Last 7 days: {w['undos']} taken back, {w['sent_back_later']} sent back after an accept, "
        f"{w['missed_deadlines']} missed deadline{'' if w['missed_deadlines'] == 1 else 's'}.\n"
        "Next: if these grow, answer Quick look cards one at a time: orch review list --group quick",
    )


def _list(args, root: Path) -> None:
    if getattr(args, "week", False):
        return _week(args, root)
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
    group = getattr(args, "group", None)
    if group:  # ORCH-2184: the same groups the Review page's tiles show
        cards = [c for c in cards if (c.get("attention") or {}).get("group") == group]
    n = len(cards)
    lines, lane = [], None
    for c in cards:  # grouped as on the Review page (R2 A): what holds up work first, then by what you do
        ck = c.get("card_kind") or {}
        if ck.get("lane") != lane:
            lane = ck.get("lane")
            lines.append(cardkinds.LANES.get(lane, ""))
        name = ck.get("name") or c["kind"]
        lines.append(
            f"  {c['ticket_key'] or c['ticket']}  {c['key']}  [{name}]  {c['card'].get('title', '')}"
        )
    where = f" in {attention.GROUPS[group]}" if group else ""
    text = (
        "\n".join([f"{n} thing{'' if n == 1 else 's'} wait{'s' if n == 1 else ''} on you{where}.", *lines])
        if cards
        else f"Nothing waits for you{where}."
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
        if (
            t.get("status") != "review"
        ):  # decided elsewhere (the Reviewer, the phone, another tab): say who and when
            raise ReviewError("decided", review.not_in_review(root, t))
        current = review.check_digest(t, root)
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
    who = tickets.acting_by(args)
    if not who.startswith("human:"):
        raise ReviewError("needs_person", review_server.AGENT_REFUSED)
    if q is not None and q.get("answer") is not None and given is not None:
        # ORCH-921: a card the page showed open, answered meanwhile in the terminal, on the phone or in
        # another tab. Its digest still matches (it is what was shown, not whether it was answered): say
        # who answered and when, and change nothing. Changing an answer on purpose works without --digest.
        raise ReviewError("decided", review.answered_elsewhere(root, t, q, who))
    digest = given or current
    # ORCH-582: a draft, or the Check of a ticket that carries one, needs the signed-in dashboard's one-time
    # person grant (a paired phone answers through the relay); never a script or a helper's shell
    granted = ownerpick.person_granted(root, who)  # always used up, so no child inherits it
    needs = ownerpick.is_draft_card(q) if q is not None else ownerpick.carries_draft(t)
    person = needs and granted
    fn = review.change if q is not None and q.get("answer") is not None else review.decide
    entry = _guard(
        fn,
        root,
        tid,
        key,
        args.verdict,
        args.picked,
        args.note,
        by=who,
        via=args.via,
        digest=digest,
        person=person,
    )
    import contextlib

    with contextlib.suppress(Refused):  # saved; a busy run only delays it reaching the agent
        runs_live.pass_answer(root, tid, entry, who, wait=False)
    _out(args, entry, f"Answered {entry['id']}: {entry.get('answer')}")


def _run(args, root: Path) -> None:
    """`orch review run TICKET q3 --digest D [--confirmed] [--via WORD]` (ORCH-848): runs the card's
    command for the signed-in person (the page's one-time grant) and answers it on success."""
    from orch import runcard

    t = _ticket(root, args)
    if not KEY_RE.fullmatch(args.key) or args.key == "review":
        raise ReviewError("not_found", f"'{args.key[:20]}' is not a question of {t['id']}.")
    if not re.fullmatch(r"[0-9a-f]{64}", args.digest or ""):
        raise ReviewError("changed", runcard.CHANGED)
    who = tickets.current_actor(args.by)
    granted = ownerpick.person_granted(root, who)  # always used up, so no child inherits it
    via = args.via if re.fullmatch(r"[a-z][a-z0-9-]{0,19}", args.via or "") else "cli"
    if via == "phone":  # a phone runs it through the relay (relay._apply_run), never this command
        raise ReviewError("needs_person", runcard.PERSON_REFUSAL)
    res = _guard(runcard.run, root, t["id"], args.key, args.digest, by=who, person=granted, via=via,
                 confirmed=args.confirmed)  # fmt: skip
    if res["answered"]:
        import contextlib

        with contextlib.suppress(Refused, KeyError):
            q = next(x for x in tickets.load(root, t["id"])["questions"] if x["id"] == args.key)
            entry = {"id": args.key, "answer": q.get("answer"), "decision": q.get("decision")}
            runs_live.pass_answer(root, t["id"], entry, who, wait=False)
    words = res.get("error") or res["output"][-300:]
    _out(args, res, ("Ran it: " if res["ok"] else "It did not work: ") + words)
    if not res["ok"]:
        args._exit = 1  # it ran and failed: the card stays open (2 = refused, nothing ran)


def _signin(args, root: Path) -> None:
    """`orch review signin TICKET q3` (ORCH-865), only in the terminal window a sign-in card's Run it now
    opened: starts the sign-in program on this terminal and answers the card once it worked."""
    import select

    from orch import runcard

    t = _ticket(root, args)
    if not KEY_RE.fullmatch(args.key) or args.key == "review":
        raise ReviewError("not_found", f"'{args.key[:20]}' is not a question of {t['id']}.")
    nonce = os.environ.pop("ORCH_SIGNIN", None)  # the program it starts never sees it

    def wait() -> None:  # the window stays until Enter (or 2 minutes), so the person reads how it went
        print("\nPress Enter to close this window.", flush=True)
        with contextlib.suppress(OSError, ValueError):
            select.select([sys.stdin], [], [], 120)

    rc = runcard.signin(root, t["id"], args.key, nonce, say=lambda s: print(s, flush=True), wait=wait)
    args._exit = rc


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


def _tend(args, root: Path) -> None:
    from orch import reviewer

    res = reviewer.run(root, dry_run=args.dry_run)
    _out(args, res, reviewer.text(res, args.dry_run))


def _tend_releases(args, root: Path) -> None:
    res = review.tend_releases(root, dry_run=args.dry_run)
    _out(args, res, review.tend_releases_text(res, args.dry_run))


def _accepted(args, root: Path) -> None:
    from orch import relay, reviewer

    rows = reviewer.accepted(root, reviewer.since_time(args.since))
    picks = ownerpick.waiting_rows(root)  # ORCH-582: drafts waiting for the owner, shown on their own
    word = "today" if args.since == "today" else "since " + args.since  # issue 1920: yesterday AND today
    text = reviewer.accepted_text(rows, word, picks)
    data: dict = {"since": args.since, "accepted": rows, "waiting_pick": picks}
    if args.phone:
        data["sent"] = False
        if rows or picks:  # nothing accepted and no draft waiting: no message
            try:
                relay.send_text(root, "phones", text, general=True)
                data["sent"] = True
            except Refused as e:
                data["not_sent"] = str(e)
        text += "\n" + (
            "Sent to your phones."
            if data["sent"]
            else "Not sent to your phones"
            + (f": {data['not_sent']}" if "not_sent" in data else " (nothing to send).")
        )
    _out(args, data, text)


def _undo(args, root: Path) -> None:
    from orch import autoreview

    who = tickets.acting_by(args)
    if not who.startswith("human:"):
        raise Refused("Only a person can undo what the Reviewer did.")
    tid = _ticket(root, args)["id"]
    q = args.question
    if q is not None and not re.fullmatch(r"q[0-9]{1,4}", q):
        raise Refused("Give the question like q3.")
    res = autoreview.undo(root, tid, who, q)
    said = {
        "accept": "back in Review for you, with “I review the result” on",
        "back": "back in Review for you, with “I review the result” on; the helper's new task is gone",
        "answer": f"{q} waits for your answer again; the helper was told",
    }[res["undone"]]
    _out(args, res, f"{res['key']}: undone: {said}.")


def _verdict(args, root: Path) -> None:
    from orch import lookreview

    tid = _ticket(root, args)["id"]
    res = _guard(lookreview.verdict, root, tid, args.word, args.why, args.point)
    _out(args, res, f"{res['key']}: {lookreview.VERDICT_TEXT[res['verdict']]}: {res['why']}")


def _security(args, root: Path) -> None:
    from orch import secreview

    by = tickets.current_actor(args.by)
    if args.word == "fixed-by":
        fix = str(args.why or "").strip().lstrip("#")
        if not fix.isdigit():
            raise ReviewError(
                "refused", "Give the number of the pull request that fixes it, e.g. fixed-by 1566."
            )
        res = _guard(secreview.link_fix, root, args.pr, int(fix), by)
        _out(
            args,
            res,
            f"Pull request #{res['pr']}: its finding is fixed by #{res['fixed_by']}. The release waits until "
            f"#{res['fixed_by']} is merged with a security OK.",
        )
        return
    res = _guard(secreview.verdict, root, args.pr, args.word, args.why, by, args.sha or "")
    words = "OK: the release may include it" if res["verdict"] == "ok" else "problems: releases wait"
    _out(args, res, f"Pull request #{res['pr']}: security review {words}. {res['line']}")


def dispatch(args, root: Path) -> bool:
    if args.cmd != "review":
        return False
    if args.sub is None:
        rc = review_server.serve(args)
        if rc:
            raise SystemExit(rc)
        return True
    {
        "list": _list,
        "answer": _answer,
        "run": _run,
        "signin": _signin,
        "wait": _wait,
        "link": _link,
        "tend": _tend,
        "tend-releases": _tend_releases,
        "accepted": _accepted,
        "verdict": _verdict,
        "undo": _undo,
        "security": _security,
    }[args.sub](args, root)
    return True

"""`orch report problem|feature "<words>"`: one plain line for a helper to report a problem it met or a
feature wish, the same report the dashboard's dialog makes (`orch diag report`'s own code).

The report is written into `.orch/diag/reports/` here. When this workspace is connected to a relay (and the
relay is turned on) it is also sent to that relay's admin, like the dialog's "Send this report" box, unless
`--no-send`. A send that fails keeps the report here and says why.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orch import diag_report
from orch.errors import Refused


def add_parsers(sub, common) -> None:
    r = sub.add_parser("report", help="report a problem or a feature wish").add_subparsers(
        dest="about", required=True
    )
    for about, hlp, words, why in (
        ("problem", "something in orch went wrong", "what happened", "what you expected instead"),
        ("feature", "a feature you wish orch had", "what you want", "why it would help"),
    ):
        x = r.add_parser(about, parents=[common], help=hlp)
        x.add_argument("text", help=f"{words}, in plain words (up to 600 characters)")
        x.add_argument("--why" if about == "feature" else "--expected", dest="expected", help=why)
        x.add_argument("--more", help="further details, up to 4000 characters")
        x.add_argument("--file", action="append", default=[], help="add a picture or file (up to 10 times)")
        x.add_argument("--ticket", help="the ticket it is about")
        x.add_argument(
            "--content",
            action=argparse.BooleanOptionalAction,
            default=about == "problem",
            help="include ticket text and helper excerpts (default: on for a problem, off for a wish)",
        )
        x.add_argument("--no-send", action="store_true", help="keep it on this computer, even with a relay")


def _relay_ready(root: Path) -> bool:
    """The relay is turned on here and this workspace is connected to it (else nothing is sent or said)."""
    from orch import addons, net

    try:
        if "relay" not in addons.active(root):
            return False
        net.load_service(root, "relay")
    except Refused:
        return False
    return True


def report(
    root: Path,
    about: str,
    text: str,
    *,
    expected=None,
    more=None,
    files=(),
    ticket=None,
    content=None,
    send=True,
) -> dict:
    text = str(text or "").strip()
    if not text:
        raise Refused("Say in a few words " + ("what happened." if about == "problem" else "what you want."))
    made = diag_report.make(
        root,
        ticket=ticket,
        note=text[:600],
        expected=(str(expected).strip()[:600] or None) if expected else None,
        more=more,
        files=list(files),
        content=(about == "problem") if content is None else bool(content),
        about=about,
    )
    if not diag_report.is_kept(made["path"]):
        raise Refused(
            f"The report {made['ref']} is NOT kept: it is no longer on this computer. Report again."
        )
    out = {
        "ref": made["ref"],
        "about": about,
        "path": made["path"],
        "problems": made["problems"],
        "kept": True,
    }
    if send and _relay_ready(root):
        from orch import relay_problems

        try:
            got = relay_problems.share(root, made["ref"])
            out["shared"] = {"to": got["to"], "id": got["id"]}
        except Refused as e:
            out["share_error"] = str(e)
    return out


def _text(res: dict) -> str:
    what = "Feature wish" if res["about"] == "feature" else "Problem report"
    lines = [f"{what} {res['ref']} is kept here until it becomes a ticket or you delete it.", res["path"]]
    if res.get("shared"):
        lines.append(f"Sent to the admin of {res['shared']['to']}.")
    elif res.get("share_error"):
        lines.append(
            f"Not sent: {res['share_error']} It is saved here; send it later: "
            f"orch relay problem share {res['ref']}"
        )
    if res["problems"]:
        lines.append("Problems found: " + ", ".join(res["problems"]))
    return "\n".join(lines)


def dispatch(args, root: Path) -> bool:
    if args.cmd != "report":
        return False
    from orch import cli_diag, tickets

    if args.ticket:
        args.ticket = tickets.resolve(root, args.ticket)  # the key (ORCH-81) works too
    cli_diag._check_id(args.ticket, "ticket", tickets._ID_RE)
    res = report(
        root,
        args.about,
        args.text,
        expected=args.expected,
        more=args.more,
        files=cli_diag.read_files(args.file),
        ticket=args.ticket,
        content=args.content,
        send=not args.no_send,
    )
    print(json.dumps(res, ensure_ascii=False) if args.json else _text(res))
    return True

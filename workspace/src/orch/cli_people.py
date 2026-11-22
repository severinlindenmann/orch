"""`orch people`: the workspace's person list (ORCH-1161). Changes are for the owner at this computer only; a
helper's environment is refused. The dashboard's Settings, People runs the same commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orch import history, nextstep, people, tickets
from orch.errors import Refused


def add_parsers(sub, common) -> None:
    # hidden from help: a person sets people up in Settings > People; helpers are refused
    p = sub.add_parser("people", parents=[common], help=argparse.SUPPRESS)
    ps = p.add_subparsers(dest="people_cmd", metavar="<command>")
    ps.add_parser("list", parents=[common], help="show the people and their rights (the default)")
    q = ps.add_parser("on", parents=[common], help="turn the people list on, with you as its owner")
    q.add_argument("--name", help="your name in the list (default: this computer's user name)")
    q = ps.add_parser("add", parents=[common], help="add a person (Write only unless --rights says more)")
    q.add_argument("name")
    q.add_argument("--rights", help="write, decide, start (comma separated)")
    q.add_argument("--expect", type=int, help=argparse_hidden())
    q = ps.add_parser("rename", parents=[common], help="give a person a new name")
    q.add_argument("who", help="the person's id or name")
    q.add_argument("name")
    q.add_argument("--expect", type=int, help=argparse_hidden())
    q = ps.add_parser("rights", parents=[common], help="set a person's rights")
    q.add_argument("who", help="the person's id or name")
    q.add_argument("rights", help="write, decide, start (comma separated); 'none' for no rights")
    q.add_argument("--expect", type=int, help=argparse_hidden())
    q = ps.add_parser("tie", parents=[common], help="tie a paired phone to a person")
    q.add_argument("phone", help="the phone's id (ph_...)")
    q.add_argument("who", help="the person's id or name")
    q.add_argument("--expect", type=int, help=argparse_hidden())
    q = ps.add_parser("cut", parents=[common], help="cut off one phone (a lost phone)")
    q.add_argument("phone", help="the phone's id (ph_...)")
    q.add_argument("--expect", type=int, help=argparse_hidden())
    q = ps.add_parser("may-start", parents=[common], help=argparse_hidden())
    q.add_argument("ticket")
    q = ps.add_parser("remove", parents=[common], help="remove a person (old history keeps their name)")
    q.add_argument("who", help="the person's id or name")
    q.add_argument("--expect", type=int, help=argparse_hidden())


def argparse_hidden():
    import argparse

    return argparse.SUPPRESS


def _out(args, data, text: str) -> None:
    if args.json:
        data = history.shown_json(history.args_root(args), data)
    nextstep.remember(args, data)
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def _list_text(v: dict) -> str:
    if v["state"] == "off":
        return "The people list is off: only you work here.\nTurn it on: orch people on"
    if v["state"] == "broken":
        return "The people list is damaged. Move .orch/local/people.json away, then: orch people on"
    rows = []
    for p in v["people"]:
        rights = (
            "owner" if p["owner"] else (", ".join(people.RIGHT_WORDS[r] for r in p["rights"]) or "no rights")
        )
        rows.append(f"  {p['name']}{' (removed)' if p['removed'] else ''}  [{p['id']}]  {rights}")
    names = {p["id"]: p["name"] for p in v["people"]}
    for ph in v.get("phones") or []:
        whose = "cut off" if ph["cut"] else names.get(ph["person"]) or "not tied yet"
        kind, gone = ph.get("kind") or "phone", "" if ph["paired"] else ", not paired"
        rows.append(f"  {kind} {ph['name']}  [{ph['id']}]  {whose}{gone}")
    return "People:\n" + "\n".join(rows)


def _rights(text: str) -> list[str]:
    return [] if text.strip().lower() == "none" else text.split(",")


def _default_name() -> str:
    who = tickets.current_actor()
    return who.split(":", 1)[1]


def dispatch(args, root: Path) -> bool:
    if args.cmd != "people":
        return False
    cmd = getattr(args, "people_cmd", None) or "list"
    expect = getattr(args, "expect", None)
    if cmd == "list":
        v = people.view(root)
        _out(args, v, _list_text(v))
        return True
    if cmd == "on":
        doc = people.turn_on(root, args.name or _default_name())
        o = people.owner(doc)
        _out(args, {"ok": True, **people.view(root)}, f"People list on. Owner: {o['name']} [{o['id']}]")
        return True
    if cmd == "add":
        p = people.add(root, args.name, _rights(args.rights) if args.rights else None, expect=expect)
        _out(args, {"ok": True, "person": p}, f"Added {p['name']} [{p['id']}]")
        return True
    if cmd == "rename":
        p = people.rename(root, args.who, args.name, expect=expect)
        _out(args, {"ok": True, "person": p}, f"Renamed to {p['name']} [{p['id']}]")
        return True
    if cmd == "rights":
        p = people.set_rights(root, args.who, _rights(args.rights), expect=expect)
        words = ", ".join(people.RIGHT_WORDS[r] for r in p["rights"]) or "no rights"
        _out(args, {"ok": True, "person": p}, f"{p['name']}: {words}")
        return True
    if cmd == "remove":
        p = people.remove(root, args.who, expect=expect)
        _out(args, {"ok": True, "person": p}, f"Removed {p['name']}. Old history keeps the name.")
        return True
    if cmd == "tie":
        d = people.tie(root, args.phone, args.who, expect=expect)
        _out(args, {"ok": True, "device": d}, f"Tied {d['id']} to the person [{d['person']}]")
        return True
    if cmd == "cut":
        d = people.cut(root, args.phone, expect=expect)
        _out(args, {"ok": True, "device": d}, f"Cut off {d['id']}. Also remove it on the relay admin page.")
        return True
    if cmd == "may-start":  # the automation host, before the one run for a ticket a phone text made
        ok, why = people.ticket_may_start(root, args.ticket)
        _out(args, {"ok": ok, "why": why}, "yes" if ok else f"no: {why}")
        return True
    raise Refused(f"Unknown: orch people {cmd}")

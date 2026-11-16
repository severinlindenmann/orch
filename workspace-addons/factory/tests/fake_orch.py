"""Small public-CLI fake. Human labels are deliberately preserved for authority tests."""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

root = Path.cwd()
folder = root / "fake-tickets"
folder.mkdir(exist_ok=True)
args = sys.argv[1:]
assert "--json" in args
args.remove("--json")
by = None
if "--by" in args:
    i = args.index("--by")
    by = args[i + 1]
    del args[i : i + 2]
with (root / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps({"args": args, "by": by}) + "\n")


def load(tid):
    return json.loads((folder / (tid + ".json")).read_text())


def save(t):
    (folder / (t["id"] + ".json")).write_text(json.dumps(t))


def stamp():
    return os.environ.get("FACTORY_NOW") or datetime.now(UTC).isoformat().replace("+00:00", "Z")


def flag(name):
    return args[args.index(name) + 1]


if args[:2] == ["ticket", "new"]:
    t = {
        "id": f"t_{len(list(folder.iterdir())) + 1:06d}",
        "title": args[2],
        "revision": 1,
        "ext": {},
        "questions": [],
        "status": "open",
        "parent": flag("--parent") if "--parent" in args else None,
        "history": [],
    }
    # ---- #816 A (ask another workspace): `--ext factory=<json>` is written with the ticket
    if "--ext" in args:
        addon, _, raw = args[args.index("--ext") + 1].partition("=")
        t["ext"][addon] = json.loads(raw)
    note = next((a.split("=", 1)[1] for a in args if a.startswith("--note=")), None)
    if note:
        t["note"] = note
    gate = next((a.split("=", 1)[1] for a in args if a.startswith("--start-requires=")), None)
    if gate:  # core's start gate: "<ticket>:<question>=<answer>"
        g_ticket, rest = gate.split(":", 1)
        g_question, g_answer = rest.split("=", 1)
        t["start_requires"] = {"ticket": g_ticket, "question": g_question, "answer": g_answer}
    save(t)
    result = t
elif args[:2] == ["ticket", "show"]:
    result = load(args[2])
elif args[:2] == ["ticket", "list"]:
    assert args[2:] == ["--all"]
    result = [json.loads(p.read_text()) for p in sorted(folder.iterdir())]
elif args[:2] == ["ext", "set"]:
    t = load(args[2])
    if t["revision"] != int(flag("--if-revision")) or (root / "fail-ext").exists():
        print(json.dumps({"error": "Ticket changed.", "code": "conflict"}))
        sys.exit(2)
    t["ext"][args[3]] = json.loads(args[4])
    t["revision"] += 1
    save(t)
    result = t
# ---- #816 A (ask another workspace): the core commands ask.py uses. Part B appends its own block below.
elif args[:2] == ["secret", "scan"]:
    data = sys.stdin.buffer.read()
    if b"SECRET" in data:
        print(
            json.dumps(
                {
                    "error": "The text has a secret on line 1.",
                    "code": "refused",
                    "found": [{"kind": "k", "line": 1}],
                }
            )
        )
        sys.exit(2)
    result = {"found": []}
elif args[:2] == ["ticket", "summary"]:
    t = load(args[2])
    t["summary"] = args[3]
    save(t)
    result = t
elif args[:2] == ["check", "add"]:
    t = load(args[2])
    t.setdefault("checklist", []).append({"text": args[3], "done": False})
    save(t)
    result = t
elif args[:2] == ["ticket", "attach"]:
    name = args[3].split("=", 1)[1] if args[3].startswith("--name=") else args[3]
    target = root / "fake-attach" / args[2]
    target.mkdir(parents=True, exist_ok=True)
    (target / name).write_bytes(sys.stdin.buffer.read())
    result = {"name": name, "size": 1, "path": f"fake-attach/{args[2]}/{name}"}
elif args[:2] == ["ticket", "status"]:
    t = load(args[2])
    t["status"] = args[3]
    save(t)
    result = t
elif (
    args[:3] == ["relay", "group", "share"] and (root / "groups.json").exists()
):  # the hand-over groups (#816 B)
    name = Path(args[4]).name
    refused = (root / "refuse-share").read_text().split() if (root / "refuse-share").exists() else []
    if name.startswith(".") or name in refused:
        print(
            json.dumps({"error": f"{args[4]} can't be shared (it looks like a secret).", "code": "refused"})
        )
        sys.exit(2)
    with (root / "shares.jsonl").open("a") as stream:
        stream.write(json.dumps({"ticket": args[3], "file": args[4], "click": "--click" in args}) + "\n")
    result = {"group": "grp_" + args[3], "errors": []}
elif args[:3] == ["relay", "group", "add"]:
    if (root / "fail-group").exists():
        print(json.dumps({"error": "Design is no longer connected to you.", "code": "refused"}))
        sys.exit(2)
    result = {"added": True}
elif args[:3] == ["relay", "group", "share"]:
    assert "--click" in args
    if (root / "offline-share").exists():  # the relay can't be reached (blob upload): core's own words
        print(
            json.dumps(
                {
                    "error": "Can't reach relay.test right now. Check your internet and try again.",
                    "code": "refused",
                }
            )
        )
        sys.exit(2)
    if (root / "fail-share-after").exists():  # let N shares through, then a clear refusal
        done = (
            sum(
                1
                for x in (root / "calls.jsonl").read_text().splitlines()
                if json.loads(x)["args"][:3] == args[:3]
            )
            - 1
        )
        if done >= int((root / "fail-share-after").read_text()):
            print(json.dumps({"error": "The relay refused the file.", "code": "refused"}))
            sys.exit(2)
    result = {"group": "g1"}
elif args[:3] == ["relay", "group", "ask"]:
    if (root / "kept-ask").exists():
        print(
            json.dumps(
                {
                    "error": "The question could not be sent now. It is kept and goes out with the next relay command.",
                    "code": "refused",
                }
            )
        )
        sys.exit(2)
    result = {"id": "m1"}
elif args[:2] == ["relay", "outbox"]:
    result = {
        "waiting": json.loads((root / "outbox.json").read_text()) if (root / "outbox.json").exists() else []
    }
# ---- end #816 A
elif args[0] == "ask":
    if (root / "fail-ask").exists():
        print(json.dumps({"error": "Ask unavailable.", "code": "not_available"}))
        sys.exit(2)
    t = load(args[1])
    if "--take-back" in args:  # core's take-back: settled with "Taken back: <reason>", answered by the caller
        q = next(x for x in t["questions"] if x["id"] == flag("--take-back"))
        q.update(answer="Taken back: " + args[2], answered_by=by, taken_back={"by": by, "reason": args[2]})
        t["revision"] += 1
        save(t)
        print(json.dumps(q))
        sys.exit(0)
    options = [args[i + 1] for i, a in enumerate(args) if a == "--option"]
    result = next(
        (
            q
            for q in t["questions"]
            if q["text"] == args[2] and q["options"] == options and q["answer"] is None
        ),
        None,
    )
    if result is None:
        result = {
            "id": f"q{len(t['questions']) + 1}",
            "text": args[2],
            "kind": flag("--kind") if "--kind" in args else None,  # no kind: an information question (#816 A)
            "action": json.loads(flag("--action")) if "--action" in args else None,
            "options": options,
            "answer": None,
            "answered_by": None,
        }
        t["questions"].append(result)
        t["revision"] += 1
        save(t)
elif args[0] == "answer":
    t = load(args[1])
    result = next(q for q in t["questions"] if q["id"] == args[2])
    result.update(answer=args[3], answered_by=by)
    t.setdefault("history", []).append({"at": stamp(), "by": by, "text": f"Answered {args[2]}: {args[3]}"})
    t["revision"] += 1
    save(t)
elif args[0] == "log":
    t = load(args[1])
    t.setdefault("history", []).append({"at": stamp(), "by": by, "text": args[2]})
    t["revision"] += 1
    save(t)
    result = {}
elif args[:2] == ["run", "start"]:
    load(args[2])
    if (root / "fail-run").exists():
        print(json.dumps({"error": "No agent.", "code": "not_available"}))
        sys.exit(2)
    with (root / "runs.jsonl").open("a") as stream:
        stream.write(
            json.dumps({"ticket": args[2], "agent": flag("--agent") if "--agent" in args else None, "by": by})
            + "\n"
        )
    result = {"run": "r1"}
elif args[:2] == ["record", "query"]:  # core's activity record: events per ticket from record.json (tests)
    events = json.loads((root / "record.json").read_text()) if (root / "record.json").exists() else {}
    if (root / "fail-record").exists():
        print(json.dumps({"error": "The record cannot be read.", "code": "not_available"}))
        sys.exit(2)
    result = {"items": events.get(flag("--ticket"), []), "next": None}
elif args[:2] == ["run", "status"]:
    load(args[2])
    live = (root / "live-runs").read_text().split() if (root / "live-runs").exists() else []
    result = {"ticket": args[2], "running": args[2] in live}
    states = json.loads((root / "live-state").read_text()) if (root / "live-state").exists() else {}
    if (
        args[2] in live and args[2] in states
    ):  # a live session and its state (starting, working, idle, attention)
        result["claim"] = {"mode": "live", "live": {"state": states[args[2]]}}
# ---- #816 B: hand-over (relay delegate, group share/say/list, outbox, ticket status). Part A appends its own block. ----
elif args[:2] == ["relay", "delegate"]:
    if (root / "fail-delegate").exists():
        print(json.dumps({"error": "Design is not reachable.", "code": "refused"}))
        sys.exit(2)
    mid = f"m_{len(list(root.glob('delegate-*.json'))) + 1:016d}"
    ticket = flag("--ticket")
    record = {
        "id": mid,
        "ws": args[2],
        "title": args[3],
        "text": flag("--text"),
        "checks": [args[i + 1] for i, a in enumerate(args) if a == "--check"],
        "ticket": ticket,
        "group": "--group" in args,
    }
    (root / f"delegate-{mid}.json").write_text(json.dumps(record))
    if "--group" in args and not (root / "no-group").exists():
        groups = (
            json.loads((root / "groups.json").read_text())
            if (root / "groups.json").exists()
            else {"hosted": []}
        )
        g = next((x for x in groups["hosted"] if x["ticket"] == ticket), None)
        if g is None:
            g = {
                "id": "grp_" + ticket,
                "ticket": ticket,
                "tasks": [],
                "members": [{"ws": "ws_host000001", "host": True}],
            }
            groups["hosted"].append(g)
        g["members"].append({"ws": args[2], "host": False, "left_at": None})
        g["tasks"].append({"delegate": mid, "ws": args[2], "status": "waiting_start", "title": args[3]})
        (root / "groups.json").write_text(json.dumps(groups))
    result = {"id": mid, "sent": True}
elif args[:3] == ["relay", "group", "say"]:
    with (root / "says.jsonl").open("a") as stream:
        stream.write(json.dumps({"ticket": args[3], "text": args[4]}) + "\n")
    result = {}
elif args[:3] == ["relay", "group", "list"]:
    result = (
        json.loads((root / "groups.json").read_text()) if (root / "groups.json").exists() else {"hosted": []}
    )
    result.setdefault("joined", [])
# ---- end of the hand-over block ----
else:
    raise AssertionError(args)
print(json.dumps(result))

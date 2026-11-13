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
elif args[0] == "ask":
    if (root / "fail-ask").exists():
        print(json.dumps({"error": "Ask unavailable.", "code": "not_available"}))
        sys.exit(2)
    t = load(args[1])
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
            "kind": flag("--kind"),
            "action": json.loads(flag("--action")),
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
    with (root / "runs.jsonl").open("a") as stream:
        stream.write(json.dumps({"ticket": args[2], "agent": flag("--agent"), "by": by}) + "\n")
    result = {"run": "r1"}
else:
    raise AssertionError(args)
print(json.dumps(result))

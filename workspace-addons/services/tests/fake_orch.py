"""A small fake of the public orch CLI for `orch services check` (tickets as JSON files in <root>/fake-tickets)."""

import json
import sys
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


def path(ref):
    for p in folder.glob("*.json"):
        t = json.loads(p.read_text())
        if ref in (t["id"], t.get("key")):
            return p
    print(json.dumps({"error": f"Ticket {ref} doesn't exist."}))
    sys.exit(2)


def load(ref):
    return json.loads(path(ref).read_text())


def save(t):
    (folder / (t["id"] + ".json")).write_text(json.dumps(t))


if args[:2] == ["ticket", "list"]:
    result = [json.loads(p.read_text()) for p in sorted(folder.glob("*.json"))]
elif args[:2] == ["ticket", "new"]:
    n = len(list(folder.glob("*.json"))) + 1
    t = {"id": f"t_new{n:03d}", "key": f"ORCH-{900 + n}", "title": args[2], "questions": [], "history": []}
    save(t)
    result = t
elif args[:2] == ["ticket", "show"]:
    result = load(args[2])
elif args[0] == "ask" and "--take-back" in args:
    t = load(args[1])
    qid = args[args.index("--take-back") + 1]
    q = next(q for q in t["questions"] if q["id"] == qid)
    if q["answer"] is not None:
        print(json.dumps({"error": f"{qid} is already answered."}))
        sys.exit(2)
    q["taken_back"] = {"reason": args[2]}
    q["answer"] = "Taken back: " + args[2]
    save(t)
    result = q
elif args[0] == "ask":
    t = load(args[1])
    opts = [args[i + 1] for i, a in enumerate(args) if a == "--option"]
    # as the core: the same open question is not asked twice, the open one comes back
    same = [
        q for q in t["questions"] if q["answer"] is None and q["text"] == args[2] and q["options"] == opts
    ]
    rec = args[args.index("--recommend") + 1] if "--recommend" in args else None
    q = {
        "id": f"q{len(t['questions']) + 1}",
        "text": args[2],
        "options": opts,
        "recommended": rec,
        "answer": None,
    }
    if "--kind" in args:
        q["kind"] = args[args.index("--kind") + 1]
    if same:
        q = same[0]
    else:
        t["questions"].append(q)
        save(t)
    result = q
elif args[0] == "log":
    t = load(args[1])
    t["history"].append({"by": by, "text": args[2]})
    save(t)
    result = t["history"][-1]
else:
    print(json.dumps({"error": f"fake orch does not know {args}"}))
    sys.exit(2)
print(json.dumps(result))

#!/usr/bin/env python3
"""A fake `orch` for add-on tests (contracts/addon-manifest.md, "A fake orch for tests: ORCH_BIN").

Point ORCH_BIN at `workspace/tests/fakes/orch` (the shim next to this file) or run this file directly.
It replays the contract vectors/examples, so add-on code never changes when the real commands arrive:

  record tail [--ticket T|--run R] [--since C|--after C] [--follow] --json   NDJSON lines (activity.md)
  record query [--ticket T] [--run R] [--limit N] [--after C] --json   page, newest first
  record counts [--days N|--from D --to D] --json   orch.counts/1 (with "not seen")
  job start|step|progress|artifact|metric|table|link|log|end ... --json   one orch.job/1 event
  run screen <ticket> --follow --json   orch.screen/1 lines (real capture)
  anything else   exit 2 {"error", "code": "not_available"}

Scenario: env ORCH_FAKE_SCENARIO (or the flag --fake-scenario X, taken out before parsing):
  default  the contract examples
  paged    250 synthetic activity events (several pages of --limit)
  empty    nothing recorded yet (no events, counts "nothing yet", job refuses)
  drop     tail: the stream breaks with an error line after about half of the events (a reconnect with the
           last cursor gets the rest); screen: breaks after 5 lines
  refused  screen: the "Live session is off" refusal
Other env: ORCH_FAKE_FOLLOW_PINGS (pings before a followed stream ends cleanly, default 1; 0 = none),
ORCH_FAKE_STATE (a folder: keeps the job's sequence between calls, else every job call is seq 1),
ORCH_FAKE_CONTRACTS (the contracts folder, default: found relative to this file).
Reads only contract files; writes only into ORCH_FAKE_STATE. Never reads a key, home or workspace.
"""

import copy
import json
import os
import re
import sys
from pathlib import Path

CONTRACTS = Path(os.environ.get("ORCH_FAKE_CONTRACTS") or Path(__file__).resolve().parents[3] / "contracts")
SCENARIOS = ("default", "paged", "empty", "drop", "refused")
CURSOR = re.compile(r"^[A-Za-z0-9._~-]{1,4096}$")
NOW = "2026-11-16T09:30:00Z"


def out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def fail(msg, code="invalid"):
    out({"error": msg, "code": code})
    sys.exit(2)


def load(rel):
    return json.loads((CONTRACTS / rel).read_text())


def take_flags(argv, valued, bools=()):
    """Split argv into (positionals, flags). Unknown --flags are an error; `--` ends flags."""
    pos, flags, i = [], {}, 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            pos += argv[i + 1 :]
            break
        if a.startswith("--"):
            name = a[2:]
            if name in bools:
                flags[name] = True
            elif name in valued:
                if i + 1 >= len(argv):
                    fail(f"The option --{name} needs a value.")
                flags[name] = argv[i + 1]
                i += 1
            else:
                fail(f"Unknown option --{name}.")
        else:
            pos.append(a)
        i += 1
    return pos, flags


def int_flag(flags, name, lo, hi, default=None):
    if name not in flags:
        return default
    try:
        n = int(flags[name])
    except ValueError:
        fail(f"--{name} must be a whole number.")
    if not lo <= n <= hi:
        fail(f"--{name} must be between {lo} and {hi}.")
    return n


# --- data ---
def activity_events(scenario):
    """Chronological (oldest first) orch.activity/1 events."""
    if scenario == "empty":
        return []
    base = sorted((CONTRACTS / "examples" / "activity").glob("valid-*.json"))
    events = [load(f"examples/activity/{f.name}") for f in base]
    if scenario != "paged":
        return events
    tpl = load("examples/activity/valid-step-started.json")
    res = []
    for n in range(1, 251):
        e = copy.deepcopy(tpl)
        e["seq"] = n
        e["id"] = f"toolu_fake{n:04d}"
        e["at"] = f"2026-11-16T{9 + n // 3600:02d}:{n // 60 % 60:02d}:{n % 60:02d}Z"
        e.pop("detail", None)
        res.append(e)
    return res


def cursor_after(i):
    return f"c{i}"


def parse_tail_cursor(c, total):
    m = re.fullmatch(r"c(\d{1,9})", c)
    if not m or int(m.group(1)) > total:
        fail("That position in the record is not valid.")
    return int(m.group(1))


# --- record ---
def filtered(events, flags):
    def keep(e):
        return ("ticket" not in flags or e.get("ticket") == flags["ticket"]) and (
            "run" not in flags or e.get("run") == flags["run"]
        )

    return [(i + 1, e) for i, e in enumerate(events) if keep(e)]


def record_tail(argv, scenario):
    pos, flags = take_flags(argv, {"ticket", "run", "since", "after"}, {"follow", "json"})
    if pos:
        fail("record tail takes no arguments.")
    if "json" not in flags:
        fail("Use --json.")
    events = activity_events(scenario)
    rows = filtered(events, flags)
    since = flags.get("since", flags.get("after"))
    start = 0
    if since == "gone":  # a cursor whose data was pruned: reset, then start over (activity.md)
        out({"type": "reset", "cursor": cursor_after(0), "reason": "pruned"})
    elif since is not None:
        start = parse_tail_cursor(since, len(events))
    rows = [(i, e) for i, e in rows if i > start]
    drop_at = None
    if scenario == "drop" and start < (len(events) + 1) // 2:
        drop_at = (len(events) + 1) // 2  # events 1..drop_at arrive, then the stream breaks
    for i, e in rows:
        if drop_at is not None and i > drop_at:
            break
        out({"type": "event", "cursor": cursor_after(i), "event": e})
    if drop_at is not None:
        out({"type": "error", "error": "The connection to the record was lost.", "code": "busy"})
        sys.exit(2)
    if "follow" in flags:
        last = rows[-1][0] if rows else start
        for _ in range(int(os.environ.get("ORCH_FAKE_FOLLOW_PINGS", "1"))):
            out({"type": "ping", "cursor": cursor_after(last), "at": NOW})


def record_query(argv, scenario):
    pos, flags = take_flags(
        argv, {"ticket", "run", "kind", "from", "to", "limit", "after", "detail"}, {"json"}
    )
    if pos or "detail" in flags:
        fail("This command is not available in the test orch.", "not_available")
    if "json" not in flags:
        fail("Use --json.")
    limit = int_flag(flags, "limit", 1, 500, 100)
    rows = [e for _, e in reversed(filtered(activity_events(scenario), flags))]  # newest first
    off = 0
    if "after" in flags:
        m = re.fullmatch(r"o(\d{1,9})", flags["after"])
        if not m or int(m.group(1)) > len(rows):
            fail("That page position is not valid.")
        off = int(m.group(1))
    nxt = f"o{off + limit}" if off + limit < len(rows) else None
    out({"items": rows[off : off + limit], "next": nxt, "unavailable": []})


def record_counts(argv, scenario):
    pos, flags = take_flags(argv, {"days", "from", "to", "ticket", "kind"}, {"json"})
    if pos:
        fail("record counts takes no arguments.")
    if "json" not in flags:
        fail("Use --json.")
    int_flag(flags, "days", 1, 3650)
    if ("from" in flags) != ("to" in flags) or ("days" in flags and "from" in flags):
        fail("Use --days, or --from with --to.")
    for k in ("from", "to"):
        if k in flags and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", flags[k]):
            fail(f"--{k} must be a day like 2026-11-16.")
    answer = load(
        "examples/counts/valid-nothing-yet.json"
        if scenario == "empty"
        else "examples/counts/valid-answer.json"
    )
    out({**answer, "unavailable": [], "complete": True})


# --- job ---
JOB, RUN, TICKET = "j_x7k2m9", "r_8k2m01", "t_inv7c2"


def job(argv, scenario):
    if not argv or argv[0] not in (
        "start",
        "step",
        "progress",
        "artifact",
        "metric",
        "table",
        "link",
        "log",
        "end",
    ):
        fail("This command is not available in the test orch.", "not_available")
    kind, rest = argv[0], argv[1:]
    valued = {
        "title",
        "ticket",
        "quiet-minutes",
        "label",
        "state",
        "done",
        "total",
        "unit",
        "text",
        "status",
        "summary",
        "json-doc",
    }
    pos, flags = take_flags(rest, valued, {"json", "err"})
    if "json" in flags and kind == "table":  # `orch job table --json '<table>'` carries the table itself
        pass
    state_dir = os.environ.get("ORCH_FAKE_STATE")
    sf = Path(state_dir) / "job.json" if state_dir else None
    st = json.loads(sf.read_text()) if sf and sf.exists() else {"seq": 0, "ended": False}
    if scenario == "empty" and kind != "start" and st["seq"] == 0:
        fail("Refused: this job has not started.", "refused")
    if st["ended"]:
        fail("Refused: this job has already ended.", "refused")
    ev = {
        "v": 1,
        "job": JOB,
        "run": RUN,
        "ticket": flags.get("ticket", TICKET),
        "seq": st["seq"] + 1,
        "at": NOW,
        "type": kind,
    }
    if kind == "start":
        ev["title"] = flags.get("title") or fail("A job needs --title.")
        if "quiet-minutes" in flags:
            ev["quiet_minutes"] = int_flag(flags, "quiet-minutes", 1, 240)
    elif kind == "step":
        if len(pos) != 1 or "label" not in flags:
            fail("Use: job step <name> --label <text>.")
        ev.update(step=pos[0], label=flags["label"], state=flags.get("state", "running"))
    elif kind == "progress":
        ev["done"] = int_flag(flags, "done", 0, 10**12) if "done" in flags else fail("Progress needs --done.")
        ev["total"] = int_flag(flags, "total", 0, 10**12)
        for k in ("unit", "text"):
            if k in flags:
                ev[k] = flags[k]
    elif kind == "artifact":
        if len(pos) != 1:
            fail("Use: job artifact <path>.")
        if not re.fullmatch(
            r"(\.orch/tickets/t_[a-z0-9]{6,16}/artifacts/)?(?![/\\])(?![A-Za-z]:)(?!.*(^|/)\.)(?!.*\\)[^\x00-\x1f\x7f]+",
            pos[0],
        ):
            fail("An artifact must be a file inside the workspace.")
        ev["path"] = pos[0]
        if "label" in flags:
            ev["label"] = flags["label"]
    elif kind == "metric":
        if len(pos) != 2:
            fail("Use: job metric <name> <number>.")
        try:
            ev["value"] = float(pos[1]) if "." in pos[1] else int(pos[1])
        except ValueError:
            fail("The metric value must be a number.")
        ev["name"] = pos[0]
        if "unit" in flags:
            ev["unit"] = flags["unit"]
    elif kind == "link":
        if len(pos) != 1 or not pos[0].startswith("https://"):
            fail("A link must be an https:// address.")
        ev["url"] = pos[0]
        if "label" in flags:
            ev["label"] = flags["label"]
    elif kind == "log":
        if len(pos) != 1:
            fail("Use: job log <text>.")
        ev.update(stream="err" if "err" in flags else "out", text=pos[0])
    elif kind == "end":
        if flags.get("status") not in ("ok", "failed", "cancelled"):
            fail("--status must be ok, failed or cancelled.")
        ev["status"] = flags["status"]
        if "summary" in flags:
            ev["summary"] = flags["summary"]
    elif kind == "table":
        fail("Use the table through the real orch.", "not_available")
    if kind == "step" and ev["state"] not in ("pending", "running", "done", "failed", "skipped"):
        fail("Unknown step state.")
    st = {"seq": ev["seq"], "ended": kind == "end"}
    if sf:
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text(json.dumps(st))
    out({"job": JOB} if kind == "start" else ev)


# --- run screen ---
def run_screen(argv, scenario):
    pos, flags = take_flags(argv, set(), {"follow", "json"})
    if len(pos) != 1 or "follow" not in flags or "json" not in flags:
        fail("Use: run screen <ticket> --follow --json.")
    if not re.fullmatch(r"t_[a-z0-9]{6,16}", pos[0]):
        fail("That ticket does not exist.", "not_found")
    if pos[0] == "t_nolive":
        fail("This ticket has no live session.", "not_available")
    lines = load(
        "examples/screen/valid-refused.json"
        if scenario == "refused"
        else "examples/screen/valid-real-capture.json"
    )
    if scenario == "empty":
        lines = lines[:2]  # hello, snapshot, then quiet
    for ln in lines:
        if ln.get("type") == "hello":
            ln["ticket"] = pos[0]
    if scenario == "drop":
        for ln in lines[:5]:
            out(ln)
        out(
            {
                "v": 1,
                "seq": 6,
                "type": "error",
                "error": "The live session stream was dropped.",
                "code": "busy",
            }
        )
        sys.exit(2)
    for ln in lines:
        out(ln)
        if ln.get("type") == "error":
            sys.exit(2)
    if scenario == "empty":
        out({"v": 1, "seq": 3, "type": "ping", "at": NOW})


# --- main ---
def main(argv):
    scenario = os.environ.get("ORCH_FAKE_SCENARIO") or "default"
    if "--fake-scenario" in argv:
        i = argv.index("--fake-scenario")
        scenario = argv[i + 1] if i + 1 < len(argv) else ""
        argv = argv[:i] + argv[i + 2 :]
    if scenario not in SCENARIOS:
        fail(f"Unknown test scenario {scenario!r}.")
    if argv[:2] == ["record", "tail"]:
        record_tail(argv[2:], scenario)
    elif argv[:2] == ["record", "query"]:
        record_query(argv[2:], scenario)
    elif argv[:2] == ["record", "counts"]:
        record_counts(argv[2:], scenario)
    elif argv[:1] == ["job"]:
        job(argv[1:], scenario)
    elif argv[:2] == ["run", "screen"]:
        run_screen(argv[2:], scenario)
    else:
        fail("This command is not available in the test orch.", "not_available")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except BrokenPipeError:
        sys.exit(0)

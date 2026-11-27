"""`orch needs` and `orch counts`. `orch agents` lives in cli_config.py."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orch import needs as needs_mod
from orch import nextstep, tickets


def add_parsers(sub, common) -> None:
    x = sub.add_parser("needs", parents=[common], help="what waits for a person")
    # orch's own detached run: asks GitHub about pull requests left open (stuck.py), prints nothing
    x.add_argument("--look-at-pulls", action="store_true", help=argparse.SUPPRESS)
    # orch's own detached run: saves a fresh answer of an add-on that was late (needs.refresh), prints nothing
    x.add_argument("--refresh-addon", metavar="NAME", help=argparse.SUPPRESS)
    sub.add_parser(
        "counts", parents=[common], help="the numbers every page shows (needs you, working, stuck)"
    )


def _helpers_now(n: int) -> str:
    if not n:
        return "no helper running right now"
    return f"{n} {'helper' if n == 1 else 'helpers'} running right now"


def _counts_text(c: dict) -> str:
    n, p = c["needs_you"], lambda k, one, many: f"{k} {one if k == 1 else many}"
    return "\n".join(
        [
            f"Needs you: {n['count']} ({p(n['questions'], 'question', 'questions')}, "
            f"{p(n['results'], 'result to review', 'results to review')}"
            + (
                f", {p(n['failed'], 'helper that could not start', 'helpers that could not start')}"
                if n.get("failed")
                else ""
            )
            + (f", {n['stopped']} stopped short" if n.get("stopped") else "")
            + ")",
            f"In progress: {len(c.get('in_progress') or [])} ({_helpers_now(c.get('running', 0))})",
            f"Not started: {len(c.get('not_started') or [])}",
            f"Stuck: {c['stuck']}",
        ]
    )


def _line(r: dict, keys: dict[str, str]) -> str:
    who = keys.get(r["ticket"], r["ticket"]) if r["ticket"] else r["source"]
    pad = " " * 14
    ans = r.get("answer")
    stale = "  (not up to date)" if r.get("stale") else ""
    # A ticket question: one line to answer it, never a choice filled in for the person.
    if ans and r["ticket"]:
        opts = "  [" + " | ".join(ans.get("labels") or ans["options"]) + "]" if ans.get("options") else ""
        how = f'{pad}you answer: orch answer {who} {ans["question"]} "<your choice>"'
        return f"  {who:<10}  Question: {r['text']}{opts}{stale}\n{how}"
    extra = ""
    if ans and ans["options"]:
        extra = "  [" + " | ".join(ans.get("labels") or ans["options"]) + "]"
    elif r.get("cli"):
        extra = f"  ({r['cli']})"
    if r.get("kind") == "addon:not-running":
        # ORCH-2149: "core  factory: factory is not running" named the core for an add-on and the add-on twice
        return f"  {'add-on':<10}  {r['text']}{extra}{stale}"
    return f"  {who:<10}  {r['title']}: {r['text']}{extra}{stale}"


def _person_line(item: dict, t: dict) -> str:
    """ORCH-2140: a result to review or a helper that could not start, the rest of the needs-you number."""
    who, pad = t.get("key") or t["id"], " " * 14
    if item.get("start"):
        return (
            f"  {who:<10}  Helper could not start: {t.get('title', who)}\n"
            f"{pad}try again: orch run start {who}"
        )
    first = next((x.strip() for x in str(t.get("summary") or "").splitlines() if x.strip()), "")
    what = first or t.get("title", who)
    return (
        f"  {who:<10}  Result to review: {what[:200]}\n"
        f"{pad}looks good: orch ticket status {who} done\n"
        f'{pad}send back: orch ticket changes {who} "<what should change>"'
    )


def _person_rows(root: Path, rows: list[dict]) -> list[tuple[dict, dict]]:
    """The needs-you items `orch counts` counts that are no needs row: a result to review and a helper that
    could not start (the same items, by the same rule, as counts.needs_you), with their tickets."""
    from orch import counts, history, ticketindex

    def keep(r: dict) -> bool:
        w = r.get("waiting_on") or {}
        return r.get("status") == "review" or (r.get("status") == "waiting" and w.get("start") is True)

    try:
        shown = history.shown_json(root, ticketindex.load_where(root, keep))
        items = counts.needs_you(shown, counts.quiet(root, shown), rows)["items"]
    except Exception:  # noqa: BLE001 - a listing never stalls on a bad file
        return []
    by = {t["id"]: t for t in shown}
    return [(i, by[i["ticket"]]) for i in items if not i["question"] and not i.get("stopped")]


def _keys(root: Path, rows: list[dict]) -> dict[str, str]:
    """Each row's ticket id -> the key a person reads (MPU-2); the id when it has none."""
    out = {}
    for tid in {r["ticket"] for r in rows if r.get("ticket")}:
        try:
            out[tid] = tickets.load(root, tid).get("key") or tid
        except Exception:  # a listing never stalls on a bad file
            out[tid] = tid
    return out


def dispatch(args, root: Path) -> bool:
    if args.cmd == "counts":
        from orch import counts

        c = counts.now(root)
        nextstep.remember(args, c)
        print(json.dumps(c, indent=2, ensure_ascii=False) if args.json else _counts_text(c))
        return True
    if args.cmd != "needs":
        return False
    if args.look_at_pulls:
        from orch import history, stuck

        stuck.look(root, history.shown_json(root, tickets.list_all(root)))
        return True
    if args.refresh_addon:
        needs_mod.refresh(root, args.refresh_addon)
        return True
    from orch import ticketindex

    # one read-only pass: the ticket files are looked at once, not once per list (ORCH-2289: the rows, the
    # shown fields and the results to review each stat'ed all 10,000 files again)
    with ticketindex.reuse():
        rows = needs_mod.needs(root)
        if args.json:
            nextstep.remember(args, rows)
            print(json.dumps(rows, indent=2, ensure_ascii=False))
            return True
        more = _person_rows(root, rows)
        nextstep.remember(args, {"rows": rows, "more": len(more)})
        if not rows and not more:
            print("Nothing needs you.")
        else:
            print(f"Needs you ({len(rows) + len(more)})")
            keys = _keys(root, rows)
            print("\n".join([*(_line(r, keys) for r in rows), *(_person_line(i, t) for i, t in more)]))
    return True

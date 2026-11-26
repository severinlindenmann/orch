"""`orch automation view --json`: read-only blocks for the dashboard tab (Schedule first, then Listen) (addon-view.schema.json)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

from croniter import croniter

from . import listen, needs, orchcli, scripts, service
from .cron import fmt, next_after, parse
from .loop import scheduled
from .plain import new_repeat_zone, repeat_zone, workspace_tz, zone
from .runner import load_state
from .syncapproval import allowed

DAYS = (
    "Sundays",
    "Mondays",
    "Tuesdays",
    "Wednesdays",
    "Thursdays",
    "Fridays",
    "Saturdays",
)  # cron 0 = Sunday
_NAMES = {n: i for i, n in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))}
HOUR = 3600
SCAN = 7 * 1440 + 1  # at most one run per minute for a week


def clean(s: object, n: int = 80) -> str:
    out = "".join(c for c in str(s) if c not in "<>").strip()
    if len(out) > n:  # cut at a whole word and say so, never in the middle of one
        cut = out[: n - 1]
        head = cut if out[n - 1].isspace() or len(cut.split()) < 2 else cut.rsplit(None, 1)[0]
        out = head.rstrip(" ,;:.-\u2013\u2014") + "\u2026"
    return out or "-"


def _name(t: dict) -> str:
    """A ticket as people read it: its short key first when it has one ("DM1-12 · Invoice export")."""
    key = t.get("key")
    return clean(f"{key} · {t['title']}" if isinstance(key, str) and key else t["title"])


def clip(s: str, n: int = 80) -> str:
    """Shorten at a word end with an ellipsis (never mid-word, never longer than n)."""
    if len(s) <= n:
        return s
    cut = s[: n - 1].rstrip()
    if s[n - 1].isspace() or s[n - 1] in ",;:.":
        pass  # the cut fell exactly on a word end
    elif " " in cut:
        cut = cut.rsplit(" ", 1)[0].rstrip(" ,;:.-")
    return cut + "…"


def _title(t: dict) -> str:
    """A ticket by its title only (the week strip shows no ticket codes), cut at a word end with an ellipsis."""
    return clip(clean(t["title"], 400))


def _full(t: dict) -> dict:
    """The whole title for the hover text, only when the shown one was cut."""
    full = clean(t["title"], 400)
    return {"full": full} if _title(t) != full else {}


def _dows(field: str) -> set[int] | None:
    out: set[int] = set()
    for part in field.lower().split(","):
        lo, _, hi = part.partition("-")
        try:
            a = _NAMES[lo] if lo in _NAMES else int(lo)
            z = (_NAMES[hi] if hi in _NAMES else int(hi)) if hi else a
        except ValueError:
            return None
        if not (0 <= a <= 7 and 0 <= z <= 7 and a <= z):
            return None
        out |= {d % 7 for d in range(a, z + 1)}
    return out


def _days_words(days: set[int]) -> str:
    if days == {1, 2, 3, 4, 5}:
        return "Weekdays"
    if days == {0, 6}:
        return "Weekends"
    names = [DAYS[d] for d in sorted(days, key=lambda d: (d - 1) % 7)]  # Monday first
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def local_next(expr: str, tz=None, now: datetime | None = None, local=None) -> tuple[datetime, int] | None:
    """The next run in the person's zone (`local`, default this computer's) and how many days it moves
    against the cron's own zone (`tz`, UTC when None). The one conversion the words and "Next run" share."""
    nxt = next_after(expr, now or datetime.now(UTC), tz)
    if nxt is None:
        return None
    here = nxt.astimezone(local) if local else nxt.astimezone()
    return here, (here.date() - nxt.astimezone(tz or UTC).date()).days


def cron_human(expr: str, tz=None, now: datetime | None = None, local=None) -> str:
    """Plain words for a 5-field cron read in `tz` (UTC when None), said in the person's local time:
    "Every 5 minutes", "Mondays at 08:00"."""
    try:
        m, h, dom, mon, dow = expr.split()
    except ValueError:
        return f"On a custom plan ({expr})"
    if dom == mon == "*" and dow == "*" and h == "*":
        if m == "*":
            return "Every minute"
        if m.startswith("*/") and m[2:].isdigit():
            return f"Every {int(m[2:])} minutes"
        if m.isdigit():
            return "Every hour" if int(m) == 0 else f"Every hour at {int(m)} past"
    if dom == mon == dow == "*" and m.isdigit() and h.startswith("*/") and h[2:].isdigit():
        return f"Every {int(h[2:])} hours"
    if m.isdigit() and h.isdigit() and mon == "*" and (ln := local_next(expr, tz, now, local)):
        here, shift = ln
        at = here.strftime("%H:%M")
        if dom == "*" and dow == "*":
            return f"Every day at {at}"
        if dom == "*":
            days = _dows(dow)
            if days:
                return f"{_days_words({(d + shift) % 7 for d in days})} at {at}"
        # a day the local conversion moves is only safe while every month has it
        if dow == "*" and dom.isdigit() and (shift == 0 or 1 <= int(dom) + shift <= 28):
            d = int(dom) + shift
            more = " (the last day in shorter months)" if d >= 29 else ""
            return f"Every month on day {d}{more} at {at}"
    return f"On a custom plan ({expr})"


def _every(gap: int) -> str:
    if gap <= 60:
        return "Every minute"
    if gap >= HOUR and gap % HOUR == 0:
        n = gap // HOUR
        return "Every hour" if n == 1 else f"Every {n} hours"
    return f"Every {gap // 60} min"


def _in(delta: timedelta) -> str:
    s = int(delta.total_seconds())
    if s < 60:
        return "now"
    n, unit = (s // 60, "minute") if s < 3600 else (s // 3600, "hour") if s < 86400 else (s // 86400, "day")
    return f"in {n} {unit}{'' if n == 1 else 's'}"


def _tz(t: dict, ws=None):
    """The zone a repeat is read in, as the scheduler reads it (loop.tz_of): its own, else the workspace's
    (`ws`), else UTC (None)."""
    return zone(((t.get("ext") or {}).get("automation") or {}).get("tz")) or ws


def _day(at: datetime) -> str:
    """The day as the week strip writes it, no leading zero: "Tue 1 Dec"."""
    return f"{at:%a} {at.day} {at:%b}"


def _soon(at: datetime, now: datetime) -> str:
    """A start within the week in this computer's time: "today at 07:30", "tomorrow at 07:30", "Monday at 07:30"."""
    local = at.astimezone()
    days = (local.date() - now.astimezone().date()).days
    day = "today" if days == 0 else "tomorrow" if days == 1 else f"{local:%A}"
    return f"{day} at {local:%H:%M}"


def _basis(at: datetime) -> str:
    """The zone a shown time is in ("CET"): this computer's, not the reader's. A long Windows name becomes the
    offset ("UTC+01:00")."""
    name = at.tzname() or ""
    if name and len(name) <= 5 and " " not in name:
        return name
    off = at.utcoffset() or timedelta(0)
    m = int(off.total_seconds()) // 60
    return f"UTC{'-' if m < 0 else '+'}{abs(m) // 60:02d}:{abs(m) % 60:02d}"


def _repeats(t: dict, paused_too: bool = False) -> str | None:
    sched = (t.get("ext") or {}).get("automation") or {}
    cron = sched.get("cron")
    if sched.get("paused") is True and not paused_too:
        return None  # switched off: stays listed, never planned
    if (
        sched.get("recurring") is True
        and isinstance(cron, str)
        and len(cron.split()) == 5
        and croniter.is_valid(cron)
    ):
        return cron
    return None


def _times(cron: str, start: datetime, end: datetime, tz=None) -> list[datetime]:
    """Runs of a cron in [start, end), at most SCAN."""
    out: list[datetime] = []
    it = croniter(cron, (start - timedelta(seconds=1)).astimezone(tz or UTC))
    while len(out) < SCAN:
        nxt = it.get_next(datetime).astimezone(UTC)
        if nxt >= end:
            break
        out.append(nxt)
    return out


def _events(
    tickets: list[dict], now: datetime, horizon: datetime, ws=None
) -> list[tuple[datetime, dict, str]]:
    """The next start of each ticket (time wait or cron repeat) until `horizon`, soonest first."""
    out: list[tuple[datetime, dict, str]] = []
    for t in tickets:
        if not scheduled(t):
            continue
        w = t.get("waiting_on") or {}
        until = parse(w.get("until")) if w.get("kind") == "time" else None
        if until and until <= horizon:
            out.append((max(until, now), t, f"Wakes {until.astimezone().strftime('%a %d %b, %H:%M')}"))
        cron = _repeats(t)
        nxt = next_after(cron, now, _tz(t, ws)) if cron else None
        if nxt and nxt <= horizon:
            out.append(
                (
                    nxt,
                    t,
                    f"{cron_human(cron, _tz(t, ws), now)} · next {nxt.astimezone().strftime('%a %H:%M')}",
                )
            )
    return sorted(out, key=lambda e: e[0])


def _day_items(
    tickets: list[dict], now: datetime, day_start: datetime, day_end: datetime, today: bool, ws=None
) -> list[dict]:
    """Calendar items for one local day. A repeat more often than hourly is ONE item ("Every 5 min",
    "next 15:05 · 288 times a day"); hourly or less shows each time."""
    items: list[tuple[datetime, dict]] = []
    for t in tickets:
        if not scheduled(t):
            continue
        w = t.get("waiting_on") or {}
        until = parse(w.get("until")) if w.get("kind") == "time" else None
        if until:
            at = max(until, now)
            if day_start <= at < day_end:
                items.append(
                    (
                        at,
                        {
                            "time": at.astimezone().strftime("%H:%M"),
                            "title": _title(t),
                            "link": t["id"],
                            **_full(t),
                        },
                    )
                )
        cron = _repeats(t)
        if not cron:
            continue
        whole = _times(cron, day_start, day_end, _tz(t, ws))
        left = [x for x in whole if x >= now]
        if not left:
            continue
        gaps = [(b - a).total_seconds() for a, b in pairwise(whole)]
        if (
            len(whole) >= 3
        ):  # three or more a day: one item with the rhythm, never the same ticket again and again
            first = left[0].astimezone().strftime("%H:%M")
            lead = f"next {first}" if today else (f"from {first}" if first != "00:00" else "")
            note = " · ".join(x for x in (lead, f"{len(whole)} times a day") if x)
            items.append(
                (
                    left[0],
                    {
                        "time": first,
                        "every": _every(int(min(gaps))),
                        "title": _title(t),
                        "note": note,
                        "link": t["id"],
                        **_full(t),
                    },
                )
            )
        else:
            items += [
                (
                    x,
                    {
                        "time": x.astimezone().strftime("%H:%M"),
                        "title": _title(t),
                        "link": t["id"],
                        **_full(t),
                    },
                )
                for x in left
            ]
    return [i for _, i in sorted(items, key=lambda e: e[0])][:20]


_KINDS = {
    "text": "Message",
    "file": "File",
    "delegate": "Task",
    "start": "Start request",
    "webhook": "Webhook",
    "answer": "Answer",
    "question": "Question",
}


def _arrival(a: dict) -> dict:
    kind = _KINDS.get(a.get("type"), "Message")
    when = (parse(a.get("at")) or datetime.now(UTC)).astimezone().strftime("%a %H:%M")
    if a.get("type") in ("start", "delegate"):
        chip = (
            {"label": "Started", "tone": "good"}
            if a.get("allowed")
            else {"label": "Waiting for you", "tone": "warn"}
        )
    elif a.get("type") == "answer" and a.get("applied"):
        chip = {"label": "Answered", "tone": "good"}
    else:
        chip = {"label": "Seen" if a.get("seen") else "New"}
    return {"title": kind, "subtitle": when, "chips": [chip]}


_STATUS = {
    "ready": ("Ready", "neutral"),
    "review": ("Review", "warn"),
    "open": ("Backlog", "neutral"),
    "active": ("Working", "good"),
    "waiting": ("Waiting", "warn"),
    "blocked": ("Blocked", "warn"),
    "done": ("Done", "good"),
    "dropped": ("Dropped", "neutral"),
}


def _what_runs(t: dict, sched: dict) -> str:
    """What a repeat runs, in a few words: a script, a group of scripts or a helper, and when it waits for a change."""
    from .loop import change_of, group_of

    group = group_of(t)
    what = (
        f"Runs {len(group)} scripts, each on its own plan"
        if group
        else f"Runs {sched['script']}"
        if sched.get("script")
        else sched.get("agent") or "Your helper"
    )
    spec = change_of(t)
    return f"{what}, only when {spec.split('@')[1]} changed" if spec else what


def waiting_script(root: Path, t: dict) -> str | None:
    """The first script of this repeat (its script or one of its group) set up here but not allowed yet."""
    from .loop import group_of

    sched = (t.get("ext") or {}).get("automation") or {}
    names = sorted(group_of(t)) or [sched.get("script")]
    for name in names:
        if isinstance(name, str) and scripts.NAME_RE.match(name):
            argv = scripts.load(root).get(name)
            if argv and not scripts.approved(root, name, argv):
                return name
    return None


def _script_waits(root: Path, t: dict) -> bool:
    """The repeat names a script that is set up here but not allowed on this computer yet."""
    return waiting_script(root, t) is not None


def _act(verb: str, tid: str) -> dict:
    return {"op": "addon.act", "args": {"verb": verb, "target": tid}}


def _linked(t: dict, tickets: list[dict]) -> list[dict]:
    """The ticket itself, then the sub-tickets made for its runs."""
    out = []
    for x in [t] + [c for c in tickets if c.get("parent") == t["id"]][:9]:
        label, tone = _STATUS.get(x.get("status"), (clean(x.get("status", "-"), 40), "neutral"))
        out.append({"id": x["id"], "title": _name(x), "status": {"label": label, "tone": tone}})
    return out


def _last_result(runs: list[dict], tid: str) -> str | None:
    """The newest recorded run of a ticket in words (\"Done · Mon 09:00\"), or None when it never ran."""
    mine = [r for r in runs if r.get("ticket") == tid]
    if not mine:
        return None
    r = mine[-1]
    when = parse(r["at"]).astimezone().strftime("%a %H:%M")
    newest = {x["script"]: x for x in mine if x.get("script")}  # a group: each script's own newest run
    if len(newest) > 1 and any(x["exit"] != 0 for x in newest.values()):
        return f"A script failed · {when}"
    return f"{'Done' if r['exit'] == 0 else 'Stopped'} · {when}"


def _started(tickets: list[dict], runs: list[dict], state: dict | None = None) -> list[tuple[datetime, dict]]:
    """Scheduled tickets whose newest run started after the newest finished run: nothing recorded it yet, but it
    did start ("Last result" shows it, so "Recent starts" must too)."""
    out = []
    for t in tickets:
        if not scheduled(t):
            continue
        last = parse(((t.get("ext") or {}).get("automation") or {}).get("last_run")) or parse(
            ((state or {}).get(t["id"]) or {}).get("last_run")  # a wake-up started with Start now has no ext
        )
        done = [parse(r["at"]) for r in runs if r.get("ticket") == t["id"]]
        if last and not any(d >= last for d in done):
            out.append((last, t))
    return out


def _schedules(
    tickets: list[dict],
    now: datetime,
    running: bool = True,
    runs: list[dict] | None = None,
    waiting: frozenset = frozenset(),
    scripts_waiting: frozenset = frozenset(),
    ws=None,
) -> list[dict]:
    """`running` False (background work stopped): nothing will start, so a schedule shows Paused, not a countdown.
    `waiting`: ids of schedules that arrived by sync and are not allowed on this computer yet: they offer
    "Allow on this computer" (the person signs it) instead of Start now. `scripts_waiting`: ids of repeats whose
    script is set up here but not allowed yet: "Allow this script" shows its command first."""
    rows = []
    for t in tickets:
        if not scheduled(t) or not (cron := _repeats(t, True)):
            continue
        sched = (t.get("ext") or {}).get("automation") or {}
        paused = sched.get("paused") is True
        tz = _tz(t, ws)
        words = cron_human(cron, tz, now)
        nxt = next_after(cron, now, tz)
        here = local_next(cron, tz, now)
        nxt_s = f"{_day(here[0])}, {here[0]:%H:%M} {_basis(here[0])}" if here else "none"
        last = parse(sched.get("last_run"))
        result = _last_result(runs or [], t["id"])
        rows.append(
            (
                nxt or now,
                {
                    "cells": {
                        "schedule": _name(t),
                        "repeats": clean(words, 200),
                        "next": "Off" if paused else "Paused" if not running else clean(nxt_s, 40),
                        "last": result
                        or (f"Started \u00b7 {last.astimezone():%a %H:%M}" if last else "Not yet"),
                    },
                    "link": t["id"],
                    "subtitle": clean(_what_runs(t, sched), 80),
                    "toggle": {
                        "on": not paused,
                        "label": clean(t["title"], 40) + " on or off",
                        "text": "Repeats",
                        "action": _act("toggle", t["id"]),
                    },
                    "actions": [
                        {
                            "label": "Allow on this computer",
                            "action": {"op": "addon.allow", "args": {"target": t["id"]}},
                        }
                        if t["id"] in waiting
                        else {  # a script nobody allowed here yet: the page shows its command before the click
                            "label": "Allow this script",
                            "action": {
                                "op": "addon.act",
                                "args": {"verb": "allow-script", "target": t["id"], "review": True},
                            },
                        }
                        if t["id"] in scripts_waiting
                        else {"label": "Start now", "action": _act("run", t["id"])},
                        {"label": "Edit", "action": {"op": "addon.edit", "args": {"target": t["id"]}}},
                    ],
                },
            )
        )
    # one-time wake-ups ("check again in 2 hours"): rows without a switch; build() puts them in their own table
    for t in tickets:
        w = t.get("waiting_on") or {}
        until = parse(w.get("until")) if w.get("kind") == "time" else None
        if not scheduled(t) or not until or _repeats(t, True):
            continue
        at = until.astimezone()
        rows.append(
            (
                max(until, now),
                {
                    "cells": {
                        "schedule": _name(t),
                        "repeats": "Once",
                        "next": "Paused" if not running else clean(f"{_day(at)}, {at:%H:%M} {_basis(at)}", 40),
                        "last": "Not yet",
                    },
                    "link": t["id"],
                    "actions": [{"label": "Start now", "action": _act("run", t["id"])}],
                },
            )
        )
    return [r for _, r in sorted(rows, key=lambda e: e[0])]


def _incoming(ls: dict, running: bool) -> str:
    """Whether work from the phone and other workspaces comes in, in plain words (no "relay", no "listening")."""
    if ls.get("listening"):
        return "On"
    if running and "could not be reached" in str(ls.get("note") or ""):
        return "Can't connect just now, trying again"
    return "Off"


def _sources(tickets: list[dict], ls: dict, running: bool) -> list[dict]:
    """The relay inbox (phone and other workspaces), then each ticket that waits for an outside webhook."""
    recent = [_arrival(a) for a in reversed(ls.get("recent") or []) if isinstance(a, dict)]
    last = f"last: {recent[0]['title']} {recent[0]['subtitle']}" if recent else "nothing arrived yet"
    state = _incoming(ls, running)
    rows = [
        {
            "title": "Phone and other workspaces",
            "subtitle": clean(f"{state} · {last}", 200),
            "detail": [
                {
                    "label": "Recent",
                    "lines": [
                        clean(f"{r['subtitle']} {r['title']} · {r['chips'][0]['label']}", 150)
                        for r in recent[:5]
                    ]
                    or ["Nothing yet"],
                }
            ],
        }
    ]
    for t in tickets:
        w = t.get("waiting_on") or {}
        if (
            t["status"] == "waiting"
            and w.get("kind") == "external"
            and isinstance(w.get("ref"), str)
            and w["ref"].startswith("wh_")
        ):
            rows.append(
                {
                    "title": _name(t),
                    "subtitle": "Webhook · waiting for it to arrive",
                    "detail": [{"label": "Webhook address", "value": clean(w["ref"], 200), "copy": True}],
                    "tickets": _linked(t, []),
                }
            )
    return rows


def _runs(root: Path) -> list[dict]:
    out = []
    try:
        lines = (root / ".orch" / "addons" / "automation" / "runs.jsonl").read_text().splitlines()
    except OSError:
        return out
    for line in lines[-200:]:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        # a run the quick check skipped started nothing: it is on the role page, not in Recent starts
        if (
            isinstance(r, dict)
            and parse(r.get("at"))
            and isinstance(r.get("exit"), int)
            and not r.get("skipped")
        ):
            out.append(r)
    return out


SHOW = 5  # rows a table shows before "Show more"
ROWS = 100  # rows a table carries at most (the contract's limit); the rest is "+N more"


def files_words(tot: dict) -> str:
    """Run files nobody opened, in words: "2 unopened, 5 unknown"; "unknown" when nothing is measured."""
    f = tot["files"]
    if not any(f.values()):
        return "none"
    parts = [
        f"{f['unopened']} unopened" if f["unopened"] else "",
        f"{f['unknown']} unknown" if f["unknown"] else "",
    ]
    return ", ".join(x for x in parts if x) or "all opened"


def roles_table(root: Path, tickets: list[dict]) -> dict | None:
    """One row per repeating ticket that has run: runs, findings, the tickets they became (fixed / open / dropped)
    and run files nobody opened. The same totals as the role's own ticket page (roles.totals)."""
    from . import roles

    by_id = {t["id"]: t for t in tickets}
    rows = []
    for t in tickets:
        if ((t.get("ext") or {}).get("automation") or {}).get("recurring") is not True:
            continue
        rl = roles.runs(root, t)
        if not rl:
            continue
        tot = roles.totals(root, t, by_id, rl)
        skipped = tot["by_outcome"].get("skipped", 0)
        runs_w = f"{tot['runs']}" + (f" ({skipped} skipped)" if skipped else "")
        if tot["scripts"]:
            runs_w += " \u00b7 " + ", ".join(f"{k} {v}" for k, v in sorted(tot["scripts"].items()))
        rows.append(
            {
                "cells": {
                    "role": _name(t),
                    "runs": clean(runs_w, 120),
                    "findings": str(tot["findings"]),
                    "tickets": f"{tot['fixed']} fixed \u00b7 {tot['open']} open \u00b7 {tot['dropped']} dropped"
                    if tot["tickets"]
                    else "none",
                    "files": files_words(tot),
                },
                "link": t["id"],
            }
        )
    if not rows:
        return None
    return {
        "type": "table",
        "title": "What the roles found",
        "columns": [
            {"key": "role", "label": "Runs by itself", "type": "text"},
            {"key": "runs", "label": "Runs", "type": "text"},
            {"key": "findings", "label": "Findings", "type": "text"},
            {"key": "tickets", "label": "Their tickets", "type": "text"},
            {"key": "files", "label": "Files nobody opened", "type": "text"},
        ],
        "rows": rows[:20],
        "more": max(0, len(rows) - 20),
    }


def build(root: Path, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    tickets = orchcli.tickets(root)
    by_id = {t["id"]: t for t in tickets}
    title = lambda tid: _name(by_id[tid]) if tid in by_id else clean(tid)
    ws = zone(workspace_tz(root))
    events = _events(tickets, now, now + timedelta(days=7), ws)
    runs = _runs(root)
    pid = service.running_pid(root, clean=False)
    blocks: list[dict] = []

    waiting = frozenset(t["id"] for t in tickets if scheduled(t) and not allowed(root, t))
    scripts_waiting = frozenset(t["id"] for t in tickets if scheduled(t) and _script_waits(root, t))
    sched_rows = _schedules(tickets, now, bool(pid), runs, waiting, scripts_waiting, ws)
    if sched_rows:
        # ORCH-537 (owner 18 Nov): repeats and one-time wake-ups in two compact tables, the first rows shown
        # and the rest behind "Show more"
        repeat_rows = [r for r in sched_rows if "toggle" in r]
        once_rows = [r for r in sched_rows if "toggle" not in r]
        tables = []
        if repeat_rows:
            tables.append(
                {
                    "type": "table",
                    "title": "Repeating",
                    "meta": str(len(repeat_rows)),
                    "compact": True,
                    "show": SHOW,
                    "columns": [
                        {"key": "schedule", "label": "Ticket", "type": "text"},
                        {"key": "repeats", "label": "Plan", "type": "text"},
                        {"key": "next", "label": "Next time", "type": "text"},
                        {"key": "last", "label": "Last time", "type": "text"},
                    ],
                    "rows": repeat_rows[:ROWS],
                    "more": max(0, len(repeat_rows) - ROWS),
                }
            )
        if once_rows:
            tables.append(
                {
                    "type": "table",
                    "title": "Once",
                    "meta": str(len(once_rows)),
                    "compact": True,
                    "show": SHOW,
                    "columns": [
                        {"key": "schedule", "label": "Ticket", "type": "text"},
                        {"key": "next", "label": "Starts", "type": "text"},
                    ],
                    "rows": [
                        {**r, "cells": {k: r["cells"][k] for k in ("schedule", "next")}}
                        for r in once_rows[:ROWS]
                    ],
                    "more": max(0, len(once_rows) - ROWS),
                }
            )
        days = []
        local_now = now.astimezone()
        for n in range(7):
            start = (local_now + timedelta(days=n)).replace(hour=0, minute=0, second=0, microsecond=0)
            days.append(
                {
                    "date": start.strftime("%Y-%m-%d"),
                    "items": _day_items(tickets, now, start, start + timedelta(days=1), n == 0, ws),
                }
            )
        first, last = local_now.date(), (local_now + timedelta(days=6)).date()
        span = (
            f"{first.day}\u2013{last.day} {last:%B}"
            if first.month == last.month
            else f"{first.day} {first:%B} \u2013 {last.day} {last:%B}"
        )
        # the times on the calendar are this computer's: the heading names that zone once (ORCH-1969), both
        # names when the week crosses a change to or from summer time
        bases = dict.fromkeys(_basis((now + timedelta(days=n)).astimezone()) for n in (0, 6))
        week = {
            "type": "calendar",
            "title": "Coming up",
            "compact": True,
            "meta": f"{span} \u00b7 {' / '.join(bases)}",
            "days": days,
        }
        # the week strip sits above the stable table, and only with two or more schedules (one needs no calendar)
        blocks += [week, *tables] if len(sched_rows) >= 2 else tables
        found = roles_table(root, tickets)
        if found:
            blocks.append(found)
    else:
        blocks.append(
            {
                "type": "list",
                "title": "Repeating",
                "above": True,
                "items": [],
                "empty": {
                    "title": "No repeats yet",
                    "text": "Repeat any ticket on a plan you choose. Your upcoming work and results will appear here.",
                    "mark": "repeat",
                },
            }
        )

    # R1.1: with the relay off here, nothing on the page names the phone, other workspaces or the relay
    relay = bool(orchcli.addon_on(root, "relay"))
    ls = listen.read(root) if pid else {}
    sources = _sources(tickets, ls, bool(pid))
    # the first row is the phone and workspaces inbox: with nothing arrived it is just the footnote below
    waiting_hooks = sources if relay and (ls.get("recent") or []) else sources[1:]
    warn = needs.rows(root, now)
    if warn:
        blocks.append(
            {
                "type": "list",
                "title": "Needs a look",
                "items": [
                    {
                        "title": clean(r["title"]),
                        "subtitle": clean(r["text"], 200),
                        "tone": r["tone"],
                        "link": r["ticket"],
                    }
                    for r in warn[:10]
                ],
            }
        )

    recent = []  # Recent starts: one line each (ORCH-537), ticket, when, how it ended
    events_ = [(parse(r["at"]), r, None) for r in runs[-5:]] + [
        (at, None, t) for at, t in _started(tickets, runs, load_state(root))
    ]
    for _at, r, started in sorted(events_, key=lambda e: e[0], reverse=True)[:5]:
        if started:
            recent.append(
                {
                    "cells": {
                        "ticket": _name(started),
                        "when": f"{_at.astimezone():%a %H:%M}",
                        "result": "Started",
                    },
                    "link": started["id"],
                }
            )
            continue
        ok = r["exit"] == 0
        took = r.get("took")
        how = (
            "Done" + (f" in {max(1, round(took / 60))} min" if isinstance(took, int | float) and took else "")
            if ok
            else "Stopped"
        )
        row = {
            "cells": {
                "ticket": title(r["ticket"]),
                "when": parse(r["at"]).astimezone().strftime("%a %H:%M"),
                "result": how,
            }
        }
        if r["ticket"] in by_id:
            row["link"] = r["ticket"]
        recent.append(row)
    if waiting_hooks:
        blocks.append(
            {
                "type": "list",
                "title": "Incoming work",
                "items": waiting_hooks[:20],
                "more": max(0, len(waiting_hooks) - 20),
            }
        )
    if recent or sched_rows:
        # the next start in plain words, as the line at the top says it; nothing starts by itself while stopped
        soon = (
            f"{clean(events[0][1].get('title'), 60)} starts {_soon(events[0][0], now)}. "
            if pid and events
            else ""
        )
        blocks.append(
            {
                "type": "table",
                "title": "Recent starts",
                "compact": True,
                "columns": [
                    {"key": "ticket", "label": "Ticket", "type": "text"},
                    {"key": "when", "label": "When", "type": "text"},
                    {"key": "result", "label": "Result", "type": "text"},
                ],
                "rows": recent,
            }
            if recent
            else {
                "type": "list",
                "title": "Recent starts",
                "above": True,
                "items": [],
                "empty": {
                    "title": "Nothing has run yet",
                    "text": soon + "Use Start now to run one sooner.",
                    "mark": "repeat",
                },
            }
        )
    if relay:
        state = _incoming(ls, bool(pid))
        arrived = (ls.get("recent") or [None])[-1] if ls.get("recent") else None
        blocks.append(
            {
                "type": "footnote",
                "text": clean(
                    "Incoming from your phone and other workspaces \u00b7 "
                    + (state if not arrived else f"{state}, last message {_arrival(arrived)['subtitle']}"),
                    200,
                ),
                "link": {"label": "Manage incoming work", "to": "app:addon/relay"},
            }
        )

    # "today" is the person's day on this computer, not the UTC date (ORCH-89: 00:00-01:00 counted yesterday's runs)
    today = now.astimezone().date()
    ran = sum(parse(r["at"]).astimezone().date() == today for r in runs)
    view = {"schema": "orch.addon-view/1", "generated_at": fmt(now), "blocks": blocks}
    # the zone the repeat window's time is read in: a new repeat's (what `repeat` saves without --tz) and each
    # saved repeat's (as the scheduler reads it), so a person elsewhere sees which 08:00 it is
    view["zones"] = {
        "new": new_repeat_zone(root),
        "repeats": {
            t["id"]: repeat_zone(root, (t.get("ext") or {}).get("automation") or {})
            for t in tickets
            if _repeats(t, True)
        },
    }
    if pid:
        nxt = events[0][0] if events else None
        if nxt:  # nothing planned: no row at all (owner sweep 14 Nov)
            line = f"On. Next: {_soon(nxt, now)} {_basis(nxt.astimezone())}"
            if ran >= 5:
                line += f". Ran {ran} times today"
            view.update(notice=line, notice_tone="good")
    else:
        view.update(
            notice="Automation is stopped: nothing starts by itself.",
            notice_tone="warn",
            button={"label": "Start", "action": {"op": "addon.start"}},
        )
    return view

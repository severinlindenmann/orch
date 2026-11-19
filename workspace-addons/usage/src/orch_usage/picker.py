"""Usage picks the tool, the account and the model for one helper start, by the owner's share (ORCH-658).

    pick(root, request, share, sources, at)  -> Pick   (a source, or wait with a reason)
    started(root, start) / failed(root, start) / finished(root, start, spent)
    spread(root, day)                        -> starts and dollars per source that day

The request (one helper start):
    {"start": "<id, the same on every retry of this start>", "ticket": "ORCH-12",
     "kind": "lead|code|reviews|builds|scripts|helpers", "model": "opus|sonnet" (orch's pick)}

The share (what the owner sets, ORCH-657; every field may be missing):
    {"order": ["a_sub001", "a_key001", "a_cdx001"],   # fallback order; sources not named follow in their own order
     "week": {"wed": 70, "fri": 95},                  # subscriptions: percent of the week used allowed by the end of
                                                      #   that weekday (a straight line between the marks, 0 at the
                                                      #   start of the week, 100 at its end)
     "credit_kinds": ["reviews"],                     # kinds of work that go to an API key first
     "one_in": {"tool": "<a helper tool's registry name>", "every": 4},
                                                      # one in N code starts goes to that tool first
     "ahead_dollars_day": 10}                         # subscriptions ahead of the week line: up to N dollars a day
                                                      #   of new starts go to API keys instead

A source (one per account, built by the caller from accounts.json and the readers; labels and numbers only):
    {"id", "label", "tool": "<helper tool's registry name>", "tool_label": "<its name for people>", "type": "subscription|api-key|helper-tool", "on": bool,
     "at_limit": bool, "resets": "<UTC time it has room again>" | None,
     "week_used": percent (subscription) | None,
     "left": dollars left | None (unknown), "left_at": "<UTC time that number was read>" | None,
     "day_limit": dollars a day | None, "spent_today": dollars | None (a reader may lag: Usage counts the larger of
     it and the finished starts it knows of),
     "models": {"opus": "<the tool's model name>", ...} | None, "model": "<default model of the tool>" | None}

Money is held before the start: a pick writes a hold of the start's estimated dollars into starts.json under the
Usage lock, and every later pick counts the open holds against what is left and against the day limit, so two starts
at once cannot both take the last dollars. finished() replaces the hold with what the start really spent, failed()
gives the money back; both are final. Each start id is in the file once: a retry of a held, started or finished start gets the same
answer and no second hold; a retry after failed() picks again into the same entry, so it still counts once.
A hold that never started within HOLD_HOURS is treated as failed (the starter crashed).

Days and weeks are UTC (the day starts at 00:00, the week on Monday 00:00). Entries older than KEEP_DAYS go.
Only labels, numbers and times: never a key or login.
"""

from __future__ import annotations

import itertools
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import store

STARTS = "starts.json"
SCHEMA = "orch.usage-starts/1"
HOLD_HOURS = 2
KEEP_DAYS = 8
MONEY_TYPES = ("api-key", "helper-tool")
OPEN = ("held", "started")
COUNTED = ("held", "started", "done")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_WORDS = dict(zip(DAYS, ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")))
# Dollars held for one start until its real spend is known: medians per ticket from our own records (ORCH-656).
ESTIMATE = {"opus": 3.70, "sonnet": 1.05, "haiku": 0.40}
ESTIMATE_DEFAULT = 2.40
KIND_WORDS = {
    "lead": "lead work",
    "code": "code work",
    "reviews": "review work",
    "builds": "build work",
    "scripts": "script work",
    "helpers": "helper work",
}


@dataclass
class Pick:
    start: str
    wait: bool = False
    source: str | None = None
    label: str | None = None
    tool: str | None = None
    account_type: str | None = None
    model: str | None = None
    dollars: float = 0.0
    why: str = ""
    until: str | None = None
    repeat: bool = False
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---- the file ------------------------------------------------------------------------------------------------


def _path(root: Path) -> Path:
    return store.usage_dir(root) / STARTS


def _load(root: Path) -> dict:
    """The starts on file. No file yet: none. A file that cannot be read is refused, never overwritten: it holds
    money other starts count on."""
    try:
        text = _path(root).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise store.Refused(f"Usage cannot read its list of helper starts ({e.strerror}).") from None
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    starts = data.get("starts") if isinstance(data, dict) else None
    if not isinstance(starts, dict):
        raise store.Refused(
            f"Usage's list of helper starts is damaged; fix or remove {_path(root).name} in the Usage folder."
        )
    return {k: v for k, v in (starts or {}).items() if isinstance(k, str) and isinstance(v, dict)}


def _save(root: Path, starts: dict) -> None:
    d = store.usage_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    body = (
        json.dumps({"schema": SCHEMA, "starts": starts}, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    )
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".starts.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, _path(root))


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%d")


def _tidy(starts: dict, at: datetime) -> None:
    """Old entries go; a hold that never started within HOLD_HOURS gives its money back."""
    keep_from = _day(at - timedelta(days=KEEP_DAYS))
    for sid in list(starts):
        e = starts[sid]
        if str(e.get("day", "")) < keep_from:
            del starts[sid]
            continue
        if e.get("state") == "held":
            try:
                held_at = store.to_time(e["at"])
            except (KeyError, ValueError):
                held_at = at
            if at - held_at > timedelta(hours=HOLD_HOURS):
                e["state"] = "failed"
                e["note"] = "never started"


# ---- what is used ---------------------------------------------------------------------------------------------


def _money(e: dict) -> float:
    if e.get("state") in OPEN:
        return float(e.get("dollars") or 0)
    if e.get("state") == "done":
        spent = e.get("spent")
        return float(spent if spent is not None else e.get("dollars") or 0)
    return 0.0


def _open_holds(starts: dict, s: dict) -> float:
    """Dollars not yet in what is left: open holds, and finished starts that ended after `left_at` (the time the
    number left was read). Without `left_at` the number already counts every finished start."""
    since = s.get("left_at")
    total = 0.0
    for e in starts.values():
        if e.get("source") != s["id"]:
            continue
        if e.get("state") in OPEN:
            total += float(e.get("dollars") or 0)
        elif e.get("state") == "done" and since and str(e.get("ended") or "") > str(since):
            total += _money(e)
    return round(total, 4)


def _used_today(starts: dict, s: dict, day: str) -> float:
    """Dollars of the day on this source: what the reader saw or what this file knows of finished starts, whichever
    is more (a reader can lag behind a start that just ended), plus the open holds."""
    holds = sum(
        float(e.get("dollars") or 0)
        for e in starts.values()
        if e.get("source") == s["id"] and e.get("day") == day and e.get("state") in OPEN
    )
    done = sum(
        _money(e)
        for e in starts.values()
        if e.get("source") == s["id"] and e.get("day") == day and e.get("state") == "done"
    )
    seen = s.get("spent_today")
    return round(max(float(seen or 0), done) + holds, 4)


def _ahead_used(starts: dict, day: str) -> float:
    return round(sum(_money(e) for e in starts.values() if e.get("day") == day and e.get("ahead")), 4)


def _code_starts(starts: dict, day: str) -> int:
    return sum(
        1
        for e in starts.values()
        if e.get("day") == day and e.get("kind") == "code" and e.get("state") in COUNTED
    )


def week_line(week: dict | None, at: datetime) -> float | None:
    """Percent of the week a subscription may have used by `at` (straight line between the owner's marks)."""
    marks = []
    for k, v in (week or {}).items():
        if k in DAYS and isinstance(v, (int, float)) and 0 <= v <= 100:
            marks.append(((DAYS.index(k) + 1) * 24.0, float(v)))  # by the END of that day
    if not marks:
        return None
    t = at.astimezone(UTC)
    hours = t.weekday() * 24 + t.hour + t.minute / 60
    points = [(0.0, 0.0), *sorted(marks), (168.0, 100.0)]
    for (h0, v0), (h1, v1) in itertools.pairwise(points):
        if h0 <= hours <= h1:
            return v0 if h1 == h0 else round(v0 + (v1 - v0) * (hours - h0) / (h1 - h0), 1)
    return 100.0


def estimate(request: dict) -> float:
    return ESTIMATE.get(str(request.get("model") or ""), ESTIMATE_DEFAULT)


# ---- the choice -----------------------------------------------------------------------------------------------


def _fmt(v: float) -> str:
    return store.fmt_value(round(v, 2), "$")


def _ordered(sources: list[dict], share: dict) -> list[dict]:
    order = [x for x in (share.get("order") or []) if isinstance(x, str)]
    named = {x: i for i, x in enumerate(order)}
    return sorted(sources, key=lambda s: (0, named[s["id"]]) if s["id"] in named else (1, sources.index(s)))


def _room(s: dict, need: float, starts: dict, day: str) -> tuple[bool, str]:
    if not s.get("on", True):
        return False, "off"
    if s.get("at_limit"):
        return False, "at its limit"
    if s.get("type") in MONEY_TYPES:
        left = s.get("left")
        if left is not None:
            free = float(left) - _open_holds(starts, s)
            if float(left) <= 0:
                return False, "empty"
            if free < need:
                return False, f"only {_fmt(max(free, 0))} left"
        lim = s.get("day_limit")
        if lim is not None and _used_today(starts, s, day) + need > float(lim):
            return False, f"at its day limit of {_fmt(float(lim))}"
    return True, ""


def _model(s: dict, request: dict) -> str | None:
    want = request.get("model")
    models = s.get("models") or {}
    if want in models:
        return models[want]
    if s.get("model"):
        return s["model"]
    return want  # a tool that takes orch's own model names


def _wake(sources: list[dict], at: datetime, day_limited: bool) -> str | None:
    times = []
    for s in sources:
        if s.get("on", True) and s.get("resets"):
            try:
                t = store.to_time(s["resets"])
            except ValueError:
                continue
            if t > at:
                times.append(t)
    if day_limited:
        u = at.astimezone(UTC)
        times.append(datetime(u.year, u.month, u.day, tzinfo=UTC) + timedelta(days=1))
    return _iso(min(times)) if times else None


def _choose(request: dict, share: dict, sources: list[dict], starts: dict, at: datetime) -> tuple[Pick, bool]:
    """(the pick, counted against the ahead budget)."""
    day = _day(at)
    kind = str(request.get("kind") or "helpers")
    need = estimate(request)
    ordered = _ordered([s for s in sources if isinstance(s, dict) and s.get("id")], share)
    subs = [s for s in ordered if s.get("type") == "subscription"]
    money = [s for s in ordered if s.get("type") in MONEY_TYPES]

    first: list[dict] = []
    reason = "first in the order"
    ahead = False
    one_in = share.get("one_in") if isinstance(share.get("one_in"), dict) else {}
    n, tool = one_in.get("every"), one_in.get("tool")
    if kind in (share.get("credit_kinds") or []):
        first = money
        reason = f"{KIND_WORDS.get(kind, kind)} goes to API credit"
    elif (
        kind == "code" and tool and isinstance(n, int) and n > 0 and (_code_starts(starts, day) + 1) % n == 0
    ):
        same = [s for s in ordered if s.get("tool") == tool]
        first = sorted(same, key=lambda s: s.get("type") != "subscription")  # flat price first, then a key
        name = next((s.get("tool_label") for s in same if s.get("tool_label")), tool)
        reason = f"one in {n} code starts goes to {name}"
    else:
        line = week_line(share.get("week"), at)
        cap = share.get("ahead_dollars_day")
        on_subs = [s for s in subs if s.get("on", True) and s.get("week_used") is not None]
        if (
            line is not None
            and on_subs
            and cap
            and all(float(s["week_used"]) > line for s in on_subs)
            and _ahead_used(starts, day) + need <= float(cap)
        ):
            first = money
            ahead = True
            used = min(float(s["week_used"]) for s in on_subs)
            reason = (
                f"subscriptions are ahead of the week ({used:g}% used, {line:g}% planned by now), "
                f"{_fmt(_ahead_used(starts, day))} of {_fmt(float(cap))} for that used today"
            )
    rest = [s for s in ordered if s not in first]
    skipped = []
    day_limited = False
    for s in [*first, *rest]:
        ok, why = _room(s, need, starts, day)
        if not ok:
            skipped.append(f"{s.get('label') or s['id']} {why}")
            day_limited = day_limited or why.startswith("at its day limit")
            continue
        chosen_reason = reason if s in first else ("first with room" if skipped else "first in the order")
        text = f"runs on {s.get('label') or s['id']}: {chosen_reason}"
        if s.get("type") in MONEY_TYPES:
            lim = s.get("day_limit")
            used = _used_today(starts, s, day)
            text += f"; {_fmt(used + need)} of {_fmt(float(lim))} today" if lim is not None else ""
        if skipped:
            text += f" (skipped: {', '.join(skipped)})"
        return (
            Pick(
                start=request["start"],
                source=s["id"],
                label=s.get("label") or s["id"],
                tool=s.get("tool"),
                account_type=s.get("type"),
                model=_model(s, request),
                dollars=need if s.get("type") in MONEY_TYPES else 0.0,
                why=text,
                skipped=skipped,
            ),
            ahead and s in first,
        )
    why = "waits: no account has room" + (f" ({', '.join(skipped)})" if skipped else " (none is set up)")
    return Pick(
        start=request["start"], wait=True, why=why, until=_wake(ordered, at, day_limited), skipped=skipped
    ), False


def pick(
    root: Path, request: dict, share: dict | None, sources: list[dict], at: datetime | None = None
) -> Pick:
    """Pick a source for this start and hold its money, or say wait. Same start id = same answer, counted once."""
    at = at or datetime.now(UTC)
    sid = str(request.get("start") or "").strip()
    if not sid:
        raise store.Refused("A helper start needs its start id.")
    request = {**request, "start": sid}
    with store._lock(root):
        starts = _load(root)
        _tidy(starts, at)
        old = starts.get(sid)
        if old and old.get("state") in COUNTED:
            _save(root, starts)
            return Pick(
                start=sid,
                source=old.get("source"),
                label=old.get("label"),
                tool=old.get("tool"),
                account_type=old.get("type"),
                model=old.get("model"),
                dollars=float(old.get("dollars") or 0),
                why=old.get("why", ""),
                repeat=True,
            )
        p, ahead = _choose(request, share or {}, sources, starts, at)
        if not p.wait:
            starts[sid] = {
                "state": "held",
                "at": _iso(at),
                "day": _day(at),
                "ticket": request.get("ticket"),
                "kind": request.get("kind") or "helpers",
                "source": p.source,
                "label": p.label,
                "tool": p.tool,
                "type": p.account_type,
                "model": p.model,
                "dollars": p.dollars,
                "ahead": ahead,
                "why": p.why,
                "tries": int((old or {}).get("tries", 0)) + 1,
            }
        _save(root, starts)
        return p


def _set(root: Path, sid: str, state: str, spent: float | None = None, at: datetime | None = None) -> bool:
    with store._lock(root):
        starts = _load(root)
        e = starts.get(sid)
        if not e:
            return False
        if state == "started" and e.get("state") != "held":
            return False
        if state in ("failed", "done") and e.get("state") not in OPEN:
            return False  # failed and finished are final; a second call changes nothing
        e["state"] = state
        if state == "done":
            e["spent"] = None if spent is None else round(float(spent), 4)
            e["ended"] = _iso(at or datetime.now(UTC))
        _save(root, starts)
        return True


def started(root: Path, start: str) -> bool:
    """The helper is running: its hold stays until finished() or failed()."""
    return _set(root, start, "started")


def failed(root: Path, start: str) -> bool:
    """The start did not happen: the money goes back and it does not count. A retry picks again."""
    return _set(root, start, "failed")


def finished(root: Path, start: str, spent: float | None = None, at: datetime | None = None) -> bool:
    """The helper ended: its real spend replaces the hold (unknown spend keeps the hold as the number)."""
    return _set(root, start, "done", spent, at)


def spread(root: Path, day: str) -> dict[str, dict]:
    """Per source that day: {"label", "starts", "dollars"} over held, started and finished starts."""
    out: dict[str, dict] = {}
    for e in _load(root).values():
        if e.get("day") != day or e.get("state") not in COUNTED:
            continue
        row = out.setdefault(e.get("source"), {"label": e.get("label"), "starts": 0, "dollars": 0.0})
        row["starts"] += 1
        row["dollars"] = round(row["dollars"] + _money(e), 4)
    return out

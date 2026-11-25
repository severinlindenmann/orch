"""What is left on an API credit: the amount the person typed (with the time they set it) minus the spend reported
since (ORCH-626).

A credit skill reports each spend with `orch usage spent <credit> <amount>`; Usage keeps it in its own log,
`spent.jsonl` in the computer's Usage folder (store.usage_dir), one JSON line per spend: `{"t", "account": <account id>, "usd", "who"}`. The log
holds amounts, times and account ids only, never a key. The same spend counts for the account's $ limits (the
credit_use() below is what every reader call goes through), so a skill reports each spend once: either through its
own spend log (the account's reader) or through `orch usage spent`, not both.
"""

from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path

from . import store
from .readers import CreditUse, credit_reader

LOG = "spent.jsonl"
SPEND_MAX = 100_000  # dollars in one report: a bigger number is a typo


def log_path(root: Path) -> Path:
    return store.usage_dir(root) / LOG


def _when(text) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        return store.to_time(text)
    except ValueError:
        return None


def _rows(root: Path) -> tuple[list[dict], bool]:
    """(every readable line of the spend log, whether the whole file could be read). Read line by line with no size
    cap: a skipped log would give credit back. A missing file is an empty log."""
    out: list[dict] = []
    try:
        with open(log_path(root), encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(r, dict) or not isinstance(r.get("account"), str):
                    continue
                usd, t = r.get("usd"), _when(r.get("t"))
                if not isinstance(usd, (int, float)) or isinstance(usd, bool) or not usd >= 0 or t is None:
                    continue
                out.append({"t": t, "account": r["account"], "usd": float(usd)})
    except FileNotFoundError:
        return out, True
    except OSError:
        return out, False  # what was read still counts; the caller says the number may be short
    return out, True


def record(root: Path, a: dict, amount: float, who: str, at: str | None = None) -> dict:
    """Write down one spend on an API credit. Amounts only; the line never holds a key."""
    if a["type"] not in store.MONEY_TYPES:
        raise store.Refused(
            f"{a['label']} is a subscription; spend is reported only on API credits and helper tools."
        )
    if (
        not isinstance(amount, (int, float))
        or isinstance(amount, bool)
        or not math.isfinite(amount)
        or not 0 < amount <= SPEND_MAX
    ):
        raise store.Refused(f"Say what was spent as an amount of dollars above 0, at most ${SPEND_MAX:,}.")
    row = {"t": at or store.now(), "account": a["id"], "usd": round(float(amount), 6), "who": who}
    p = log_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, data)  # one write per line: two skills reporting at once never mix their lines
    finally:
        os.close(fd)
    return row


def reported(
    root: Path, account_id: str, since: datetime | None, until: datetime | None = None
) -> tuple[float, bool, bool]:
    """(dollars reported for the account from `since` up to `until`, whether it ever reported anything, whether the
    whole log could be read)."""
    total, ever = 0.0, False
    rows, ok = _rows(root)
    for r in rows:
        if r["account"] != account_id:
            continue
        ever = True
        if since and r["t"] < since:
            continue
        if until and r["t"] >= until:
            continue
        total += r["usd"]
    return round(total, 6), ever, ok


def credit_use(root: Path | None, a: dict, since: str | None) -> CreditUse:
    """What the account spent since a time: its reader (a skill's own spend log) plus what was reported with
    `orch usage spent`. A reader that cannot tell and no report ever: unknown (spent None)."""
    src = a.get("source", {})
    reader = credit_reader(src.get("reader", "none")) or credit_reader("none")
    c = reader(src, since)
    if root is None:
        return c
    extra, ever, ok = reported(root, a["id"], _when(since) if since else None)
    if not ever and ok:
        return c
    # the reader saw helper steps whose spend is unknown (spend_log: estimated, with a note): never counted as 0,
    # and the note stays. A reader with no number at all (no log, no reader) leaves the reports as the count.
    unknown = c.note if c.estimated else None
    if c.spent is None and unknown and extra == 0 and ok:
        return c  # nothing known in dollars: unknown, never 0
    spent = round((c.spent or 0.0) + extra, 4)
    if not ok:
        short = "The Usage spend log could not be read fully; the spend may be more."
        return CreditUse(
            spent=spent,
            since=since,
            as_of=c.as_of,
            estimated=True,
            note=f"{unknown}. {short}" if unknown else short,
        )
    return CreditUse(
        spent=spent, since=since, as_of=c.as_of, estimated=c.estimated or bool(unknown), note=unknown
    )


def _spent_from(root: Path, a: dict, start: datetime) -> float | None:
    return credit_use(root, a, store.utc_text(start)).spent


def view(root: Path, a: dict, at: datetime | None = None) -> dict:
    """For an API credit: what is left now, the amount set and when, the spend since, today and this month.
    `left` is None when the person has not set an amount. Amounts in dollars."""
    at = at or datetime.now(UTC)
    local = at.astimezone()
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    out: dict = {
        "left": None,
        "set": None,
        "set_at": None,
        "spent_since": None,
        "spent_today": _spent_from(root, a, day),
        "spent_month": _spent_from(root, a, month),
    }
    lv = a.get("left")
    if isinstance(lv, dict):
        # a spend in the same second as the figure counts: rather a cent too little left than too much
        c = credit_use(root, a, lv["at"])
        since = c.spent
        spent = round(since or 0.0, 4)
        if c.note and since is not None:
            out["note"] = c.note  # unknown spend, or a log not read fully: the amount left may be less
        out.update(
            set=lv["value"],
            set_at=lv["at"],
            spent_since=spent,
            left=round(max(0.0, lv["value"] - spent), 4),
            over=round(max(0.0, spent - lv["value"]), 4),
            measured=since is not None and not c.note,
        )
    return out


def money(v: float | None) -> str:
    """$74, $3.50, $0.0042 (small spends keep their digits)."""
    if v is None:
        return "?"
    if float(v).is_integer():
        return f"${int(v):,}"
    if abs(v) >= 0.01:
        return f"${v:,.2f}"
    return f"${v:.4f}".rstrip("0")


def text(v: dict, tz=None) -> str:
    """One line for `orch usage list` (days in the workspace's zone `tz`), or '' when there is nothing to say."""
    bits = []
    if v.get("left") is not None:
        day = store.to_time(v["set_at"]).astimezone(tz).strftime("%Y-%m-%d")
        s = f"left: {money(v['left'])} (set on {day}, minus {money(v['spent_since'])} spent since)"
        if v.get("over"):
            s += f", {money(v['over'])} over"
        if v.get("note"):
            s += f" (may be less: {str(v['note']).rstrip('.')})"
        bits.append(s)
    if v.get("spent_today") is not None or v.get("spent_month") is not None:
        bits.append(f"spent today {money(v['spent_today'] or 0)}, this month {money(v['spent_month'] or 0)}")
    return "; ".join(bits)

"""Tokens per model, read from the conversation files a tool keeps for a ticket's sessions (ORCH-82).

Where they are comes from the adapter (session.transcript: dir_env, home, path such as
projects/{folder}/{session}.jsonl). Only <dir>/<first part>/*/<session>.jsonl (and <session>/subagents/*)
are read, one by one, in any start folder (a ticket may run in its own copy); a bad
line is skipped. Per file the result is cached by (path, size, mtime_ns) in .orch/run/usage-cache.json."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orch import adapters, modelpick, tickets
from orch.session_ids import valid_session_id

SCHEMA = "orch.usage/1"
FAMILIES = ("opus", "sonnet", "haiku")
CACHE_NAME = "usage-cache.json"


def family(model: object) -> str:
    low = str(model or "").lower()
    return next((f for f in FAMILIES if f in low), "other")


def _base(root: Path, agent: str, environ: Mapping[str, str] | None) -> Path | None:
    """The folder that holds one sub-folder per start folder, for an adapter whose transcript path is
    <first part>/{folder}/{session}.jsonl; None for an adapter that keeps none (or another layout)."""
    try:
        t = (adapters.load(agent, root).get("session") or {}).get("transcript")
    except Exception:
        return None
    if not t or list(t.get("path") or [])[1:] != ["{folder}", "{session}.jsonl"]:
        return None
    env = os.environ if environ is None else environ
    home = Path(env.get(t.get("dir_env") or "", "") or Path(env.get("HOME") or Path.home()) / t["home"])
    return home / t["path"][0]


def _cache_path(root: Path) -> Path:
    return Path(root) / ".orch" / "run" / CACHE_NAME


def _load_cache(root: Path) -> dict:
    try:
        data = json.loads(_cache_path(root).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache(root: Path, cache: dict) -> None:
    p = _cache_path(root)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(cache), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        pass  # a cache that cannot be written only costs time


def _n(u: dict, k: str) -> int:
    v = u.get(k)
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


# List price in dollars per million tokens: (input, output, cache read); a cache write costs 1.25 x input.
# From Anthropic's price list (3 Nov 2026). The longest matching start of the model id wins; an unknown model
# of a known family takes the family's newest row, anything else counts no money (time still counts).
PRICES = {
    "claude-fable-5-2": (8.0, 40.0, 0.20),
    "claude-fable-5": (10.0, 50.0, 1.00),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-sonnet-4": (3.0, 15.0, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-haiku-4": (1.0, 5.0, 0.10),
}
FAMILY_PRICE = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}
# Helper working time: the gaps between two lines of a conversation, a gap longer than this counts as a pause.
PAUSE_SECONDS = 300
CACHE_VERSION = 2


def price(model: object) -> tuple[float, float, float] | None:
    low = str(model or "").lower()
    best = max((k for k in PRICES if low.startswith(k)), key=len, default=None)
    if best is None and family(low) in FAMILY_PRICE:
        best = FAMILY_PRICE[family(low)]
    return PRICES[best] if best else None


def _cost(model: object, plain: int, write: int, read: int, out: int) -> float:
    p = price(model)
    if p is None:
        return 0.0
    return (plain * p[0] + write * p[0] * 1.25 + read * p[2] + out * p[1]) / 1_000_000


def _stamp(d: dict) -> float | None:
    v = d.get("timestamp")
    if not isinstance(v, str):
        return None
    try:
        at = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (at if at.tzinfo else at.replace(tzinfo=UTC)).timestamp()


def _read_file(path: Path) -> dict:
    """One transcript: {"use": {family: {"in": n, "out": n}}, "cost": dollars at list price, "secs": working
    seconds}. Each message id counts once (its last usage). Working time = the sum of the gaps between two
    dated lines, a gap over PAUSE_SECONDS left out."""
    seen: dict[str, tuple[str, int, int, float]] = {}
    anon = 0
    secs, last = 0.0, None
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                at = _stamp(d)
                if at is not None:
                    if last is not None and 0 < at - last <= PAUSE_SECONDS:
                        secs += at - last
                    last = at if last is None else max(last, at)
                if d.get("type") != "assistant":
                    continue
                m = d.get("message")
                u = m.get("usage") if isinstance(m, dict) else None
                if not isinstance(u, dict):
                    continue

                mid = m.get("id")
                if not isinstance(mid, str) or not mid:
                    anon += 1
                    mid = f"_anon{anon}"
                plain, write = _n(u, "input_tokens"), _n(u, "cache_creation_input_tokens")
                read, out = _n(u, "cache_read_input_tokens"), _n(u, "output_tokens")
                seen[mid] = (
                    family(m.get("model")),
                    plain + write + read,
                    out,
                    _cost(m.get("model"), plain, write, read, out),
                )
    except OSError:
        return {"use": {}, "cost": 0.0, "secs": 0}
    use: dict = {}
    cost = 0.0
    for fam, i, o, c in seen.values():
        t = use.setdefault(fam, {"in": 0, "out": 0})
        t["in"] += i
        t["out"] += o
        cost += c
    return {"use": use, "cost": cost, "secs": int(secs)}


MISS_RETRY = 600  # a session whose conversation was not found is looked for again after this many seconds


def _files(proj: Path, sid: str, where: dict | None = None) -> list[Path]:
    """The conversation files of one session: <proj>/<folder>/<sid>.jsonl and its helpers' files. `where`
    remembers the folders a session was found in (and when it was missed), so a dashboard refresh does not
    list thousands of folders for every session (ORCH-189: 5 s per refresh before)."""
    if not proj.is_dir() or not valid_session_id(sid):
        return []
    import time

    where = {} if where is None else where
    known = where.get(sid)
    folders: list[Path] = []
    if (
        isinstance(known, list)
        and known
        and all((proj / d / f"{sid}.jsonl").is_file() for d in known if isinstance(d, str))
    ):
        folders = [proj / d for d in known if isinstance(d, str)]
    elif isinstance(known, dict) and time.time() - float(known.get("miss") or 0) < MISS_RETRY:
        return []
    else:
        try:
            folders = [d for d in sorted(proj.iterdir()) if (d / f"{sid}.jsonl").is_file()]
        except OSError:
            folders = []
        where[sid] = [d.name for d in folders] if folders else {"miss": time.time()}
    found: list[Path] = []
    for d in folders:
        found.append(d / f"{sid}.jsonl")
        sub = d / sid / "subagents"
        if sub.is_dir():
            found.extend(sorted(p for p in sub.glob("*.jsonl") if p.is_file()))
    return found


def _add(total: dict, part: dict) -> None:
    for fam, v in part.items():
        t = total.setdefault(fam, {"in": 0, "out": 0})
        t["in"] += v["in"]
        t["out"] += v["out"]


def _scan(root: Path, ticket: dict, environ: Mapping[str, str] | None, cache: dict, live: set) -> dict:
    """{"use": tokens per family, "cost": dollars at list price, "seconds": helper working time} of a ticket's
    sessions. Time counts the main conversation only: helpers it starts run beside it, not after it."""
    total: dict = {}
    cost, secs = 0.0, 0
    bases: dict = {}
    for s in ticket.get("sessions") or []:
        if not isinstance(s, dict) or not isinstance(s.get("agent"), str):
            continue
        if s["agent"] not in bases:
            bases[s["agent"]] = _base(root, s["agent"], environ)
        base = bases[s["agent"]]
        if base is None:
            continue
        where = cache.setdefault("_where", {})
        if not isinstance(where, dict):
            where = cache["_where"] = {}
        for f in _files(base, s.get("id"), where):
            try:
                st = f.stat()
            except OSError:
                continue
            key = str(f)
            live.add(key)
            sig = [st.st_size, st.st_mtime_ns]
            hit = cache.get(key)
            if not (
                isinstance(hit, dict)
                and hit.get("sig") == sig
                and hit.get("v") == CACHE_VERSION
                and isinstance(hit.get("use"), dict)
            ):
                hit = {"sig": sig, "v": CACHE_VERSION, **_read_file(f)}
                cache[key] = hit
            _add(total, hit["use"])
            cost += float(hit.get("cost") or 0)
            if f.parent.name != "subagents":
                secs += int(hit.get("secs") or 0)
    return {"use": total, "cost": round(cost, 4), "seconds": secs}


def _usage(root: Path, ticket: dict, environ: Mapping[str, str] | None, cache: dict, live: set) -> dict:
    return _scan(root, ticket, environ, cache, live)["use"]


def spend(root: Path, items: list[dict], environ: Mapping[str, str] | None = None) -> dict:
    """{ticket id: {"cost": dollars, "seconds": n}} for tickets with helper sessions; one cache read and write
    for all of them (the dashboard asks for every listed ticket at once)."""
    root = Path(root)
    cache = _load_cache(root)
    before = json.dumps(cache, sort_keys=True)
    out = {}
    for t in items:
        if not isinstance(t, dict) or not t.get("sessions") or not isinstance(t.get("id"), str):
            continue
        r = _scan(root, t, environ, cache, set())
        if r["use"] or r["seconds"]:
            out[t["id"]] = {"cost": r["cost"], "seconds": r["seconds"]}
    if json.dumps(cache, sort_keys=True) != before:
        _save_cache(root, cache)
    return out


def ticket_usage(root: Path, ticket: dict, environ: Mapping[str, str] | None = None) -> dict:
    root = Path(root)
    cache = _load_cache(root)
    before = json.dumps(cache, sort_keys=True)
    out = _usage(root, ticket, environ, cache, set())
    if json.dumps(cache, sort_keys=True) != before:
        _save_cache(root, cache)
    return out


def _moved_up(ticket: dict) -> bool:
    """orch or the helper moved this ticket up to Opus (the stored model choice says so, not the history)."""
    return modelpick.moved_up(ticket)


def _who(owner: object) -> str:
    return owner.strip() if isinstance(owner, str) else ""


def _member() -> dict:
    return {"finished": 0, "open": 0, "seconds": 0, "cost": 0.0}


def workspace_usage(root: Path, days: int = 30, environ: Mapping[str, str] | None = None) -> dict:
    root = Path(root)
    cutoff = (datetime.now(UTC) - timedelta(days=max(days, 0))).isoformat()
    cache = _load_cache(root)
    before = json.dumps(cache, sort_keys=True)
    live: set = set()
    rows, totals, moved, with_model = [], {}, 0, 0
    cost, secs = 0.0, 0
    team: dict = {}
    finished = stuck = 0
    for t in tickets.list_all(root):
        who = _who(t.get("owner"))
        status = t.get("status")
        if status not in ("done", "dropped"):
            team.setdefault(who, _member())["open"] += 1
            stuck += bool(tickets.stuck_why(t))
        elif status == "done" and str(t.get("done_at") or t.get("updated_at") or "") >= cutoff:
            team.setdefault(who, _member())["finished"] += 1
            finished += 1
        if str(t.get("updated_at") or t.get("created_at") or "") < cutoff:
            continue
        m = t.get("model")
        name = m.get("name") if isinstance(m, dict) else None
        if name:
            with_model += 1
        r = _scan(root, t, environ, cache, live)
        use = r["use"]
        if not use:
            continue
        cost += r["cost"]
        secs += r["seconds"]
        member = team.setdefault(who, _member())
        member["cost"] = round(member["cost"] + r["cost"], 4)
        member["seconds"] += r["seconds"]
        up = _moved_up(t)
        moved += up
        _add(totals, use)
        rows.append(
            {
                "id": t["id"],
                "key": t.get("key") or t["id"],
                "title": t.get("title") or "",
                "models": use,
                "total": sum(v["in"] + v["out"] for v in use.values()),
                "moved_up": up,
                "model": name,
                "owner": t.get("owner") or "",
                "status": t.get("status") or "",
                "cost": r["cost"],
                "seconds": r["seconds"],
            }
        )
    rows.sort(key=lambda r: -r["total"])
    for k in [k for k in cache if not k.startswith("_") and k not in live and not Path(k).exists()]:
        del cache[k]
    if json.dumps(cache, sort_keys=True) != before:
        _save_cache(root, cache)
    return {
        "schema": SCHEMA,
        "days": days,
        "tickets": rows,
        "totals": totals,
        "cost": round(cost, 2),
        "seconds": secs,
        "finished": finished,
        "stuck": stuck,
        # ORCH-189 manager view: per owner ("" = nobody), finished in the window, open now, helper time, money
        "team": [
            {"owner": k, **v} for k, v in sorted(team.items(), key=lambda kv: (-kv[1]["seconds"], kv[0]))
        ],
        "moved_up": moved,
        "with_model": with_model,
    }


def _short(v: int) -> str:
    return f"{v / 1_000_000:.1f}M" if v >= 1_000_000 else f"{v / 1000:.1f}k" if v >= 1000 else str(v)


def duration(seconds: object) -> str:
    """Working time in plain words: "45 min", "2 h 5 min", "–" for none."""
    n = int(seconds) if isinstance(seconds, int | float) and not isinstance(seconds, bool) else 0
    m = round(n / 60)
    if n <= 0:
        return "–"
    if m < 1:
        return "under 1 min"
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"


def money(cost: object) -> str:
    v = float(cost) if isinstance(cost, int | float) and not isinstance(cost, bool) else 0.0
    return f"${v:,.2f}"


def text(data: dict, top: int = 5) -> str:
    if not data["tickets"]:
        return f"No model use in the last {data['days']} days."
    lines = [f"{f}: {_short(v['in'])} in, {_short(v['out'])} out" for f, v in sorted(data["totals"].items())]
    lines.append(f"Helper time: {duration(data.get('seconds'))} · {money(data.get('cost'))} at list price")
    lines.append(f"Moved up to Opus: {data['moved_up']} of {data['with_model']} tickets with a model")
    lines.append("Most tokens:")
    lines += [
        f"  {r['key']}  {_short(r['total'])}  {money(r.get('cost'))}  {r['title']}"
        for r in data["tickets"][:top]
    ]
    return "\n".join(lines)

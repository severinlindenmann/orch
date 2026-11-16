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

from orch import adapters, tickets
from orch.session_ids import valid_session_id

SCHEMA = "orch.usage/1"
FAMILIES = ("opus", "sonnet", "haiku")
MOVED_UP = "Model moved up to Opus"
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


def _read_file(path: Path) -> dict:
    """{family: {"in": n, "out": n}} of one transcript; each message id counts once (its last usage)."""
    seen: dict[str, tuple[str, int, int]] = {}
    anon = 0
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict) or d.get("type") != "assistant":
                    continue
                m = d.get("message")
                u = m.get("usage") if isinstance(m, dict) else None
                if not isinstance(u, dict):
                    continue

                mid = m.get("id")
                if not isinstance(mid, str) or not mid:
                    anon += 1
                    mid = f"_anon{anon}"
                seen[mid] = (
                    family(m.get("model")),
                    _n(u, "input_tokens")
                    + _n(u, "cache_creation_input_tokens")
                    + _n(u, "cache_read_input_tokens"),
                    _n(u, "output_tokens"),
                )
    except OSError:
        return {}
    out: dict = {}
    for fam, i, o in seen.values():
        t = out.setdefault(fam, {"in": 0, "out": 0})
        t["in"] += i
        t["out"] += o
    return out


def _files(proj: Path, sid: str) -> list[Path]:
    if not proj.is_dir() or not valid_session_id(sid):
        return []
    found: list[Path] = []
    try:
        for d in sorted(proj.iterdir()):
            f = d / f"{sid}.jsonl"
            if f.is_file():
                found.append(f)
            sub = d / sid / "subagents"
            if sub.is_dir():
                found.extend(sorted(p for p in sub.glob("*.jsonl") if p.is_file()))
    except OSError:
        pass
    return found


def _add(total: dict, part: dict) -> None:
    for fam, v in part.items():
        t = total.setdefault(fam, {"in": 0, "out": 0})
        t["in"] += v["in"]
        t["out"] += v["out"]


def _usage(root: Path, ticket: dict, environ: Mapping[str, str] | None, cache: dict, live: set) -> dict:
    total: dict = {}
    bases: dict = {}
    for s in ticket.get("sessions") or []:
        if not isinstance(s, dict) or not isinstance(s.get("agent"), str):
            continue
        if s["agent"] not in bases:
            bases[s["agent"]] = _base(root, s["agent"], environ)
        base = bases[s["agent"]]
        if base is None:
            continue
        for f in _files(base, s.get("id")):
            try:
                st = f.stat()
            except OSError:
                continue
            key = str(f)
            live.add(key)
            sig = [st.st_size, st.st_mtime_ns]
            hit = cache.get(key)
            if not (isinstance(hit, dict) and hit.get("sig") == sig and isinstance(hit.get("use"), dict)):
                hit = {"sig": sig, "use": _read_file(f)}
                cache[key] = hit
            _add(total, hit["use"])
    return total


def ticket_usage(root: Path, ticket: dict, environ: Mapping[str, str] | None = None) -> dict:
    root = Path(root)
    cache = _load_cache(root)
    before = json.dumps(cache, sort_keys=True)
    out = _usage(root, ticket, environ, cache, set())
    if json.dumps(cache, sort_keys=True) != before:
        _save_cache(root, cache)
    return out


def _moved_up(ticket: dict) -> bool:
    return any(
        isinstance(h, dict) and str(h.get("text") or "").startswith(MOVED_UP)
        for h in ticket.get("history") or []
    )


def workspace_usage(root: Path, days: int = 30, environ: Mapping[str, str] | None = None) -> dict:
    root = Path(root)
    cutoff = (datetime.now(UTC) - timedelta(days=max(days, 0))).isoformat()
    cache = _load_cache(root)
    before = json.dumps(cache, sort_keys=True)
    live: set = set()
    rows, totals, moved, with_model = [], {}, 0, 0
    for t in tickets.list_all(root):
        if str(t.get("updated_at") or t.get("created_at") or "") < cutoff:
            continue
        m = t.get("model")
        name = m.get("name") if isinstance(m, dict) else None
        if name:
            with_model += 1
        use = _usage(root, t, environ, cache, live)
        if not use:
            continue
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
            }
        )
    rows.sort(key=lambda r: -r["total"])
    for k in [k for k in cache if k not in live and not Path(k).exists()]:
        del cache[k]
    if json.dumps(cache, sort_keys=True) != before:
        _save_cache(root, cache)
    return {
        "schema": SCHEMA,
        "days": days,
        "tickets": rows,
        "totals": totals,
        "moved_up": moved,
        "with_model": with_model,
    }


def _short(v: int) -> str:
    return f"{v / 1_000_000:.1f}M" if v >= 1_000_000 else f"{v / 1000:.1f}k" if v >= 1000 else str(v)


def text(data: dict, top: int = 5) -> str:
    if not data["tickets"]:
        return f"No model use in the last {data['days']} days."
    lines = [f"{f}: {_short(v['in'])} in, {_short(v['out'])} out" for f, v in sorted(data["totals"].items())]
    lines.append(f"Moved up to Opus: {data['moved_up']} of {data['with_model']} tickets with a model")
    lines.append("Most tokens:")
    lines += [f"  {r['key']}  {_short(r['total'])}  {r['title']}" for r in data["tickets"][:top]]
    return "\n".join(lines)

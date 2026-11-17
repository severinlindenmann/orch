"""One pass of the helper watcher (`orch run tend`, ORCH-78): what a person watching the helpers did by hand.

- Sessions stay open as long as possible, so the tool's prompt cache stays warm (ORCH-149). A live
  session at its prompt on a ticket that is Done or Dropped is ended after END_FINISHED_MINUTES. One on a
  ticket in Review or that only waits (on a person's answer, a time or another ticket) is ended early only
  when the sessions are full (runs_live._crowded); otherwise it stays open until the idle limit
  (workspace.live_idle_minutes, an hour). Its conversation stays on the ticket, so the answer, the time or
  a person's Continue resumes it, and the slot is free for the next ticket meanwhile. A ticket waiting on
  another ticket is started again here once that one is finished (nothing else promises that wake-up).
  Waiting on something outside (a release, a CI run) is no reason to end: such a helper gets the reminder.
- A live session idle at its prompt with nothing running for IDLE_MINUTES, on a ticket still being worked on,
  gets one message with what changed since it went quiet (ticket history, its pull request's last look, the
  open steps).
- When it is still idle near the idle limit (BEFORE_LIMIT ahead of it; the cache is gone by then) and nothing
  happened on the ticket since that message, its session is ended and the helper is started fresh from the
  ticket (at most once per RESTART_EVERY per ticket; after that the idle row in `orch needs` is for a person).
- Tickets waiting in line for a free slot start in priority order (runs_live.start_waiting).

Every action is a line in the ticket's history. Nothing happens while automation is paused (`orch pause`). No
daemon: a repeating automation script runs the pass. A session with input still waiting to go in, a running
command (a CI watcher, a test run) or a question on its screen is never touched.
"""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path

from orch import brake, history, runs, runs_live, runwatch, stuck, tickets

BY = "agent:helper-watcher"
VIA = "watcher"
IDLE_MINUTES = 20  # idle with nothing running, ticket still Working: one message
RESTART_MINUTES = 10  # at least this long after the message (and idle the full limit), nothing changed: fresh
END_WAITING_MINUTES = 5  # quiet this long while the ticket only waits and the sessions are full: it ends
END_FINISHED_MINUTES = 10  # quiet this long on a Done/Dropped ticket, or in Review when full
BEFORE_LIMIT = 5 * 60  # a stuck helper starts fresh this long before any `orch run` call closes it silently
GONE = ("done", "dropped")  # nothing is left: no reason to keep the session warm
RESTART_EVERY = 6 * 3600  # at most one fresh start per ticket in this time
FINISHED = runs_live.FINISHED
WAIT_KINDS = ("person", "time", "ticket")  # something wakes these; "external" gets the reminder instead
STATE_MAX = 256 * 1024


def _state_path(root: Path) -> Path:
    return runs.run_dir(root) / "tend.json"


def _read_state(root: Path) -> dict:
    try:
        p = _state_path(root)
        if p.stat().st_size > STATE_MAX:
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def _write_state(root: Path, state: dict) -> None:
    with contextlib.suppress(OSError):
        runs.run_dir(root).mkdir(parents=True, exist_ok=True)
        runs._atomic(_state_path(root), json.dumps(state, indent=1) + "\n")


def _ts(iso: str | None) -> float | None:
    try:
        return runs._parse(iso) if iso else None
    except (TypeError, ValueError):
        return None


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _clock(iso: str | None) -> str:
    t = _ts(iso)
    return time.strftime("%H:%M", time.localtime(t)) if t is not None else "?"


def _key(t: dict) -> str:
    return str(t.get("key") or t.get("id"))


def _what_changed(root: Path, t: dict, since: str | None) -> str:
    """The facts for the reminder: history since the helper went quiet, its pull requests, the open steps."""
    s = _ts(since) or 0
    lines = [
        f"- {_clock(h.get('at'))} {h.get('by')}: {' '.join(str(h.get('text') or '').split())[:160]}"
        for h in history.lines(root, t)
        if (_ts(h.get("at")) or 0) > s and h.get("by") != BY
    ][-5:]
    out = ["What changed on the ticket since you went quiet:"]
    out += lines or ["- nothing"]
    pulls = (stuck._read(root).get("pulls") or {}) if stuck.open_pulls(t) else {}
    for url in stuck.open_pulls(t)[:3]:
        seen = pulls.get(url)
        if not isinstance(seen, dict):
            out.append(f"Pull request {url}: not looked at yet.")
            continue
        state = str(seen.get("state") or "").lower()
        if state in ("merged", "closed"):
            word = state
        elif seen.get("green") is True:
            word = "every check passed, not merged"
        elif seen.get("green") is False:
            word = "a check failed or was cancelled"
        else:
            word = "checks not finished"
        at = _clock(_iso(seen["at"])) if isinstance(seen.get("at"), (int, float)) else "?"
        out.append(f"Pull request {url}: {word} (looked at {at}).")
    open_steps = [c for c in t.get("checklist") or [] if not c.get("done") and not c.get("wont_do")]
    if open_steps:
        out.append("Open tasks: " + "; ".join(f"{c['id']} {str(c.get('text'))[:80]}" for c in open_steps[:3]))
    return "\n".join(out)


def nudge_text(root: Path, t: dict, idle_secs: int | None, since: str | None) -> str:
    k = _key(t)
    return (
        f"The helper watcher: you have been idle at your prompt for {runwatch.span(idle_secs)} with nothing "
        f"running, and {k} is still being worked on.\n"
        + _what_changed(root, t, since)
        + f"\nCarry on with the next open task. If you wait on something, say so (orch wait or orch ask); if "
        f"you are finished, run orch ticket status {k} done. If nothing happens until it has been idle "
        f"for {runwatch.span(int(runs_live.idle_seconds(root)))}, this session is ended and a fresh one "
        "starts from the ticket."
    )


def restart_text(t: dict) -> str:
    return (
        f"The helper watcher started you fresh: the earlier session sat idle at its prompt and did not move "
        f"after a reminder. Read the ticket (orch ticket show {_key(t)}) and go on from the first open task."
    )


def _waits(info: dict) -> list[dict]:
    return info.get("waiting_on") or []


def plan(root: Path, now: float | None = None) -> list[dict]:
    """What a pass would do now, one row per live session that needs an action (read-only)."""
    now = time.time() if now is None else now
    state = _read_state(root)
    table = runwatch._table()
    limit = runs_live.idle_seconds(root)  # the idle limit: the cache is gone after it
    crowded = runs_live._crowded(root)
    out = []
    for rec in runs_live.records(root):
        if rec.get("mode") != "live" or runs.state(rec) != "alive" or rec.get("closing"):
            continue
        tid = rec["ticket"]
        live = rec.get("live") or {}
        if live.get("state") != "idle" or runs.undelivered(root, tid):
            continue  # working, starting, a question on its screen, or input on the way in
        try:
            t = tickets.load(root, tid)
        except Exception:  # noqa: BLE001, S112 - a broken ticket is never acted on
            continue
        if t.get("general") is True:
            continue  # Chat: a person talks to it
        info = runwatch.describe(root, tid, rec, table)
        waits = _waits(info)
        if any(w.get("kind") == "command" for w in waits):
            continue  # a CI watcher or a test run: it is waiting on purpose
        quiet = info.get("idle_seconds")
        if quiet is None:
            continue
        row = {"ticket": tid, "key": _key(t), "run": rec["run"], "idle_seconds": quiet, "rec": rec, "t": t}
        if t.get("status") in FINISHED:
            early = t.get("status") in GONE or crowded  # Review keeps its warm session unless full
            if quiet >= (END_FINISHED_MINUTES * 60 if early else limit):
                out.append({**row, "action": "end", "why": "finished"})
            continue
        kinds = [w["kind"] for w in waits if w.get("kind") in WAIT_KINDS]
        if kinds:
            if quiet >= (END_WAITING_MINUTES * 60 if crowded else limit):
                what = ", ".join(w["what"] for w in waits if w.get("kind") in WAIT_KINDS)
                out.append({**row, "action": "end", "why": "waiting", "waits": what})
            continue
        seen = state.get(tid) or {}
        nudged = _ts(seen.get("nudged_at")) if seen.get("run") == rec["run"] else None
        if nudged is None:
            if quiet >= IDLE_MINUTES * 60:
                out.append({**row, "action": "nudge", "since": info.get("idle_since")})
            continue
        helper = f"agent:{rec.get('agent')}"
        moved = any(
            (_ts(h.get("at")) or 0) > nudged and (h.get("by") == helper or history.is_person_line(h))
            for h in history.lines(root, t)
        )
        if moved:
            out.append({**row, "action": "forget"})  # it did something after the reminder: a new chance
            continue
        if now - nudged < RESTART_MINUTES * 60 or quiet < max(limit - BEFORE_LIMIT, RESTART_MINUTES * 60):
            continue
        last = _ts(seen.get("restarted_at"))
        if last is not None and now - last < RESTART_EVERY:
            if not seen.get("left"):
                out.append({**row, "action": "leave"})
            continue
        out.append({**row, "action": "restart"})
    return out + _wakes(root)


def _wakes(root: Path) -> list[dict]:
    """Tickets waiting on another ticket that is finished now, with no run: start them again."""
    out = []
    for t in tickets.list_all(root):
        w = t.get("waiting_on") if t.get("status") == "waiting" else None
        if not isinstance(w, dict) or w.get("kind") != "ticket" or runs.read(root, t["id"]):
            continue
        try:
            other = tickets.load(root, tickets.resolve(root, str(w.get("ref") or "")))
        except Exception:  # noqa: BLE001, S112 - an unknown ticket wakes nothing
            continue
        if other.get("status") in FINISHED:
            out.append(
                {
                    "ticket": t["id"], "key": _key(t), "action": "wake", "t": t,
                    "other": _key(other), "other_status": other.get("status"),
                }
            )  # fmt: skip
    return out


def wake_text(row: dict) -> str:
    word = {"review": "in Review", "done": "Done", "dropped": "Dropped"}.get(row["other_status"], "finished")
    return (
        f"The helper watcher: {row['other']}, the ticket you waited on, is {word} now. "
        f"Go on with {row['key']}."
    )


def _end(root: Path, row: dict) -> bool:
    rec = row["rec"]
    if not runs_live._claim_close(root, rec):
        return False  # it moved meanwhile
    try:
        runs_live._close(root, rec, interrupt=False)
    except Exception:  # noqa: BLE001 - the next pass tries again
        runs_live._unclaim_close(root, rec)
        return False
    return True


def _restart(root: Path, row: dict) -> str:
    """End the idle session and start the helper fresh. Returns what came of the start in plain words."""
    tid, t = row["ticket"], row["t"]
    if not _end(root, row):
        return ""
    runs.pending_add(root, tid, BY, "event", restart_text(t), VIA)
    try:
        r = runs.start(root, tid, runs_live.AUTOMATION_BY, fresh=True)
    except runs.Busy:
        return "it waits in line for a free slot"
    except Exception as e:  # noqa: BLE001 - the reason goes into the history
        return f"it could not start: {e}"
    return f"run {r['run']}"


def run(root: Path, dry_run: bool = False, now: float | None = None) -> dict:
    """One pass: {"paused": bool, "actions": [...], "queue": [...]}. dry_run only says what it would do."""
    now = time.time() if now is None else now
    if brake.paused(root) is not None:
        return {"paused": True, "actions": [], "queue": queue(root)}
    rows = plan(root, now)
    state = _read_state(root)
    done = []
    for row in rows:
        tid, action = row["ticket"], row["action"]
        public = {k: row[k] for k in ("ticket", "key", "action", "idle_seconds") if k in row}
        quiet = runwatch.span(row.get("idle_seconds"))
        if dry_run:
            done.append({**public, "done": False})
            continue
        line = ""
        if action == "end" and _end(root, row):
            if row["why"] == "finished":
                line = f"Ended the helper's session: the ticket is finished and it was quiet for {quiet}."
            else:
                line = (
                    f"Ended the helper's session while it waits on {row['waits']} (quiet for {quiet}); it "
                    "continues when that comes."
                )
            state.pop(tid, None)
        elif action == "nudge":
            runs_live.send(root, tid, BY, nudge_text(root, row["t"], row["idle_seconds"], row.get("since")))
            state[tid] = {"run": row["run"], "nudged_at": _iso(now)}
            line = f"Reminded the helper: idle for {quiet} with nothing running."
        elif action == "forget":
            state.pop(tid, None)
        elif action == "wake":
            tickets.wait(root, tid, None, None, BY, clear=True)  # it is Working again: never woken twice
            runs.pending_add(root, tid, BY, "event", wake_text(row), VIA)
            try:
                r = runs.start(root, tid, runs_live.AUTOMATION_BY)
                how = f"run {r['run']}"
            except runs.Busy:
                how = "it waits in line for a free slot"
            except Exception as e:  # noqa: BLE001 - the reason goes into the history
                how = f"it could not start: {e}"
            line = f"Started the helper again: {row['other']}, the ticket it waited on, is finished ({how})."
        elif action == "leave":
            state[tid] = {**state.get(tid, {}), "left": True}
            line = (
                "The helper is idle again after a reminder, and it was already started fresh in the last "
                f"{RESTART_EVERY // 3600} hours: left for a person."
            )
        elif action == "restart":
            how = _restart(root, row)
            if how:
                state[tid] = {"restarted_at": _iso(now)}
                line = (
                    f"Started the helper fresh: it stayed idle for {quiet} after a reminder and nothing "
                    f"changed ({how})."
                )
        if line:
            with contextlib.suppress(Exception):
                tickets.log(root, tid, line, BY)
        if line or action == "forget":
            done.append({**public, "done": True, "text": line})
    # tickets whose state is about a run that no longer exists: keep a restart time, drop the rest
    live_runs = {r["ticket"]: r["run"] for r in runs_live.records(root)}
    for tid in list(state):
        s = state[tid]
        if "nudged_at" in s and live_runs.get(tid) != s.get("run"):
            if "restarted_at" in s:
                state[tid] = {"restarted_at": s["restarted_at"]}
            else:
                state.pop(tid)
        elif "restarted_at" in s and now - (_ts(s["restarted_at"]) or 0) > RESTART_EVERY:
            state.pop(tid)
    if not dry_run:
        _write_state(root, state)
        started = runs_live.start_waiting(root)
        for tid in started:
            with contextlib.suppress(Exception):
                done.append({"ticket": tid, "key": runs_live.ref(root, tid), "action": "start", "done": True})
    return {"paused": False, "actions": done, "queue": queue(root)}


def queue(root: Path) -> list[dict]:
    """Tickets waiting in line for a free slot, in the order they will start."""
    return [
        {"ticket": tid, "key": runs_live.ref(root, tid), "priority": p}
        for tid, p in runs_live.waiting_line(root)
    ]


WORDS = {
    "end": "ended",
    "nudge": "reminded",
    "restart": "started fresh",
    "leave": "left for a person",
    "wake": "started again (the ticket it waited on is finished)",
}


def text(result: dict, dry_run: bool = False) -> str:
    if result["paused"]:
        return "Automation is paused here: the helper watcher did nothing. Turn it back on: orch resume."
    lines = []
    for a in result["actions"]:
        if a["action"] == "forget":
            continue
        if a["action"] == "start":
            lines.append(f"{a['key']}: started from the line")
        elif dry_run:
            lines.append(f"{a['key']}: would be {WORDS.get(a['action'], a['action'])}")
        else:
            lines.append(f"{a['key']}: {a.get('text') or WORDS.get(a['action'], a['action'])}")
    if result["queue"]:
        lines.append(
            "Waiting in line: " + ", ".join(f"{q['key']} ({q['priority']})" for q in result["queue"])
        )
    return "\n".join(lines) or "All helpers are fine: nothing to do."

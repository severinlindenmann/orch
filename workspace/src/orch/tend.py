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
- A helper that stopped right after its start (its first turn ended within EARLY_TURN_SECONDS, ORCH-190: it
  asked "shall I go ahead?" in its own window, where nobody reads it, and the tool showed a greyed-out "go
  ahead" in the box) gets that message after EARLY_IDLE_MINUTES instead, and is started fresh when it still
  has not moved EARLY_RESTART_MINUTES after it: no person needed, no wait for the idle limit.
- ORCH-318: a helper idle at its prompt with open steps (and no question, no wait, no running command) is sent
  on after OPEN_STEPS_SECONDS, whenever it stopped. The second time on one ticket, the ticket also moves up to
  Opus (a person's own model choice stays). This replaces the IDLE_MINUTES reminder for that case.
- When it is still idle near the idle limit (BEFORE_LIMIT ahead of it; the cache is gone by then) and nothing
  happened on the ticket since that message, its session is ended and the helper is started fresh from the
  ticket (at most once per RESTART_EVERY per ticket; after that the idle row in `orch needs` is for a person).
- Tickets waiting in line for a free slot start in priority order (runs_live.start_waiting).
- ORCH-179: a helper that stopped on the subscription's usage limit (the last answer in its saved conversation
  is the limit error, or its run ended on it) is noted with the reset time (limitstop). Until then nobody is
  reminded, started fresh or woken, and automatic starts wait in line; after it, each noted ticket that is
  still worked on starts again on its earlier conversation (a live session still at the limit is ended first).
  ORCH-642: the tool's own notice counts too ("Usage limit reached · continuing automatically at 7:10pm"),
  also when the session still shows as working (the tool ends such a turn without the Stop hook) for
  STUCK_WORKING_SECONDS. When the login changed meanwhile (Usage switched the account: "Automatic continue
  stopped · your login changed"), nothing continues it by itself: it gets one message to carry on at once
  (at most once per CARRY_AGAIN_SECONDS), and the hold is lifted for every other ticket too.

Every action is a line in the ticket's history. Nothing happens while automation is paused (`orch pause`). No
daemon: a repeating automation script runs the pass. A session with input still waiting to go in, a running
command (a CI watcher, a test run), helpers of its own still running in the background, a question on its
screen, or a person who typed to it in its window in the last bgwork.TALK_MINUTES is never touched (ORCH-267).
"""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path

from orch import adapters, bgwork, brake, history, limitstop, runs, runs_live, runwatch, stuck, tickets

BY = "agent:helper-watcher"
VIA = "watcher"
IDLE_MINUTES = 20  # idle with nothing running, ticket still Working: one message
EARLY_TURN_SECONDS = 5 * 60  # the first turn ended this soon after the start: it stopped instead of working
EARLY_IDLE_MINUTES = 3  # such a helper gets the message this soon
OPEN_STEPS_SECONDS = 45  # ORCH-318: idle with open steps, no question, no wait: sent on this soon
EARLY_RESTART_MINUTES = 5  # ... and is started fresh when nothing changed this long after it
RESTART_MINUTES = 10  # at least this long after the message (and idle the full limit), nothing changed: fresh
END_WAITING_MINUTES = 5  # quiet this long, waiting on a time or ticket (not a person), sessions full
END_FINISHED_MINUTES = 10  # quiet this long on a Done/Dropped ticket, or in Review when full
BEFORE_LIMIT = 5 * 60  # a stuck helper starts fresh this long before any `orch run` call closes it silently
GONE = ("done", "dropped")  # nothing is left: no reason to keep the session warm
RESTART_EVERY = 6 * 3600  # at most one fresh start per ticket in this time
FINISHED = runs_live.FINISHED
WAIT_KINDS = ("person", "time", "ticket")  # something wakes these; "external" gets the reminder instead
STATE_MAX = 256 * 1024
# ORCH-642: "working" this long with no hook: look whether it stopped on the limit
STUCK_WORKING_SECONDS = 2 * 60
CARRY_AGAIN_SECONDS = 10 * 60  # a carry-on that did not take is sent again after this


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


EARLY_WORDS = (
    "You stopped right after the start. Nobody reads this window: do not wait here for a go-ahead. "
    "Ask a person only with orch ask, otherwise carry on.\n"
)


def nudge_text(root: Path, t: dict, idle_secs: int | None, since: str | None, early: bool = False) -> str:
    k = _key(t)
    return (
        f"The helper watcher: you have been idle at your prompt for {runwatch.span(idle_secs)} with nothing "
        f"running, and {k} is still being worked on.\n"
        + (EARLY_WORDS if early else "")
        + _what_changed(root, t, since)
        + f"\nCarry on with the next open task. If you wait on something, say so (orch wait or orch ask); if "
        f"you are finished, run orch ticket status {k} done. If nothing happens until it has been idle "
        f"for {runwatch.span(EARLY_RESTART_MINUTES * 60 if early else int(runs_live.idle_seconds(root)))}"
        + (" more" if early else "")
        + ", this session is ended and a fresh one starts from the ticket."
    )


def _move_up(root: Path, tid: str, n: int) -> str:
    """The second early stop on one ticket: the small model is not carrying it, move it up to Opus."""
    try:
        t, moved = tickets.move_up(root, tid, f"the helper stopped with open tasks {n} times", BY)
    except Exception:  # noqa: BLE001 - a person's model choice (or a broken ticket) stays as it is
        return ""
    if not moved:
        return ""
    with contextlib.suppress(Exception):
        runs_live.switch_model(root, tid, "opus", BY)
    return " The ticket moved up to Opus."


def restart_text(t: dict) -> str:
    return (
        f"The helper watcher started you fresh: the earlier session sat idle at its prompt and did not move "
        f"after a reminder. Read the ticket (orch ticket show {_key(t)}) and go on from the first open task."
    )


def _early(rec: dict, since: str | None) -> bool:
    """The run went idle within EARLY_TURN_SECONDS of its start: its first turn ended before any real work."""
    start, idle = _ts(rec.get("started_at")), _ts(since)
    return start is not None and idle is not None and 0 <= idle - start <= EARLY_TURN_SECONDS


def _open_steps(t: dict) -> bool:
    return any(not c.get("done") and not c.get("wont_do") for c in t.get("checklist") or [])


def _queued_pr(root: Path, waits: list[dict]) -> bool:
    """The helper waits on a pull request in the merge queue: the queue writes its verdict on the ticket and
    wakes the helper, so it is left alone (no reminder, no fresh start) until the queue is done with it."""
    refs = [w.get("ref") for w in waits if w.get("kind") == "external" and w.get("ref")]
    if not refs:
        return False
    try:  # the add-on's queue file, read without the add-on: absent or damaged means nothing is queued
        data = json.loads((root / ".orch" / "addons" / "pull-requests" / "queue.json").read_text("utf-8"))
        rows = [r for r in data.get("entries") or [] if isinstance(r, dict)]
    except (OSError, ValueError, AttributeError):
        return False
    refs = {str(r).lower() for r in refs}
    return any(
        r.get("state") in ("waiting", "running") and str(r.get("url") or "").lower() in refs for r in rows
    )


def _waits(info: dict) -> list[dict]:
    return info.get("waiting_on") or []


def limit_of(root: Path, rec: dict) -> dict | None:
    """The usage-limit stop a live session shows (the last answer in its saved conversation), or None."""
    sid = rec.get("session")
    if not rec.get("agent"):
        return None
    if not isinstance(sid, str):  # ORCH-642: a live run record holds no session id; the ticket keeps it
        try:
            sid = tickets.sessions_for(
                root, rec["ticket"], tickets.load(root, rec["ticket"]), rec["agent"], runs.host()
            )
        except Exception:  # noqa: BLE001 - a broken ticket: no limit seen
            sid = None
        if not isinstance(sid, str):
            return None
    try:
        path = adapters.transcript_path(
            rec["agent"], sid, root, folder=runs.workdir_for(root, rec, rec["ticket"])
        )
    except Exception:  # noqa: BLE001 - an unknown tool or copy: no limit seen
        return None
    return limitstop.from_transcript(path)


def plan(root: Path, now: float | None = None) -> list[dict]:
    """What a pass would do now, one row per live session that needs an action (read-only)."""
    now = time.time() if now is None else now
    state = _read_state(root)
    table = runwatch._table()
    limit = runs_live.idle_seconds(root)  # the idle limit: the cache is gone after it
    crowded = runs_live._crowded(root)
    noted = limitstop.read(root).get("tickets") or {}
    held = limitstop.active(root, now) is not None
    out = []
    for rec in runs_live.records(root):
        if rec.get("mode") != "live" or runs.state(rec) != "alive" or rec.get("closing"):
            continue
        tid = rec["ticket"]
        live = rec.get("live") or {}
        since = _ts(live.get("since"))
        stuck_working = (
            live.get("state") == "working" and since is not None and now - since >= STUCK_WORKING_SECONDS
        )
        if live.get("state") in ("idle", "attention") or stuck_working:
            hit = limit_of(root, rec)
            if hit is not None and hit.get("switched"):
                # the account changed while it waited at the limit: carry it on now
                seen = state.get(f"carry:{tid}") or {}
                if seen.get("run") != rec["run"] or now - (_ts(seen.get("at")) or 0) >= CARRY_AGAIN_SECONDS:
                    key = runs_live.ref(root, tid)
                    out.append({"ticket": tid, "key": key, "run": rec["run"], "action": "carry", "rec": rec})
                continue
            if hit is not None and tid not in noted:
                # stopped on the usage limit: note it, nothing else until the reset
                key = runs_live.ref(root, tid)
                out.append({"ticket": tid, "key": key, "run": rec["run"], "action": "limit", "info": hit})
                continue
        if tid in noted:
            continue  # held until the reset; then _resumes starts it again
        if live.get("state") != "idle" or runs.undelivered(root, tid):
            continue  # working, starting, a question on its screen, or input on the way in
        try:
            t = tickets.load(root, tid)
        except Exception:  # noqa: BLE001, S112 - a broken ticket is never acted on
            continue
        if tickets.is_hidden(t):
            continue  # Chat, Manager, no-ticket sessions: a person talks to them; never nudged or ended
        info = runwatch.describe(root, tid, rec, table)
        waits = _waits(info)
        if any(w.get("kind") == "command" for w in waits):
            continue  # a CI watcher, a test run or its own background helpers: it is waiting on purpose
        if _queued_pr(root, waits):
            continue  # it waits on a pull request in the merge queue: the queue's verdict wakes it
        if bgwork.talking(root, rec, now):
            continue  # ORCH-267: a person typed to it in its window lately: never ended, restarted or nudged
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
            # a person may still answer (a mockup round): that session keeps its hour, full or not (ORCH-254)
            if quiet >= (END_WAITING_MINUTES * 60 if crowded and "person" not in kinds else limit):
                what = ", ".join(w["what"] for w in waits if w.get("kind") in WAIT_KINDS)
                out.append({**row, "action": "end", "why": "waiting", "waits": what})
            continue
        if held:
            continue  # the usage limit: a reminder or a fresh start would only stop on it again
        seen = state.get(tid) or {}
        nudged = _ts(seen.get("nudged_at")) if seen.get("run") == rec["run"] else None
        if nudged is None:
            early = _early(rec, info.get("idle_since"))
            open_steps = _open_steps(t)
            soon = OPEN_STEPS_SECONDS if open_steps else (EARLY_IDLE_MINUTES if early else IDLE_MINUTES) * 60
            if quiet >= soon:
                since = info.get("idle_since")
                out.append({**row, "action": "nudge", "since": since, "early": early, "open": open_steps})
            continue
        helper = f"agent:{rec.get('agent')}"
        moved = any(
            (_ts(h.get("at")) or 0) > nudged and (h.get("by") == helper or history.is_person_line(h))
            for h in history.lines(root, t)
        )
        if moved:
            out.append({**row, "action": "forget"})  # it did something after the reminder: a new chance
            continue
        if seen.get("early"):  # it stopped right after the start: no wait for the idle limit
            if now - nudged < EARLY_RESTART_MINUTES * 60 or quiet < EARLY_RESTART_MINUTES * 60:
                continue
        elif now - nudged < RESTART_MINUTES * 60 or quiet < max(limit - BEFORE_LIMIT, RESTART_MINUTES * 60):
            continue
        last = _ts(seen.get("restarted_at"))
        if last is not None and now - last < RESTART_EVERY:
            if not seen.get("left"):
                out.append({**row, "action": "leave"})
            continue
        out.append({**row, "action": "restart"})
    if held or any(r["action"] == "limit" for r in out):
        return out  # nothing is woken while the limit holds
    return out + _resumes(root, now) + _wakes(root)


def _resumes(root: Path, now: float) -> list[dict]:
    """Tickets that stopped on the usage limit, now that it reset: start them again where they stood. A ticket
    that is finished, waits on something that wakes it, or is worked on again already is only forgotten."""
    out = []
    for tid in limitstop.due(root, now):
        row: dict = {"ticket": tid, "key": tid, "action": "resume"}
        try:
            t = tickets.load(root, tid)
        except Exception:  # noqa: BLE001 - a ticket that is gone is forgotten
            out.append({**row, "action": "unlimit"})
            continue
        row.update(key=_key(t), t=t)
        rec = runs.read(root, tid)
        waits = runwatch.waiting_on(root, None, t, [])
        if t.get("status") in FINISHED or any(w.get("kind") in WAIT_KINDS for w in waits):
            out.append({**row, "action": "unlimit"})  # the answer, the time or the other ticket wakes it
            continue
        if rec and runs.state(rec) == "alive":
            if rec.get("mode") != "live" or limit_of(root, rec) is None:
                out.append({**row, "action": "unlimit"})  # it goes on already (a person, or a new turn)
                continue
            row["rec"] = rec
        out.append(row)
    return out


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


def _carry(root: Path, row: dict, now: float) -> str:
    """ORCH-642: the session waits at the limit and the account changed: mark it at its prompt (the tool
    ended the turn without the Stop hook) and send it on. The hold is lifted: the new account has room."""
    tid, rec = row["ticket"], row["rec"]
    runs_live._set_state(root, tid, rec["run"], "idle")
    limitstop.forget(root, [tid])
    limitstop.lift(root, now)
    r = runs_live.send(root, tid, BY, limitstop.switched_text())
    later = "" if r.get("delivered") else " It goes in when the session takes input."
    return "Sent the helper on: the account was switched while it waited at the usage limit." + later


SWITCH_KEY = "computer-switch"


def _computer_switch(root: Path, state: dict, now: float) -> list[dict]:
    """ORCH-943: another workspace's Usage (or this one's) switched the account on this computer. The logins
    belong to the computer, so the new account has room for every workspace: lift the limit hold here, and
    each noted ticket gets one line saying who switched. Sessions that stopped with "login changed" are
    carried on by plan()."""
    row = limitstop.computer_switch()
    n = row.get("n")
    if not isinstance(n, int):
        return []
    seen = (state.get(SWITCH_KEY) or {}).get("n")
    state[SWITCH_KEY] = {"n": n}
    if seen == n:
        return []
    if seen is None:  # the first look here: only a switch from the last minutes counts
        first = _ts(row.get("at") if isinstance(row.get("at"), str) else None)
        if first is None or now - first > limitstop.COMPUTER_SWITCH_FRESH:
            return []
    at = _ts(row.get("at") if isinstance(row.get("at"), str) else None)
    ticks = limitstop.read(root).get("tickets") or {}
    # only helpers held before that switch: a hold noted after it is about the new account's own limit
    noted = [t for t, v in ticks.items() if at is not None and (_ts_num(v) or 0) < at + 1]  # whole seconds
    if not noted:
        return []
    if len(noted) < len(ticks):  # a newer hold stays: start only the older ones again, one by one
        limitstop.forget(root, noted)
        for tid in noted:
            runs.pending_add(root, tid, BY, "event", limitstop.computer_switched_text(row), VIA)
        return [_restart_after_switch(root, tid, row) for tid in noted]
    limitstop.lift(root, now)
    line = limitstop.computer_switched_text(row)
    out = []
    for tid in noted:
        with contextlib.suppress(Exception):
            tickets.log(root, tid, line, BY)
        out.append(
            {"ticket": tid, "key": runs_live.ref(root, tid), "action": "switched", "done": True, "text": line}
        )
    return out


def _ts_num(v: object) -> float | None:
    at = v.get("at") if isinstance(v, dict) else None
    return float(at) if isinstance(at, (int, float)) and not isinstance(at, bool) else None


def _restart_after_switch(root: Path, tid: str, row: dict) -> dict:
    """A ticket held before the switch, while a newer hold stays for the others: start it again on its own."""
    try:
        r = runs.start(root, tid, runs_live.AUTOMATION_BY)
        how = f"run {r['run']}"
    except runs.Busy:
        how = "it waits in line for a free slot"
    except Exception as e:  # noqa: BLE001 - the reason goes into the history
        how = f"it could not start: {e}"
    line = f"{limitstop.computer_switched_text(row)} ({how})"
    with contextlib.suppress(Exception):
        tickets.log(root, tid, line, BY)
    return {"ticket": tid, "key": runs_live.ref(root, tid), "action": "switched", "done": True, "text": line}


def _resume(root: Path, row: dict) -> str:
    """Start a ticket again after the usage limit reset (ending its session first when it still sits at the
    limit). Returns the history line, or "" when its session could not be ended (the next pass tries
    again)."""
    tid = row["ticket"]
    if row.get("rec") and not _end(root, row):
        return ""
    data = limitstop.read(root)
    limitstop.forget(root, [tid])
    runs.pending_add(root, tid, BY, "event", limitstop.resume_text(row["key"], data), VIA)
    try:
        r = runs.start(root, tid, runs_live.AUTOMATION_BY)
        how = f"run {r['run']}"
    except runs.Busy:
        how = "it waits in line for a free slot"
    except Exception as e:  # noqa: BLE001 - the reason goes into the history
        how = f"it could not start: {e}"
    return f"Started the helper again: the usage limit reset at {limitstop.clock(data.get('until'))} ({how})."


def run(root: Path, dry_run: bool = False, now: float | None = None) -> dict:
    """One pass: {"paused": bool, "actions": [...], "queue": [...]}. dry_run only says what it would do."""
    now = time.time() if now is None else now
    if brake.paused(root) is not None:
        return {"paused": True, "actions": [], "queue": queue(root)}
    state = _read_state(root)
    done = []
    if not dry_run:
        done += _computer_switch(root, state, now)
    rows = plan(root, now)
    for row in rows:
        tid, action = row["ticket"], row["action"]
        public = {k: row[k] for k in ("ticket", "key", "action", "idle_seconds") if k in row}
        quiet = runwatch.span(row.get("idle_seconds"))
        if dry_run:
            done.append({**public, "done": False})
            continue
        line = ""
        if action == "limit":
            if limitstop.note(root, tid, row["info"], now):
                line = limitstop.stopped_text(row["info"])
        elif action == "unlimit":
            limitstop.forget(root, [tid])
        elif action == "carry":
            line = _carry(root, row, now)
            state[f"carry:{tid}"] = {"run": row["run"], "at": _iso(now)}
        elif action == "resume":
            line = _resume(root, row)
        elif action == "end" and _end(root, row):
            if row["why"] == "finished":
                line = f"Ended the helper's session: the ticket is finished and it was quiet for {quiet}."
            else:
                line = (
                    f"Ended the helper's session while it waits on {row['waits']} (quiet for {quiet}); it "
                    "continues when that comes."
                )
            state.pop(tid, None)
        elif action == "nudge":
            early = bool(row.get("early"))
            up = ""
            if row.get("open"):
                n = int((state.get(f"stops:{tid}") or {}).get("n") or 0) + 1
                state[f"stops:{tid}"] = {"n": n}
                if n >= 2:
                    up = _move_up(root, tid, n)
            text = nudge_text(root, row["t"], row["idle_seconds"], row.get("since"), early)
            runs_live.send(root, tid, BY, text)
            state[tid] = {"run": row["run"], "nudged_at": _iso(now), **({"early": True} if early else {})}
            line = f"Reminded the helper: idle for {quiet} with nothing running" + (
                ", right after its start." if early else "."
            )
            if row.get("open"):
                line = f"Sent the helper on: it stopped with open tasks (idle for {quiet}, stop {n})." + up
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
        if line or action in ("forget", "unlimit"):
            done.append({**public, "done": True, "text": line})
    # tickets whose state is about a run that no longer exists: keep a restart time, drop the rest
    live_runs = {r["ticket"]: r["run"] for r in runs_live.records(root)}
    for tid in list(state):
        s = state[tid]
        if tid.startswith("carry:"):
            if live_runs.get(tid[6:]) != s.get("run"):
                state.pop(tid)
            continue
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
    "limit": "held until the usage limit resets",
    "resume": "started again (the usage limit reset)",
    "carry": "sent on (the account was switched at the usage limit)",
    "switched": "no longer held (the account was switched on this computer)",
}


def text(result: dict, dry_run: bool = False) -> str:
    if result["paused"]:
        return "Automation is paused here: the helper watcher did nothing. Turn it back on: orch resume."
    lines = []
    for a in result["actions"]:
        if a["action"] in ("forget", "unlimit"):
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

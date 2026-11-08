"""Live runs: the agent runs interactively in its own tmux session, one per ticket.

  tmux -L orch-<hash8(workspace)> new-session -d -s <ticket id> -- orch run _wrap <run> --live -- <agent argv>

orch owns that tmux server (own socket), so a person's own tmux is never touched. The claim's pid is the pane
process (the wrapper). Input waits in the pending file and is pasted (bracketed paste, then a separate Enter)
only when the agent says it is idle (the wrapper then checks that it was submitted: watch_submit): the tool's
own hooks call `orch run event --kind idle`, a generic agent calls
`orch run done`. At most 4 live sessions per workspace. A session idle (or waiting for a person) for an
hour (workspace.live_idle_minutes; 10 minutes once the ticket is in Review, Done or Dropped, and such a
session does not count toward the limit), or on a ticket Done for that long, is closed on the next
`orch run` call (there is no daemon); its session id stays on the ticket, so the next start continues it.
Nothing here reads the screen to decide anything, with one exception: a run still "starting" (no hook has
fired) is checked against the adapter's live.screens (a screen the tool shows before it is up). The run's
own wrapper passes the harmless first-run ones (theme, notes, trust of the `orch init` folder) with the
adapter's keys, once each; any other (a login) and a start not up after STARTUP_SECONDS are shown as
waiting for a person instead of "working".
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from orch import adapters, procs, runs, tickets
from orch.errors import Refused

MAX_LIVE = 4
IDLE_SECONDS = 60 * 60
FINISHED_IDLE_SECONDS = 10 * 60  # a session on a ticket in Review, Done or Dropped closes after this
HARD_EXTRA = 4  # most sessions over the limit that finished tickets may keep open
FINISHED = ("review", "done", "dropped")
PASTE_DELAY = 0.3
STARTUP_SECONDS = 60
# Input pasted into a live session must be submitted. A tool that is still drawing (a resumed session right
# after its SessionStart hook) can drop the Enter and leave the text in its prompt box. The wrapper checks:
SUBMIT_CHECK_SECONDS = 2.0  # no sign the input went in: Enter once more
SUBMIT_WATCHDOG_SECONDS = 60.0  # still nothing: Enter a last time
SUBMIT_GIVE_UP_SECONDS = 90.0  # still unsent: end the session; the input waits for a one-step run
SUBMIT_QUIET_SECONDS = 30.0  # ... but only once the pane has not changed for this long
SUBMIT_POLL = 0.5
KINDS = ("session", "idle", "working", "attention")


def idle_seconds(root: Path | None = None) -> float:
    """How long a live session may wait before it is closed: [workspace] live_idle_minutes (default 60).
    ORCH_RUN_IDLE_SECONDS overrides it (tests)."""
    from orch import config

    try:
        return float(os.environ["ORCH_RUN_IDLE_SECONDS"])
    except (KeyError, ValueError):
        return config.live_idle_minutes(root) * 60.0


def available(adapter: dict) -> bool:
    """A live run needs a machine with tmux (not Windows) and an agent that can run interactively."""
    return bool(
        os.name != "nt"
        and shutil.which("tmux")
        and adapter.get("live")
        and adapter["capabilities"].get("interactive_tmux")
    )


def ref(root: Path, tid: str) -> str:
    """How a person names the ticket in a command: its key (DM1-12), else its id."""
    with contextlib.suppress(Exception):
        k = tickets.load(root, tid).get("key")
        if isinstance(k, str) and k:
            return k
    return tid


def socket_name(root: Path) -> str:
    return "orch-" + hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:8]


def target(tid: str) -> str:
    return f"={tid}:"  # exact session name, its only pane


def tmux(
    root: Path, *args: str, input: str | None = None, timeout: float = 20
) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "TMUX"}  # never nest in the person's own tmux
    return subprocess.run(
        ["tmux", "-L", socket_name(root), *args],
        input=input,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def session_exists(root: Path, tid: str) -> bool:
    return shutil.which("tmux") is not None and tmux(root, "has-session", "-t", target(tid)).returncode == 0


def records(root: Path) -> list[dict]:
    out = []
    d = runs.run_dir(root) / "tickets"
    for f in sorted(d.glob("t_*.json")) if d.is_dir() else []:
        rec = runs.read(root, f.stem)
        if rec:
            out.append(rec)
    return out


def _finished(root: Path, tid: str) -> bool:
    """True when the ticket is in Review, Done or Dropped: its session no longer needs a slot."""
    with contextlib.suppress(Exception):
        return tickets.load(root, tid).get("status") in FINISHED
    return False


def live_all(root: Path) -> list[dict]:
    """Every alive live run except the hidden General ticket's."""
    return [
        r
        for r in records(root)
        if r.get("mode") == "live" and runs.state(r) == "alive" and not tickets.is_general(root, r["ticket"])
    ]


def live_alive(root: Path) -> list[dict]:
    """Live runs that count against MAX_LIVE. A session that is idle or waiting for a person on a ticket in
    Review, Done or Dropped does not (it closes by itself after FINISHED_IDLE_SECONDS); a working or starting
    one does."""
    return [
        r
        for r in live_all(root)
        if not ((r.get("live") or {}).get("state") in ("idle", "attention") and _finished(root, r["ticket"]))
    ]


def _crowded(root: Path) -> bool:
    """So many live sessions are open that idle ones on finished tickets should make room."""
    return len(live_all(root)) >= MAX_LIVE


def _full(root: Path) -> bool:
    return len(live_alive(root)) >= MAX_LIVE or len(live_all(root)) >= MAX_LIVE + HARD_EXTRA


# ---------------------------------------------------------------- start


def _queue_for_slot(root: Path, tid: str, by: str, text: str) -> None:
    with runs.locked(root, tid):
        runs._pending_add_locked(root, tid, by, "event", text, "slots", None)


def start_live(
    root: Path, tid: str, by: str, name: str, *, fresh: bool, take_over: bool, busy_text: str
) -> dict:
    cur = runs.read(root, tid)
    mine = cur is not None and runs.state(cur) == "alive"
    if not mine and _full(root):
        _queue_for_slot(root, tid, by, busy_text)
        n = (
            MAX_LIVE if len(live_alive(root)) >= MAX_LIVE else MAX_LIVE + HARD_EXTRA
        )  # name the limit that was really hit
        raise runs.Busy(
            f"{n} live sessions are open here, the most at once. Your request for {tid} is saved and "
            f"starts when one closes. To close one: orch run stop <ticket>",
            {"pending": True, "limit": n},
        )
    if not mine and session_exists(root, tid):
        tmux(root, "kill-session", "-t", target(tid))  # left over from a crash: the claim is gone
    rec = runs.claim(root, tid, by, name, "live", take_over=take_over, busy_text=busy_text)
    run = rec["run"]
    # never blocks a start: a screen the tool still shows is explained by check_starting
    with contextlib.suppress(Exception):
        adapters.trust_folder(name, root)
    hooks_path = runs.run_dir(root) / f"hooks-{run}.json"
    try:
        hooks = adapters.hooks_doc(name, run, root)
        if hooks:
            runs._atomic(hooks_path, json.dumps(hooks, indent=2) + "\n", 0o600)
        p = runs.plan(root, tid, fresh=fresh, mode="live", agent=name, hooks_file=str(hooks_path))
        # the first input is the prompt: queued like any other input, pasted when the agent is ready
        with runs.locked(root, tid):
            runs._pending_add_locked(root, tid, by, "text", p["prompt"], "start", None)
            runs.mark_delivered_locked(root, tid, p["item_ids"])  # those are inside the prompt now
        cmd = procs.orch_python_argv("run", "_wrap", run, "--ticket", tid, "--agent", name, "--live")
        if p["session"] and not p["resumed"]:
            cmd += ["--new-session", p["session"]]
        # The agent gets the environment of whoever starts this run, not of whoever started the tmux server.
        # It travels in a private file (never in argv, where `ps` shows it); the wrapper reads and removes it.
        env_file = runs.run_dir(root) / f"env-{run}.json"
        runs._atomic(env_file, json.dumps(runs._agent_environ()), 0o600)
        cmd += ["--env-file", str(env_file), "--"] + p["argv"]
        r = tmux(
            root, "new-session", "-d", "-P", "-F", "#{pane_pid}", "-x", "200", "-y", "50",
            "-s", tid, "-c", str(root), "--", *cmd,
        )  # fmt: skip
        if r.returncode != 0:
            raise Refused(f"tmux could not start the session: {r.stderr.strip() or 'unknown error'}")
        runs.set_process(
            root, tid, run, int(r.stdout.strip()),
            tmux={"socket": socket_name(root), "session": tid},
            live={"state": "starting", "since": tickets.now()},
        )  # fmt: skip
    except BaseException:
        runs.release(root, tid, run)
        hooks_path.unlink(missing_ok=True)
        (runs.run_dir(root) / f"env-{run}.json").unlink(missing_ok=True)
        with contextlib.suppress(Exception):
            tmux(root, "kill-session", "-t", target(tid))
        raise
    return {
        **{k: p[k] for k in ("agent", "adapter", "mode", "resumed", "session")},
        "tmux": {"socket": socket_name(root), "session": tid},
        "run": run,
        "log": None,
    }


# ---------------------------------------------------------------- input and idle


_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")  # keeps \n and \t only


def clean(text: str) -> str:
    """Text is data: no escape sequences or other control characters reach the agent's terminal."""
    return _CONTROL.sub("", text)


# ---------------------------------------------------------------- the notice line
#
# orch never types or pastes a person's text into the agent's screen. It types ONE short fixed ASCII line
# (the notice), then Enter as its own key; the agent reads the input itself with `orch run input <ticket>`,
# and that read is what marks it delivered. So nothing a person wrote can end a bracketed paste, be collapsed
# by the tool, or answer a dialog; and "delivered" means the agent really has it.

QUICK = 3  # tmux timeout on the submit-check path: a hung tmux never keeps the wrapper waiting long
NONE_POLLS = 20  # checks in a row that could not tell (a dialog, copy mode): counted like "still unsent"
NUDGES = 2  # notices for the same waiting input the agent took but did not read; then a one-step run
_ASCII = re.compile(r"[^\x20-\x7e]")


def notice_line(tid: str, start: bool) -> str:
    """The only text orch types into a live session. ASCII, one line, no person's words."""
    if start:
        text = f"Your task for orch ticket {tid} is ready. Read it with: orch run input {tid}"
    else:
        text = f"New input on orch ticket {tid}. Read it with: orch run input {tid}"
    return _ASCII.sub("", clean(text))


def input_text(items: list[dict]) -> str:
    """What `orch run input` prints: a start prompt as it is, everything else as '- <by>: <text>'."""
    start = [i["text"] for i in items if i.get("via") == "start"]
    rest = [i for i in items if i.get("via") != "start"]
    parts = start[-1:]  # a newer start prompt replaces an older one
    if rest:
        parts.append("New input:\n" + "\n".join(f"- {i['by']}: {i['text']}" for i in rest))
    return "\n\n".join(parts)


def _type_line(root: Path, tid: str, line: str, timeout: float = 20) -> bool:
    """The notice as literal keys (send-keys -l: no key names, no paste), then Enter as its own key."""
    if tmux(root, "send-keys", "-t", target(tid), "-l", line, timeout=timeout).returncode != 0:
        return False
    time.sleep(PASTE_DELAY)
    _enter(root, tid, timeout)
    return True


def _enter(root: Path, tid: str, timeout: float = 20) -> bool:
    return tmux(root, "send-keys", "-t", target(tid), "Enter", timeout=timeout).returncode == 0


def deliver(root: Path, tid: str) -> int:
    """Tell the agent input waits, once, if (and only if) it said it is idle: type the notice line. Returns
    how many items wait. The items stay undelivered until the agent reads them (read_input)."""
    with runs.locked(root, tid):
        rec = runs.read(root, tid)
        if not rec or rec.get("mode") != "live" or (rec.get("live") or {}).get("state") != "idle":
            return 0
        if rec.get("closing"):  # an idle close is under way: the item waits for the next start
            return 0
        items = runs.undelivered(root, tid)
        if not items or not session_exists(root, tid):
            return 0
        old = rec.get("submit") or {}
        nudges = int(old.get("nudges") or 0)
        if nudges >= NUDGES:  # it took the notice and went idle without reading, twice: the wrapper ends it
            if not old.get("stale"):
                rec["submit"] = {**old, "stale": True}
                runs._write(root, rec)
            return 0
        line = notice_line(tid, any(i.get("via") == "start" for i in items))
        if not _type_line(root, tid, line):
            return 0
        rec = runs.read(root, tid) or rec
        rec["live"] = {"state": "working", "since": tickets.now()}
        rec["renewed_at"] = tickets.now()
        rec["submit"] = {"at": tickets.now(), "line": line, "enters": 1, "nudges": nudges + 1}
        runs._write(root, rec)
        return len(items)


def read_input(root: Path, tid: str, run: str | None) -> tuple[str, int]:
    """`orch run input`: the agent reads what waits for it; this is what marks it delivered."""
    with runs.locked(root, tid):
        rec = runs.read(root, tid)
        if run and rec and rec["run"] != run:
            raise Refused(f"Another run works on {tid} now.")
        items = runs.undelivered(root, tid)
        if items:
            runs.mark_delivered_locked(root, tid, [i["id"] for i in items])
        rec = runs.read(root, tid)
        if rec and rec.get("mode") == "live" and (not run or rec["run"] == run):
            rec.pop("submit", None)  # the agent has it: nothing more to check or type
            rec["live"] = {"state": "working", "since": tickets.now()}
            rec["renewed_at"] = tickets.now()
            runs._write(root, rec)
    if items:
        runs.notify_working(root)
    return input_text(items), len(items)


def _squeeze(text: str) -> str:
    return "".join(text.split())


def _log_submit(root: Path, tid: str, run: str, what: str) -> None:
    with contextlib.suppress(OSError):
        f = runs.run_dir(root) / "live-submit.log"
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(f"{tickets.now()} {tid} {run} {what}\n")


_BORDER = re.compile(r"^\s*[╭╰┌└]?[─━═]{20,}[╮╯┐┘]?\s*$")


def _box_rows(lines: list[str], cy: int) -> tuple[int, int]:
    """The prompt box: the rows between the last two border lines when the tool draws them, else the cursor
    line and the two above it."""
    borders = [i for i, ln in enumerate(lines) if _BORDER.match(ln)]
    if len(borders) >= 2:
        return borders[-2] + 1, borders[-1]
    return max(0, cy - 2), cy + 1


def _look(root: Path, tid: str, line: str, dialog: str | None) -> tuple[bool | None, str]:
    """(unsent, pane hash). unsent: True when the notice line still sits in the prompt box, False when it does
    not, None when that cannot be told safely: copy mode, the tool's dialog shows outside the box (an Enter
    would answer it), or tmux failed."""
    pane = tmux(root, "capture-pane", "-p", "-t", target(tid), timeout=QUICK)
    if pane.returncode != 0:
        return None, ""
    digest = hashlib.sha256(pane.stdout.encode("utf-8")).hexdigest()[:16]
    d = tmux(root, "display-message", "-p", "-t", target(tid), "#{pane_in_mode} #{cursor_y}", timeout=QUICK)
    try:
        in_mode, y = d.stdout.split()
        cy = int(y)
    except ValueError:
        return None, digest
    if d.returncode != 0 or in_mode != "0":
        return None, digest
    lines = pane.stdout.split("\n")
    a, b = _box_rows(lines, cy)
    outside = [ln for ln in lines[:a] + lines[b:] if ln.strip()]
    if dialog and re.search(dialog, "\n".join(outside[-15:]), re.IGNORECASE | re.MULTILINE):
        return None, digest
    return _squeeze(line) in _squeeze("".join(lines[a:b])), digest


def check_submit(
    root: Path, tid: str, run: str, now: float | None = None, end=None, guard=None, stop=None
) -> str | None:
    """A notice line with no sign the agent took it. Enter is sent again only while the line still sits in the
    prompt box and no dialog shows: after SUBMIT_CHECK_SECONDS, and a last time after SUBMIT_WATCHDOG_SECONDS
    (each re-checked right before the key). The input is given up on (put back with live_retry: the next start
    works one step at a time; `end` ends the session) after SUBMIT_GIVE_UP_SECONDS with the pane unchanged for
    SUBMIT_QUIET_SECONDS and the line still there (or NONE_POLLS checks in a row that could not tell), or when
    the agent took the notice twice and never read the input (stale). The agent reading its input
    (`orch run input`) ends all of this. guard/stop: the wrapper's in-process lock and stop flag (the SIGTERM
    handler takes the guard; after stop nothing is written). Returns "enter", "gave_up" or None."""
    with guard if guard is not None else contextlib.nullcontext():
        if stop is not None and stop.is_set():
            return None
        return _check_submit(root, tid, run, time.time() if now is None else now, end, stop)


def _check_submit(root: Path, tid: str, run: str, t: float, end, stop) -> str | None:
    with runs.locked(root, tid):
        rec = runs.read(root, tid)
        if not rec or rec["run"] != run or rec.get("mode") != "live" or not rec.get("submit"):
            return None
        s = dict(rec["submit"])
        try:
            age = t - runs._parse(s["at"])
        except (KeyError, ValueError):
            return None
        if s.get("stale"):
            stuck = True
            unsent = None
        else:
            if age < SUBMIT_CHECK_SECONDS or not session_exists(root, tid):
                return None
            dialog = (adapters.load(rec["agent"], root).get("live") or {}).get("dialog")
            unsent, digest = _look(root, tid, s.get("line") or "", dialog)
            if digest and digest != s.get("pane"):
                s["pane"], s["quiet"] = digest, runs._iso(t)
            quiet = t - runs._parse(s.get("quiet") or s["at"])
            s["unknown"] = int(s.get("unknown") or 0) + 1 if unsent is None else 0
            enters = int(s.get("enters") or 1)
            stuck = (
                age >= SUBMIT_GIVE_UP_SECONDS
                and quiet >= SUBMIT_QUIET_SECONDS
                and ((s.get("watchdog") and unsent is True) or s["unknown"] >= NONE_POLLS)
            )
        did = None
        if (
            not stuck
            and unsent is True
            and not s.get("watchdog")
            and (enters == 1 or age >= SUBMIT_WATCHDOG_SECONDS)
        ):
            again, _ = _look(root, tid, s.get("line") or "", dialog)  # the screen may have changed meanwhile
            if again is True and _enter(root, tid, QUICK):
                s["enters"] = enters + 1
                if age >= SUBMIT_WATCHDOG_SECONDS:
                    s["watchdog"] = True
                did = "enter"
                _log_submit(
                    root,
                    tid,
                    run,
                    f"Enter again ({s['enters']}): the notice still sat in the box at {int(age)} s",
                )
        elif (
            not stuck
            and age >= SUBMIT_GIVE_UP_SECONDS + 60
            and not s.get("noisy")
            and quiet < SUBMIT_QUIET_SECONDS
        ):
            s["noisy"] = True
            _log_submit(root, tid, run, "the pane never goes quiet: no give-up while it changes")
        if stop is not None and stop.is_set():
            return None  # the wrapper is ending: no write after stop
        if stuck:
            _give_up_locked(root, rec)
        else:
            if s != rec["submit"]:
                rec["submit"] = s
                runs._write(root, rec)
            return did
    label = adapters.load(rec["agent"], root)["label"]
    with contextlib.suppress(Exception):
        tickets.log(
            root,
            tid,
            f"{label} did not take the new input in its live session, so the session was closed. "
            "The input is kept and goes in with the next start, one step at a time.",
            f"agent:{rec['agent']}",
        )
    _log_submit(root, tid, run, "gave up: the agent did not take the notice; input queued for a one-step run")
    if end is not None:
        end()
    return "gave_up"


def _give_up_locked(root: Path, rec: dict) -> None:
    """Under the run lock: the waiting input gets live_retry (the next start is one step at a time); a start
    prompt is dropped (the next start builds it again), and if nothing else waits, a note item is queued so
    the next start is one step too. Never lost, never a live loop."""
    tid = rec["ticket"]
    items = runs._pending_read(root, tid)
    back = False
    for i in items:
        if i.get("delivered_at"):
            continue
        if i.get("via") == "start":
            i["delivered_at"] = tickets.now()
        else:
            i["live_retry"] = True
            back = True
    runs._pending_write(root, tid, items)
    if not back:
        note = runs._pending_add_locked(
            root, tid, "orch", "event",
            "The live session did not take its task. Continue the work on this ticket.",
            "live_retry", None,
        )  # fmt: skip
        items = runs._pending_read(root, tid)
        for i in items:
            if i["id"] == note["id"]:
                i["live_retry"] = True
        runs._pending_write(root, tid, items)
    rec.pop("submit", None)
    rec["live_retry"] = True
    rec["pending"] = True
    rec["stop_requested"] = tickets.now()  # our own end, set before the agent is ended
    runs._write(root, rec)


def watch_submit(root: Path, tid: str, run: str, proc: subprocess.Popen, guard=None, stop=None) -> None:
    """In the pane's wrapper, for the whole session: check_submit while a notice waits to be taken."""
    while proc.poll() is None and not (stop is not None and stop.is_set()):
        time.sleep(SUBMIT_POLL)
        try:
            rec = runs.read(root, tid)
            if not rec or rec["run"] != run:
                return
            if rec.get("submit"):
                check_submit(root, tid, run, end=proc.terminate, guard=guard, stop=stop)
        except Exception:  # never take the wrapper down
            continue


def _set_state(root: Path, tid: str, run: str, state: str) -> bool:
    with runs.locked(root, tid):
        rec = runs.read(root, tid)
        if not rec or rec["run"] != run:
            return False
        rec["live"] = {"state": state, "since": tickets.now()}
        if state in ("idle", "working"):
            rec["up"] = True  # the tool has been up: a later notice is never a first-run screen
        rec["renewed_at"] = tickets.now()
        rec.pop("maybe_stale_since", None)
        runs._write(root, rec)
        return True


def find_run(root: Path, run: str | None, tid: str | None) -> dict | None:
    if tid:
        rec = runs.read(root, tid)
        return rec if rec and (not run or rec["run"] == run) else None
    for rec in records(root):
        if rec["run"] == run:
            return rec
    return None


def idle_notice(agent: str, root: Path, payload: dict | None) -> bool:
    """True when an attention hook's input says the tool waits at its prompt (adapter `live.idle_notice`)."""
    rule = (adapters.load(agent, root).get("live") or {}).get("idle_notice")
    if not rule or not isinstance(payload, dict):
        return False
    # the first field the tool sent decides (a typed notice type wins over free message text)
    val = next((payload[f] for f in rule["fields"] if isinstance(payload.get(f), str)), None)
    return val is not None and re.search(rule["match"], val, re.IGNORECASE) is not None


def event(
    root: Path,
    kind: str,
    run: str | None,
    tid: str | None,
    session_id: str | None,
    payload: dict | None = None,
) -> int:
    """From a tool hook (session | idle | working | attention). Quiet when nothing matches: a hook must never
    fail. An attention hook that is the tool's own "waiting for your input" notice counts as idle."""
    if kind not in KINDS:
        raise Refused(f"The event kind must be one of: {', '.join(KINDS)}.")
    rec = find_run(root, run, tid)
    if not rec or rec.get("mode") != "live":
        return 0
    tid, run = rec["ticket"], rec["run"]

    def up(state: str) -> None:
        # tool is up: resume after the state is written (else check_starting could win), for this run
        if _set_state(root, tid, run, state):
            tickets.resume_after_start_wait(root, tid, f"agent:{rec['agent']}")

    if kind == "session":
        if session_id and adapters.SESSION_RE.match(session_id):
            tickets.record_session(root, tid, rec["agent"], session_id, runs.host())
        up("idle")  # the tool is up and waiting for its first input
    elif kind == "idle":
        up("idle")
    elif kind == "attention" and idle_notice(rec["agent"], root, payload):
        # "still waiting for your input": input may go in only if the run is idle already (after Stop); in any
        # other state (a dialog may be open) nothing changes, and the next Stop sets idle.
        return deliver(root, tid)
    elif kind == "working":  # a prompt went in (also one a person typed in the live session): never paste now
        up("working")
        return 0
    else:  # a permission prompt or any other notice: a person answers it; nothing is pasted
        _set_state(root, tid, run, "attention")
        return 0
    return deliver(root, tid)


def pass_answer(root: Path, tid: str, q: dict, by: str) -> dict | None:
    """A person answered. An agent works on the ticket: the answer goes to it like a message (live: pasted
    when it is idle). None works on it: the agent that asked is started again on the ticket (its own session
    resumed when there is one) once no question of it is open any more, so nobody has to press Continue.
    An agent's own answer, or an add-on's question, starts nothing. Returns the start result, if any."""
    if by.startswith("agent:"):
        return None
    rec = runs.read(root, tid)
    if rec and runs.state(rec) == "alive":
        send(root, tid, by, f"Answer to your question {q['id']} ({q['text']}): {q['answer']}", "answer")
        return None
    return resume_after_answer(root, tid, q, by)


def _asker(ticket: dict, qid: str) -> str | None:
    """The agent name that asked qid (the exact line `orch ask` writes), else None."""
    for h in ticket.get("history") or []:
        who = str(h.get("by", ""))
        if who.startswith("agent:") and re.fullmatch(rf"Asked {re.escape(qid)}, waiting", str(h.get("text"))):
            return who.partition(":")[2]
    return None


def resume_after_answer(root: Path, tid: str, q: dict, by: str) -> dict | None:
    ticket = tickets.load(root, tid)
    asker = _asker(ticket, q["id"]) if q.get("kind") in (None, "plain") else None
    if not asker or ticket.get("status") in ("done", "dropped") or tickets._open_questions(ticket):
        return None  # tickets.answer left it Ready (not Working): nobody works on it
    try:
        adapters.load(asker, root)
    except Refused:
        asker = None  # not a registry name (e.g. an add-on's agent:<name>): the folder's agent goes on
    try:
        return runs.start(root, tid, by, agent=asker)
    except Refused as e:  # no agent set, sessions full (queued), ...: the answer is saved either way
        with contextlib.suppress(Exception):
            tickets.log(root, tid, f"The agent could not be started again after the answer: {e}", "orch")
        return None


def send(root: Path, tid: str, by: str, text: str, kind: str = "message") -> dict:
    tickets.load(root, tid)
    item = runs.pending_add(root, tid, by, kind, text)
    rec = runs.read(root, tid)
    if not rec or runs.state(rec) != "alive":
        return {"id": item["id"], "delivered": 0, "state": "none"}
    n = deliver(root, tid) if rec.get("mode") == "live" else 0
    rec = runs.read(root, tid) or rec
    return {"id": item["id"], "delivered": n, "state": (rec.get("live") or {}).get("state", rec["mode"])}


def send_text(result: dict, tid: str) -> str:
    if result["delivered"]:
        return "Sent."
    if result["state"] == "none":
        return f"Saved. Nothing is working on {tid} now; it goes in when you start it: orch run start {tid}"
    return "Saved. It goes in when the agent is done with this step."


# ---------------------------------------------------------------- attach, stop, cleanup


def attach(root: Path, tid: str, watch: bool) -> None:
    rec = runs.read(root, tid)
    if rec and rec.get("mode") != "live" and runs.state(rec) == "alive":
        log = f" Or follow its output: tail -f {rec['log']}" if rec.get("log") else ""
        raise Refused(
            f"The agent on {tid} works one step at a time, so there is no live session to open. "
            f"Watch it in Focus: orch focus open {tid}.{log}"
        )
    if not rec or rec.get("mode") != "live" or not session_exists(root, tid):
        why = "" if shutil.which("tmux") else " Live sessions need tmux, which is not installed here."
        raise Refused(f"No live session on {tid}.{why} Start one: orch run start {tid}")
    env = {k: v for k, v in os.environ.items() if k != "TMUX"}
    argv = ["tmux", "-L", socket_name(root), "attach", "-t", target(tid)] + (["-r"] if watch else [])
    os.execvpe("tmux", argv, env)


def _close(root: Path, rec: dict, interrupt: bool) -> None:
    """End the agent, its tmux session and the claim. The work done stays; so does the session id."""
    tid, run = rec["ticket"], rec["run"]
    now = runs.read(root, tid)
    if now and now["run"] != run:
        return  # a new run took over meanwhile: it is not ours to stop
    if rec.get("mode") == "live" and session_exists(root, tid):
        if interrupt:
            for k in adapters.load(rec["agent"], root).get("live", {}).get("interrupt_keys") or []:
                tmux(root, "send-keys", "-t", target(tid), k)
            time.sleep(PASTE_DELAY)
        tmux(root, "kill-session", "-t", target(tid))
    for pid, started in (
        (rec.get("pid"), rec.get("pid_started")),
        (rec.get("agent_pid"), rec.get("agent_pid_started")),
    ):
        now = runs.read(root, tid)
        if now and now["run"] != run:
            return
        if runs._running(pid, started):
            runs.kill_tree(pid)
    runs.release(root, tid, run)
    runs.settle(root, tid, f"agent:{rec.get('agent')}", ignore_input=True)  # what waits stays queued
    (runs.run_dir(root) / f"hooks-{run}.json").unlink(missing_ok=True)


def stop(root: Path, tid: str) -> bool:
    with runs.locked(root, tid):  # the run we stop is the one that holds the claim now
        rec = runs.read(root, tid)
        if rec:
            rec["stop_requested"] = tickets.now()
            runs._write(root, rec)
    if not rec:
        if session_exists(root, tid):  # a session without a claim: nothing may be left running
            tmux(root, "kill-session", "-t", target(tid))
            return True
        return False
    _close(root, rec, interrupt=True)
    start_waiting(root)
    return True


def cleanup(root: Path) -> list[str]:
    """Close live sessions that have waited (idle, or for a person) for more than the limit, or whose ticket
    has been Done that long (no daemon: this runs on every `orch run` call), and remove tmux sessions whose
    claim is gone. The limit is [workspace] live_idle_minutes, an hour by default: the tool's prompt cache
    is gone by then. The session id stays on the ticket, so Continue resumes."""
    limit = idle_seconds(root)
    closed = []
    for rec in records(root):
        if rec.get("mode") != "live":
            continue
        live = rec.get("live") or {}
        tid = rec["ticket"]
        st = runs.state(rec)
        if st == "dead":
            if session_exists(root, tid):
                tmux(root, "kill-session", "-t", target(tid))
            continue
        if st == "alive" and (
            live.get("state") == "starting" or (live.get("state") == "attention" and not live.get("why"))
        ):
            check_starting(root, rec)  # a login/trust screen also hides behind a tool notice (attention)
            if live.get("state") == "starting":
                continue
        if st != "alive" or live.get("state") not in ("idle", "attention") or runs.undelivered(root, tid):
            continue
        try:
            idle = time.time() - runs._parse(live["since"])
        except (KeyError, ValueError):
            continue
        # A finished ticket's idle session closes early only when the sessions are full; else it stays warm
        # the full hour, so Continue on a Review ticket keeps its session (fb4). Attention keeps the hour.
        short = live.get("state") == "idle" and _finished(root, tid) and _crowded(root)
        lim = min(limit, FINISHED_IDLE_SECONDS) if short else limit
        if (idle > lim or _done_for(root, tid, limit)) and _claim_close(root, rec, short and idle <= limit):
            try:
                _close(root, rec, interrupt=False)
            except Exception:  # the close failed: input may go in again; the next cleanup tries again
                _unclaim_close(root, rec)
                continue
            closed.append(tid)
    start_waiting(root)  # a ticket that moved to Review/Done/Dropped may have freed a slot
    return closed


def _claim_close(root: Path, rec: dict, needs_finished: bool = False) -> bool:
    """Right before an idle close: under the run lock, the run must still be the same, still idle (or waiting
    for a person) since the same moment, with nothing waiting to go in. It is then marked closing, so
    deliver() pastes nothing more into it; a message sent meanwhile stays waiting for the next start."""
    tid = rec["ticket"]
    with runs.locked(root, tid):
        now = runs.read(root, tid)
        if not now or now["run"] != rec["run"] or runs.state(now) != "alive":
            return False
        if (now.get("live") or {}) != (rec.get("live") or {}) or runs.undelivered(root, tid):
            return False
        if needs_finished and not _finished(root, tid):  # sent back to Working meanwhile
            return False
        now["closing"] = tickets.now()
        runs._write(root, now)
    return True


def _unclaim_close(root: Path, rec: dict) -> None:
    with runs.locked(root, rec["ticket"]):
        now = runs.read(root, rec["ticket"])
        if now and now["run"] == rec["run"] and now.pop("closing", None):
            runs._write(root, now)


def _done_for(root: Path, tid: str, limit: float) -> bool:
    """True when the ticket has been Done for longer than limit seconds."""
    with contextlib.suppress(Exception):
        t = tickets.load(root, tid)
        if t.get("status") == "done":
            return time.time() - runs._parse(t["updated_at"]) > limit
    return False


def check_starting(
    root: Path, rec: dict, now: float | None = None, answered: list[str] | None = None
) -> str | None:
    """A live run whose tool has not said it is up: if its pane shows a screen the adapter knows that waits
    for a person, or it is still not up after STARTUP_SECONDS, mark it as waiting for a person, with why.

    Only the run's own wrapper passes `answered` (see watch_start): it then answers a harmless first-run
    screen (adapter live.screens with answer) by sending those keys to this run's own pane, at most once per
    screen per run. A folder-trust screen is answered only for the folder set up with `orch init` (its
    consent), and only when the screen names that folder. A login or any other screen is never answered.
    The tool's own hooks set the state again once it is up."""
    tid, run = rec["ticket"], rec["run"]
    try:
        age = (time.time() if now is None else now) - runs._parse((rec.get("live") or {})["since"])
    except (KeyError, ValueError):
        return None
    if age < 3:
        return None
    pane = tmux(root, "capture-pane", "-p", "-t", target(tid)) if session_exists(root, tid) else None
    scr = None
    if pane is not None and pane.returncode == 0:
        scr = adapters.screen(rec["agent"], root, pane.stdout, ref(root, tid))
    if scr and scr.get("answer"):
        if answered is None or scr["what"] in answered:
            scr = None  # the wrapper answers it (or already did: the tool is still redrawing)
        elif not scr.get("folder") or _names_own_folder(root, pane.stdout):
            for i, k in enumerate(scr["answer"]):
                if i:
                    time.sleep(PASTE_DELAY)
                tmux(root, "send-keys", "-t", target(tid), k)
            answered.append(scr["what"])
            return None
    note = scr["say"] if scr else None
    if note is None and age >= STARTUP_SECONDS and (rec.get("live") or {}).get("state") == "starting":
        label = adapters.load(rec["agent"], root)["label"]
        note = (
            f"{label} has not started up after a minute. "
            f"Open the live session to see why: orch run attach {ref(root, tid)}"
        )
    if note is None:
        return None
    with runs.locked(root, tid):
        cur = runs.read(root, tid)
        lv = cur.get("live") or {} if cur else {}
        if (
            cur
            and cur["run"] == run
            and (
                lv.get("state") == "starting"
                or (lv.get("state") == "attention" and not lv.get("why") and not cur.get("up"))
            )
        ):
            cur["live"] = {"state": "attention", "since": tickets.now(), "why": note}
            runs._write(root, cur)
            tickets.wait_for_start(root, tid, note, f"agent:{rec['agent']}")
    return note


def _names_own_folder(root: Path, text: str) -> bool:
    if not adapters.orch_folder(root):
        return False
    lines = [ln.strip() for ln in text.splitlines()]
    joined = lines + [a + b for a, b in zip(lines, lines[1:], strict=False)]  # a long path may wrap
    return bool({str(root), str(root.resolve())} & set(joined))  # the whole line, not a part of a path


def watch_start(root: Path, tid: str, run: str, name: str, proc: subprocess.Popen) -> list[str]:
    """In the pane's wrapper, while the tool starts up: pass its harmless first-run screens (check_starting
    with answers) so nobody has to open the live session, and say so once in the ticket history. Ends when
    the tool is up (a hook changed the state), waits for a person, ends, or after STARTUP_SECONDS."""
    answered: list[str] = []
    if not any(s.get("answer") for s in (adapters.load(name, root).get("live") or {}).get("screens") or []):
        return answered
    end = time.time() + STARTUP_SECONDS + 5
    while proc.poll() is None and time.time() < end:
        rec = runs.read(root, tid)
        if not rec or rec["run"] != run:
            break
        if (rec.get("live") or {"state": "starting"}).get("state") != "starting":
            break
        if rec.get("live") and check_starting(root, rec, answered=answered) is not None:
            break
        time.sleep(1)
    if answered:
        label = adapters.load(name, root)["label"]
        with contextlib.suppress(Exception):
            tickets.log(
                root, tid, f"Answered {label}'s first-run screens ({', '.join(answered)}).", f"agent:{name}"
            )
    return answered


def start_waiting(root: Path) -> None:
    """A slot opened: start the oldest ticket whose live start was queued for lack of one."""
    if _full(root):
        return
    d = runs.run_dir(root) / "pending"
    waiting = []
    for f in sorted(d.glob("t_*.jsonl")) if d.is_dir() else []:
        tid = f.stem
        if runs.read(root, tid):
            continue
        items = [i for i in runs.undelivered(root, tid) if i.get("via") == "slots"]
        if items:
            waiting.append((items[0]["at"], tid, items[0]["by"]))
    for _, tid, by in sorted(waiting)[:1]:
        with contextlib.suppress(Exception):
            runs.start(root, tid, by, mode="live")


def line(rec: dict, root: Path | None = None) -> str:
    """One plain sentence about a live run, for `orch run status`."""
    state = (rec.get("live") or {}).get("state", "starting")
    if (rec.get("live") or {}).get("why"):
        return rec["live"]["why"]
    words = {
        "starting": "starting up",
        "idle": "waiting for input",
        "working": "working",
        "attention": "waiting for your OK",
    }
    name = ref(root, rec["ticket"]) if root is not None else rec["ticket"]
    return f"In a live session ({words.get(state, state)}). See it: orch run attach {name}"

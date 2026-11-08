"""Live runs: the agent runs interactively in its own tmux session, one per ticket.

  tmux -L orch-<hash8(workspace)> new-session -d -s <ticket id> -- orch run _wrap <run> --live -- <agent argv>

orch owns that tmux server (own socket), so a person's own tmux is never touched. The claim's pid is the pane
process (the wrapper). Input waits in the pending file and is pasted (bracketed paste, then Enter) only when
the agent says it is idle: the tool's own hooks call `orch run event --kind idle`, a generic agent calls
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


def tmux(root: Path, *args: str, input: str | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "TMUX"}  # never nest in the person's own tmux
    return subprocess.run(
        ["tmux", "-L", socket_name(root), *args],
        input=input,
        capture_output=True,
        text=True,
        timeout=20,
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
    """Pasted text is data: no escape sequences or other control characters reach the agent's terminal
    (an old tmux may pass `ESC[201~` through and end the bracketed paste early)."""
    return _CONTROL.sub("", text)


def _format(items: list[dict], flat: bool) -> str:
    parts = []
    for i in items:
        t = clean(i["text"] if i.get("via") == "start" else f"From {i['by']}: {i['text']}")
        parts.append(t)
    text = "\n".join(parts)
    return " ".join(text.split()) if flat else text


def deliver(root: Path, tid: str) -> int:
    """Paste what waits, once, if (and only if) the agent said it is idle. Returns how many items went in."""
    with runs.locked(root, tid):
        rec = runs.read(root, tid)
        if not rec or rec.get("mode") != "live" or (rec.get("live") or {}).get("state") != "idle":
            return 0
        if rec.get("closing"):  # an idle close is under way: the item waits for the next start
            return 0
        items = runs.undelivered(root, tid)
        if not items or not session_exists(root, tid):
            return 0
        flat = not adapters.caps(rec["agent"], root)["hooks"]  # no bracketed paste to rely on: one line
        buf = f"orch-{rec['run']}"
        if tmux(root, "load-buffer", "-b", buf, "-", input=_format(items, flat)).returncode != 0:
            return 0
        if tmux(root, "paste-buffer", "-p", "-d", "-b", buf, "-t", target(tid)).returncode != 0:
            return 0
        time.sleep(PASTE_DELAY)  # let the paste land before Enter
        if tmux(root, "send-keys", "-t", target(tid), "Enter").returncode != 0:
            return 0
        runs.mark_delivered_locked(root, tid, [i["id"] for i in items])
        rec = runs.read(root, tid) or rec
        rec["live"] = {"state": "working", "since": tickets.now()}
        rec["renewed_at"] = tickets.now()
        runs._write(root, rec)
        return len(items)


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
    runs.settle(root, tid, f"agent:{rec.get('agent')}")
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

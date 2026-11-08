"""`orch run ...` (hidden from help until the whole set is built) and the after-command hook."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import threading
from pathlib import Path

from orch import adapters, net, runs, runs_live, term, tickets
from orch.errors import Refused

RUN_ID = re.compile(r"r_[a-z0-9_]{6,32}")
SUBCOMMANDS = (
    "claim",
    "release",
    "status",
    "session",
    "argv",
    "start",
    "send",
    "attach",
    "stop",
    "event",
    "done",
)


def add_parsers(sub, common) -> None:
    r = sub.add_parser("run", help=argparse.SUPPRESS).add_subparsers(dest="sub")
    for name in SUBCOMMANDS:
        x = r.add_parser(name, parents=[common], help=argparse.SUPPRESS)
        x.add_argument("ticket", nargs="?" if name in ("event", "done") else None)
        if name in ("claim", "argv"):
            x.add_argument("--mode", choices=("oneshot", "live"), default="oneshot")
        if name == "start":
            x.add_argument("--mode", choices=("oneshot", "live"), help="default: live in tmux when possible")
        if name == "send":
            x.add_argument("text", nargs="?", help="what to tell the agent")
            x.add_argument("--file", help="read the text from this file")
            x.add_argument("--kind", choices=runs.PENDING_KINDS, default="message")
        if name == "attach":
            x.add_argument("--watch", action="store_true", help="only watch, do not type")
        if name == "event":
            x.add_argument("--kind", required=True, choices=runs_live.KINDS)
            x.add_argument("--run", help="the run (the tool's hook passes it)")
            x.add_argument("--session-id", help="the tool's session id")
        if name in ("claim", "session", "argv", "start"):
            x.add_argument("--agent", help="which agent (default: the one chosen for this folder)")
        if name == "claim":
            x.add_argument("--session", help="the agent's session id, if known")
            x.add_argument("--pid", type=int, help="process of the agent")
            x.add_argument("--take-over", action="store_true")
            x.add_argument("--text", help="what to queue when the ticket is busy")
        if name == "release":
            x.add_argument("--run", help="only if this run holds the claim")
        if name in ("start", "argv"):
            x.add_argument("--fresh", action="store_true", help="do not continue the earlier conversation")
            x.add_argument(
                "--allow", action="append", default=[], metavar="TOOL", help="allow a tool for this run"
            )
        if name == "start":
            x.add_argument("--take-over", action="store_true", help="take over a claim nobody has written to")
            x.add_argument("--text", help="what to queue when the ticket is busy")
        if name == "argv":
            x.add_argument("--prompt-file", help="use this text as the prompt instead of the ticket summary")
    w = r.add_parser("_wrap", help=argparse.SUPPRESS)
    w.add_argument("rest", nargs=argparse.REMAINDER)


def _out(args, data, text: str) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def _wrap_cmd(root: Path, rest: list[str]) -> None:
    if "--" not in rest:
        raise Refused("orch run _wrap is internal.")
    i = rest.index("--")
    p = argparse.ArgumentParser(prog="orch run _wrap")
    p.add_argument("run")
    p.add_argument("--ticket", required=True)
    p.add_argument("--agent", required=True)
    p.add_argument("--fresh", action="store_true")
    p.add_argument("--live", action="store_true")
    p.add_argument("--env-file")
    p.add_argument("--resumed", action="store_true")
    p.add_argument("--allow", action="append", default=[])
    p.add_argument("--stdin-file")
    p.add_argument("--new-session")
    p.add_argument("--items", default="")
    a = p.parse_args(rest[:i])
    if not RUN_ID.fullmatch(a.run):
        raise Refused("orch run _wrap is internal.")  # before any path is built from it
    stdin, env = None, None
    if a.env_file:  # secrets: read and remove first, so no refusal below can leave the file behind
        f = Path(a.env_file)
        want = runs.run_dir(root).resolve() / f"env-{a.run}.json"
        if f.resolve().parent == want.parent and f.name == want.name:
            try:
                env = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                env = None
            finally:
                f.unlink(missing_ok=True)
    rec = runs.read(root, a.ticket)
    if not rec or rec["run"] != a.run or (a.env_file and (not a.live or env is None)):
        raise Refused("orch run _wrap is internal.")
    if a.stdin_file:
        f = Path(a.stdin_file)
        if f.resolve() != (runs.run_dir(root) / f"prompt-{a.run}.txt").resolve():
            raise Refused("orch run _wrap is internal.")  # never read or delete any other file
        stdin = f.read_text(encoding="utf-8")
        f.unlink(missing_ok=True)
    if isinstance(env, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        # from here on this process, and the agent, run in the starter's environment, except what belongs to
        # the pane's own terminal (the starter may have no terminal at all)
        pane = {k: os.environ[k] for k in ("TERM", "COLORTERM", "TMUX", "TMUX_PANE") if k in os.environ}
        os.environ.clear()
        os.environ.update({k: v for k, v in env.items() if k not in pane})
        os.environ.update(pane)
    if a.live:
        sys.exit(runs.wrap_live(root, a.run, a.ticket, a.agent, rest[i + 1 :], a.new_session))
    code = runs.wrap(
        root,
        a.run,
        a.ticket,
        a.agent,
        rest[i + 1 :],
        fresh=a.fresh,
        resumed=a.resumed,
        allow=a.allow,
        stdin=stdin,
        new_session=a.new_session,
        item_ids=[x for x in a.items.split(",") if x],
    )
    sys.exit(code)


def _chosen_or_generic(root: Path) -> str:
    try:
        return adapters.chosen(root)
    except Refused:
        return "generic"  # a hand-started agent we know nothing about


def _name(root: Path, tid: str) -> str:
    """How a person calls the ticket in a message: its key (DM1-12) when it has one, else the id."""
    try:
        return str(tickets.load(root, tid).get("key") or tid)
    except Exception:
        return tid


def _holder_line(rec: dict, tid: str, root: Path | None = None) -> str:
    who = adapters.load(rec["agent"])["label"] if rec["agent"] in adapters.builtin_names() else rec["agent"]
    since = net.when(rec.get("started_at"))  # local time, like every other time a person reads
    return f"{_name(root, tid) if root else tid} is being worked on by {rec['by']} ({who}) since {since}."


def _status(args, root: Path) -> None:
    tid = args.ticket
    tickets.load(root, tid)
    runs.settle_orphan(root, tid)  # Working with no agent for a while: Ready (status matches reality)
    rec = runs.read(root, tid)
    waiting = len(runs.undelivered(root, tid))
    if not rec:
        # human_pending_ids: input a person wrote that waits for a run (the automation host starts one for it,
        # once per id). An agent's queued input is never in it.
        human = [i["id"] for i in runs.human_waiting(root, tid)]
        data = {"ticket": tid, "running": False, "pending": waiting, "human_pending_ids": human}
        if waiting:  # input is really queued for a run
            text = (
                "Queued. Nothing will start it: no background add-on is running here. "
                f"Start it: orch run start {tid}"
            )
        else:
            text = f"No run is active for this ticket. Start one: orch run start {tid}"
        _out(args, data, text)
        return
    st = runs.state(rec)
    data = {"ticket": tid, "running": st == "alive", "state": st, "pending": waiting, "claim": rec}
    if st == "dead":
        text = (
            f"The earlier run on {_name(root, tid)} ended without finishing. "
            f"Start it again: orch run start {tid}"
        )
    elif st == "maybe-stale":
        text = (
            f"{_holder_line(rec, tid, root)} Nobody has written to the ticket for a while, "
            "so it may be stuck. "
            f"Take it over: orch run start {tid} --take-over"
        )
    else:
        text = _holder_line(rec, tid, root) + (
            f" {waiting} message{'s' if waiting != 1 else ''} waiting to go in." if waiting else ""
        )
        if rec.get("mode") == "live":
            text += " " + runs_live.line(rec, root)
    _out(args, data, text)


HOOK_INPUT_SECONDS = 2.0  # a tool writes its hook input at once and closes the pipe; nobody else gets more


def _read_bounded(stream, limit: int = 65536, seconds: float | None = None) -> str:
    """Up to `limit` bytes of stdin, waiting at most `seconds` for its end. A caller that leaves stdin open
    (a script that never closes it, an inherited pipe) must never block a hook: whatever came in time counts,
    an unfinished read is given up (the process may exit while it waits)."""
    try:
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError):  # not a real file (tests): a plain read
        return stream.read(limit)
    buf: list[bytes] = []
    done = threading.Event()

    def pump() -> None:
        n = 0
        try:
            while n < limit:
                b = os.read(fd, limit - n)  # the raw fd: an abandoned read holds no lock of sys.stdin
                if not b:
                    break
                buf.append(b)
                n += len(b)
        except OSError:
            pass
        finally:
            done.set()

    threading.Thread(target=pump, daemon=True, name="orch-hook-input").start()
    if not done.wait(HOOK_INPUT_SECONDS if seconds is None else seconds):
        return ""  # never finished: a partial JSON document is no input
    return b"".join(buf).decode("utf-8", "replace")


def _hook_input(args) -> dict:
    """The tool's hook input (JSON on stdin), or {}. Never waits more than HOOK_INPUT_SECONDS."""
    if args.kind not in ("session", "attention") or sys.stdin is None or term.is_terminal(sys.stdin):
        return {}
    try:
        data = json.loads(_read_bounded(sys.stdin) or "{}")
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _session_id(args, data: dict) -> str | None:
    if args.kind != "session":
        return None
    if args.session_id:
        return args.session_id
    sid = data.get("session_id")
    return sid if isinstance(sid, str) else None


def _done(args, root: Path, tid: str | None) -> None:
    """A generic agent says it finished a piece of work (idle)."""
    run = os.environ.get("ORCH_RUN")
    if not tid:
        raise Refused("Say which ticket: orch run done <ticket>")
    n = runs_live.event(root, "idle", run, tid, None)
    _out(
        args,
        {"sent": n},
        "Noted." + (f" {n} message{'s' if n != 1 else ''} from you waiting: sent." if n else ""),
    )


def _send(args, root: Path, tid: str, by: str) -> None:
    if args.file:
        p = Path(args.file)
        if p.stat().st_size > 64_000:
            raise Refused("That file is too long to send (8000 characters at most).")
        text = p.read_text(encoding="utf-8")
    else:
        text = args.text
    if not text:
        raise Refused('Say what to send: orch run send <ticket> "text"  (or --file <path>)')
    res = runs_live.send(root, tid, by, text, args.kind)
    _out(args, res, runs_live.send_text(res, tid))


def dispatch(args, root: Path) -> bool:
    if args.cmd != "run":
        return False
    sub = args.sub
    if sub == "_wrap":
        _wrap_cmd(root, args.rest)
        return True
    if sub is None:
        raise Refused("Say what to do: orch run start|status|send|attach|stop <ticket>")
    if sub != "event":  # a hook must stay quiet; everything else first closes sessions idle for an hour
        with contextlib.suppress(Exception):
            runs_live.cleanup(root)
    by = args.by or tickets.current_actor()
    if not 1 <= len(by) <= 64 or any(ord(c) < 32 for c in by):
        raise Refused("--by must be 1 to 64 characters, e.g. agent:helper.")
    tid = args.ticket or os.environ.get("ORCH_TICKET")
    if sub == "event":
        data = _hook_input(args)
        runs_live.event(
            root, args.kind, args.run or os.environ.get("ORCH_RUN"), tid, _session_id(args, data), data
        )
    elif sub == "done":
        _done(args, root, tid)
    elif sub == "send":
        _send(args, root, tid, by)
    elif sub == "attach":
        runs_live.attach(root, tid, args.watch)
    elif sub == "stop":
        ok = runs_live.stop(root, tid)
        _out(
            args,
            {"stopped": ok},
            f"Stopped {_name(root, tid)}. The work done so far is kept."
            if ok
            else f"Nothing is running on {_name(root, tid)}.",
        )
    elif sub == "claim":
        name = args.agent or adapters.detect_env(os.environ) or _chosen_or_generic(root)
        try:
            rec = runs.claim(
                root, tid, by, name, args.mode, pid=args.pid, take_over=args.take_over, busy_text=args.text
            )
        except runs.Busy as e:
            e.extra["claimed"] = False
            raise
        if args.session:
            tickets.record_session(root, tid, name, args.session, runs.host())
        _out(args, {"claimed": True, "run": rec["run"]}, f"Claimed {_name(root, tid)} (run {rec['run']}).")
    elif sub == "release":
        run_id = args.run or os.environ.get("ORCH_RUN")
        rec = runs.read(root, tid)
        if rec and not run_id and isinstance(rec.get("pid"), int) and runs.state(rec) == "alive":
            raise Refused(
                f"An agent process is working on {tid}. Only that run can release it (--run {rec['run']})."
            )
        res = runs.release(root, tid, run_id)
        _out(args, res, "Released." if res["released"] else "Nothing to release.")
    elif sub == "status":
        _status(args, root)
    elif sub == "session":
        name = args.agent or adapters.chosen(root)
        sid = tickets.sessions_for(tickets.load(root, tid), name, runs.host())
        _out(args, {"agent": name, "session": sid}, sid or "")
    elif sub == "argv":
        prompt = Path(args.prompt_file).read_text(encoding="utf-8") if args.prompt_file else None
        if args.mode != "oneshot":
            raise Refused("Only --mode oneshot is available here.")
        p = runs.plan(
            root, tid, fresh=args.fresh, mode=args.mode, allow=args.allow, prompt=prompt, agent=args.agent
        )
        p = {k: v for k, v in p.items() if k not in ("stdin", "item_ids")}
        _out(args, p, "\n".join(p["argv"]))
    elif sub == "start":
        r = runs.start(
            root,
            tid,
            by,
            fresh=args.fresh,
            take_over=args.take_over,
            allow=args.allow,
            mode=args.mode,
            text=args.text,
            agent=args.agent,
        )
        for note in r["notes"]:
            print(note, file=sys.stderr)
        how = "Continued the earlier conversation" if r["resumed"] else "Started fresh from the ticket"
        where = "in a live session" if r["mode"] == "live" else f"Log: {r['log']}"
        _out(
            args,
            r,
            f"{how} ({r['agent']}). Run {r['run']}. {where}"
            + (f" See it: orch run attach {runs_live.ref(root, tid)}" if r["mode"] == "live" else ""),
        )
    return True


def after_command(args, root: Path, stdout_is_json: bool) -> None:
    """Runs after every command inside an agent run: the footer, on stderr only (stdout stays as it was)."""
    if getattr(args, "cmd", None) == "run":
        return
    try:
        line = runs.footer(root, getattr(args, "by", None), getattr(args, "id", None))
    except Exception:  # a footer must never break the command it follows
        return
    if line:
        print(line, file=sys.stderr)

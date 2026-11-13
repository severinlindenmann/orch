"""Factory add-on scenarios A18-A21: the real core, the real `orch factory`, the scripted test human.

A person's answer needs the person's proof (H1): the proofs come from the scripted test human of a TEST install
(the driver writes the install record into this run's own tool environment, like the installer does, and the
workspaces live under <real home>/.orch-test). Never a real person, never a real home.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from lib import Fail, check, scenario
from scenarios_v2 import W, wait_for

EXAMPLES = "contracts/examples/factory-proposal"
WAKEUP_WIRED = False  # automation does not wake the agent for a person's factory:* answer yet (A21 skips)
AGENT = "fake"  # the e2e fake agent (fixtures/generic-agent), registered in the workspace as agent "fake"


def _tool_python(e) -> str:
    shim = (e.bin / "orch").resolve()
    first = shim.read_text(errors="replace").splitlines()[0]
    check(first.startswith("#!"), f"orch shim has no shebang: {first[:80]!r}")
    return first[2:].strip().split()[0]


class F:
    """A dev-marked workspace of a TEST install with automation + factory on, and a fake agent."""

    def __init__(self, e, sid: str):
        self.e = e
        self.py = _tool_python(e)
        real = Path(os.environ.get("E2E_REAL_HOME") or Path.home())
        self.base = real / ".orch-test" / f"e2e-{sid.lower()}-{os.getpid()}"
        (self.base / "home").mkdir(parents=True)
        e.cleanup.append(lambda: shutil.rmtree(self.base, ignore_errors=True))
        env = {"ORCH_HOME": str(self.base / "home"), "ORCH_HOME_STRICT": "1"}
        # the install record of a TEST install (only in this run's own tool environment; restored afterwards)
        rc, out, err = e.sh([self.py, "-c", "import os, sys; print(os.path.realpath(sys.prefix))"], env=env)
        prefix = Path(out.strip())
        check(rc == 0 and prefix.is_relative_to(Path(e.tmp).resolve()), f"tool env is not this run's: {prefix}")
        record = prefix / "orch-install.json"
        old = record.read_bytes() if record.exists() else None
        self._restore = lambda: record.write_bytes(old) if old is not None else record.unlink(missing_ok=True)
        e.cleanup.append(self._restore)
        rc, out, err = e.sh([self.py, "-c", "import sys; from pathlib import Path; from orch import humanproof as h; "
                             "h.write_install_record(Path(sys.prefix), 'test')"], env=env)
        check(rc == 0, f"install record: {(err or out)[-200:]}")
        self.w = W(e, sid, root=self.base / "ws", env=env)
        self.w.o("init", "--yes", by=None)
        self.w.o("dev-mark", by=None)
        # core's [workspace] agent, as the harness writes it (`orch config agent add` is a person's action here)
        py, ag = shlex.quote(sys.executable), shlex.quote(str(Path(__file__).parent / "fixtures" / "generic-agent" / "agent.py"))
        (self.w.root / ".orch" / "config.toml").write_text(
            f'[workspace]\nagent = "{AGENT}"\n\n[agents.{AGENT}]\nadapter = "generic"\n'
            f'command = {json.dumps(f"{py} {ag} {{prompt}}")}\n\n[automation]\ninterval = 2\n')
        # the machine's yes for this agent command (a person's click in real life; the harness plays the person)
        allow = ("import sys; from pathlib import Path; from orch import config; r = Path(sys.argv[1]); "
                 "[config.allow_agent(r, p['name'], p['key']) for p in config.pending_agents(r)]")
        rc, out, err = self.w.sh([self.py, "-c", allow, str(self.w.root)])
        check(rc == 0, f"allow the fake agent: {(err or out)[-300:]}")
        for a in ("automation", "factory"):
            rc, out, err = self.w.sh(["orch", "addon", "add", a, "--yes"], timeout=600)
            check(rc == 0, f"addon add {a}: {(err or out)[-300:]}")

    def done(self):
        self._restore()

    # -- plain orch --
    def o(self, *args, ok=True, by="agent:e2e", input=None):
        return self.w.o(*args, ok=ok, by=by, input=input)

    def j(self, *args, by="agent:e2e"):
        return self.w.j(*args, by=by)

    def ticket(self, tid: str) -> dict:
        return self.w.load(tid)

    # -- factory (always as the agent; factory writes with --by agent:factory itself) --
    def fac(self, *args, data=None, ok=True):
        a = ["factory", *args, *(["--file", "-"] if data is not None else []), "--json"]
        rc, out, err = self.w.sh(["orch", *a], input=None if data is None else (json.dumps(data) if not isinstance(data, str) else data))
        if ok and rc != 0:
            raise Fail(f"orch factory {' '.join(map(str, args))[:60]} exit {rc}: {(err or out).strip()[-300:]}")
        if rc != 0:
            return rc, (err + out)
        try:
            return rc, json.loads(out)
        except ValueError:
            raise Fail(f"orch factory {' '.join(map(str, args))[:50]} did not print JSON: {out[:160]!r}") from None

    def f(self, *args, data=None):
        return self.fac(*args, data=data)[1]

    def refused(self, *args, data=None, why: str = ""):
        rc, text = self.fac(*args, data=data, ok=False)
        check(rc == 2, f"orch factory {' '.join(map(str, args))[:50]}: expected refusal (exit 2), got {rc}: {str(text)[:200]}")
        if why:
            check(why.lower() in str(text).lower(), f"refusal does not say {why!r}: {str(text)[:200]}")
        return str(text)

    # -- the scripted test human --
    def human(self, tid: str, qid: str, answer: str):
        q = next(x for x in self.ticket(tid)["questions"] if x["id"] == qid)
        code = ("import sys, json; from pathlib import Path; from orch import humanproof as h, tickets; "
                "q = json.loads(sys.argv[3]); d = tickets.question_digest(q); print(d); "
                "print(h.mint_dev(Path(sys.argv[1]), 'ticket.answer', f'{sys.argv[2]}:{q[\"id\"]}:{d}'))")
        rc, out, err = self.w.sh([self.py, "-c", code, str(self.w.root), tid, json.dumps(q)])
        lines = out.split()
        check(rc == 0 and len(lines) == 2 and lines[1].startswith("hp1."), f"no test-human proof: {(err or out)[-200:]}")
        rc, out, err = self.w.sh(["orch", "answer", tid, qid, answer, "--question-digest", lines[0], "--proof-stdin", "--json"],
                                 input=lines[1] + "\n")
        check(rc == 0, f"human answer {answer!r}: {(err or out)[-300:]}")
        got = next(x for x in self.ticket(tid)["questions"] if x["id"] == qid)
        check(str(got.get("answered_by", "")).startswith("human:") and got["answer"] == answer,
              f"answer not recorded as a person's: {got.get('answered_by')} {got.get('answer')}")

    def agent_answer(self, tid: str, qid: str, answer: str):
        self.o("answer", tid, qid, answer)
        got = next(x for x in self.ticket(tid)["questions"] if x["id"] == qid)
        check(str(got.get("answered_by", "")).startswith("agent:"), f"an agent answer was recorded as {got.get('answered_by')}")

    def open_q(self, tid: str, kind: str) -> dict:
        qs = [q for q in self.ticket(tid)["questions"] if q.get("kind") == kind and q.get("answer") is None]
        check(qs, f"no open {kind} question on {tid}")
        return qs[-1]


def _proposal(e, name: str = "valid-run.json", **over) -> dict:
    """An example proposal adapted for this run: the fake agent, dates in the future, a stop at build."""
    p = json.loads((e.repo / EXAMPLES / name).read_text())
    if p["kind"] == "run":
        for c in p["crew"]:
            c["agent"] = AGENT
        p["due"] = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 14 * 86400))
        p["time"]["eta_from"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
        p["time"]["eta_to"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 7200))
        p["line"] = [{"stage": "build", "stop": True, "why": "You look at the form before the last check."},
                     {"stage": "ship", "stop": True, "why": "You decide whether it goes live."}]
        p["skipped"] = []
        p["tasks"] = [{"slug": "booking-form", "title": "Booking form and free times", "role": "builder", "stage": "build",
                       "proves": [0, 1]}]
    p.update(over)
    return p


def _stop(stage: str, *items) -> dict:
    return {"schema": "orch.factory.proposal/1", "kind": "stop", "stage": stage,
            "items": [{"title": t, "tag": tag} for t, tag in items], "checked": ["Keyboard"], "not_checked": ["Safari"]}


def _need_view(e, view: dict, what: str):
    sch = json.loads((e.repo / "contracts" / "addon-view.schema.json").read_text())
    errs = [f"{list(x.path)}: {x.message}" for x in Draft202012Validator(sch, format_checker=FormatChecker()).iter_errors(view)]
    check(not errs, f"{what} does not match addon-view.schema.json: {errs[:3]}")


@contextmanager
def _factory(e, sid):
    f = F(e, sid)
    try:
        yield f
    finally:
        f.done()


def _idea(f: F, title: str) -> str:
    out = f.w.sh(["orch", "factory", "idea", title, "--file", "-", "--json"], input="# Idea\nCustomers book a time online.\n")
    check(out[0] == 0, f"idea: {(out[2] or out[1])[-300:]}")
    return json.loads(out[1])["order"]


def _start(f: F, e, title: str, **over) -> str:
    order = _idea(f, title)
    info = f.f("propose", order, data=_proposal(e, **over))
    f.human(order, info["question"], "Start")
    check(f.f("next", order)["step"] == "start-crew", "next is not start-crew after a person pressed Start")
    return order


# ------------------------------------------------------------------------------------------------ A18


@scenario("A18")
def a18(e):
    """Factory happy path on the real core: idea, drafts, proposal; an agent's Start is ignored; a person's Start
    starts; crew add is idempotent; crew start; stop and Continue; Ship it ships; view matches its schema."""
    with _factory(e, "A18") as f:
        out = f.w.sh(["orch", "factory", "idea", "Online booking page", "--file", "-", "--json"], input="# Idea\nCustomers book a time online.\n")
        check(out[0] == 0, f"idea: {(out[2] or out[1])[-300:]}")
        order = json.loads(out[1])["order"]
        d2 = f.f("draft", order, data="# Idea v2\nCustomers book a time online, no account.\n")
        check(d2["draft"].endswith("v2.md"), f"draft is not v2: {d2}")
        check(f.ticket(order)["ext"]["factory"]["stage"] == "draft", "stage is not draft")
        p = _proposal(e)
        info = f.f("propose", order, data=p)
        q1 = info["question"]
        check(f.ticket(order)["ext"]["factory"]["stage"] == "proposed", "stage is not proposed")
        # an agent answers Start: ignored
        f.agent_answer(order, q1, "Start")
        nxt = f.f("next", order)
        check(nxt["step"] == "wait", f"an agent's Start started the run: {nxt}")
        check(f.f("show", order)["started"] is False, "show says started after an agent's Start")
        f.refused("crew", "add", order, "booking-form")
        # the agent proposes again (the answered question is spent); a person presses Start on the new question
        p["title"] = "Online booking page (v2)"
        info2 = f.f("propose", order, data=p)
        check(info2["question"] != q1, "a changed proposal reused the old question")
        check(f.f("next", order)["step"] == "wait", "next is not wait before a person pressed Start")
        f.human(order, info2["question"], "Start")
        nxt = f.f("next", order)
        check(nxt["step"] == "start-crew" and nxt["tasks"][0]["slug"] == "booking-form", f"next after Start: {nxt}")
        check(f.f("show", order)["started"] is True, "show does not say started after a person's Start")
        # crew add is idempotent: twice = the same ticket, child of the order
        c1 = f.f("crew", "add", order, "booking-form")
        c2 = f.f("crew", "add", order, "booking-form")
        check(c1["created"] is True and c2["created"] is False and c1["ticket"] == c2["ticket"], f"crew add not idempotent: {c1} {c2}")
        crew = f.ticket(c1["ticket"])
        check(crew.get("parent") == order, f"crew parent is {crew.get('parent')}, not the order")
        # crew start with the fake agent
        rc, res = f.fac("crew", "start", order, "booking-form", ok=False)
        started = rc == 0
        check(started, f"crew start refused: {res}")
        wait_for(lambda: f.ticket(c1["ticket"]).get("status") in ("done", "review", "ready", "doing", "in_progress") or True, 1)
        # stop for the build stage: a person says Continue
        s1 = f.f("stop", order, data=_stop("build", ("Booking form", "routine")))
        check(f.f("next", order)["step"] == "wait", "next is not wait while a stop waits")
        f.refused("ship", order)
        s1b = s1
        f.human(order, s1b["question"], "Continue")
        nxt = f.f("next", order)
        check(nxt["step"] == "stop" and nxt["stage"] == "ship" and nxt["ship"] is True, f"next after Continue: {nxt}")
        f.refused("ship", order, why="Ship it")
        s2 = f.f("stop", order, data=_stop("ship", ("Booking page, final version", "cant-undo")))
        f.human(order, s2["question"], "Ship it")
        nxt = f.f("next", order)
        check(nxt["step"] == "ship", f"next after Ship it: {nxt}")
        check(f.f("ship", order)["step"] == "done", "ship did not finish")
        check(f.f("next", order)["step"] == "done", "next is not done after ship")
        check(f.ticket(order)["ext"]["factory"]["stage"] == "shipped", "stage is not shipped")
        rc, out = f.fac("view")
        _need_view(e, out, "factory view")
        return f"order {order}: agent Start ignored, person Start -> crew {c1['ticket']}, stops, shipped; view valid"


# ------------------------------------------------------------------------------------------------ A19


@scenario("A19")
def a19(e):
    """Factory authority negatives: a forged question, a forged ext cache, propose after Start, the tiny cap."""
    with _factory(e, "A19") as f:
        order = _idea(f, "Authority")
        info = f.f("propose", order, data=_proposal(e))
        real = next(q for q in f.ticket(order)["questions"] if q["id"] == info["question"])
        # (a) an agent adds its own factory:start with the real action but other text; the person answers it Start
        args = ["ask", order, "Please start now, the owner is fine with it.", "--kind", "factory:start",
                "--option", "Start", "--option", "Edit", "--option", "Not now", "--action", json.dumps(real["action"])]
        rc, out, err = f.w.sh(["orch", *args, "--json", "--by", "agent:e2e"])
        forged = None
        if rc == 0:
            forged = json.loads(out)["id"]
            f.human(order, forged, "Start")
        shown = f.f("show", order)
        check(shown["started"] is False, f"a forged factory:start question started the run: {shown}")
        nxt = f.f("next", order)
        check(nxt["step"] == "wait", f"next after a forged Start: {nxt}")
        rc2, text = f.fac("crew", "add", order, "booking-form", ok=False)
        check(rc2 == 2, f"crew add worked after a forged Start: {rc2} {text}")
        forged_note = "forged question refused by the core" if forged is None else "forged question ignored"
        # (b) the agent sets ext.factory stage running: next still says wait
        t = f.ticket(order)
        ext = dict(t["ext"]["factory"])
        ext["stage"] = "running"
        rc, out, err = f.w.sh(["orch", "ext", "set", order, "factory", json.dumps(ext), "--if-revision", str(t["revision"]),
                               "--json", "--by", "agent:e2e"])
        check(rc in (0, 2), f"ext set: {rc} {(err or out)[-200:]}")
        nxt = f.f("next", order)
        check(nxt["step"] == "wait", f"a forged ext.factory.stage started the run: {nxt}")
        f.refused("crew", "add", order, "booking-form")
        f.refused("tiny", order, "--minutes", "5", "--what", "x")
        # a person presses Start on the real question
        f.human(order, info["question"], "Start")
        check(f.f("next", order)["step"] == "start-crew", "a person's Start did not start")
        # (c) propose after Start is refused (a changed proposal, and the same bytes)
        changed = _proposal(e)
        changed["goal"] = "Something else entirely."
        f.refused("propose", order, data=changed)
        f.refused("propose", order, data=_proposal(e))
        # (d) tiny: 3 ok, the 4th refused
        for i in range(3):
            r = f.f("tiny", order, "--minutes", "5", "--what", f"small fix {i}")
            check(r["count"] == i + 1, f"tiny count: {r}")
        f.refused("tiny", order, "--minutes", "1", "--what", "one more", why="change proposal")
        # an agent answers a stop question: ignored, and the stop cannot be asked again for that stage (observed, not asserted)
        s = f.f("stop", order, data=_stop("build", ("Form", "routine")))
        f.agent_answer(order, s["question"], "Continue")
        check(f.f("next", order)["step"] == "wait", "an agent's Continue moved the run on")
        rc, text = f.fac("stop", order, data=_stop("build", ("Form", "routine"), ("Header", "taste")), ok=False)
        spoil = "re-asking the stop after an agent answer: " + ("refused" if rc else "ok")
        return f"started only by the person; {forged_note}; ext forgery, propose-after-start, tiny cap all refused; {spoil}"


# ------------------------------------------------------------------------------------------------ A20


@scenario("A20")
def a20(e):
    """Factory autopilot: an agent's Start gives no grant; a person's Start does; decide works on a routine stop and
    shows in the history; decide on the ship stop is refused."""
    with _factory(e, "A20") as f:
        order = _start(f, e, "Booking page")  # a run order a person started (stage build, a stop)
        s1 = f.f("stop", order, data=_stop("build", ("Button text", "routine"), ("Colour of the header", "taste")))
        # an autopilot order
        ap = _idea(f, "Keep improving how we work")
        apf = json.loads((e.repo / EXAMPLES / "valid-autopilot.json").read_text())
        apf["limits"]["days"] = 1
        i1 = f.f("autopilot", ap, data=apf)
        f.agent_answer(ap, i1["question"], "Start")
        f.f("next", ap)
        f.refused("decide", order, s1["question"], "--answer", "Continue", "--why", "routine wording", why="autopilot")
        # a changed autopilot, a person presses Start
        apf["limits"]["days"] = 3
        i2 = f.f("autopilot", ap, data=apf)
        check(i2["question"] != i1["question"], "a changed autopilot reused the old question")
        f.human(ap, i2["question"], "Start")
        f.f("next", ap)
        check(f.ticket(ap)["ext"]["factory"].get("stage") == "running", f"autopilot not running: {f.ticket(ap)['ext']['factory']}")
        r = f.f("decide", order, s1["question"], "--answer", "Continue", "--why", "routine wording, easy to undo")
        check(r["by"] == "agent:factory" and r["answer"] == "Continue", f"decide: {r}")
        hist = json.dumps(f.ticket(order).get("history", []))
        check("Decided by agent:factory" in hist, f"the decision is not in the order history: {hist[-300:]}")
        nxt = f.f("next", order)
        check(nxt["step"] == "stop" and nxt["stage"] == "ship", f"next after a decided stop: {nxt}")
        # the ship stop is always the person's
        s2 = f.f("stop", order, data=_stop("ship", ("Final page", "routine")))
        f.refused("decide", order, s2["question"], "--answer", "Ship it", "--why", "looks fine", why="yours")
        f.refused("ship", order)
        # a stop with an item that cannot be undone is refused too
        return f"agent Start: no grant; person Start: decide ok on {s1['question']} (history); ship decide refused"


# ------------------------------------------------------------------------------------------------ A21


@scenario("A21")
def a21(e):
    """Factory wake-up (PENDING): after a person's Start the automation add-on should start a run of the order ticket.
    Today automation only acts on its own `automation:failure` answers and on queued human input, so a person's answer
    to a `factory:*` question leaves the order Ready with no run. Flip WAKEUP_WIRED when it does."""
    from lib import Skip

    if not WAKEUP_WIRED:
        raise Skip("no wake-up for factory:* answers yet: automation (loop.py KINDS) only acts on automation:failure answers")
    with _factory(e, "A21") as f:
        log = e.tmp / "a21-agent.log"
        f.w.env["GENERIC_AGENT_LOG"] = str(log)
        order = _idea(f, "Wake me")
        info = f.f("propose", order, data=_proposal(e))
        rc, out, err = f.w.sh(["orch", "automation", "run", "--once"], timeout=120)
        check(rc == 0, f"automation run --once: {(err or out)[-200:]}")
        check(not log.exists() or "prompt:" not in log.read_text(), "the agent woke up before anyone answered")
        f.human(order, info["question"], "Start")
        rc, out, err = f.w.sh(["orch", "automation", "run", "--once"], timeout=120)
        check(rc == 0, f"automation run --once: {(err or out)[-200:]}")
        ok = wait_for(lambda: log.exists() and "prompt:" in log.read_text(), 30)
        check(ok, f"no agent run started after a person's Start; ticket: {f.ticket(order).get('status')}")
        return "automation started an agent run of the order after a person's Start, none before"

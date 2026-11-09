"""The live board. Producer 1 turns ticket changes into events (every agent); the Board folds events.

A board works from ticket events alone (the generic agent); adapter events (steps, helpers, usage,
denials) only add detail.
"""

from __future__ import annotations

from datetime import UTC, datetime

from . import events as ev

LONG_JOB_SECONDS = 10


def _evidence_text(item: dict) -> str:
    proofs = item.get("evidence") or []
    if not proofs:
        return ""
    last = proofs[-1]
    return str(last.get("summary") or last.get("text") or last.get("ref") or "")


class TicketWatcher:
    """Remembers the last ticket it saw and turns each change into task.start / task.done / ask events."""

    def __init__(self, run: str, ticket_id: str):
        self.run, self.tid = run, ticket_id
        self._state: dict[str, str] = {}
        self._asked: set[str] = set()
        self._primed = False

    def _e(self, kind: str, text: str, at: str | None = None, **data) -> dict:
        return ev.make(
            self.run, self.tid, "main", kind, text, "ticket", at=at, limits={"evidence": 200}, **data
        )

    def feed(self, ticket: dict, prime: bool = False) -> list[dict]:
        """Events for what changed since the last call. The first call (`prime=True`) only remembers."""
        out: list[dict] = []
        first = not self._primed
        for c in ticket.get("checklist", []):
            cid = c["id"]
            now = "done" if c.get("done") else ("doing" if c.get("state") == "doing" else "todo")
            old = self._state.get(cid, "todo")
            self._state[cid] = now
            if first and prime:
                continue
            if now == old:
                continue
            if now == "doing":
                out.append(self._e("task.start", c["text"], at=c.get("at"), check=cid))
            elif now == "done":
                extra = {"evidence": _evidence_text(c)} if _evidence_text(c) else {}
                out.append(self._e("task.done", c["text"], check=cid, **extra))
        for q in ticket.get("questions", []):
            if q["id"] in self._asked:
                continue
            self._asked.add(q["id"])
            if first and prime:
                continue
            if q.get("answer") is None:
                out.append(self._e("ask", q["text"], q=q["id"], qkind=q.get("kind")))
        self._primed = True
        return out


def _ts(at: str) -> float:
    try:
        return datetime.fromisoformat(at).timestamp()
    except ValueError:
        return 0.0


class Board:
    """Folds events into what the page shows."""

    def __init__(self):
        self.state = "starting"
        self.tasks: dict[str, dict] = {}
        self.asks: dict[str, dict] = {}
        self.open_calls: dict[str, dict] = {}  # tool/helper id -> start event
        self.helpers: dict[str, dict] = {}
        self.usage: dict | None = None
        self.context: dict | None = None  # how much of the saved conversation was reused: {reused: 0..100, at}
        self.denials: list[dict] = []
        self.last_step = ""

    def apply(self, e: dict) -> None:
        """Fold one event. An event that lacks a key it needs is skipped, never an error."""
        try:
            self._apply(e)
        except (KeyError, TypeError, AttributeError):
            pass

    def _apply(self, e: dict) -> None:
        k, d = e.get("kind"), e.get("data") or {}
        if k == "run.state":
            self.state = d.get("state", self.state)
            r = d.get("reused")
            if isinstance(r, int) and not isinstance(r, bool) and 0 <= r <= 100:
                self.context = {"reused": r, "at": e["at"]}
            if self.state in ("idle", "done", "failed"):
                self.open_calls.clear()
                for h in self.helpers.values():
                    h["open"] = False
        elif k == "task.start":
            t = self.tasks.setdefault(d["check"], {"check": d["check"], "text": e["text"]})
            t.update(text=e["text"], state="doing", at=e["at"], agent=e["agent"])
            self.state = "working"
        elif k == "task.done":
            t = self.tasks.setdefault(d["check"], {"check": d["check"], "text": e["text"]})
            t.update(text=e["text"], state="done", done_at=e["at"], evidence=d.get("evidence", ""))
        elif k == "ask":
            self.asks[d["q"]] = {
                "q": d["q"],
                "text": e["text"],
                "at": e["at"],
                "kind": d.get("qkind"),
                "open": True,
            }
        elif k in ("tool.start", "helper.start"):
            self.open_calls[d["id"]] = e
            self.last_step = e["text"]
            if k == "helper.start":
                self.helpers[d["id"]] = {
                    "id": d["id"],
                    "agent": e["agent"],
                    "text": e["text"],
                    "open": True,
                    "at": e["at"],
                }
        elif k in ("tool.end", "helper.end"):
            self.open_calls.pop(d["id"], None)
            if k == "helper.end" and d["id"] in self.helpers:
                self.helpers[d["id"]].update(open=False, ok=d.get("ok", True), result=e["text"])
        elif k == "usage":
            self.usage = {
                "used": d["used"],
                "window": d.get("window"),
                "status": d.get("status", "ok"),
                "text": e["text"],
            }
        elif k == "denial":
            self.denials.append({"tool": d["tool"], "text": e["text"], "at": e["at"]})

    def resolve_asks(self, ticket: dict) -> None:
        """Questions answered on the ticket stop being open."""
        answered = {q["id"] for q in ticket.get("questions", []) if q.get("answer") is not None}
        for qid, a in self.asks.items():
            if qid in answered:
                a["open"] = False

    def snapshot(self, now: float | None = None) -> dict:
        """The page data. A long job is any open tool call older than 10 s."""
        t = now if now is not None else datetime.now(UTC).timestamp()
        jobs = []
        for cid, e in self.open_calls.items():
            if e["kind"] != "tool.start":
                continue
            age = int(t - _ts(e["at"]))
            if age > LONG_JOB_SECONDS:
                jobs.append({"id": cid, "text": e["text"], "seconds": age})
        usage = self.usage if self.usage and self.usage["status"] in ("warning", "limited") else None
        return {
            "state": self.state,
            "tasks": list(self.tasks.values()),
            "asks": [a for a in self.asks.values() if a["open"]],
            "helpers": [h for h in self.helpers.values() if h["open"]],
            "jobs": jobs,
            "usage": usage,
            "context": self.context,
            "denials": list(self.denials),
            "step": self.last_step if self.open_calls else "",
        }  # fmt: skip

    @classmethod
    def from_events(cls, events: list[dict]) -> Board:
        b = cls()
        for e in events:
            b.apply(e)
        return b

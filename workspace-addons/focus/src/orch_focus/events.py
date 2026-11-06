"""The run event log: one JSON line per event (orch.run.event/1), the same for every agent.

Lives at .orch/addons/focus/runs/<run>.events.jsonl, append-only, capped at 5 MB (the old half is
kept once as .1). Texts are plain words; commands are redacted before they are written.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

CAP_BYTES = 5 * 1024 * 1024
KINDS = (
    "run.state", "task.start", "task.done", "ask", "tool.start", "tool.end",
    "helper.start", "helper.end", "usage", "denial",
)  # fmt: skip

_SECRETS = [
    re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{12,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"),
    re.compile(r"(?i)(\b[A-Z0-9_]*(?:token|secret|password|passwd|api_?key|key)[A-Z0-9_]*\s*[=:]\s*)\S+"),
    re.compile(r"(?i)(--(?:token|password|secret|key)[= ])\S+"),
    re.compile(r"\S*\.orch/secrets\S*"),
]


def _hide(m: re.Match) -> str:
    return (m.group(1) if m.re.groups else "") + "[hidden]"


def redact(text: str) -> str:
    """Hide secrets, tokens and .orch/secrets paths in one piece of text."""
    out = str(text)
    for pat in _SECRETS:
        out = pat.sub(_hide, out)
    return out


def _redact_all(v):
    if isinstance(v, str):
        return redact(v)
    if isinstance(v, dict):
        return {k: _redact_all(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_redact_all(x) for x in v]
    return v


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def make(
    run: str, ticket: str, agent: str, kind: str, text: str, source: str, at: str | None = None, **data
) -> dict:
    """One event dict in the contract shape. `text` is clipped to 500 chars and redacted."""
    if kind not in KINDS:
        raise ValueError(f"unknown event kind {kind}")
    d = {k: v for k, v in data.items() if v is not None}
    d = _redact_all(d)  # every string in data, whatever its key
    if "command" in d:
        d["command"] = d["command"][:500]
    d["source"] = source
    return {
        "v": 1, "at": at or now(), "run": run, "ticket": ticket, "agent": agent, "kind": kind,
        "text": redact(text)[:500], "data": d,
    }  # fmt: skip


class EventLog:
    def __init__(self, root: Path, run: str):
        self.path = Path(root) / ".orch" / "addons" / "focus" / "runs" / f"{run}.events.jsonl"

    def append(self, *events: dict) -> None:
        if not events:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.path.stat().st_size > CAP_BYTES:
                os.replace(self.path, self.path.with_name(self.path.name + ".1"))
        except FileNotFoundError:
            pass
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n")

    def read(self, since: int = 0) -> tuple[list[dict], int]:
        """Events from byte offset `since`, and the new offset. Bad lines and unknown kinds are skipped."""
        try:
            with open(self.path, "rb") as f:
                f.seek(since)
                raw = f.read()
        except FileNotFoundError:
            return [], since
        end = raw.rfind(b"\n") + 1  # a half-written last line waits for the next read
        out = []
        for line in raw[:end].decode("utf-8", "replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("kind") in KINDS:
                out.append(e)
        return out, since + end

"""The run event log: one JSON line per event (orch.run.event/1), the same for every agent.

Lives at .orch/addons/focus/runs/<run>.events.jsonl, append-only, capped at 5 MB (the old half is
kept once as .1). Texts are plain words; commands are redacted before they are written.
"""

from __future__ import annotations

import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path

from . import runfiles

RUN_ID = re.compile(r"r_[a-z0-9]{8}")  # what core.runs.new_run_id makes
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
CAP_BYTES = 5 * 1024 * 1024
KINDS = (
    "run.state", "task.start", "task.done", "ask", "tool.start", "tool.end",
    "helper.start", "helper.end", "usage", "denial",
)  # fmt: skip

_SECRETS = [
    # a PEM block hides from its start marker to its end marker, or to the end of the text when that is cut off
    re.compile(r"-----BEGIN [A-Z0-9 ]+-----[\s\S]*?(?:-----END [A-Z0-9 ]+-----|\Z)"),
    re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{12,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"),
    re.compile(r"(?i)(\b[A-Z0-9_]*(?:token|secret|password|passwd|api_?key|key)[A-Z0-9_]*\s*[=:]\s*)\S+"),
    re.compile(r"(?i)(--(?:token|password|secret|key)[= ])\S+"),
    re.compile(r"(?<!\S)\S*?\.orch/secrets\S*"),
]


def _hide(m: re.Match) -> str:
    return (m.group(1) if m.re.groups else "") + "[hidden]"


def redact(text: str) -> str:
    """Hide secrets, tokens and .orch/secrets paths in one piece of text."""
    out = str(text)
    for pat in _SECRETS:
        out = pat.sub(_hide, out)
    return out


def clip(v: str, limit: int) -> str:
    """Cap the work first (a 5 MB value is not scanned whole), redact, then clip to the limit.
    The window ends at the next whitespace after limit + 256 (at most 4 KB further), so no token is split."""
    end = limit + 256
    if len(v) > end:
        m = re.search(r"\s", v[end : end + 4096])
        end = end + m.start() if m else end + 4096
    return redact(v[:end])[:limit]


def _clean(v, limit: int):
    """Redact first, then clip: a secret across the limit is hidden before it is cut."""
    if isinstance(v, str):
        return clip(v, limit)
    if isinstance(v, dict):
        return {k: _clean(x, limit) for k, x in v.items()}
    if isinstance(v, list):
        return [_clean(x, limit) for x in v]
    return v


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def make(
    run: str,
    ticket: str,
    agent: str,
    kind: str,
    text: str,
    source: str,
    at: str | None = None,
    text_max: int = 500,
    limits: dict[str, int] | None = None,
    **data,
) -> dict:
    """One event dict in the contract shape. The ONLY place that clips: every string (text and each data
    value) is redacted in full, then clipped to its limit (`text_max`, `limits[key]`, else 500)."""
    if kind not in KINDS:
        raise ValueError(f"unknown event kind {kind}")
    lim = limits or {}
    d = {k: _clean(v, lim.get(k, 500)) for k, v in data.items() if v is not None}
    d["source"] = source
    return {
        "v": 1, "at": at or now(), "run": run, "ticket": ticket, "agent": agent, "kind": kind,
        "text": clip(str(text), min(text_max, 500)), "data": d,
    }  # fmt: skip


def _plain(p: Path) -> None:
    if runfiles.is_link(p) or not p.is_dir():
        raise OSError(f"{p} is not a plain folder; Focus does not use it.")


def runs_dir(root: Path, create: bool = True) -> Path:
    """.orch/addons/focus/runs/, every level a plain folder (a symlink at any level is refused)."""
    d = Path(root)
    for part in (".orch", "addons", "focus", "runs"):
        d = d / part
        if create and not runfiles.is_link(d) and not runfiles.mkdir_private(d) and part == "runs":
            runfiles.check_listable(d)
        _plain(d)
    return d


class EventLog:
    def __init__(self, root: Path, run: str):
        if not isinstance(run, str) or not RUN_ID.fullmatch(run):
            raise ValueError("That is not a run id.")
        self.root = Path(root)
        self.path = self.root / ".orch" / "addons" / "focus" / "runs" / f"{run}.events.jsonl"

    def append(self, *events: dict) -> None:
        if not events:
            return
        runs_dir(self.root)
        old = self.path.with_name(self.path.name + ".1")
        try:
            st = os.lstat(self.path)
            if stat.S_ISREG(st.st_mode) and st.st_size > CAP_BYTES:
                os.replace(self.path, old)  # the file moves; its mode (0600) goes with it
        except FileNotFoundError:
            pass
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
        except AttributeError:  # Windows
            pass
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n")

    def read(self, since: int = 0) -> tuple[list[dict], int]:
        """Events from byte offset `since`, and the new offset. Bad lines and unknown kinds are skipped."""
        try:
            runs_dir(self.root, create=False)
            with os.fdopen(os.open(self.path, os.O_RDONLY | NOFOLLOW), "rb") as f:
                if since > os.fstat(f.fileno()).st_size:  # the log was rotated: start again
                    since = 0
                f.seek(since)
                raw = f.read()
        except OSError:
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


NOISE = re.compile(
    r"^\s*(New on t_[a-z0-9]+ since you looked|Base directory for this skill|---\s*name:)", re.IGNORECASE
)


def for_display(events: list[dict]) -> list[dict]:
    """What the page's feed shows (the log itself stays whole): no raw tool output (a step that worked shows
    only its start line; a failed one shows its first words), no orch's own "New on t_x since you looked"
    lines, and no line twice in a row."""
    out: list[dict] = []
    last = None
    for e in events:
        kind, text = e.get("kind"), str(e.get("text") or "")
        if kind == "tool.end":
            if (e.get("data") or {}).get("ok") is not False or NOISE.match(text):
                continue
            e = {**e, "text": "Failed: " + text[:100]}
        elif NOISE.match(text):
            continue
        key = (e.get("agent"), e.get("kind"), e.get("text"))
        if key == last:
            continue
        last = key
        out.append(e)
    return out

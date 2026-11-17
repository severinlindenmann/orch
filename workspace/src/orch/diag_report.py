"""`orch diag report`: one folder that holds what an agent needs to find out why something went wrong.

Layout (contracts/diag.md, "Report"): SUMMARY.md (< 20 KB, read first), manifest.json, timeline.jsonl,
errors.json,
checks.json, state/, logs/, record/, content/ (only with content on). Every file passes the workspace's
key hider
before it is written. A report is local: nothing here uploads anything. Reads only; it writes only into
`.orch/diag/reports/`.
"""

from __future__ import annotations

import contextlib
import heapq
import json
import os
import platform
import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

from orch import __version__, diag, diag_checks, diag_collect, diag_query, runs, tickets
from orch.errors import Refused

SCHEMA = "orch.diag-report/1"
SUMMARY_MAX = 20 * 1024
TIMELINE_MAX = 20_000
LOG_FILE_MAX = 5 * 1024 * 1024
CONTENT_CUT = 4000
PAGE_MAX = 2 * 1024 * 1024
MORE_MAX = 4000
ATTACH_MAX = 10
ATTACH_FILE_BYTES = 8 * 1024 * 1024
ATTACH_BYTES = 25 * 1024 * 1024
INCIDENT_MAX = 20
INCIDENT_BYTES = 50 * 1024 * 1024
REPORT_BYTES = 100 * 1024 * 1024  # reports have their own room: they never count against the debug log's 200 MB
TICKETS_STATE = "report-tickets.json"  # written by report_tickets.py: which reports became a ticket
REPORTS = "reports"
ABOUT = ("problem", "feature")  # what a report is about: something went wrong, or a feature wish
_SCOPE = re.compile(r"[^A-Za-z0-9_.-]")


def reports_dir(root: Path) -> Path:
    return root / ".orch" / "diag" / REPORTS


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Writer:
    """Makes the report folder (0700) and its files (0600, never through a link), hiding keys in each text."""

    def __init__(self, root: Path, folder: Path, hide):
        self.root, self.folder, self.hide, self.files = root, folder, hide, []

    def put(self, rel: str, text: str) -> None:
        p = self.folder / rel
        base = self.folder.resolve()
        if not (p.resolve().parent == base or base in p.resolve().parents):
            raise Refused("A report file would land outside the report folder. No report was made.")
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(p, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(self.hide(text))
        self.files.append(rel)

    def put_bytes(self, rel: str, data: bytes) -> None:
        """A file the person picked, stored as it is (a picture cannot pass the hider)."""
        p = self.folder / rel
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = (
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        )
        with os.fdopen(os.open(p, flags, 0o600), "wb") as f:
            f.write(data)
        self.files.append(rel)

    def put_json(self, rel: str, obj) -> None:
        self.put(rel, json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n")

    def put_lines(self, rel: str, rows) -> None:
        self.put(
            rel,
            "".join(
                json.dumps(r, ensure_ascii=False, default=str, separators=(",", ":")) + "\n" for r in rows
            ),
        )


def default_start(root: Path, scope: dict, collected: dict, now: float) -> tuple[float, str]:
    """From the scoped run's start, else the ticket's last successful transition, else 2 h back."""
    for rec in (collected["runs"]["data"].get("runs") or {}).values():
        if rec.get("started_at") and (not scope.get("run") or rec.get("run") == scope["run"]):
            with contextlib.suppress(ValueError):
                return runs._parse(rec["started_at"]), "start of the run"
    if scope.get("ticket"):
        last = None
        for e in diag_collect.recent_events(root, now - 7 * 86400):
            if (
                e.get("ev") == "ticket.op_applied"
                and e.get("ticket") == scope["ticket"]
                and (e.get("kv") or {}).get("written")
            ):
                last = e["at"]
        if last:
            return diag_query._epoch(last), "last successful change of the ticket"
        t = (collected["tickets"]["data"].get("tickets") or {}).get(scope["ticket"])
        if t and t.get("history_last_at"):
            with contextlib.suppress(ValueError, TypeError):
                return runs._parse(t["history_last_at"]), "last history line of the ticket"
    return now - 2 * 3600, "2 hours back (nothing narrower is known)"


def _safe_src(src) -> str:
    return src if isinstance(src, str) and diag._SRC.fullmatch(src) else "unknown"


def _in_scope(e: dict, scope: dict) -> bool:
    if scope.get("ticket") and e.get("ticket") not in (None, scope["ticket"]):
        return False
    if scope.get("run") and e.get("run") not in (None, scope["run"]):
        return False
    if scope.get("addon") and e.get("src") not in (scope["addon"], "cli", "host"):
        return False
    return True


def _timeline(root: Path, scope: dict, lo: float, hi: float, activity: list[dict], cap: int):
    streams: dict[tuple, list[dict]] = {}
    for e in diag_collect.recent_events(root, lo, hi):
        if _in_scope(e, scope):
            streams.setdefault(("diag", e.get("src"), e.get("pid"), e.get("proc_start")), []).append(
                diag_query._diag_item(e)
            )
    for e in activity:
        with contextlib.suppress(KeyError, ValueError):
            if lo <= diag_query._epoch(e["at"]) <= hi:
                streams.setdefault(("record", e.get("run")), []).append(diag_query._rec_item(e))
    for (
        rows
    ) in streams.values():  # one source keeps its own order (seq / mono_ms), whatever the wall clock did
        rows.sort(key=lambda r: (r.get("seq") or 0, r.get("mono_ms") or 0))
    merged = list(heapq.merge(*streams.values(), key=lambda r: r.get("at") or ""))
    return merged[-cap:], len(merged) > cap


def _errors(root: Path, lo: float, hi: float) -> list[dict]:
    groups: dict[str, dict] = {}
    for e in diag_collect.recent_events(root, lo, hi):
        err = e.get("err")
        if not err and e.get("lvl") != "error":
            continue
        fp = (err or {}).get("fingerprint") or f"ev:{e.get('ev')}"
        g = groups.setdefault(
            fp,
            {
                "fingerprint": fp,
                "type": (err or {}).get("type"),
                "ev": e.get("ev"),
                "count": 0,
                "first_seen": e["at"],
                "last_seen": e["at"],
                "code": e.get("code"),
                "sample_frames": (err or {}).get("frames") or [],
            },
        )
        g["count"] += 1
        g["last_seen"] = e["at"]
    return sorted(groups.values(), key=lambda g: -g["count"])


def _one_line(r: dict) -> str:
    kv = r.get("kv")
    extra = " ".join(f"{k}={v}" for k, v in (kv or {}).items())[:120] if kv else (r.get("kind") or "")
    who = f"{r.get('ticket') or ''} {r.get('run') or ''}"
    head = f"{(r.get('at') or '')[11:23]} {r.get('source')}/{r.get('lvl') or ''} {r.get('ev')}"
    return f"{head} {who} {extra}".rstrip()


def attachment_name(name, taken: set[str]) -> str:
    """A plain file name for attachments/: no folders, no leading dot, no control characters; a name already
    used gets -2, -3."""
    base = re.sub(r"[\x00-\x1f\x7f]", "", str(name or "")).replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[^\w. ()+-]", "_", base).strip(" .")[:80] or "file"
    stem, dot, ext = base.rpartition(".")
    stem, ext = (stem, dot + ext) if stem else (base, "")
    out, n = base, 1
    while out.lower() in taken:
        n += 1
        out = f"{stem}-{n}{ext}"
    taken.add(out.lower())
    return out


def check_attachments(files) -> list[tuple[str, bytes]]:
    """[(clean name, bytes)] of the files a person added, or Refused with what to do."""
    files = list(files or [])
    if len(files) > ATTACH_MAX:
        raise Refused(f"A report takes at most {ATTACH_MAX} added files. Remove some and try again.")
    taken: set[str] = set()
    out = []
    for name, data in files:
        if len(data) > ATTACH_FILE_BYTES:
            raise Refused(
                f"{str(name)[:60]} is bigger than {ATTACH_FILE_BYTES // 1024 // 1024} "
                f"MB. Leave it out or make it smaller."
            )
        out.append((attachment_name(name, taken), bytes(data)))
    if sum(len(d) for _, d in out) > ATTACH_BYTES:
        raise Refused(
            f"The added files are bigger than {ATTACH_BYTES // 1024 // 1024} MB "
            f"together. Remove some and try again."
        )
    return out


def summary(
    ref: str,
    scope: dict,
    lo: float,
    hi: float,
    why_start: str,
    checks,
    errors,
    timeline,
    note,
    expected,
    notes,
    content: bool,
    more=None,
    attachments=(),
    about="problem",
) -> str:
    wish = about == "feature"

    def build(n_timeline: int, n_errors: int) -> str:
        out = [f"# {'Feature wish' if wish else 'Diagnostic report'} {ref}", ""]
        if wish:
            out += [
                "This is a feature wish, not a problem: sort it first, do not start building it blindly.",
                "",
            ]
        if note:
            out += ["## What the person wants" if wish else "## What the person said", note[:600], ""]
        if expected:
            out += ["## Why it would help" if wish else "## What they expected", expected[:600], ""]
        if more:
            out += ["## More details from the person", more[:MORE_MAX], ""]
        if attachments:
            out += ["## Files the person added (attachments/)", *[f"- {n}" for n in attachments], ""]
        sc = ", ".join(f"{k} {v}" for k, v in scope.items() if v) or "whole workspace"
        out += [
            "## Scope and window",
            f"- scope: {sc}",
            f"- window: {_iso(lo)} to {_iso(hi)} ({why_start})",
            "- content (ticket text, helper excerpts): "
            + ("included in content/" if content else "not included"),
            "",
            "## Checks",
        ]
        order = {"problem": 0, "cannot_check": 1, "ok": 2}
        for c in sorted(checks, key=lambda c: order[c["verdict"]]):
            tag = {"problem": "PROBLEM", "cannot_check": "cannot check", "ok": "ok"}[c["verdict"]]
            out.append(f"- [{tag}] {c['name']}: {c['fact']}")
            out += [f"    - {x}" for x in c["evidence"][:5]]
        out += ["", "## Top errors"]
        out += [
            f"- {g['count']}x {g['type'] or g['ev']} ({g['fingerprint']}) "
            f"{g['first_seen']} .. {g['last_seen']} at {g['code']}"
            for g in errors[:n_errors]
        ] or ["- none in the window"]
        out += ["", f"## Last {n_timeline} timeline lines"]
        out += [f"    {_one_line(r)}" for r in timeline[-n_timeline:]] or ["    (empty)"]
        if notes:
            out += ["", "## Gaps (what could not be collected)", *[f"- {g}" for g in notes[:30]]]
        out += [
            "",
            "## Where to look next",
            "- checks.json: every check with its evidence",
            "- timeline.jsonl: all sources merged by time (per source in seq order)",
            "- errors.json: errors grouped by fingerprint",
            "- state/: tickets, runs, services, queues, locks, env as they were when the report was made",
            "- logs/: the raw debug log lines of the window; record/: the activity events, normalized",
            "- manifest.json: versions, OS, what was collected and what was skipped",
        ]
        return "\n".join(out) + "\n"

    n_t, n_e = 50, 10
    text = build(n_t, n_e)
    while len(text.encode()) > SUMMARY_MAX and (n_t > 0 or n_e > 0):
        n_t, n_e = max(0, n_t - 10), max(0, n_e - 2)
        text = build(n_t, n_e)
    if len(text.encode()) > SUMMARY_MAX:  # last resort: a hard cut, still starts with the checks
        text = text.encode()[: SUMMARY_MAX - 40].decode("utf-8", "ignore") + "\n(cut)\n"
    return text


def _content(root: Path, scope: dict, activity: list[dict], w: _Writer) -> None:
    ids = [scope["ticket"]] if scope.get("ticket") else []
    for tid in ids:
        with contextlib.suppress(Exception):
            t = tickets._load_raw(root, tid)
            w.put_json(f"content/ticket-{tid}.json", t)
    rows = []
    for e in activity:
        s = json.dumps(e, ensure_ascii=False, default=str)
        rows.append({k: e.get(k) for k in diag_query._REC_KEYS} | {"data": s[:CONTENT_CUT]})
    if rows:
        w.put_lines("content/helper-transcript.jsonl", rows[-500:])


def make(
    root: Path,
    *,
    ticket=None,
    run=None,
    addon=None,
    since=None,
    note=None,
    expected=None,
    content=True,
    kind="r",
    now=None,
    window_s=None,
    timeline_cap=TIMELINE_MAX,
    hide=None,
    page=None,
    more=None,
    files=None,
    about="problem",
) -> dict:
    """Make a report (`kind` r) or an incident (`kind` i, structure only, a short window). Returns {ref,
    path, ...}."""
    now = time.time() if now is None else now
    hide = hide or diag._hider(root)
    if hide is None:
        raise Refused("Secrets cannot be hidden here, so no report was made.")
    if about not in ABOUT:
        raise Refused("A report is about a problem or a feature.")
    scope = {"ticket": ticket, "run": run, "addon": addon}
    added = check_attachments(files) if kind == "r" else []
    more = (str(more).strip()[:MORE_MAX] or None) if more and kind == "r" else None
    collected = diag_collect.collect_all(root, scope, now)
    if since:
        lo = diag_query.window(since=since, now=now)[0]
        why = f"--since {since}"
    elif window_s:
        lo, why = now - window_s, f"the last {int(window_s // 60)} minutes"
    else:
        lo, why = default_start(root, scope, collected, now)
    hi = now
    events = list(diag_collect.recent_events(root, now - 86400))
    checks = diag_checks.run_all({"now": now, "collected": collected, "events": events})
    activity = collected["activity"]["data"].get("events", [])
    timeline, cut = _timeline(root, scope, lo, hi, activity, timeline_cap)
    errors = _errors(root, lo, hi)
    gaps = [f"{n}: {g}" for n, c in collected.items() for g in c["gaps"]]
    if cut:
        gaps.append(f"timeline: only the newest {timeline_cap} lines are kept")
    if addon:
        gaps.append("add-on collectors are not part of this report yet")
    label = _SCOPE.sub("", ticket or run or addon or "ws")[:40] or "ws"
    base = f"{kind}-{datetime.fromtimestamp(now, UTC).strftime('%m%d-%H%M')}-{label}"
    rdir = reports_dir(root)
    for part in (root / ".orch", root / ".orch" / "diag", rdir):
        if part.is_symlink():
            raise Refused(f"{part} is a link. No report was made.")
    rdir.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder = None
    used = _ticketed(root)  # a name that already has a ticket is never given out again
    for n in range(1, 50):
        ref = base if n == 1 else f"{base}-{n}"
        if ref in used:
            continue
        try:
            (rdir / ref).mkdir(mode=0o700)
            folder = rdir / ref
            break
        except FileExistsError:
            continue
    if folder is None:
        raise Refused("Too many reports in the same minute.")
    w = _Writer(root, folder, hide)
    try:
        w.put(
            "SUMMARY.md",
            summary(
                ref,
                scope,
                lo,
                hi,
                why,
                checks,
                errors,
                timeline,
                note,
                expected,
                gaps,
                bool(content),
                more,
                [n for n, _ in added],
                about if kind == "r" else "problem",
            ),
        )
        for name, data in added:
            w.put_bytes(f"attachments/{name}", data)
        w.put_json("checks.json", checks)
        w.put_lines("timeline.jsonl", timeline)
        w.put_json("errors.json", errors)
        for name in ("tickets", "runs", "services", "queues", "locks", "env", "disk", "diag"):
            w.put_json(f"state/{name}.json", collected[name])
        by_src: dict[str, list[str]] = {}
        for e in diag_collect.recent_events(root, lo, hi):
            if _in_scope(e, scope):
                by_src.setdefault(_safe_src(e.get("src")), []).append(
                    json.dumps(e, ensure_ascii=False, separators=(",", ":"))
                )
        for src, lines in by_src.items():
            text = "\n".join(lines) + "\n"
            if len(text) > LOG_FILE_MAX:
                text = text[-LOG_FILE_MAX:].split("\n", 1)[-1]
                gaps.append(f"logs/{src}.jsonl: only the newest {LOG_FILE_MAX // 1024 // 1024} MB is kept")
            w.put(f"logs/{src}.jsonl", text)
        by_run: dict[str, list[dict]] = {}
        for e in activity:
            by_run.setdefault(str(e.get("run")), []).append(
                {k: e.get(k) for k in diag_query._REC_KEYS} | {"kind": e.get("kind")}
            )
        for r, rows in by_run.items():
            w.put_lines(f"record/{_SCOPE.sub('', r)}.jsonl", rows)
        if content and kind == "r":
            _content(root, scope, activity, w)
        if (
            page and kind == "r"
        ):  # the dashboard's page snapshot (inputs masked there; text still hidden here)
            w.put("screen/page.html", str(page)[:PAGE_MAX])
        w.put_json(
            "manifest.json",
            {
                "schema": SCHEMA,
                "ref": ref,
                "kind": "report" if kind == "r" else "incident",
                "about": about if kind == "r" else "problem",
                "created_at": _iso(now),
                "scope": scope,
                "window": {"from": _iso(lo), "to": _iso(hi), "why": why},
                "content": bool(content and kind == "r"),
                "note": (note or "")[:600] or None,
                "expected": (expected or "")[:600] or None,
                "more": more,
                "attachments": [{"name": n, "size": len(d)} for n, d in added],
                "orch_version": __version__,
                "python": platform.python_version(),
                "os": f"{platform.system()} {platform.release()}",
                "tz_offset_s": time.localtime().tm_gmtoff,
                "collected": {n: {"at": c["collected_at"], "gaps": c["gaps"]} for n, c in collected.items()},
                "files": sorted(w.files),
                "problems": [c["name"] for c in checks if c["verdict"] == "problem"],
            },
        )
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)  # exactly the folder this call made
        raise
    prune(root)
    return {
        "ref": ref,
        "about": about if kind == "r" else "problem",
        "path": str(folder),
        "problems": [c["name"] for c in checks if c["verdict"] == "problem"],
        "checks": checks,
    }


# ---------------------------------------------------------------- budgets


def _size(p: Path) -> int:
    total = 0
    for dp, _dn, fn in os.walk(p, followlinks=False):
        for f in fn:
            with contextlib.suppress(OSError):
                total += (Path(dp) / f).lstat().st_size
    return total


def delete_all(root: Path) -> int:
    """Settings > Delete all: every report folder (r-...) goes, by its exact path; incidents (i-...) stay
    (they are the log's own safety net). Returns how many went."""
    rdir = reports_dir(root)
    gone = 0
    if rdir.is_symlink() or not rdir.is_dir():
        return 0
    for p in list(rdir.iterdir()):
        if p.name.startswith("r-") and p.is_dir() and not p.is_symlink():
            shutil.rmtree(p, ignore_errors=True)
            gone += 1
    diag.log("diag.reports_deleted", "info", root=root, count=gone)
    return gone


def _ticketed(root: Path) -> set[str]:
    """Report names the ticket pass has seen (a ticket was made, or the report was there when it was turned on)."""
    try:
        d = json.loads((root / ".orch" / "diag" / TICKETS_STATE).read_text())
        seen = d.get("seen") if isinstance(d, dict) else None
        return set(seen) if isinstance(seen, dict) else set()
    except (OSError, ValueError):
        return set()


def prune(root: Path) -> list[str]:
    """Reports and incidents do NOT count against the debug log's 200 MB: the log gives way on its own
    (diag.prune). More than 20 incidents or 50 MB of them, the oldest incident goes. Reports have their own
    room (REPORT_BYTES); over it, the oldest report that already became a ticket goes. A report without a
    ticket is never removed here (only `orch diag delete reports` does that). Each removal is a
    `diag.report_pruned` event."""
    rdir = reports_dir(root)
    if rdir.is_symlink() or not rdir.is_dir():
        return []
    items = []
    for p in rdir.iterdir():
        if p.is_symlink() or not p.is_dir() or p.name[:2] not in ("r-", "i-"):
            continue
        with contextlib.suppress(OSError):
            items.append((p.stat().st_mtime, p.name, p, _size(p)))
    items.sort()
    gone: list[str] = []

    def drop(it, why):
        shutil.rmtree(it[2], ignore_errors=True)  # a folder this module made, by its exact path
        items.remove(it)
        gone.append(it[1])
        diag.log("diag.report_pruned", "info", root=root, ref=it[1], why=why)

    inc = [i for i in items if i[1].startswith("i-")]
    while inc and (len(inc) > INCIDENT_MAX or sum(i[3] for i in inc) > INCIDENT_BYTES):
        drop(inc[0], "incident budget")
        inc.pop(0)
    rep = [i for i in items if i[1].startswith("r-")]
    done = _ticketed(root)
    for it in list(rep):
        if sum(i[3] for i in rep) <= REPORT_BYTES:
            break
        if it[1] in done:
            drop(it, "report budget, already a ticket")
            rep.remove(it)
    return gone

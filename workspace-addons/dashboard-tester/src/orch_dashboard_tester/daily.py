"""One daily look: open every dashboard page, report what is new, check reported findings again.

A pass that finds nothing new costs no tokens. Each pass
  1. opens every page at 1280, 1920 and 390 px (browser.py), plus the newest working and the newest Review ticket.
     It only opens and reads: it never presses a button, so it cannot answer a card, start, merge, allow or delete.
  2. reports NEW findings with `orch report problem --no-send` (kept on this computer, never shared), with
     pictures: each big one (page error, server error, empty page, sign-in broken) alone, the small ones together,
     at most MAX_REPORTS a pass. A finding whose words already stand in an open ticket is not reported.
  3. checks again: a reported finding remembers its report and, once a ticket "Investigate orch report <ref>"
     exists, that ticket. When that ticket is finished and the finding is gone, it counts as fixed; when it is
     still there it is reported again ("still there after ..."). A fixed finding that comes back is reported again.
  4. with --helper-each-release only: when orch's version changed since the last helper, one sub-ticket for a
     helper that reads the pass's pictures and page texts like the person would (low priority, the small model).
  5. writes one line on the ticket of the repeat (orch log) and keeps the result in .orch/addons/dashboard-tester/.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from . import words

BY = "agent:dashboard-tester"
MAX_REPORTS = 3
FINISHED = {"done", "review", "archived"}
GONE = {"dropped", "wontdo"}
CORE_ROUTES = ["#home", "#tickets", "#review", "#chat", "#settings"]

HELPER_BRIEF = """You look at the dashboard of this workspace for orch release {version} like the person who uses it.
Today's daily look saved a picture of every page at 1280, 1920 and 390 px and the text of each page in
{folder} (shots/ and texts/). Read them; do not open the dashboard and never click anything.

Look for: wrong or unclear words, steps that seem to need more than one click, things that look broken or cut off,
pages that are hard to read at phone width. The daily look already reports page errors, slow and empty pages,
sideways scroll and never-list words: do not report those again.

Report every finding with `orch report problem "<what>" --expected "<what you expected>" --file <picture> --no-send`
(not shared); put small related findings into one report. Before a report, check `orch ticket list`: never report
what already has an open ticket. When you finish: list the reports you made in the ticket summary and set this
ticket to done."""


def stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ref_of(title: str) -> str | None:
    m = re.match(r"Investigate orch report (r-\d{4}-\d{4}[-\w]*)", title or "")
    return m.group(1) if m else None


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)


def space(root: Path) -> Path:
    return root / ".orch" / "addons" / "dashboard-tester"


def orch_bin() -> str:
    return os.environ.get("ORCH_BIN") or shutil.which("orch") or "orch"


def orch(root: Path, args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [orch_bin(), *args], cwd=root, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess([orch_bin(), *args], 1, "", str(e))


def as_json(p: subprocess.CompletedProcess):
    try:
        return json.loads(p.stdout)
    except ValueError:
        return None


class Refused(Exception):
    pass


class World:
    """Everything a pass reads or does outside itself (orch, the browser); tests replace it."""

    def __init__(self, root: Path, out: Path, dry: bool = False):
        self.root, self.out, self.dry = root, out, dry
        self.sent: list[dict] = []

    def tickets(self) -> list[dict]:
        data = as_json(orch(self.root, ["ticket", "list", "--all", "--json"]))
        items = data.get("tickets", []) if isinstance(data, dict) else data
        return [t for t in items or [] if isinstance(t, dict) and isinstance(t.get("id"), str)]

    def addons(self) -> list[dict]:
        data = as_json(orch(self.root, ["addon", "list", "--json"]))
        items = data.get("addons", []) if isinstance(data, dict) else data
        return [a for a in items or [] if isinstance(a, dict)]

    def version(self) -> str:
        r = orch(self.root, ["--version"], timeout=30)
        return r.stdout.strip().split()[-1] if r.stdout.strip() else ""

    def launch_url(self) -> str:
        """A one-time sign-in link to this workspace's dashboard (starts it when it is not running). orch makes it
        only for a run a person started (the daily repeat), never for a helper; it is never printed."""
        r = orch(self.root, ["start", "--print-launch-url", "--json"], timeout=180)
        data = as_json(r)
        for row in (data or {}).get("launch", []) if isinstance(data, dict) else []:
            if isinstance(row, dict) and row.get("addon") == "dashboard" and isinstance(row.get("url"), str):
                return row["url"]
        why = (r.stdout + r.stderr).strip().splitlines()
        raise Refused(
            "Could not sign in to the dashboard"
            + (f": {why[-1][:200]}" if why else ".")
            + " The daily look runs from the repeat a person allowed, not from a helper."
        )

    def browse(self, routes: list[str]) -> dict:
        from . import browser

        return browser.look(self.launch_url(), routes, words.load(), self.out)

    def send(self, rep: dict) -> tuple[str | None, str]:
        """One report through `orch report problem`, kept on this computer (not shared). (ref, how)."""
        self.sent.append(rep)
        if self.dry:
            return (None, "dry run")
        args = ["report", "problem", rep["what"][:600], "--expected", rep.get("expected", ""), "--by", BY,
                "--no-send", "--json"]  # fmt: skip
        if rep.get("more"):
            args += ["--more", rep["more"][:4000]]
        for p in rep.get("pictures", [])[:5]:
            if p and Path(p).is_file():
                args += ["--file", p]
        c = orch(self.root, args, timeout=300)
        ref = (as_json(c) or {}).get("ref") if isinstance(as_json(c), dict) else None
        return (ref, "orch report problem" if ref else "the report failed: " + (c.stdout + c.stderr)[-120:])

    def start_helper(self, parent: str | None, version: str) -> str | None:
        if self.dry:
            return "dry run"
        args = ["ticket", "new", f"Dashboard tester: look at release {version} like the person", "--by", BY,
                "--note", HELPER_BRIEF.format(version=version, folder=".orch/addons/dashboard-tester/last"),
                "--done-when", "Every finding of this release is reported", "--json"]  # fmt: skip
        if parent:
            args += ["--parent", parent]
        data = as_json(orch(self.root, args))
        tid = data.get("id") if isinstance(data, dict) else None
        if not tid:
            return None
        orch(
            self.root, ["ticket", "model", tid, "sonnet", "--by", BY]
        )  # a look-and-report job: the small model
        orch(self.root, ["run", "start", tid, "--priority", "low", "--by", BY])
        return tid

    def note(self, ticket: str | None, text: str) -> None:
        if ticket and not self.dry:
            orch(self.root, ["log", ticket, text[:1900], "--by", BY])


def routes_for(addons: list[dict], tickets: list[dict]) -> list[str]:
    """The pages of this workspace: the core pages, one per add-on that is on and shows in the dashboard, and the
    newest working and newest Review ticket."""
    out = list(CORE_ROUTES)
    for a in addons:
        name = a.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", name):
            continue
        if a.get("active") is False or not (a.get("dashboard") or a.get("page")):
            continue
        dash = a.get("dashboard") if isinstance(a.get("dashboard"), dict) else {}
        r = f"#settings/addons/{name}" if dash.get("place") == "settings" else f"#addon/{name}"
        if r not in out:
            out.append(r)

    def newest(status: str) -> str | None:
        ts = sorted(
            (t for t in tickets if t.get("status") == status), key=lambda t: t.get("updated_at") or ""
        )
        return ts[-1]["id"] if ts else None

    for tid in (newest("active"), newest("review")):
        if tid and re.fullmatch(r"t_[a-z0-9]{6,16}", tid):
            out.append(f"#ticket/{tid}")
    return out


def person_words(f: dict, titles: list[str]) -> bool:
    """A program value (null, NaN) or a never-list word inside a ticket's own title is a person's words, not a bug."""
    if not str(f.get("key", "")).startswith(("leak|", "word|")):
        return False
    m = re.search(r'"(.+)"\s*$', f.get("text", ""))
    shown = re.sub(r"^[A-Z][A-Z0-9]*-\d+\s+", "", m.group(1)).strip() if m else ""  # without a key like WS-2
    return len(shown) >= 8 and any(shown in t or t in shown for t in titles)


def build_reports(new: list[dict], back: list[tuple[dict, dict]]) -> list[dict]:
    """Big findings one per report, small ones (and every 'still there') together in one report."""
    reps, smalls = [], []
    for f in new:
        if f.get("severity") == "big":
            reps.append({"keys": [f["key"]], "pictures": [f["shot"]] if f.get("shot") else [],
                         "what": f"Dashboard tester: {f['text']} ({f.get('viewport', '')} width).",
                         "expected": "The page shows its content within a few seconds, with no error.",
                         "more": f"Found by the daily dashboard look ({stamp()}). Page {f.get('route')}."})  # fmt: skip
        else:
            smalls.append(f)
    lines, keys, pics = [], [], []
    for f in smalls:
        lines.append(f"- {f['text']} ({f.get('viewport', '')})")
        keys.append(f["key"])
        if f.get("shot") and f["shot"] not in pics:
            pics.append(f["shot"])
    for f, old in back:
        after = old.get("ticket_key") or old.get("ticket") or old.get("ref")
        lines.append(f"- Still there after {after} was finished: {f['text']}")
        keys.append(f["key"])
        if f.get("shot") and f["shot"] not in pics:
            pics.append(f["shot"])
    if lines:
        what = f"Dashboard tester found {len(lines)} small problem(s) in the daily look: " + "; ".join(
            x[2:] for x in lines
        )
        reps.append({"keys": keys, "pictures": pics[:5], "what": what[:590],
                     "expected": "Pages fit the phone width, load within a few seconds and use the plain orch words.",
                     "more": "Each finding:\n" + "\n".join(lines)})  # fmt: skip
    return reps[:MAX_REPORTS]  # the biggest first; the rest waits for the next pass


def run_pass(world, state: dict, ticket: str | None, helper_each_release: bool = False) -> dict:
    tickets = world.tickets()
    by_ref: dict[str, dict] = {}
    for t in tickets:
        r = ref_of(t.get("title", ""))
        if r and r not in by_ref:
            by_ref[r] = t
    summary = {"at": stamp(), "found": 0, "new": [], "fixed": [], "back": [], "waiting": [], "reports": [],
               "has_ticket": [], "error": None}  # fmt: skip
    try:
        data = world.browse(routes_for(world.addons(), tickets))
    except Refused as e:
        summary["error"] = str(e)
        state["last_pass"] = summary["at"]
        return summary
    except Exception as e:  # noqa: BLE001 - the browser broke: say so on the ticket, keep the findings
        summary["error"] = f"The browser look broke: {str(e)[-300:]}"
        state["last_pass"] = summary["at"]
        return summary
    titles = [t["title"] for t in tickets if isinstance(t.get("title"), str) and len(t["title"]) >= 8]
    cur = {
        f["key"]: f
        for f in data.get("findings", [])
        if isinstance(f, dict) and f.get("key") and not person_words(f, titles)
    }
    summary["found"] = len(cur)
    known: dict = state.setdefault("findings", {})

    new, back = [], []
    for key, old in known.items():
        t = by_ref.get(old.get("ref") or "")
        if t:
            old["ticket"], old["ticket_key"], old["ticket_status"] = t["id"], t.get("key"), t.get("status")
        finished = old.get("ticket_status") in FINISHED
        if old.get("status") == "reported":
            if key in cur and finished:
                back.append((cur[key], old))
                summary["back"].append(cur[key]["text"])
            elif key not in cur and finished:
                old["status"], old["fixed_at"] = "fixed", stamp()
                summary["fixed"].append(old["text"])
            elif key not in cur and old.get("ticket_status") in GONE:
                old["status"] = "dropped"
            else:
                summary["waiting"].append(old["text"])
                if key in cur:
                    old["last_seen"] = stamp()
        elif old.get("status") == "fixed" and key in cur:
            back.append((cur[key], old))
            summary["back"].append(cur[key]["text"])
    open_text = [
        (t.get("title") or "") + "\n" + (t.get("note") or "") + "\n" + (t.get("description") or "")
        for t in tickets
        if t.get("status") not in FINISHED | GONE
    ]
    for key, f in cur.items():
        if key in known:
            continue
        if any(f["text"][:60] in txt for txt in open_text):
            summary["has_ticket"].append(f["text"])  # an open ticket already has it: no second report
            continue
        new.append(f)
        summary["new"].append(f["text"])
    new.sort(key=lambda f: f.get("severity") != "big")

    for rep in build_reports(new, back):
        ref, how = world.send(rep)
        summary["reports"].append({"ref": ref, "how": how, "what": rep["what"][:200]})
        for k in rep["keys"]:
            f = cur[k]
            known[k] = {"text": f["text"], "kind": f.get("kind"), "route": f.get("route"), "ref": ref,
                        "status": "reported" if ref else "not-sent",
                        "first_seen": known.get(k, {}).get("first_seen", stamp()),
                        "last_seen": stamp(), "reported_at": stamp(), "how": how}  # fmt: skip
    # a finding whose report failed is tried again next time (not-sent is not known yet)
    for k in [k for k, v in known.items() if v.get("status") == "not-sent"]:
        known.pop(k)

    if helper_each_release:
        version = world.version()
        if version and version != state.get("helper_version"):
            tid = world.start_helper(ticket, version)
            if tid:
                state["helper_version"] = version
                summary["helper"] = f"release {version}: {tid}"
    state["last_pass"] = summary["at"]
    return summary


def note_text(s: dict) -> str:
    parts = [f"Dashboard look {s['at'][:16].replace('T', ' ')} UTC: {s['found']} finding(s) on screen."]
    if s.get("error"):
        parts.append(s["error"][-300:])
    for label, k in (
        ("New", "new"),
        ("Fixed and checked again", "fixed"),
        ("Still there after the fix", "back"),
    ):
        if s[k]:
            parts.append(f"{label}: " + " | ".join(x[:120] for x in s[k][:8]))
    if s["has_ticket"]:
        parts.append(f"{len(s['has_ticket'])} finding(s) already have an open ticket.")
    if s["waiting"]:
        parts.append(f"{len(s['waiting'])} reported finding(s) wait for their ticket.")
    for r in s["reports"]:
        parts.append(f"Report {r['ref'] or '(not made)'}: {r['how'][:80]}.")
    if s.get("helper"):
        parts.append("Helper started for " + s["helper"] + ".")
    return " ".join(parts)

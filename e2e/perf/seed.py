"""Seed a throwaway workspace with many realistic tickets, to measure how orch behaves at size (ORCH-518).

usage: python e2e/perf/seed.py <workspace folder> --tickets 10000 [--seed 1] [--live 50] [--pictures clone|copy|link]

The folder must already hold a workspace made by `orch init` in a throwaway home, and it must lie under
~/.orch-test, the system temp folder or $RUNNER_TEMP: the script refuses any other folder, a folder that
already holds tickets that it did not seed, and an ORCH_HOME that is not strict (never the real workspace).

What it writes, shaped like a real workspace (measured on the orch workspace on 18 Nov: 527 tickets, median
12 KB per ticket file, 4 steps, 25 history lines, 1 question, about 3.5 pictures per ticket):
- ticket files in .orch/tickets with mixed states (about 78% done, 6% dropped, 7% waiting, 6% to do, the
  rest working, ready or in review), epics with parts and other parents, notes, done-when lines,
  descriptions, summaries, estimates, steps with evidence (notes, commands, pull requests, commits, files),
  questions with options and answers, history, pull request links and add-on data (pull-requests, factory,
  automation), helper sessions;
- per ticket an artifacts folder with pictures and notes, evidence files and reviewed before/after pictures;
  the pictures come from a small pool of real-sized PNGs: on macOS as clones (own files, no extra disk, so
  50,000 tickets fit on a laptop), elsewhere as copies (--pictures link: hard links, which sync refuses);
- live helper records in .orch/run/tickets for --live working tickets (pid of this script's parent, so the
  dashboard shows them as running while that shell lives);
- the ticket counter, so `orch ticket new` goes on after the highest number.

The same --seed gives the same workspace. Prints one JSON line with what it wrote and how long it took.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import random
import struct
import sys
import tempfile
import time
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

MARK = "seeded.json"  # .orch/seeded.json: written by this script, so a second run may add to its own seed

ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"

# share of each status among all tickets (real workspace, 18 Nov)
STATUS_MIX = [
    ("done", 78.0),
    ("dropped", 5.5),
    ("waiting", 7.2),
    ("open", 5.7),
    ("ready", 1.3),
    ("active", 1.2),
    ("review", 1.1),
]

AREAS = {
    "sales": (
        ["Monthly sales report for", "Follow up with", "Prepare the offer for", "Update the price list for",
         "Call back", "Plan the visit to", "Check the open invoices of"],  # fmt: skip
        ["Linde AG", "Rössli Hotel", "Seegarten", "the Bern office", "Müller & Co", "the trade fair team",
         "October", "November", "the new customers", "Alpina Sport"],  # fmt: skip
    ),
    "support": (
        ["Answer the question from", "Find out why the export fails for", "Write a help page about",
         "Close the old requests of", "Reply to the complaint of", "Test the fix for"],  # fmt: skip
        ["Frau Keller", "the login page", "the phone app", "the shop export", "printing labels",
         "the weekly mail", "the partner portal", "Herr Brunner"],  # fmt: skip
    ),
    "engineering": (
        ["Fix the crash in", "Speed up", "Add paging to", "Write tests for", "Move", "Clean up",
         "Review the pull request for", "Update the docs of"],  # fmt: skip
        ["the ticket list", "the dashboard Home", "the sync step", "the relay inbox", "the search box",
         "the merge queue", "the settings page", "the board view", "the import"],  # fmt: skip
    ),
    "marketing": (
        ["Draft the newsletter for", "Plan the campaign for", "Make pictures for", "Write the post about",
         "Collect quotes for", "Check the numbers of"],  # fmt: skip
        ["spring", "the new app", "the trade fair", "the website", "the partner day", "the blog",
         "the October launch"],  # fmt: skip
    ),
    "management": (
        ["Prepare the board meeting on", "Decide on", "Plan the budget for", "Hire for", "Review the goals of"],
        ["the next quarter", "the new office", "the support team", "the year 2027", "the tooling"],
    ),
}

WORDS = (
    "the team checked the numbers again and found that the export missed two columns so the report was "
    "fixed and sent to the customer who asked for a short call next week about the new prices and the "
    "delivery dates which now fit the plan the helper wrote a test for it and the page shows the right "
    "state after a reload on the phone too nothing else changed the old file stays as it was"
).split()

STEP_TEXTS = [
    "Collect the numbers", "Write the first draft", "Ask the team who comes", "Check the old version",
    "Fix it and test it", "Take pictures at three widths", "Write the summary", "Send it to the customer",
    "Test it, open the pull request and put it in the merge queue", "Read the logs", "Compare with last month",
    "Book the room", "Update the help page", "Find three options", "Measure before and after",
]  # fmt: skip

QUESTIONS = [
    ("Which day suits the supplier?", ["Tuesday", "Thursday"]),
    ("Plan ready", ["Start work", "Change sub-tickets"]),
    ("Send the offer now or wait for the new prices?", ["Send now", "Wait"]),
    ("Merge this pull request?", ["Merge", "Not yet"]),
    ("Which of the three drafts do you want?", ["Draft A", "Draft B", "Draft C"]),
    ("Keep the old export as a fallback?", ["Keep it", "Remove it"]),
]

HUMANS = ["human:lume", "human:anna", "human:marco"]
AGENTS = ["agent:claude", "agent:claude", "agent:claude", "agent:codex", "agent:pull-requests",
          "agent:automation", "agent:reviewer", "orch"]  # fmt: skip


def real_home() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def allowed_bases() -> list[Path]:
    bases = [real_home() / ".orch-test", Path(tempfile.gettempdir()), Path("/tmp"), Path("/private/tmp")]
    if os.environ.get("RUNNER_TEMP"):
        bases.append(Path(os.environ["RUNNER_TEMP"]))
    return [b.resolve() for b in bases if b.exists()]


def refuse_unsafe(ws: Path) -> None:
    """Exit unless ws is a throwaway workspace: under an allowed base, made by orch init, and either empty of
    tickets or seeded by this script before."""
    ws = ws.resolve()
    if not any(ws.is_relative_to(b) and ws != b for b in allowed_bases()):
        sys.exit(f"Refused: {ws} is not under ~/.orch-test, the temp folder or $RUNNER_TEMP.")
    if os.environ.get("ORCH_HOME_STRICT") != "1" or not os.environ.get("ORCH_HOME"):
        sys.exit("Refused: run it with ORCH_HOME=<throwaway folder> and ORCH_HOME_STRICT=1.")
    orch_home = Path(os.environ["ORCH_HOME"]).resolve()
    if orch_home == (real_home() / ".orch-tool").resolve():
        sys.exit("Refused: ORCH_HOME is the real orch home.")
    if not (ws / ".orch" / "config.toml").is_file():
        sys.exit(f"Refused: {ws} holds no workspace. Run `orch init` there first (in the throwaway home).")
    tdir = ws / ".orch" / "tickets"
    if tdir.is_dir() and any(tdir.glob("t_*.json")) and not (ws / ".orch" / MARK).is_file():
        sys.exit(f"Refused: {ws} already holds tickets that this script did not seed.")


def workspace_code(ws: Path) -> str:
    """The workspace's ticket code; set to one made from the folder name when there is none yet (as the first
    `orch ticket new` would), through orch's own config code from this checkout."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workspace" / "src"))
    from orch import config  # noqa: PLC0415

    return config.workspace_code(ws) or config.set_code(ws, config.suggest_code(ws.name))


# ---------------------------------------------------------------- pictures


def _png(width: int, height: int, rng: random.Random) -> bytes:
    """A PNG of the given size that does not compress away (noise bands), so it weighs like a screenshot."""
    rows = []
    for y in range(height):
        band = bytes(rng.getrandbits(8) for _ in range(width * 3 // 8))
        flat = bytes([240, 242, 245]) * (width - len(band) // 3)
        rows.append(b"\x00" + band[: (len(band) // 3) * 3] + flat)
    raw = b"".join(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def picture_pool(ws: Path, rng: random.Random) -> list[Path]:
    """12 PNGs from about 20 KB to 200 KB (real median about 100 KB), kept under .orch/seed-pool."""
    pool = ws / ".orch" / "seed-pool"
    pool.mkdir(parents=True, exist_ok=True)
    out = []
    for i, (w, h) in enumerate([(390, 120), (640, 200), (1280, 200), (1280, 300), (390, 400), (800, 250),
                                (1280, 160), (1920, 140), (640, 320), (1280, 260), (390, 260), (1024, 220)]):  # fmt: skip
        p = pool / f"pool-{i}.png"
        if not p.exists():
            p.write_bytes(_png(w, h, rng))
        out.append(p)
    return out


_CLONE = None


def _clonefile(src: Path, dest: Path) -> bool:
    """A copy-on-write clone (macOS APFS): its own file, no extra disk until written."""
    global _CLONE
    if sys.platform != "darwin":
        return False
    if _CLONE is None:
        import ctypes

        _CLONE = ctypes.CDLL("libc.dylib", use_errno=True).clonefile
    return _CLONE(os.fsencode(src), os.fsencode(dest), 0) == 0


def place_picture(src: Path, dest: Path, how: str) -> None:
    """how: clone (macOS, falls back to copy), copy, or link (a hard link: least disk, but sync refuses
    files with more than one link)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return
    if how == "link":
        os.link(src, dest)
    elif how == "copy" or not _clonefile(src, dest):
        dest.write_bytes(src.read_bytes())


# ---------------------------------------------------------------- tickets


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class Seeder:
    def __init__(self, ws: Path, n: int, seed: int, live: int, pictures: str, now: datetime):
        self.ws = ws
        self.n = n
        self.rng = random.Random(seed)
        self.live = live
        self.pictures_how = pictures
        self.now = now
        self.code = workspace_code(ws)
        self.tdir = ws / ".orch" / "tickets"
        self.tdir.mkdir(parents=True, exist_ok=True)
        self.pool = picture_pool(ws, self.rng)
        self.ids: set[str] = {p.stem for p in self.tdir.glob("t_*.json")}
        self.start_key = self._last_key()
        self.files = 0
        self.bytes = 0

    def _last_key(self) -> int:
        try:
            return int(json.loads((self.ws / ".orch" / "ticket-counter.json").read_text()).get("last", 0))
        except (OSError, ValueError):
            return 0

    def new_id(self) -> str:
        while True:
            tid = "t_" + "".join(self.rng.choice(ALPHABET) for _ in range(6))
            if tid not in self.ids:
                self.ids.add(tid)
                return tid

    def words(self, lo: int, hi: int) -> str:
        n = self.rng.randint(lo, hi)
        start = self.rng.randrange(len(WORDS))
        text = " ".join(WORDS[(start + i) % len(WORDS)] for i in range(n))
        return text[:1].upper() + text[1:] + "."

    def status(self, age_days: float) -> str:
        # older tickets are mostly finished; open work is recent
        mix = STATUS_MIX if age_days > 3 else [(s, w * (6 if s not in ("done", "dropped") else 1)) for s, w in STATUS_MIX]
        return self.rng.choices([s for s, _ in mix], weights=[w for _, w in mix])[0]

    def title(self) -> str:
        verbs, objs = AREAS[self.rng.choice(list(AREAS))]
        return f"{self.rng.choice(verbs)} {self.rng.choice(objs)}"

    def history(self, created: datetime, until: datetime, count: int, status: str) -> list[dict]:
        span = max(1.0, (until - created).total_seconds())
        lines = [{"at": iso(created), "by": self.rng.choice(HUMANS), "via": "dashboard", "text": "Created",
                  "chat_message": False}]  # fmt: skip
        texts = ["Claude started", "Status: Working", "Step c1 done", "Pull request checks: Passed",
                 "Asked q1", "Answered q1: Start work", "Note added", "Model picked: Sonnet",
                 "Waiting on https://github.com/example/shop/pull/{n}", "Merged on green",
                 "Summary: {w}", "Step c2 started", "Picture added: after-1280.png"]  # fmt: skip
        for i in range(count - 1):
            at = created + timedelta(seconds=span * (i + 1) / count)
            t = self.rng.choice(texts).format(n=self.rng.randint(100, 9999), w=self.words(6, 18))
            lines.append({"at": iso(at), "by": self.rng.choice(AGENTS + HUMANS[:1]),
                          "via": self.rng.choice(["cli"] * 14 + ["dashboard", "phone", "reviewer"]),
                          "text": t, "chat_message": False})  # fmt: skip
        if status in ("done", "review"):
            lines.append({"at": iso(until), "by": "human:lume" if status == "done" else "agent:claude",
                          "via": "dashboard" if status == "done" else "cli",
                          "text": f"Status: {'Done' if status == 'done' else 'Review'}", "chat_message": False})  # fmt: skip
        return lines

    def evidence(self, tid: str, at: datetime, finished: bool) -> list[dict]:
        out = []
        for _ in range(self.rng.choice([1, 1, 2, 2, 2, 3, 3, 4]) if finished else 0):  # a done step has proof
            kind = self.rng.choices(["note", "command", "pr", "file", "commit", "url"], [16, 9, 6, 4, 1.5, 0.6])[0]
            e = {"type": kind, "by": "agent:claude", "at": iso(at)}
            if kind == "note":
                e["ref"] = self.words(15, 70)
            elif kind == "command":
                e.update(ref="pytest tests/test_export.py -q -n 2", exit=0, ran_at=iso(at))
            elif kind == "pr":
                n = self.rng.randint(100, 9999)
                e.update(ref=f"https://github.com/example/shop/pull/{n}", title=f"PR {n}")
            elif kind == "file":
                name = f"log-{self.rng.randint(1, 99)}.txt"
                self.write_text(self.tdir / tid / "evidence" / name, self.words(200, 900))
                e.update(ref=f".orch/tickets/{tid}/evidence/{name}", text="4 KB", title="Test log",
                         summary=self.words(8, 20))  # fmt: skip
            elif kind == "commit":
                e.update(ref="".join(self.rng.choice("0123456789abcdef") for _ in range(8)), title="Test log")
            else:
                e["ref"] = f"https://example.com/docs/{self.rng.randint(1, 500)}"
            out.append(e)
        return out

    def write_text(self, p: Path, text: str) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text + "\n", encoding="utf-8")
        self.files += 1
        self.bytes += len(text) + 1

    def pictures(self, tid: str, finished: bool) -> list[str]:
        names = []
        count = self.rng.choice([0, 0, 1, 2, 3, 3, 4, 5, 6, 8]) if finished else self.rng.choice([0, 0, 0, 1, 2])
        for i in range(count):
            name = self.rng.choice(["after", "before", "home", "board", "phone"]) + f"-{i}-{self.rng.choice([390, 1280, 1920])}.png"
            place_picture(self.rng.choice(self.pool), self.tdir / tid / "artifacts" / name, self.pictures_how)
            self.files += 1
            names.append(name)
        if finished and self.rng.random() < 0.8:
            self.write_text(self.tdir / tid / "artifacts" / "report.md", "# Report\n\n" + self.words(80, 400))
        if finished and self.rng.random() < 0.1:
            for side in ("before", "after"):
                place_picture(self.rng.choice(self.pool),
                              self.tdir / tid / "reviewed" / f"{self.rng.getrandbits(48):012x}" / f"{side}-1280.png",
                              self.pictures_how)  # fmt: skip
                self.files += 1
        return names

    def ticket(self, idx: int, tid: str, created: datetime, parent: str | None, epic: bool) -> dict:
        age = (self.now - created).total_seconds() / 86400
        status = self.status(age)
        finished = status in ("done", "dropped", "review")
        until = min(self.now, created + timedelta(hours=self.rng.uniform(0.3, 72)))
        if not finished:
            until = self.now - timedelta(minutes=self.rng.uniform(1, 600))
            until = max(until, created)
        t: dict = {
            "schema": "orch.ticket/1",
            "id": tid,
            "key": f"{self.code}-{self.start_key + idx + 1}",
            "title": self.title(),
            "status": status,
            "created_at": iso(created),
            "updated_at": iso(until),
            "checklist": [],
            "refs": [],
            "questions": [],
            "history": [],
            "revision": self.rng.randint(3, 60),
        }
        if parent:
            t["parent"] = parent
        if epic:
            t["epic"] = True
        if self.rng.random() < 0.87:
            t["note"] = self.words(15, 160)
        if self.rng.random() < 0.85:
            t["done_when"] = self.words(10, 40)
        if self.rng.random() < 0.63:
            t["description"] = self.words(15, 50)
            t["description_by"] = "agent:claude"
        if self.rng.random() < 0.2:
            t["estimate"] = {"minutes": self.rng.choice([30, 60, 120, 240, 600]), "cost": round(self.rng.uniform(2, 120), 1),
                             "by": "agent:claude", "at": iso(created)}  # fmt: skip
        if status != "open" or self.rng.random() < 0.3:
            t["started"] = True
            t["model"] = {"name": self.rng.choice(["sonnet", "sonnet", "opus"]), "by": "orch", "why": "picked by size"}
            t["sessions"] = [{"agent": "claude", "id": "%032x" % self.rng.getrandbits(128), "host": "laptop.local",
                              "last_used": iso(until)}]  # fmt: skip
        t["waiting_on"] = None
        names = self.pictures(tid, finished)
        for c in range(self.rng.choice([0, 1, 2, 3, 4, 4, 5, 5, 6, 7, 9, 12])):
            done = finished or self.rng.random() < 0.4
            item = {"id": f"c{c + 1}", "text": self.rng.choice(STEP_TEXTS), "done": done,
                    "evidence": self.evidence(tid, until, done)}  # fmt: skip
            if self.rng.random() < 0.5 and t.get("done_when"):
                item["covers"] = t["done_when"][:40]
            if names and done and self.rng.random() < 0.4:
                item["evidence"].append({"type": "file", "ref": f".orch/tickets/{tid}/artifacts/{names[0]}",
                                         "text": "104 KB", "title": "Picture", "by": "agent:claude", "at": iso(until)})  # fmt: skip
            t["checklist"].append(item)
        for q in range(self.rng.choice([0, 0, 1, 1, 1, 2, 2, 3, 5])):
            text, options = self.rng.choice(QUESTIONS)
            answered = finished or q > 0 or status != "waiting" or self.rng.random() < 0.3
            qd = {"id": f"q{q + 1}", "text": text + " " + self.words(3, 60), "options": options,
                  "recommended": options[0], "answer": self.rng.choice(options) if answered else None,
                  "answered_by": self.rng.choice(HUMANS) if answered else None,
                  "via": "phone" if self.rng.random() < 0.3 else "dashboard",
                  "asked_at": iso(created)}  # fmt: skip
            if answered:
                qd["answered_at"] = iso(until)
            if names and self.rng.random() < 0.3:
                qd["card"] = {"kind": "check", "title": "Look at the new pictures"}
            t["questions"].append(qd)
        for _ in range(self.rng.choice([0, 0, 0, 1, 1, 2, 3])):
            n = self.rng.randint(100, 9999)
            t["refs"].append({"kind": "github:pull", "url": f"https://github.com/example/shop/pull/{n}",
                              "at": iso(created), "by": "agent:claude", "title": f"PR {n}",
                              "status": self.rng.choice(["open", "merged", "merged", "closed"]), "seen_at": iso(until)})  # fmt: skip
        if status == "waiting":
            if t["refs"] and self.rng.random() < 0.5:
                t["waiting_on"] = {"kind": "external", "ref": t["refs"][0]["url"]}
            elif any(q["answer"] is None for q in t["questions"]):
                t["waiting_on"] = {"kind": "question", "ref": "q1"}
            else:
                t["waiting_on"] = {"kind": "time", "until": iso(self.now + timedelta(hours=self.rng.randint(1, 48)))}
        ext = {}
        if t["refs"] and self.rng.random() < 0.6:
            ext["pull-requests"] = {"pr": "#" + t["refs"][0]["url"].rsplit("/", 1)[1],
                                    "checks": self.rng.choice(["Passed", "Failed", "Running"]),
                                    "merge": self.rng.choice(["Merged", "Blocked", "Ready"])}  # fmt: skip
        if self.rng.random() < 0.08:
            ext["factory"] = {"role": "crew", "order": tid, "task": "stage1", "crew_role": "tester", "agent": "claude"}
        if self.rng.random() < 0.02:
            ext["automation"] = {"recurring": True, "cron": "0 8 * * 1", "tz": "Europe/Zurich"}
        if ext:
            t["ext"] = ext
        if finished and self.rng.random() < 0.9:
            t["summary"] = self.words(10, 30)[:200]
        t["history"] = self.history(created, until, self.rng.choice([3, 8, 12, 18, 25, 25, 30, 45, 67, 120]), status)
        return t

    def write_ticket(self, t: dict) -> None:
        p = self.tdir / f"{t['id']}.json"
        text = json.dumps(t, indent=2, ensure_ascii=False) + "\n"
        p.write_text(text, encoding="utf-8")
        self.files += 1
        self.bytes += len(text.encode("utf-8"))

    def live_record(self, t: dict, pid: int) -> None:
        d = self.ws / ".orch" / "run" / "tickets"
        d.mkdir(parents=True, exist_ok=True)
        run = "r_" + "".join(self.rng.choice(ALPHABET) for _ in range(8))
        rec = {"schema": "orch.run/1", "ticket": t["id"], "run": run, "by": "agent:claude", "agent": "claude",
               "mode": "live", "folder": str(self.ws), "pid": pid, "host": "laptop.local",
               "started_at": t["updated_at"], "renewed_at": iso(self.now), "pending": False,
               "stop_requested": None, "seen_revision": t["revision"], "seen_history": len(t["history"]),
               "live": {"state": self.rng.choice(["working", "working", "idle"]), "since": iso(self.now)}, "up": True}  # fmt: skip
        (d / f"{t['id']}.json").write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")

    def run(self) -> dict:
        t0 = time.monotonic()
        span_days = max(30.0, self.n / 25)  # about 25 new tickets a day
        created = sorted(self.now - timedelta(days=self.rng.uniform(0, span_days)) for _ in range(self.n))
        tids = [self.new_id() for _ in range(self.n)]
        # parents: about 6% of tickets have parts, half of them epics; about a third of all tickets are parts
        parent_of: dict[int, str] = {}
        epics: set[int] = set()
        for i in range(self.n):
            if self.rng.random() < 0.06 and i + 2 < self.n:
                if self.rng.random() < 0.5:
                    epics.add(i)
                for j in range(i + 1, min(self.n, i + 1 + self.rng.randint(2, 8))):
                    parent_of.setdefault(j, tids[i])
        live_left = self.live
        pid = os.getppid()
        counts: dict[str, int] = {}
        for i in range(self.n):
            t = self.ticket(i, tids[i], created[i], parent_of.get(i), i in epics)
            if live_left and t["status"] in ("active", "waiting", "ready"):
                self.live_record(t, pid)
                live_left -= 1
            self.write_ticket(t)
            counts[t["status"]] = counts.get(t["status"], 0) + 1
        last = self.start_key + self.n
        (self.ws / ".orch" / "ticket-counter.json").write_text(json.dumps({"last": last}) + "\n", encoding="utf-8")
        mark = self.ws / ".orch" / MARK
        prev = json.loads(mark.read_text()) if mark.is_file() else {"tickets": 0}
        (mark).write_text(json.dumps({"tickets": prev["tickets"] + self.n, "seeded_at": iso(self.now)}) + "\n")
        return {"tickets": self.n, "live": self.live - live_left, "statuses": counts, "files": self.files,
                "text_bytes": self.bytes, "seconds": round(time.monotonic() - t0, 1), "last_key": f"{self.code}-{last}"}  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seed a throwaway workspace with many realistic tickets.")
    ap.add_argument("workspace")
    ap.add_argument("--tickets", type=int, required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--live", type=int, default=50, help="working tickets with a live helper record")
    ap.add_argument("--pictures", choices=("clone", "copy", "link"), default="clone" if sys.platform == "darwin" else "copy",
                    help="clone (macOS: no extra disk), copy, or link (hard links: sync refuses them)")
    ap.add_argument("--now", default=None, help="the time the seed ends at (default: now), for fixed output")
    a = ap.parse_args(argv)
    if a.tickets < 1 or a.tickets > 200_000:
        sys.exit("--tickets must be 1 to 200000.")
    ws = Path(a.workspace)
    refuse_unsafe(ws)
    now = datetime.strptime(a.now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) if a.now else datetime.now(UTC).replace(microsecond=0)
    out = Seeder(ws.resolve(), a.tickets, a.seed, a.live, a.pictures, now).run()
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

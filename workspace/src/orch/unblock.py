"""The Merge unblocker (`orch github unblock`, ORCH-180): finds green pull requests that do not merge and
merges or reports them, for a repeating automation (no AI call; a pass that finds nothing writes nothing).

The manager stepped in on 17 Nov for three kinds: a merge-on-green wait that sat 50 minutes without a word,
the merge limit holding eight green pull requests, and a pull request with a GitHub workflow file the
helpers' login may not merge. Each pass

  1. reads every open pull request linked to a ticket (not Dropped) that goes into an allowed base branch
     (`github.unblock_bases`, default develop; never main or a release branch: those are the owner's and the
     Release keeper's);
  2. keeps a green clock per pull request: open, ready, no conflict, no changes requested and every check
     passed on its newest commit. A new commit starts it again;
  3. calls one green for STUCK_MIN minutes or more stuck, unless a person merges it with a Merge card or the
     merge queue has it;
  4. for a stuck one, in this order: a workflow file in it (or GitHub refused the merge for one) = one
     question to the owner on its ticket; no room in the merge limit = one line on its ticket with when the
     next place frees; into a base branch a merge queue merges into = one line on its ticket to put it in
     that queue, never merged here (#1809: merges went past the queue); otherwise it is merged on the
     checked commit as `orch ref wait --merge` merges (with
     the merge switch `github.unblock_merge` off, the default, it is only reported). Each is said once per
     commit;
  5. a pass that did or said something writes one note on the role ticket.

Off until the owner names the role ticket (`orch config set github.unblock <ticket>`). Nothing happens while
automation is paused.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
from pathlib import Path

from orch import brake, config, ghlimit, ghmerge, refs, review, runs, stuck, tickets
from orch.errors import Refused

BY = "agent:merge-unblocker"
STUCK_MIN = 15  # green this long and still open = stuck (a pass every 10 min acts within 30 min of green)
MAX_PULLS = 30  # pull requests read per pass
MAX_MERGES = 3  # merges per pass: each waits for the pause between two merges (ghlimit.PAUSE_SECS)
DEFAULT_BASES = ("develop",)
WORKFLOW_DIR = ".github/workflows/"
WORKFLOW_REFUSED = re.compile(r"workflow", re.IGNORECASE)
NEVER_BASE = re.compile(r"^(main|master|release/.*)$")
BASE_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
LOCK_STALE = 15 * 60
STATE_MAX = 512 * 1024
NOTE_MAX = 3000
VIEW_FIELDS = "state,isDraft,mergeable,reviewDecision,baseRefName,headRefOid,statusCheckRollup"
OPTIONS = ("I merged it", "Leave it open")


# ---------------------------------------------------------------- settings


def _settings(root: Path | None) -> dict:
    if root is None:
        return {}
    try:
        got = config.read(root).get("github") or {}
    except (Refused, OSError):
        return {}
    return got if isinstance(got, dict) else {}


def role(root: Path | None) -> str | None:
    """[github] unblock: the role ticket (key or id), or None (off)."""
    v = _settings(root).get("unblock")
    v = v.strip() if isinstance(v, str) else ""
    return v if v and len(v) <= 64 else None


def merge_on(root: Path | None) -> bool:
    """[github] unblock_merge: True = merge a plain stuck pull request; False (default) = only report it."""
    return _settings(root).get("unblock_merge") is True


def bases(root: Path | None) -> list[str]:
    """[github] unblock_bases: the base branches a stuck pull request may be merged into (never main or a
    release branch, whatever is set)."""
    v = _settings(root).get("unblock_bases")
    items = [b.strip() for b in v.split(",")] if isinstance(v, str) and v.strip() else list(DEFAULT_BASES)
    return [b for b in items if isinstance(b, str) and BASE_RE.match(b) and not NEVER_BASE.match(b)]


def set_role(root: Path, value: str) -> str | None:
    """A ticket key or id turns it on (the ticket must exist); off clears it."""
    v = (value or "").strip()
    if v.lower() in ("off", "none", ""):
        config.set_key(root, "github", "unblock", None)
        return None
    t = tickets.load(root, tickets.resolve(root, v))  # an unknown ticket is refused here
    keep = str(t.get("key") or t["id"])
    config.set_key(root, "github", "unblock", keep)
    return keep


def set_merge(root: Path, value: str) -> bool:
    if value not in ("on", "off"):
        raise Refused("Choose on or off.")
    config.set_key(root, "github", "unblock_merge", value == "on")
    return value == "on"


def set_bases(root: Path, value: str) -> list[str]:
    items = [b.strip() for b in (value or "").split(",") if b.strip()]
    if not items or any(not BASE_RE.match(b) for b in items):
        raise Refused("Name the base branches separated by commas, for example develop or develop,next.")
    bad = [b for b in items if NEVER_BASE.match(b)]
    if bad:
        raise Refused(f"{bad[0]} is merged by a person or the Release keeper, never by the Merge unblocker.")
    config.set_key(root, "github", "unblock_bases", ",".join(items))
    return items


# ---------------------------------------------------------------- GitHub


class GitHub:
    """Reads pull requests and merges one, through gh. Tests pass a fake with the same three methods."""

    def view(self, url: str) -> dict | None:
        try:
            got = ghmerge._gh_plain(_gh(), ["pr", "view", url, "--json", VIEW_FIELDS], 20)
            data = json.loads(got.stdout) if got.returncode == 0 else None
        except (Refused, ValueError):
            return None
        return data if isinstance(data, dict) and isinstance(data.get("headRefOid"), str) else None

    def files(self, url: str) -> list[str] | None:
        try:
            got = ghmerge._gh_plain(_gh(), ["pr", "view", url, "--json", "files"], 20)
            data = json.loads(got.stdout) if got.returncode == 0 else None
        except (Refused, ValueError):
            return None
        if not isinstance(data, dict) or not isinstance(data.get("files"), list):
            return None
        return [str(f.get("path") or "") for f in data["files"] if isinstance(f, dict)]

    def merge(self, url: str, head: str):
        """Merge as `orch ref wait --merge` does, but never wait an hour for room: only for the short pause
        between two merges. Returns a prwait.Outcome."""
        from orch import prwait

        class _Now(prwait.Live):
            def take(self, kind: str, what: str) -> bool:
                pause = ghlimit.pause_secs(kind, ghlimit.limits()[ghlimit.kind_of(kind)])
                return ghlimit.take(kind, what, wait=pause + 10)

        def same_head(now_head: str) -> str | None:
            return None if now_head == head else "it got a new commit since it was seen green"

        return prwait.run_one(url, True, timeout=5 * 60, src=_Now(url), before_merge=same_head)


def _gh() -> str:
    import shutil

    gh = shutil.which("gh")
    if gh is None:
        raise Refused("This needs the GitHub command line (gh), signed in.")
    return gh


def green(v: dict, allowed: list[str]) -> bool:
    """Open, ready, into an allowed base, no conflict, no changes requested, every check passed."""
    return (
        v.get("state") == "OPEN"
        and v.get("isDraft") is False
        and v.get("baseRefName") in allowed
        and v.get("mergeable") != "CONFLICTING"
        and v.get("reviewDecision") != "CHANGES_REQUESTED"
        and ghmerge.passed(v.get("statusCheckRollup"))
    )


# ---------------------------------------------------------------- state


def _state_path(root: Path) -> Path:
    return runs.run_dir(root) / "merge-unblock.json"


def _lock_path(root: Path) -> Path:
    return runs.run_dir(root) / "merge-unblock.lock"


def read_state(root: Path) -> dict:
    try:
        p = _state_path(root)
        if p.stat().st_size > STATE_MAX:
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and isinstance(data.get("pulls", {}), dict) else {}


def _write_state(root: Path, state: dict) -> None:
    with contextlib.suppress(OSError):
        runs.run_dir(root).mkdir(parents=True, exist_ok=True)
        runs._atomic(_state_path(root), json.dumps(state, indent=1, sort_keys=True) + "\n")


def _take_lock(root: Path) -> bool:
    """One pass at a time: a pass that merges can take a few minutes (a lock left by a dead pass ages out)."""
    p = _lock_path(root)
    with contextlib.suppress(OSError):
        runs.run_dir(root).mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            return True
        except FileExistsError:
            try:
                if time.time() - p.stat().st_mtime < LOCK_STALE:
                    return False
                p.unlink()
            except OSError:
                return False
        except OSError:
            return False
    return False


def _drop_lock(root: Path) -> None:
    with contextlib.suppress(OSError):
        _lock_path(root).unlink()


# ---------------------------------------------------------------- what is linked


def _queued(root: Path) -> set[str]:
    """Pull requests an add-on's merge queue has waiting or running, read only: any add-on folder with a
    `queue.json` of {"entries": [{"url", "state"}]} (core names no add-on, R1.2)."""
    out: set[str] = set()
    try:
        files = sorted((root / ".orch" / "addons").glob("*/queue.json"))
    except OSError:
        return out
    for p in files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = data.get("entries") if isinstance(data, dict) else None
        rows = rows if isinstance(rows, list) else []
        out |= {
            str(r["url"]).lower()
            for r in rows
            if isinstance(r, dict)
            and isinstance(r.get("url"), str)
            and r.get("state") in ("waiting", "running")
        }
    return out


def linked(root: Path) -> list[dict]:
    """[{url, ticket id, key, merge_card}] for every open pull request reference of a ticket not Dropped."""
    out: list[dict] = []
    seen: set[str] = set()
    for t in tickets.list_all(root):
        if t.get("status") == "dropped" or not isinstance(t.get("refs"), list):
            continue
        full = t
        try:
            rows = [r for _, r in refs.all_refs(root, full)]
        except (Refused, OSError, ValueError, TypeError):
            continue
        cards = {review.merge_url(q) for q in full.get("questions") or [] if q.get("answer") is None}
        for url in stuck.open_pulls({"refs": rows}):
            if url in seen:
                continue
            seen.add(url)
            out.append(
                {"url": url, "ticket": full["id"], "key": str(full.get("key") or full["id"]),
                 "merge_card": url in cards}
            )  # fmt: skip
    return out


# ---------------------------------------------------------------- one pass


def _num(url: str) -> str:
    return "#" + url.rsplit("/", 1)[-1]


def _mins(secs: float) -> int:
    return max(1, int(round(secs / 60)))


def _limit_room() -> tuple[bool, dict]:
    """(full, status row of merges): full = this hour's merges are used up (not only the short pause)."""
    try:
        row = next(r for r in ghlimit.status() if r["kind"] == "merge")
    except (StopIteration, OSError, Refused):
        return False, {}
    return row["used"] >= row["per_hour"], row


def _say(root: Path, tid: str, text: str) -> None:
    with contextlib.suppress(Refused, OSError):
        tickets.note_history(root, tid, BY, text)


def _ask_owner(root: Path, item: dict, mins: int) -> bool:
    text = (
        f"Pull request {_num(item['url'])} passed its checks {mins} minutes ago but changes a GitHub "
        f"workflow file, which the helpers' GitHub login may not merge. Please open it and merge it on "
        f"GitHub: {item['url']}"
    )
    try:
        tickets.ask(root, item["ticket"], text, list(OPTIONS), OPTIONS[0], BY)
    except (Refused, OSError):
        return False
    return True


def run(root: Path, *, dry_run: bool = False, now: float | None = None, gh=None) -> dict:
    """One pass: {"off"|"paused"|"busy", "merged", "asked", "limit", "reported", "watching", "note"}.
    dry_run reads GitHub but writes nothing and merges nothing."""
    role_ref = role(root)
    if not role_ref:
        return {"off": True}
    if brake.paused(root) is not None:
        return {"paused": True}
    role_id = tickets.resolve(root, role_ref)
    role_t = tickets.load(root, role_id)  # the role ticket was removed: Refused, said in plain words
    now = time.time() if now is None else now
    if not dry_run and not _take_lock(root):
        return {"busy": True}
    try:
        return _pass(root, role_id, str(role_t.get("key") or role_id), dry_run, now, gh or GitHub())
    finally:
        if not dry_run:
            _drop_lock(root)


def _pass(root: Path, role_id: str, role_key: str, dry: bool, now: float, gh) -> dict:
    allowed, merging = bases(root), merge_on(root)
    st = read_state(root)
    pulls = st.get("pulls") if isinstance(st.get("pulls"), dict) else {}
    queued = _queued(root)
    from orch.cli import _queue_bases  # the bases `orch ref wait --merge` refuses too (ORCH-450)

    queue_bases = set(_queue_bases(root))
    items = linked(root)[:MAX_PULLS]
    res: dict = {"off": False, "paused": False, "role": role_key, "merge": merging, "merged": [], "asked": [],
                 "limit": [], "reported": [], "held": [], "watching": 0, "errors": []}  # fmt: skip
    keep: dict = {}
    full, limit_row = _limit_room()
    merges = 0
    for item in items:
        url = item["url"]
        old = pulls.get(url) if isinstance(pulls.get(url), dict) else {}
        v = gh.view(url)
        if v is None:
            res["errors"].append(f"GitHub did not show {_num(url)}")
            if old:
                keep[url] = old
            continue
        if v.get("state") != "OPEN" or not green(v, allowed):
            continue  # merged, closed, not green or not ours: the clock stops
        head = v["headRefOid"]
        since = float(old.get("green_since") or now) if old.get("head") == head else now
        told = old.get("told") if old.get("head") == head and isinstance(old.get("told"), dict) else {}
        rec = {"head": head, "green_since": since, "told": told}
        keep[url] = rec
        res["watching"] += 1
        green_secs = now - since
        if green_secs < STUCK_MIN * 60 or item["merge_card"] or url.lower() in queued:
            continue
        mins = _mins(green_secs)
        where = f"{_num(url)} ({item['key']})"
        if told.get("asked"):
            continue  # the owner has the question for this commit
        files = gh.files(url)
        if files is None:
            res["errors"].append(f"GitHub did not list the files of {_num(url)}")
            continue
        if any(f.startswith(WORKFLOW_DIR) for f in files):
            if not dry and _ask_owner(root, item, mins):
                told["asked"] = now
            res["asked"].append(where)
            continue
        if full:
            if not told.get("limit"):
                nxt = _mins(float(limit_row.get("next_in_secs") or 60))
                line = (
                    f"Checks of {url} passed {mins} minutes ago; it waits for this computer's merge limit "
                    f"({limit_row.get('used')} of {limit_row.get('per_hour')} merges this hour), the next "
                    f"place frees in about {nxt} minutes. It is merged then (Merge unblocker)."
                )
                if not dry:
                    _say(root, item["ticket"], line)
                    told["limit"] = now
            res["limit"].append(where)
            continue
        into_queue = str(v.get("baseRefName") or "") in queue_bases  # #1809: never past the merge queue
        if not merging or into_queue:
            if not told.get("reported"):
                line = (
                    f"Checks of {url} passed {mins} minutes ago and nothing merged it. Put it in the merge "
                    f"queue: orch pull-requests queue add {url} --ticket {item['key']}"
                    if into_queue
                    else f"Checks of {url} passed {mins} minutes ago and nothing merged it. Merge it: "
                    f"orch ref wait {item['key']} --merge"
                )
                if not dry:
                    _say(root, item["ticket"], line)
                    told["reported"] = now
            res["reported"].append(where)
            continue
        if merges >= MAX_MERGES:
            continue  # the next pass
        if dry:
            res["merged"].append(where + " (would merge)")
            continue
        merges += 1
        try:
            o = gh.merge(url, head)
        except Refused as e:
            res["errors"].append(f"{_num(url)}: {e}")
            continue
        if o.ok and o.status == "merged":
            keep.pop(url, None)
            _say(
                root,
                item["ticket"],
                f"{o.line} It was green {mins} minutes and not merged (Merge unblocker).",
            )
            with contextlib.suppress(Refused, OSError):
                tickets.ref_set(root, item["ticket"], url, "merged", BY)
            res["merged"].append(where)
        elif WORKFLOW_REFUSED.search(o.line or ""):
            if _ask_owner(root, item, mins):
                told["asked"] = now
            res["asked"].append(where)
        else:
            if told.get("held") != o.line:
                _say(root, item["ticket"], f"{o.line} (Merge unblocker)")
                told["held"] = o.line
            res["held"].append(f"{where}: {o.line}")
        full, limit_row = _limit_room()
    acted = res["merged"] or res["asked"] or res["limit"] or res["reported"] or res["held"]
    res["note"] = note_text(res, now) if acted else None
    if not dry:
        if res["note"] and _changed(st, res):
            with contextlib.suppress(Refused, OSError):
                tickets.log(root, role_id, res["note"][:NOTE_MAX], BY)
            st["last_fp"] = _fp(res)
        st["pulls"] = keep
        _write_state(root, st)
    return res


def _fp(res: dict) -> str:
    return json.dumps([res[k] for k in ("merged", "asked", "limit", "reported", "held")], sort_keys=True)


def _changed(st: dict, res: dict) -> bool:
    """A merge is always worth a note; the same waits and reports again are not."""
    return bool(res["merged"]) or st.get("last_fp") != _fp(res)


def note_text(res: dict, now: float) -> str:
    parts = []
    if res["merged"]:
        parts.append("merged " + ", ".join(res["merged"]))
    if res["asked"]:
        parts.append("the owner merges (workflow file) " + ", ".join(res["asked"]))
    if res["limit"]:
        parts.append("waiting for the merge limit " + ", ".join(res["limit"]))
    if res["reported"]:
        parts.append("green and not merged (merging is off) " + ", ".join(res["reported"]))
    if res["held"]:
        parts.append("not merged: " + "; ".join(res["held"]))
    stamp = time.strftime("%d %b %H:%M", time.localtime(now))
    return f"Merge unblocker {stamp}: " + "; ".join(parts) + "."


def text(res: dict, dry_run: bool = False) -> str:
    if res.get("off"):
        return "The Merge unblocker is off here. Turn it on: orch config set github.unblock <role ticket>"
    if res.get("paused"):
        return "Automation is paused here: the Merge unblocker did nothing. Turn it back on: orch resume."
    if res.get("busy"):
        return "Another Merge unblocker pass is still running; this one did nothing."
    head = "Dry run, nothing written. " if dry_run else ""
    errs = (" " + "; ".join(res["errors"]) + ".") if res.get("errors") else ""
    if not res.get("note"):
        return head + f"Nothing stuck: {res.get('watching', 0)} green pull request(s) watched.{errs}"
    return head + res["note"] + errs

"""The background job's one pass: find the pull requests the tickets link, read their repositories (one GitHub call
per repository), keep what was seen in .orch/addons/pull-requests/prs.json, and refresh a ticket's links only when what it
shows changed. Tickets change only through the core (`orch pull-requests act refresh -- <ticket>`), never here.

prs.json: {"schema": "orch.pull-requests-prs/1", "polled_at", "repos": {"<owner/name>": {"polled_at", "error"?,
"open": [<number>]}}, "prs": {"<url>": <row>}} (rows from prstate.row).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import prread as gh
from . import prstate, store

SCHEMA = "orch.pull-requests-prs/1"
FINAL = ("merged", "closed")
REPOS_MAX = 10  # repositories read in one pass (one GitHub call each)
CACHED_ENV = (
    "ORCH_PULL_REQUESTS_CACHED"  # set for the refresh the job starts: answer from prs.json, no GitHub call
)
ID_RE = re.compile(r"^t_[a-z0-9]{6,16}$")
REPO_IN_URL = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/|$)")
BY = "agent:pull-requests"
EXT = "pull-requests"  # ext.<this add-on>


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


MAX_STATE = 4 * 1024 * 1024


def state_file(root: Path) -> Path:
    return store.folder(root) / "prs.json"


def _safe_dir(root: Path, create: bool) -> Path:
    """.orch, .orch/addons and the add-on's folder: real folders inside the workspace, never links (a repo can
    plant a link there to aim the write somewhere else)."""
    d = root
    for part in state_file(root).relative_to(root).parts[:-1]:
        d = d / part
        if d.is_symlink():
            raise OSError(f"refusing a linked folder: {d}")
        if create and not d.exists():
            d.mkdir(mode=0o700)
        if d.exists() and not d.is_dir():
            raise OSError(f"not a folder: {d}")
    return d


def load(root: Path) -> dict:
    data = None
    try:
        _safe_dir(root, create=False)
        fd = os.open(state_file(root), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as f:
            raw = f.read(MAX_STATE + 1)
        if len(raw) <= MAX_STATE:
            data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        data = {"schema": SCHEMA, "polled_at": None, "repos": {}, "prs": {}}
    if not isinstance(data.get("repos"), dict):
        data["repos"] = {}
    if not isinstance(data.get("prs"), dict):
        data["prs"] = {}
    return data


def save(root: Path, data: dict) -> None:
    """A new file next to it, then rename: a planted link at prs.json is replaced, never followed."""
    d = _safe_dir(root, create=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".prs-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, state_file(root))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------- the orch CLI


def orch(root: Path, *args: str, env: dict | None = None, timeout: int = 60):
    """`$ORCH_BIN <args> --json` → parsed JSON, or None on any failure."""
    head, tail = list(args), []
    if "--" in head:
        cut = head.index("--")
        head, tail = head[:cut], head[cut:]
    cmd = [os.environ.get("ORCH_BIN") or "orch", *head, "--json", *tail]
    try:
        p = subprocess.run(
            cmd,
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            env={**os.environ, **(env or {})},
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except ValueError:
        return None


def tickets(root: Path) -> list[dict]:
    data = orch(root, "ticket", "list", "--all")
    items = data.get("tickets", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [t for t in items if isinstance(t, dict) and isinstance(t.get("id"), str) and ID_RE.match(t["id"])]


# ---------------------------------------------------------------- what the tickets link


def links(t: dict) -> list[dict]:
    """The ticket's pull request links: [{url, repo, number, status, title}]."""
    out = []
    for r in t.get("refs") or []:
        if not isinstance(r, dict):
            continue
        p = prstate.parse_url(r.get("url") or "")
        if p:
            out.append(
                {
                    "url": f"https://github.com/{p[0]}/pull/{p[1]}",
                    "ref_url": r["url"],
                    "repo": p[0],
                    "number": p[1],
                    "status": r.get("status"),
                    "title": r.get("title"),
                }
            )
    return out


def open_ticket(t: dict) -> bool:
    return t.get("status") not in ("done", "dropped")


def plan(ts: list[dict]) -> dict[str, list[int]]:
    """{repo: [linked pull request numbers still worth asking about]}: the repositories the open tickets link (a
    pull request, an issue or the repository itself), and every link not yet merged or closed."""
    want: dict[str, set[int]] = {}
    for t in ts:
        if open_ticket(t):
            for r in t.get("refs") or []:
                m = REPO_IN_URL.match(str((r or {}).get("url") or "")) if isinstance(r, dict) else None
                if m:
                    want.setdefault(m[1], set())
        for ln in links(t):
            if ln["status"] not in FINAL:
                want.setdefault(ln["repo"], set()).add(ln["number"])
    ordered = sorted(want, key=lambda r: (-len(want[r]), r.lower()))[:REPOS_MAX]
    return {r: sorted(want[r]) for r in ordered}


def ticket_of(ts: list[dict]) -> dict[str, dict]:
    """{pull request url: {"id", "key"}} for linked pull requests (an open ticket wins over a finished one)."""
    out: dict[str, dict] = {}
    for t in sorted(ts, key=open_ticket):
        for ln in links(t):
            out[ln["url"]] = {"id": t["id"], "key": t.get("key") or t["id"], "title": t.get("title") or ""}
    return out


# ---------------------------------------------------------------- one pass


def read(root: Path, want: dict[str, list[int]], data: dict, fetch=gh.fetch) -> dict:
    """Read each repository once and merge the answer into `data` (in place). Returns data."""
    stamp = now()
    for repo, nums in want.items():
        rec = data["repos"].setdefault(repo, {})
        try:
            got = fetch(repo, nums)
        except gh.GhError as e:
            rec.update({"polled_at": stamp, "error": str(e)})
            continue
        rec.pop("error", None)
        rec["polled_at"] = stamp
        rec["open"] = [r["number"] for r in got["open"]]
        open_urls = {r["url"] for r in got["open"]}
        for r in got["open"]:
            data["prs"][r["url"]] = r
        for r in got["linked"].values():
            data["prs"][r["url"]] = r
        # a pull request that was open last time and is not any more, and that no ticket links: forget it
        for url, r in list(data["prs"].items()):
            gone = r.get("state") == "OPEN" and url not in open_urls and r.get("number") not in nums
            if r.get("repo") == repo and gone:
                del data["prs"][url]
    data["polled_at"] = stamp
    return data


def answer(t: dict, data: dict) -> dict:
    """What `act refresh` prints for one ticket (contracts/addon-manifest.md, Act: refresh), from `data`."""
    out, rows = [], []
    for ln in links(t):
        r = data["prs"].get(ln["url"])
        if r is None:
            continue
        rows.append(r)
        item = {"url": ln["ref_url"], "status": r["status"]}
        if not ln.get("title") and r.get("title"):
            item["title"] = r["title"]
        out.append(item)
    res: dict = {"ticket": t["id"], "refs": out}
    ext = prstate.ext_of(rows)
    if ext:
        res["ext"] = {EXT: ext}
    if not links(t):
        res["say"] = "This ticket links no pull request."
    elif not rows:
        res["say"] = "Its pull requests could not be read yet."
    return res


def differs(t: dict, res: dict) -> bool:
    """True when the ticket shows something else than `res` would write."""
    cur = {r.get("url"): r for r in t.get("refs") or [] if isinstance(r, dict)}
    for item in res["refs"]:
        have = cur.get(item["url"]) or {}
        if have.get("status") != item["status"] or ("title" in item and not have.get("title")):
            return True
    want = (res.get("ext") or {}).get(EXT) or {}
    have = (t.get("ext") or {}).get(EXT) or {}
    return any(have.get(k) != v for k, v in want.items())


def apply(root: Path, ts: list[dict], data: dict) -> list[str]:
    """Refresh each ticket whose links show something else now. Returns the ticket ids refreshed."""
    done = []
    for t in ts:
        if not links(t):
            continue
        res = answer(t, data)
        if res["refs"] and differs(t, res):
            got = orch(
                root, "pull-requests", "act", "refresh", "--by", BY, "--", t["id"], env={CACHED_ENV: "1"}
            )
            if got is not None:
                done.append(t["id"])
    return done


def once(root: Path, fetch=gh.fetch) -> dict:
    """One pass of the background job: {"repos", "prs", "refreshed", "errors"}."""
    ts = tickets(root)
    data = load(root)
    want = plan(ts)
    read(root, want, data, fetch)
    linked = ticket_of(ts)
    for url, r in list(data["prs"].items()):  # a finished pull request no ticket links any more: forget it
        if r.get("state") != "OPEN" and url not in linked:
            del data["prs"][url]
    save(root, data)
    refreshed = apply(root, ts, data)
    errors = {r: data["repos"][r]["error"] for r in want if data["repos"].get(r, {}).get("error")}
    return {"repos": list(want), "prs": len(data["prs"]), "refreshed": refreshed, "errors": errors}


def refresh_one(root: Path, t: dict, cached: bool, fetch=gh.fetch) -> dict:
    """`orch pull-requests act refresh -- <ticket>`: the job's own call answers from prs.json; a person's click or a
    helper looks the ticket's pull requests up at GitHub first (one call per repository)."""
    data = load(root)
    if not cached and links(t):
        want: dict[str, list[int]] = {}
        for ln in links(t):
            want.setdefault(ln["repo"], []).append(ln["number"])
        read(root, want, data, fetch)
        errors = [data["repos"][r].get("error") for r in want if data["repos"][r].get("error")]
        try:
            save(root, data)
        except OSError:
            pass
        res = answer(t, data)
        if errors and not res["refs"]:
            res["say"] = errors[0]
        return res
    return answer(t, data)

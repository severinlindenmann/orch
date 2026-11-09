"""Read .orch/ files of a workspace into one JSON-able state. Read only; never writes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from . import look, mobile, phone_delivery


def _me() -> str:
    from .actions import actor  # actions imports this module

    return actor()


STATUS_ORDER = ["open", "ready", "active", "waiting", "review", "done", "dropped"]
_NAME = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
ICONS = (
    "clock",
    "calendar",
    "inbox",
    "list",
    "chart",
    "bell",
    "book",
    "globe",
    "link",
    "check",
    "star",
    "box",
    "chat",
    "folder",
    "user",
    "bolt",
)
FORMATS = ("text", "time", "cron-human", "chips", "yes-no", "open-page")


def find_workspace(start: Path) -> Path | None:
    """Walk up from start to the first folder that has .orch/."""
    p = start.resolve()
    for d in [p, *p.parents]:
        if (d / ".orch").is_dir():
            return d
    return None


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _json_files(folder: Path):
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.json") if p.is_file() and not p.is_symlink())


# Slow-changing read-only answers (the add-on list is asked 2-3 times per page poll): kept 10 s, and dropped
# whenever the page makes a change (actions.run_op calls forget_static), so a reply never shows old settings.
STATIC_TTL = 10.0
_STATIC_CMDS = (("addon", "list"), ("agents",))
_STATIC: dict[tuple, tuple[float, object]] = {}


def forget_static() -> None:
    _STATIC.clear()


def run_orch(orch_bin: str | None, args: list[str], root: Path, timeout: float = 5.0):
    """Run `$ORCH_BIN <args>` in the workspace and return its parsed stdout JSON, or None on any failure."""
    if not orch_bin:
        return None
    if any(tuple(args[: len(c)]) == c for c in _STATIC_CMDS):
        key = (orch_bin, str(root), tuple(args))
        hit = _STATIC.get(key)
        if hit and time.monotonic() - hit[0] < STATIC_TTL:
            return hit[1]
        out = _run_orch(orch_bin, args, root, timeout)
        if out is not None:
            _STATIC[key] = (time.monotonic(), out)
        return out
    return _run_orch(orch_bin, args, root, timeout)


def _run_orch(orch_bin: str, args: list[str], root: Path, timeout: float):
    try:
        r = subprocess.run(
            [orch_bin, *args],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "ORCH_ROOT": str(root), "ORCH_BIN": orch_bin},
        )
        return json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _valid_ticket(t, stem: str | None = None) -> bool:
    return (
        isinstance(t, dict)
        and t.get("schema") == "orch.ticket/1"
        and isinstance(t.get("id"), str)
        and (stem is None or t["id"] == stem)
        and isinstance(t.get("title"), str)
        and t.get("status") in STATUS_ORDER
    )


def _file_here(root: Path, tid: str, ref: str) -> bool:
    """Is this proof file on this computer? Looked up under the workspace or the ticket's evidence folder, never outside."""
    base = root.resolve()
    for cand in (root / ref, root / ".orch" / "tickets" / tid / "evidence" / Path(ref).name):
        try:
            p = cand.resolve()
            p.relative_to(base)
        except (OSError, ValueError, RuntimeError):
            continue
        if p.is_file():
            return True
    return False


def _mark_missing_proofs(root: Path, t: dict) -> None:
    for c in t.get("checklist", []):
        for ev in (
            c.get("evidence", []) if isinstance(c, dict) and isinstance(c.get("evidence"), list) else []
        ):
            if (
                isinstance(ev, dict)
                and ev.get("type") == "file"
                and isinstance(ev.get("ref"), str)
                and "\x00" not in ev["ref"]
            ):
                ev["missing"] = not _file_here(root, str(t["id"]), ev["ref"])


def load_tickets(root: Path, orch_bin: str | None = None) -> tuple[list[dict], int]:
    """Valid-looking tickets (schema orch.ticket/1, id, title, status). Returns (tickets, skipped).
    Read through `$ORCH_BIN ticket list --all --json` (without --all, done and dropped tickets would vanish); without the orch command (standalone use) from .orch/tickets."""
    raw = run_orch(orch_bin, ["ticket", "list", "--all", "--json"], root)
    if isinstance(raw, dict):
        raw = raw.get("tickets")
    if isinstance(raw, list):
        items = [(t, None) for t in raw]
    else:
        items = [(_load(f), f.stem) for f in _json_files(root / ".orch" / "tickets")]
    tickets, skipped = [], 0
    for t, stem in items:
        if isinstance(t, dict) and t.get("general") is True:  # the hidden General conversation is no ticket
            continue
        if not _valid_ticket(t, stem):
            skipped += 1
            continue
        for k in ("checklist", "refs", "questions", "history"):
            if not isinstance(t.get(k), list):
                t[k] = []
        _mark_missing_proofs(root, t)
        mobile.mark_chat_history(t)
        tickets.append(t)
    phone_delivery.mark(root, tickets)
    add_artifact_marks(tickets)
    tickets.sort(key=lambda t: str(t.get("updated_at", "")), reverse=True)
    by_id = {t["id"]: t for t in tickets}
    for t in tickets:
        t.update(children=[], parts_done=0, parts_total=0)
    for t in tickets:
        parent = t.get("parent")
        if isinstance(parent, str) and parent in by_id:
            p = by_id[parent]
            p["children"].append(t["id"])
            p["parts_total"] += 1
            p["parts_done"] += int(t["status"] == "done")
    return tickets, skipped


def add_artifact_marks(tickets: list[dict]) -> None:
    """`art` on each ticket: {address: {id, rev, kind}} for its links and its pr/commit/url proof, with the same id, rev
    and kind (html, pr, commit, link) the phone gets (the core's phone_view); nothing is uploaded."""
    try:
        from orch import phone_view
    except ImportError:
        return
    for t in tickets:
        art: dict[str, dict] = {}
        links = t.get("refs") if isinstance(t.get("refs"), list) else []
        pairs = [("link", ln.get("url")) for ln in links if isinstance(ln, dict)]
        for c in t.get("checklist") if isinstance(t.get("checklist"), list) else []:
            evs = c.get("evidence") if isinstance(c, dict) and isinstance(c.get("evidence"), list) else []
            pairs += [
                (ev["type"], ev.get("ref"))
                for ev in evs
                if isinstance(ev, dict) and ev.get("type") in ("url", "pr", "commit")
            ]
        for source, ref in pairs[:100]:
            if not isinstance(ref, str) or not ref.startswith(("http://", "https://")):
                continue
            try:  # one bad entry never hides the others
                kind, rev = phone_view._url_art(source, ref)
                art[ref] = {"id": phone_view.artifact_id(source, ref), "rev": rev, "kind": kind}
            except ValueError:
                continue
        t["art"] = art


def load_general(root: Path) -> dict | None:
    """The General conversation of the phone (the hidden ticket with `general: true`): {id, history}, oldest first."""
    for f in _json_files(root / ".orch" / "tickets"):
        t = _load(f)
        if (
            isinstance(t, dict)
            and t.get("general") is True
            and isinstance(t.get("id"), str)
            and t["id"] == f.stem
        ):
            hist = (
                [h for h in t.get("history") if isinstance(h, dict) and isinstance(h.get("text"), str)]
                if isinstance(t.get("history"), list)
                else []
            )
            hist = [h for h in hist if mobile.is_chat_entry(h)]  # messages only
            return {"id": t["id"], "history": hist[-200:]}
    return None


def load_chat(root: Path, orch_bin: str | None) -> dict | None:
    """`orch chat status --json`: {helper, ticket, day, messages, activity, days, running}. None = not readable."""
    d = run_orch(orch_bin, ["chat", "status", "--json"], root)
    return d if isinstance(d, dict) else None


def load_chat_days(root: Path, orch_bin: str | None) -> list | None:
    d = run_orch(orch_bin, ["chat", "days", "--json"], root)
    return d if isinstance(d, list) else None


def load_chat_day(root: Path, orch_bin: str | None, day: str) -> dict | None:
    """One day of History, read only (`orch chat day <day> --json`)."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return None
    d = run_orch(orch_bin, ["chat", "day", day, "--json"], root)
    return d if isinstance(d, dict) else None


def load_addons(root: Path, orch_bin: str | None, raw=None) -> list[dict]:
    """Active add-ons that have a dashboard tab and/or ticket rows, from `orch addon list --json`, by `order`."""
    raw = run_orch(orch_bin, ["addon", "list", "--json"], root) if raw is None else raw
    out = []
    for a in raw if isinstance(raw, list) else []:
        if not (
            isinstance(a, dict)
            and a.get("active") is True
            and isinstance(a.get("name"), str)
            and _NAME.match(a["name"])
        ):
            continue
        d = a.get("dashboard") if isinstance(a.get("dashboard"), dict) else None
        if d and not (isinstance(d.get("label"), str) and d.get("icon") in ICONS):
            d = None
        tv = [
            r
            for r in a.get("ticket_view") or []
            if isinstance(r, dict)
            and isinstance(r.get("field"), str)
            and isinstance(r.get("label"), str)
            and r.get("format") in FORMATS
        ]
        pg = a.get("page") if isinstance(a.get("page"), dict) else None
        if pg and not (
            isinstance(pg.get("path"), str)
            and re.fullmatch(r"/[A-Za-z0-9_./-]*", pg["path"])
            and ".." not in pg["path"]
        ):
            pg = None
        tf = _ticket_fields(a.get("ticket_fields"))
        acts = [
            v for v in a.get("acts") or [] if isinstance(v, str) and re.fullmatch(r"[a-z][a-z-]{0,20}", v)
        ]
        kinds = [
            k.get("kind")
            for k in a.get("ticket_links") or []
            if isinstance(k, dict) and isinstance(k.get("kind"), str)
        ]
        if d or tv or tf or acts or kinds:
            out.append(
                {
                    "name": a["name"],
                    "dashboard": d
                    and {
                        "label": d["label"][:24],
                        "icon": d["icon"],
                        "order": d.get("order", 50),
                        "panel": d.get("panel") if d.get("panel") in ("repeats", "links", "phone") else None,
                    },
                    "ticket_view": tv,
                    "page": pg and {"path": pg["path"], "label": str(pg.get("label") or "")[:40]},
                    "ticket_fields": tf,
                    "acts": acts,
                    "link_kinds": kinds,
                }
            )
    out.sort(key=lambda a: (a["dashboard"] or {}).get("order", 50))
    return out


FIELD_TYPES = ("text", "number", "date", "choice", "url")


def _ticket_fields(tf) -> dict | None:
    """`ticket_fields` of `orch addon list --json` (core already typed the schema): section, show_on_card, fields."""
    if not (
        isinstance(tf, dict) and isinstance(tf.get("section"), str) and isinstance(tf.get("fields"), list)
    ):
        return None
    fields = []
    for f in tf["fields"]:
        if not (
            isinstance(f, dict)
            and isinstance(f.get("key"), str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", f["key"])
            and f.get("type") in FIELD_TYPES
            and isinstance(f.get("title"), str)
        ):
            continue
        out = {
            "key": f["key"],
            "title": f["title"][:40],
            "type": f["type"],
            "read_only": f.get("read_only") is True,
            "hidden": f.get("hidden") is True,
        }
        if f["type"] == "choice":
            out["options"] = [
                {"value": o["value"], "label": str(o.get("label") or o["value"])[:40]}
                for o in f.get("options") or []
                if isinstance(o, dict) and isinstance(o.get("value"), str)
            ]
        fields.append(out)
    card = [k for k in tf.get("show_on_card") or [] if isinstance(k, str)][:3]
    return {"section": tf["section"][:24], "show_on_card": card, "fields": fields}


def link_kinds(raw) -> list[dict]:
    """The link types of the active add-ons (`orch addon list --json` rows), for orch.refs.describe."""
    out, seen = [], set()
    for a in sorted(
        (a for a in raw if isinstance(a, dict) and a.get("active") is True) if isinstance(raw, list) else [],
        key=lambda a: str(a.get("name")),
    ):
        for k in a.get("ticket_links") or []:
            if (
                isinstance(k, dict)
                and isinstance(k.get("kind"), str)
                and k["kind"] not in seen
                and isinstance(k.get("label"), str)
                and isinstance(k.get("icon"), str)
                and isinstance(k.get("match"), list)
            ):
                seen.add(k["kind"])
                out.append({**k, "addon": a["name"]})
    return out


def add_link_views(tickets: list[dict], kinds: list[dict]) -> None:
    """Each ticket link gets `view` (label, icon, mono, title, status, group) from the core's one link module."""
    try:
        from orch import refs
    except ImportError:  # standalone use without orch: no view, so the page shows no Links card
        return
    for t in tickets:
        for ln in t.get("refs") or []:
            if isinstance(ln, dict) and isinstance(ln.get("url"), str):
                ln["view"] = refs.describe(ln, kinds)
                ln["view"].update(
                    shown_type=shown_type(ln["view"].get("label"), ln["url"], refs),
                    **dict(zip(("host_head", "domain"), host_parts(ln["url"]))),
                )


# What a link row says it is: one rule (the phone app has the same one, LinkFace in ChatParts.swift).
# Type: an allowlist. Each " · " part is a known site's name, kept only on that site's own address, or a plain
# label of ASCII letters, digits, spaces and "-", at most 24, naming no site even with spaces and "-" taken out; else
# dropped, and with nothing left the type is "Link". Host: the registrable domain (never cut) and the rest before it.
_PLAIN = re.compile(r"[A-Za-z0-9 -]{1,24}")
TWO_PART_SUFFIXES = frozenset(
    {
        "co.uk",
        "org.uk",
        "ac.uk",
        "gov.uk",
        "com.au",
        "net.au",
        "org.au",
        "co.nz",
        "co.jp",
        "ne.jp",
        "or.jp",
        "com.br",
        "com.cn",
        "com.mx",
        "co.in",
        "co.za",
        "com.tr",
        "com.sg",
        "com.hk",
        "co.kr",
        "github.io",
        "gitlab.io",
    }
)


def _squeeze(s: str) -> str:
    return s.lower().replace(" ", "").replace("-", "")


def shown_type(label, url: str, refs) -> str:
    names = {h["name"].lower() for h in refs.known_sites()["hosts"]}
    on = (refs.site(url) or {}).get("name", "").lower()
    parts = []
    for p in (label if isinstance(label, str) else "").split(" · "):
        if p.lower() in names:
            if p.lower() == on:
                parts.append(p)
        elif _PLAIN.fullmatch(p) and not any(_squeeze(n) in _squeeze(p) for n in names):
            parts.append(p)  # a free label that names no site, even squeezed ("G i t-Hub PR" is just "Link")
    return " · ".join(parts) or "Link"


def domain(host: str) -> str:
    """The registrable part of a host (eTLD+1): github.com.evil.example -> evil.example. An IP stays whole."""
    parts = host.split(".")
    if len(parts) <= 2 or all(x.isdigit() for x in parts) or ":" in host:
        return host
    return ".".join(parts[-3:] if ".".join(parts[-2:]) in TWO_PART_SUFFIXES else parts[-2:])


def host_parts(url: str) -> tuple[str, str]:
    """(the host before the domain, e.g. "gist.", the domain)."""
    try:
        host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        host = ""
    d = domain(host)
    return host[: len(host) - len(d)], d


def _consent(r: dict) -> str:
    """What turning an add-on on does, in the same words as `orch addon add` asks (built from `orch addon list`)."""
    name, d = r["name"], r.get("dashboard") if isinstance(r.get("dashboard"), dict) else None
    desc = str(r.get("description") or "").strip()
    head = f"{name} {r.get('version', '')}".replace("  ", " ").strip()
    lines = [desc, head] if desc else [head]
    if r.get("source") == "local":
        lines.append("Source: local folder (not checked by orch). It runs code on this computer.")
    lines.append(f"Adds the command: orch {name}")
    lines.append(f"Adds a skill and an entry in the local orch instructions: orch-{name}")
    if r.get("ticket_view"):
        lines.append(f"Stores data on tickets under: ext.{name}")
    if d and isinstance(d.get("label"), str):
        lines.append(f"Adds a dashboard tab: {d['label']}")
    if r.get("background"):
        lines.append("Runs a background process.")
    return "\n".join(lines)[:1200]


def _host(url) -> str:
    m = re.match(r"^https?://[^/\s]+", str(url or ""))
    return m.group(0)[:120] if m and "@" not in m.group(0) else ""


def _addon_detail(root: Path, name: str) -> dict | None:
    """Connection facts for an add-on that has a saved server link (.orch/secrets/<name>.json) and, if it keeps
    one, a list of other workspaces (.agents/skills/orch-<name>/workspaces.json). Never the token."""
    link = _load(root / ".orch" / "secrets" / f"{name}.json")
    if not isinstance(link, dict) or "url" not in link:
        return None
    url = _host(link.get("url"))
    out = {"connected": bool(url), "address": url, "workspaces": []}
    d = _load(root / ".agents" / "skills" / f"orch-{name}" / "workspaces.json")
    for w in (
        d.get("workspaces") if url and isinstance(d, dict) and isinstance(d.get("workspaces"), list) else []
    )[:50]:
        if isinstance(w, dict) and isinstance(w.get("name"), str):
            out["workspaces"].append({"name": w["name"][:60], "online": w.get("online") is True})
    return out


def load_settings(root: Path, orch_bin: str | None) -> dict:
    """What the Settings page shows: agents from `orch agents --json`, every installed add-on from `orch addon list --json`."""
    agents, rows = (
        run_orch(orch_bin, ["agents", "--json"], root),
        run_orch(orch_bin, ["addon", "list", "--json"], root),
    )
    keep = ("name", "label", "adapter", "found", "version", "can", "status", "chosen")
    perm = run_orch(orch_bin, ["config", "get", "workspace.permissions", "--json"], root)
    perm = perm.get("workspace.permissions") if isinstance(perm, dict) else None
    from orch.config import agents_may_finish

    try:  # read-only look: the entry `orch share on` writes (a link is never followed)
        f = root / "AGENTS.md"
        share = (
            f.is_file()
            and not f.is_symlink()
            and "<!-- orch:begin share -->" in f.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        share = False
    return {
        "agents_may_finish": agents_may_finish(root),
        "folder": str(root),
        "share": share,
        "permissions": perm if perm in ("ask", "auto", "full") else "auto",  # core's default is Auto
        "agents": [
            {k: a.get(k) for k in keep}
            for a in (agents if isinstance(agents, list) else [])
            if isinstance(a, dict) and isinstance(a.get("name"), str)
        ],
        "addons": [
            {
                "name": r["name"],
                "description": str(r.get("description") or "")[:200],
                "active": r.get("active") is True,
                "consent": _consent(r),
                "detail": _addon_detail(root, r["name"]),
            }
            for r in (rows if isinstance(rows, list) else [])
            if isinstance(r, dict) and isinstance(r.get("name"), str) and _NAME.match(r["name"])
        ],
    }


def load_services(root: Path, orch_bin: str | None) -> list[dict]:
    """Background add-ons of this workspace, running or not. Source: `orch status --json` only (rows: addon, running, url)."""
    raw = run_orch(orch_bin, ["status", "--json"], root)
    here = str(root.resolve())
    for w in raw if isinstance(raw, list) else []:
        if isinstance(w, dict) and w.get("workspace") == here and isinstance(w.get("addons"), list):
            return [r for r in w["addons"] if isinstance(r, dict) and isinstance(r.get("addon"), str)]
    return []


_RUNS: dict[tuple[str, str], tuple[float, dict | None]] = {}
_RUN_SIGNATURES = {}
RUNS_TTL = 5.0
RUNS_MAX = 30


def load_runs(root: Path, orch_bin: str | None, tickets: list[dict], fresh: bool = False) -> dict[str, dict]:
    """Run status for tickets that can have a run (not done or dropped, or with a claim file), from `orch run status <id> --json`.
    Cached for a few seconds so the 3 s page poll costs nothing; an action's reply passes fresh=True."""
    if not orch_bin:
        return {}
    from .events import Revisions

    signature = Revisions(root).signature()
    if _RUN_SIGNATURES.get(str(root)) != signature:
        fresh = True
        _RUN_SIGNATURES[str(root)] = signature
    claims = root / ".orch" / "run" / "tickets"  # a done ticket can still have its live session open
    ids = [t["id"] for t in tickets if t["status"] not in ("done", "dropped")][:RUNS_MAX]
    ids += [
        t["id"]
        for t in tickets
        if t["status"] in ("done", "dropped") and (claims / f"{t['id']}.json").exists()
    ]
    now = time.monotonic()
    todo = [
        i for i in ids if fresh or (str(root), i) not in _RUNS or now - _RUNS[(str(root), i)][0] > RUNS_TTL
    ]
    if todo:
        with ThreadPoolExecutor(max_workers=6) as pool:
            got = list(pool.map(lambda i: run_orch(orch_bin, ["run", "status", i, "--json"], root), todo))
        for i, r in zip(todo, got, strict=True):
            _RUNS[(str(root), i)] = (now, r if isinstance(r, dict) else None)
    return {i: _RUNS[(str(root), i)][1] for i in ids if _RUNS[(str(root), i)][1]}


def add_warmth(root: Path, tickets: list[dict], statuses: dict) -> None:
    """Count down from live.since, as idle cleanup does; heartbeats do not reset it."""
    try:
        from orch.config import live_idle_minutes
    except ImportError:
        return
    limit, now = live_idle_minutes(root) * 60, time.time()
    for t in tickets:
        t.pop("warmth", None)
        status = statuses.get(t["id"]) or {}
        rec = status.get("claim") or {}
        if status.get("running") is not True or rec.get("mode") != "live":
            continue
        try:
            since = datetime.fromisoformat(rec["live"]["since"]).timestamp()
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            continue
        t["warmth"] = {"seconds_left": max(0, int(limit - (now - since)))}


def load_state(
    root: Path,
    orch_bin: str | None = None,
    with_addons: bool = True,
    fresh: bool = False,
    with_settings: bool = False,
) -> dict:
    """with_addons=False (snapshots by default): no add-on tabs, no ticket rows, `ext` dropped from tickets."""
    from .actions import actor

    tickets, skipped = load_tickets(root, orch_bin)
    raw = run_orch(orch_bin, ["addon", "list", "--json"], root)
    addons = load_addons(root, orch_bin, raw) if with_addons else []
    if not with_addons:
        for t in tickets:
            t.pop("ext", None)
    try:
        from orch.refs import local_refs
    except ImportError:  # the core is not importable here: no local references
        local_refs = None

    for t in tickets:
        stored = t.get("refs", [])
        for n, r in enumerate(stored, 1):  # the stored number: what `orch ref list` and `orch ref rm` use
            if isinstance(r, dict):
                r["n"] = n
        t["refs"] = [r for r in stored if not (isinstance(r, dict) and r.get("local"))]
        if (
            with_settings and local_refs
        ):  # only the live local server: a snapshot is shared and must not carry local paths
            try:
                more = local_refs(root, t["id"])
            except (ValueError, TypeError, OSError):
                more = []
            more = [r for r in more if isinstance(r, dict)] if isinstance(more, list) else []
            t["refs"] += [{**r, "n": len(stored) + i} for i, r in enumerate(more, 1)]
    add_link_views(
        tickets, link_kinds(raw) if with_addons else []
    )  # snapshots: known sites only, no add-on names
    needs = run_orch(orch_bin, ["needs", "--json"], root) if with_addons else None
    state = {
        "workspace": root.name,
        "who": actor().removeprefix("human:"),
        "now": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "me": _me() if with_settings else None,  # who "You" is in a history line (the live page only)
        "tickets": tickets,
        "skipped": skipped,
        "addons": addons,
        "general": load_general(root) if with_addons else None,  # snapshots carry no phone chat
        # Chat (former General): helper name, today's texts with cards, the strip counts, the History list.
        "chat": load_chat(root, orch_bin) if with_addons else None,
        "needs": needs if isinstance(needs, list) else [],
        "services": load_services(root, orch_bin) if with_addons else [],  # snapshots name no add-on
        "runs": load_runs(root, orch_bin, tickets, fresh) if with_addons else {},
        "groups": mobile.load_groups(root, orch_bin) if with_addons else None,  # group chats; snapshots carry none
        "mobile_mode": mobile.load_mobile(root, orch_bin) if with_settings else None,  # the live page only, never a snapshot
        "look": look.load_look(root, orch_bin, fresh) if with_settings else None,  # the live page only, never a snapshot
        "settings": load_settings(root, orch_bin)
        if with_settings
        else None,  # only the live local server: it holds the folder path
    }
    add_warmth(root, tickets, state["runs"])
    state["rev"] = hashlib.sha1(
        json.dumps({k: v for k, v in state.items() if k != "now"}, sort_keys=True).encode()
    ).hexdigest()[:12]
    return state


def publish_connected(root: Path, orch_bin: str | None) -> bool:
    rows = run_orch(orch_bin, ["addon", "list", "--json"], root)
    if not isinstance(rows, list) or not any(
        isinstance(r, dict) and r.get("name") == "publish" and r.get("active") is True for r in rows
    ):
        return False
    who = run_orch(orch_bin, ["publish", "whoami", "--json"], root)
    return isinstance(who, dict) and isinstance(who.get("id"), str) and bool(who["id"]) and "error" not in who


def load_links(root: Path, orch_bin: str | None) -> dict:
    if not publish_connected(root, orch_bin):
        return {"links": []}
    raw = run_orch(orch_bin, ["publish", "list", "--json"], root)
    files = raw.get("files", []) if isinstance(raw, dict) else []
    links = []
    for f in files if isinstance(files, list) else []:
        if not isinstance(f, dict) or not isinstance(f.get("id"), str) or not re.fullmatch(r"f_[a-z0-9]+", f["id"]):
            continue
        expires = f.get("expires_at")
        try:
            when = datetime.fromisoformat(expires)
            expired = (when if when.tzinfo else when.replace(tzinfo=UTC)) <= datetime.now(UTC)
        except (ValueError, TypeError, AttributeError):
            expired = False
        key, url = f.get("key"), f.get("url")
        ok = (
            isinstance(key, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key)
            and isinstance(url, str)
            and re.fullmatch(r"https://[A-Za-z0-9.:\[\]-]+/[!-~]*", url.split("#", 1)[0])
        )
        link = url.split("#", 1)[0] + "#k=" + key if ok else None
        links.append({"id": f["id"], "name": f.get("name"), "size": f.get("size"),
                      "expires_at": expires, "expired": expired, "link": link, "copy": link is not None})
    return {"links": links}


# Workspace DM reads use the same CLI boundary as Chat History.
def load_chat_contacts(root: Path, orch_bin: str | None) -> list | None:
    data = run_orch(orch_bin, ["chat", "contacts", "--json"], root)
    return data if isinstance(data, list) else None


def load_chat_thread(root: Path, orch_bin: str | None, ws: str) -> dict | None:
    if not re.fullmatch(r"ws_[a-z0-9]{10}", ws):
        return None
    data = run_orch(orch_bin, ["chat", "thread", ws, "--json"], root)
    return data if isinstance(data, dict) else None

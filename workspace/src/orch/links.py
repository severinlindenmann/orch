"""Ticket links: which kind a link is and how it is shown. One module for the CLI, dashboard and phone.

A link is `{kind, url, title?, status?, thumb?, at, by}` in the ticket's `links` list. `kind` is a link type
an active add-on declares in its `[[ticket_links]]` (label, icon, url pattern), or `link`. How a link looks:
1. its kind belongs to an active add-on → that add-on's label and the status it stored;
2. else the address is a known site (known_sites.json, ships with core) → the site's name and icon;
3. else "Link" with the short address.
An add-on that is off changes nothing in the file: its links show as plain links and come back when it is on.
Core names no add-on: it only reads the manifests' tables. No network call anywhere here.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from urllib.parse import urlsplit

from orch.errors import Refused

KIND_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
STATUS_RE = re.compile(r"[a-z0-9][a-z0-9 -]{0,23}")
MAX_URL = 2000


@cache
def known_sites() -> dict:
    return json.loads((Path(__file__).parent / "known_sites.json").read_text(encoding="utf-8"))


def check_url(url) -> str:
    """An http(s) address with a host, one line, at most 2000 characters. Returns it stripped."""
    u = url.strip() if isinstance(url, str) else ""
    bad = not u or len(u) > MAX_URL or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in u)
    if not bad:
        try:
            p = urlsplit(u)
            bad = p.scheme.lower() not in ("http", "https") or not p.hostname
        except ValueError:
            bad = True
    if bad:
        raise Refused("A link must be a web address that starts with https:// or http://.")
    return u


def short_url(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url, flags=re.I).rstrip("/")


def _host_path(url: str) -> tuple[str, str]:
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
    except ValueError:
        return "", ""
    return host.removeprefix("www."), p.path or "/"


def site(url: str) -> dict | None:
    """The known site of an address: {name, icon, mono}, or None. First match in the table wins.
    A match is a host (`github.com`, any subdomain with `*.`) and optionally a path start (`/wiki`)."""
    host, path = _host_path(url)
    if not host:
        return None
    for h in known_sites()["hosts"]:
        for m in h["match"].split(", "):
            mhost, _, mpath = m.partition("/")
            if mhost.startswith("*."):
                ok = host.endswith(mhost[1:])
            else:
                ok = host == mhost or host.endswith("." + mhost)
            if ok and (not mpath or path == "/" + mpath or path.startswith("/" + mpath + "/")):
                return {"name": h["name"], "icon": h["icon"], "mono": h["mono"]}
    return None


def _pattern(p: str) -> re.Pattern:
    """`https://github.com/*/*/pull/*`: a `*` is one part of the address (no `/`, `?`, `#`); a `*` at the end
    also takes the rest of the address."""
    out = ""
    for i, part in enumerate(p.split("*")):
        if i:
            out += ".*" if i == p.count("*") and part == "" else r"[^/?#]+"
        out += re.escape(part)
    return re.compile(out, re.I)


def kinds_of(manifests: dict) -> list[dict]:
    """The link types of the given add-on manifests (name -> manifest), by name; first wins a kind."""
    seen, out = set(), []
    for name, m in sorted(manifests.items()):
        for k in m.get("ticket_links") or []:
            if k["kind"] in seen:
                continue
            seen.add(k["kind"])
            out.append({**k, "addon": name})
    return out


def active_kinds(root: Path) -> list[dict]:
    from orch import addons

    return kinds_of(addons.active_manifests(root))


def kind_for(url: str, kinds: list[dict]) -> str:
    """The first add-on link type whose pattern matches the address, else `link`."""
    for k in kinds:
        for p in k["match"]:
            if _pattern(p).fullmatch(url):
                return k["kind"]
    return "link"


def kind_of(link: dict) -> str:
    """Links written before `kind` existed have `type` (github, jira, file, ticket …)."""
    k = link.get("kind") or link.get("type") or "link"
    return k if isinstance(k, str) else "link"


def describe(link: dict, kinds: list[dict]) -> dict:
    """How one link is shown: label (e.g. "GitHub · Pull request", "Figma", "Link"), short label (the type
    name, for lists), icon key and monogram, title (stored, else the short address), status (only while
    the add-on that set it is on), group (Artifacts tab: the add-on label, else "Links") and preview."""
    url = link.get("url") if isinstance(link.get("url"), str) else ""
    title = link.get("title") if isinstance(link.get("title"), str) and link["title"].strip() else None
    k = next((x for x in kinds if x["kind"] == kind_of(link)), None)
    s = site(url)
    out = {
        "kind": kind_of(link),
        "title": title or short_url(url) or "Link",
        "short": short_url(url),
        "status": None,
        "preview": None,
        "addon": None,
    }
    if k:
        st = link.get("status")
        out.update(
            label=f"{s['name']} · {k['label']}" if s else k["label"],
            type=k["label"],
            icon=s["icon"] if s else k["icon"],
            mono=s["mono"] if s else k["label"][:2],
            status=st if isinstance(st, str) and STATUS_RE.fullmatch(st) else None,
            group=k["label"],
            preview=k.get("preview"),
            addon=k["addon"],
        )
    elif s:
        out.update(label=s["name"], type=s["name"], icon=s["icon"], mono=s["mono"], group="Links")
    else:
        out.update(label="Link", type="Link", icon="link", mono=None, group="Links")
    return out


def numbered(ticket: dict) -> list[tuple[int, dict]]:
    """The links a person sees and numbers (1, 2, …): web links only (no old internal ones)."""
    out = []
    for ln in ticket.get("links") or []:
        if (
            isinstance(ln, dict)
            and isinstance(ln.get("url"), str)
            and re.match(r"https?://", ln["url"], re.I)
        ):
            out.append(ln)
    return list(enumerate(out, 1))

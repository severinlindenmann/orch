"""Ticket references and shared display rules for the CLI, dashboard and phone.

Web references use active add-on kinds from [[ticket_links]], known-site labels,
then a plain Reference label. Other references identify tickets, artifacts or files.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from orch.errors import Refused
from orch.text import clean_untrusted

KIND_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}(?::[a-z0-9][a-z0-9-]{0,31})?")
STATUS_RE = re.compile(r"[a-z0-9][a-z0-9 -]{0,23}")
MAX_URL = 2000


@cache
def known_sites() -> dict:
    return json.loads((Path(__file__).parent / "known_sites.json").read_text(encoding="utf-8"))


def _ascii_host(host: str) -> str:
    """A host as ASCII: punycode for a non-ASCII name, so a look-alike (a Cyrillic i) shows as xn--…."""
    if host.isascii():
        return host
    try:
        import idna  # UTS-46 when the package is there

        return idna.encode(host, uts46=True).decode("ascii")
    except ImportError:
        return host.encode("idna").decode("ascii")


def check_url(url) -> str:
    """An http(s) address with a host, one line, at most 2000 characters. Returns it in one canonical form
    (scheme://host[:port]/path?query#fragment, host lowercase ASCII) so every reader (core, dashboard, phone,
    browser) sees the same host. Refused: backslashes, whitespace, control and invisible characters, a user
    name or password before the host (`user@`), and hosts that do not encode."""
    u = url.strip() if isinstance(url, str) else ""
    bad = not u or len(u) > MAX_URL or "\\" in u
    bad = bad or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in u)
    bad = bad or clean_untrusted(u, MAX_URL) != u  # C1, bidi and invisible characters
    out = ""
    if not bad:
        try:
            p = urlsplit(u)
            host = p.hostname
            if p.scheme.lower() in ("http", "https") and host and "@" not in p.netloc:
                host = _ascii_host(host)
                netloc = f"[{host}]" if ":" in host else host
                if p.port is not None:
                    netloc += f":{p.port}"
                out = urlunsplit((p.scheme.lower(), netloc, p.path, p.query, p.fragment))
        except (ValueError, UnicodeError):
            out = ""
    if not out or len(out) > MAX_URL:
        raise Refused("A web reference must be a web address that starts with https:// or http://.")
    return out


def one_line(text, limit: int = 200) -> str:
    """Text shown on one line (a reference title, a status, an add-on's
    `say`): control characters (C0, DEL, C1, so no terminal escapes), bidi and invisible characters go, line
    breaks become spaces, cut to `limit`. Used on write and again when shown."""
    t = clean_untrusted(str(text), limit * 2)
    return " ".join(t.split())[:limit]


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
            else:  # subdomains count too (gist.github.com is GitHub); look-alikes never do
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
            out += ".+" if i == p.count("*") and part == "" else r"[^/?#]+"
        out += re.escape(part)
    return re.compile(out, re.I)


def kinds_of(manifests: dict) -> list[dict]:
    """The reference types of the given add-on manifests (name -> manifest), by name; first wins a kind."""
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
    """The first add-on reference type whose pattern matches the address, else `url`."""
    for k in kinds:
        for p in k["match"]:
            if _pattern(p).fullmatch(url):
                return k["kind"]
    return "url"


def kind_of(link: dict) -> str:
    return link.get("kind", "url")


def _not_a_site_icon(icon: str) -> str:
    """An add-on link type on an address that is no known site never shows a site's icon (a `github` icon on
    evil.example would vouch for it): the generic link icon instead."""
    return "link" if icon in {h["icon"] for h in known_sites()["hosts"]} else icon


def describe(link: dict, kinds: list[dict], root: Path | None = None) -> dict:
    """How a reference is shown: label, short label (the type
    name, for lists), icon key and monogram, title (stored, else the short address), status (only while
    the add-on that set it is on), group (Artifacts tab: the add-on label, else "References") and preview."""
    if link.get("kind") in ("ticket", "artifact", "file"):
        label = link["kind"].capitalize()
        value = target(link)
        if root is not None and link["kind"] in ("ticket", "artifact"):
            from orch import tickets

            try:
                other = tickets.load(root, link["ticket"])
                value = (
                    f"{other.get('key') or other['id']}: {one_line(other['title'])} "
                    f"({tickets.STATUS_WORDS[other['status']]})"
                )
                if link["kind"] == "artifact":
                    value += f" / {link['name']}"
            except (Refused, OSError, ValueError, KeyError):
                pass
        return dict(
            kind=link["kind"],
            host="",
            title=value,
            short=value,
            status=None,
            preview=None,
            addon=None,
            label=label,
            type=label,
            icon=link["kind"],
            mono=None,
            group="References",
        )
    url = link.get("url") if isinstance(link.get("url"), str) else ""
    title = one_line(link["title"]) if isinstance(link.get("title"), str) else ""
    k = next((x for x in kinds if x["kind"] == kind_of(link)), None)
    s = site(url)
    out = {
        "kind": kind_of(link),
        "host": _host_path(url)[0],  # the real host, always shown next to the type
        "title": title or one_line(short_url(url), 300) or "Reference",
        "short": one_line(short_url(url), 300),
        "status": None,
        "preview": None,
        "addon": None,
    }
    if k:
        st = link.get("status")
        out.update(
            label=f"{s['name']} · {k['label']}" if s else k["label"],
            type=k["label"],
            icon=s["icon"] if s else _not_a_site_icon(k["icon"]),
            mono=s["mono"] if s else k["label"][:2],
            status=st if isinstance(st, str) and STATUS_RE.fullmatch(st) else None,
            group=k["label"],
            preview=k.get("preview"),
            addon=k["addon"],
        )
    elif s:
        out.update(label=s["name"], type=s["name"], icon=s["icon"], mono=s["mono"], group="References")
    else:
        out.update(label="Reference", type="Reference", icon="link", mono=None, group="References")
    return out


def numbered(ticket: dict) -> list[tuple[int, dict]]:
    """References in the order shown to people."""
    return list(enumerate(ticket.get("refs") or [], 1))


def target(ref: dict) -> str:
    if ref["kind"] == "ticket":
        return ref["ticket"]
    if ref["kind"] == "artifact":
        return f"artifact:{ref['ticket']}/{ref['name']}"
    if ref["kind"] == "file":
        return ref["path"] + (f":{ref['line']}" if "line" in ref else "")
    return ref["url"]


def detect(root: Path, tid: str, value: str, kind=None, title=None, kinds=(), *, check_exists=True) -> dict:
    import os
    import posixpath
    from pathlib import PureWindowsPath

    from orch import safefile, tickets

    if not value or "\0" in value:
        raise Refused("Give a reference without empty or hidden characters.")
    if re.match(r"https?://", value, re.I):
        url = check_url(value)
        kind = kind or kind_for(url, list(kinds))
        if not KIND_RE.fullmatch(kind) or kind in ("ticket", "artifact", "file"):
            raise Refused("Give a web reference kind, such as url or github:pr.")
        out = dict(kind=kind, url=url)
        if title:
            if len(title) > 200:
                raise Refused("A reference title is at most 200 characters.")
            out["title"] = one_line(title)
        return out
    if kind or title:
        raise Refused("Kind and title are only used for web references.")
    if re.fullmatch(r"(?:t_[a-z0-9]+|[a-z0-9]{2,4}-[1-9][0-9]*)", value, re.I):
        other = tickets.load(root, tickets.resolve(root, value.lower()))["id"]
        if other == tid:
            raise Refused("A ticket cannot refer to itself.")
        return dict(kind="ticket", ticket=other)
    if value.startswith("artifact:"):
        name = value[len("artifact:") :]
        owner = tid
        first, sep, rest = name.partition("/")
        if sep and re.fullmatch(r"(?:t_[a-z0-9]+|[a-z0-9]{2,4}-[1-9][0-9]*)", first, re.I):
            owner = tickets.load(root, tickets.resolve(root, first.lower()))["id"]
            name = rest
        if not check_exists:
            if safefile._parts(name) is None:
                raise Refused("Give an artifact name inside its ticket folder.")
            return dict(kind="artifact", ticket=owner, name=name)
        try:
            data = safefile.read_ticket_file(root, owner, "artifacts", name, 0)
        except safefile.TooLarge:
            data = b""
        if data is None:
            raise Refused("That artifact does not exist as a regular file.")
        return dict(kind="artifact", ticket=owner, name=name)
    if "://" in value:
        raise Refused("A web reference starts with https:// or http://.")
    value = value.replace("\\", "/")
    line = None
    match = re.fullmatch(r"(.+):([0-9]+)", value)
    if match:
        value, line = match[1], int(match[2])
        if line < 1:
            raise Refused("A file line starts at 1.")
    absolute = Path(value).is_absolute() or bool(PureWindowsPath(value).drive)
    path = posixpath.normpath(value)
    local = absolute or path == ".." or path.startswith("../")
    if not local and not Path(os.path.realpath(root / path)).is_relative_to(root.resolve()):
        raise Refused("That project path points outside the project.")
    if not local and (safefile._parts(path) is None or path.split("/")[0].lower() in (".orch", ".git")):
        raise Refused("Choose a project file outside .orch and .git.")
    out = dict(kind="file", path=str((root / path).absolute()) if local and not absolute else path)
    if line is not None:
        out["line"] = line
    if local:
        out["local"] = True
    return out


def local_path(root: Path, tid: str) -> Path:
    return root / ".orch" / "local" / "refs" / f"{tid}.json"


def local_refs(root: Path, tid: str) -> list[dict]:
    try:
        return json.loads(local_path(root, tid).read_text())
    except FileNotFoundError:
        return []


def write_local(root: Path, tid: str, values: list[dict]) -> None:
    from orch import net, skills

    path = local_path(root, tid)
    for folder in (root / ".orch", path.parent.parent, path.parent):
        if folder.is_symlink():
            raise Refused("The local references folder must be a real folder.")
    ignore = root / ".gitignore"
    if ignore.is_symlink():
        raise Refused("The project .gitignore must be a regular file.")
    skills.ensure_gitignore(root)
    content = ignore.read_text()
    if ".orch/local/" not in content.splitlines():
        net.write_atomic(ignore, (content.rstrip() + "\n.orch/local/\n").encode())
    net.write_json(path, values, private=True)


def all_refs(root: Path, ticket: dict) -> list[tuple[int, dict]]:
    return numbered({"refs": ticket["refs"] + local_refs(root, ticket["id"])})


def open_file_ref(root: Path, path: str, max_bytes: int) -> bytes | None:
    from orch.safefile import open_file_ref as read

    return read(root, path, max_bytes)

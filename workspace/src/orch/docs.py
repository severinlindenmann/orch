"""The Documentation page's content (contracts/docs-pages.md): orch's own pages (docs.json next to this file) and
the pages each add-on brings (`docs = "<file>"` in its orch-addon.toml). Only checks and reads JSON; never runs
add-on code. The dashboard draws the pages (orch_ui docs.js) and fills the live facts itself."""

from __future__ import annotations

import json
import re
from pathlib import Path

SCHEMA = "orch.docs/1"
MAX_BYTES = 96 * 1024
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
ACTORS = ("you", "orch", "helper", "other", "server")
TONES = frozenset({"muted", "info", "working", "warn", "needs", "ok"})
KINDS = frozenset({"flow", "states", "compare"})
# the icons docs.js draws (the master icon set plus a few of its own)
ICONS = frozenset(
    "ticket plus helper question check chip queue chat clock puzzle lock copy link phone bolt share upload home "
    "eye hammer target chart note merge box cloud".split()
)
# live facts the dashboard knows how to read (no network, no AI); "self" = the add-on's own state (on, running)
LIVE = frozenset({"relay", "phone", "publish", "helper-limit", "reviewer", "addons", "self"})
# groups: orch's own pages; the built-in add-ons you turn on when needed (relay, publish); every other add-on
GROUPS = ({"id": "orch", "label": "orch"}, {"id": "builtin", "label": "Turn on when needed"}, {"id": "addon", "label": "Add-ons"})


class DocsError(ValueError):
    """A docs file that does not follow contracts/docs-pages.md (the message says what is off)."""


def _text(v, limit: int, angle: bool = False) -> bool:
    return isinstance(v, str) and 0 < len(v) <= limit and (angle or ("<" not in v and ">" not in v))


def _need(ok: bool, where: str, why: str) -> None:
    if not ok:
        raise DocsError(f"{where}: {why}")


def _keys(d, allowed: set, where: str) -> None:
    _need(isinstance(d, dict), where, "is not an object")
    extra = set(d) - allowed
    _need(not extra, where, f"unknown key {sorted(extra)[0] if extra else ''}")


def _bool(d: dict, k: str, where: str) -> None:
    _need(isinstance(d.get(k, False), bool), where, f"{k} is true or false")


def _steps(steps, where: str, n: int = 16) -> None:
    _need(isinstance(steps, list) and 0 < len(steps) <= n, where, f"steps is a list of 1 to {n}")
    for i, s in enumerate(steps):
        w = f"{where} step {i + 1}"
        _keys(s, {"who", "text", "detail", "decision", "branch", "end", "proposed"}, w)
        _need(s.get("who") in ACTORS, w, "who is you, orch, helper, other or server")
        _need(_text(s.get("text"), 110), w, "text is plain words, at most 110 characters")
        _need("detail" not in s or _text(s["detail"], 260), w, "detail is at most 260 plain characters")
        for k in ("decision", "end", "proposed"):
            _bool(s, k, w)
        br = s.get("branch", [])
        _need(isinstance(br, list) and len(br) <= 4, w, "branch is a list of at most 4")
        for b in br:
            _keys(b, {"if", "then", "stop"}, w + " branch")
            _need(_text(b.get("if"), 90) and _text(b.get("then"), 90), w + " branch", "if and then are plain words")
            _bool(b, "stop", w + " branch")


def check_page(p, where: str = "page") -> dict:
    _keys(p, {"id", "icon", "title", "one", "kind", "steps", "states", "moves", "compare", "good", "related", "tech", "group"}, where)
    _need(isinstance(p.get("id"), str) and bool(ID_RE.match(p["id"])), where, "id is 2 to 41 lowercase letters, digits or dashes")
    where = f"page {p['id']}"
    _need(p.get("icon") in ICONS, where, "icon is not in the docs icon set")
    _need(_text(p.get("title"), 60), where, "title is at most 60 plain characters")
    _need(_text(p.get("one"), 200), where, "one is one plain sentence, at most 200 characters")
    kind = p.get("kind", "flow")
    _need(kind in KINDS, where, "kind is flow, states or compare")
    if kind == "flow":
        _steps(p.get("steps"), where)
    elif kind == "states":
        st = p.get("states")
        _need(isinstance(st, list) and 2 <= len(st) <= 10, where, "states is a list of 2 to 10")
        ids = set()
        for s in st:
            _keys(s, {"id", "label", "tone"}, where + " state")
            _need(isinstance(s.get("id"), str) and bool(ID_RE.match(s["id"])), where, "a state id is lowercase")
            _need(_text(s.get("label"), 30) and s.get("tone", "muted") in TONES, where, "a state has a label and a tone")
            ids.add(s["id"])
        mv = p.get("moves")
        _need(isinstance(mv, list) and 0 < len(mv) <= 24, where, "moves is a list of 1 to 24")
        for m in mv:
            _keys(m, {"from", "to", "by", "text"}, where + " move")
            _need(m.get("from") in ids and m.get("to") in ids, where, "a move goes between two of its states")
            _need(m.get("by") in ACTORS and _text(m.get("text"), 120), where, "a move has by and text")
    else:
        cmp = p.get("compare")
        _need(isinstance(cmp, list) and 2 <= len(cmp) <= 4, where, "compare is a list of 2 to 4 flows")
        for i, f in enumerate(cmp):
            _keys(f, {"title", "tone", "steps"}, f"{where} flow {i + 1}")
            _need(_text(f.get("title"), 40) and f.get("tone", "muted") in TONES, where, "a flow has a title and a tone")
            _steps(f.get("steps"), f"{where} flow {i + 1}", 8)
    good = p.get("good", [])
    _need(isinstance(good, list) and len(good) <= 5 and all(_text(g, 220) for g in good), where, "good is at most 5 plain lines")
    rel = p.get("related", [])
    _need(isinstance(rel, list) and len(rel) <= 8 and all(isinstance(r, str) and ID_RE.match(r) for r in rel), where, "related is at most 8 page ids")
    tech = p.get("tech")
    if tech is not None:
        _keys(tech, {"cmds", "files", "live"}, where + " tech")
        for k, n in (("cmds", 6), ("files", 4)):
            rows = tech.get(k, [])
            _need(isinstance(rows, list) and len(rows) <= n, where, f"tech {k} has at most {n} rows")
            for r in rows:
                _need(
                    isinstance(r, list) and len(r) == 2 and _text(r[0], 110, angle=True) and _text(r[1], 90),
                    where, f"a tech {k} row is [text, what it does]",
                )
        live = tech.get("live", [])
        _need(isinstance(live, list) and len(live) <= 4 and all(x in LIVE for x in live), where, "tech live names known live facts")
    return p


def check(data, where: str = "docs") -> list[dict]:
    """The pages of one docs file, checked. Raises DocsError with the first thing that is off."""
    _keys(data, {"schema", "pages", "actors", "groups"}, where)
    _need(data.get("schema") == SCHEMA, where, f'schema is "{SCHEMA}"')
    pages = data.get("pages")
    _need(isinstance(pages, list) and 0 < len(pages) <= 40, where, "pages is a list of 1 to 40")
    seen = set()
    for p in pages:
        try:
            check_page(p, where)
        except (TypeError, AttributeError, KeyError):  # a list where a word belongs, and the like: refused, not a crash
            raise DocsError(f"{where}: a page has a value of the wrong kind") from None
        _need(p["id"] not in seen, where, f"page id {p['id']} is used twice")
        seen.add(p["id"])
    return pages


def load(file: Path, where: str | None = None) -> list[dict]:
    where = where or file.name
    try:
        raw = file.read_bytes()
    except OSError as e:
        raise DocsError(f"{where}: it cannot be read ({type(e).__name__})") from None
    _need(len(raw) <= MAX_BYTES, where, f"it is larger than {MAX_BYTES // 1024} KB")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise DocsError(f"{where}: it is not JSON") from None
    return check(data, where)


def core_file() -> Path:
    return Path(__file__).resolve().parent / "docs.json"


def collect(addon_rows: list[dict], core_names=("relay", "publish")) -> dict:
    """Everything the Documentation page shows: orch's pages, then the pages of each add-on (built-in ones in
    "builtin", the others in "addon"), each marked with its add-on and whether it is on here. addon_rows are
    {name, active, running, background, docs_pages} (addons.docs_rows). A related id that names no shown page is dropped."""
    core = json.loads(core_file().read_text(encoding="utf-8"))
    pages = [{**p, "group": "orch"} for p in check(core, "orch docs.json")]
    seen = {p["id"] for p in pages}
    first = {n: i for i, n in enumerate(core_names)}
    for row in sorted(addon_rows, key=lambda r: (first.get(r["name"], len(first)), r["name"])):
        for p in row.get("docs_pages") or []:
            if p["id"] in seen:
                continue  # an add-on never replaces a page orch or another add-on already has
            seen.add(p["id"])
            pages.append({**p, "group": "builtin" if row["name"] in core_names else "addon", "addon": row["name"],
                          "on": bool(row.get("active")), "running": bool(row.get("running")),
                          "background": bool(row.get("background"))})
    for p in pages:
        p["related"] = [r for r in p.get("related", []) if r in seen and r != p["id"]]
    return {"schema": SCHEMA, "actors": core.get("actors", {}), "groups": list(GROUPS), "pages": pages}

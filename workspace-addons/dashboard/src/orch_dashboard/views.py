"""Pull an add-on view: `orch <name> view --json` (2 s, 256 KB), check it, keep the last good one in memory.
The dashboard never imports add-on code and never shows anything that failed the check."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from .data import _argv0, _child_env

TIMEOUT = 10.0  # a view that starts other orch commands (Focus with live sessions) needs more than 2 s on a busy machine
MAX_BYTES = 256 * 1024
TONES = ("neutral", "good", "warn", "needs-you", "bad")
BLOCKS = (
    "stat",
    "list",
    "calendar",
    "timeline",
    "chips",
    "table",
    "footnote",
    "settings",
    "radio",
    "split",
    "chart",
    "flow",
    "contacts",
)
# Same pattern as `link` in contracts/addon-view.schema.json (tests/test_views.py compares them).
_LINK = re.compile(
    r"""^(t_[a-z0-9]{6,16}|https://[^\s<>"'`]+|http://(127\.0\.0\.1|localhost):[0-9]{1,5}/?|addon:(?![/\\])(?!.*\.\.)[A-Za-z0-9_./?=&%-]{0,300}|app:(home|tickets|notes|chat|settings|addon)(/[a-z][a-z0-9-]{0,31}){0,2})$"""
)
_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HM = re.compile(r"^[0-2][0-9]:[0-5][0-9]$")
_KEY = re.compile(r"^[a-z_][a-z0-9_]{0,31}$")
COL_TYPES = ("text", "number", "duration", "date", "tone")


def _text(v, n=200):
    return isinstance(v, str) and 1 <= len(v) <= n and "<" not in v and ">" not in v


def _opt(d, k, ok):
    return k not in d or ok(d[k])


def _tone(v):
    return v in TONES


def _link(v):
    return isinstance(v, str) and len(v) <= 500 and bool(_LINK.match(v))


def _chip(c):
    return isinstance(c, dict) and _text(c.get("label"), 40) and _opt(c, "tone", _tone)


_OP = re.compile(r"^[a-z][a-z.]{0,31}$")


def _keys_only(d, allowed):
    return isinstance(d, dict) and set(d) <= set(allowed)


def _action(a):
    """{op, args}: flat scalars only; never a command line (extra keys such as `command` break the view)."""
    if not (_keys_only(a, ("op", "args")) and isinstance(a.get("op"), str) and _OP.match(a["op"])):
        return False
    args = a.get("args", {})
    return (
        isinstance(args, dict)
        and len(args) <= 6
        and all(
            _KEY.match(str(k))
            and (
                isinstance(v, (bool, int, float))
                or (isinstance(v, str) and len(v) <= 200 and "<" not in v and ">" not in v)
            )
            for k, v in args.items()
        )
    )


def _pagelink(v, n=40):
    return _keys_only(v, ("label", "to")) and _text(v.get("label"), n) and _link(v.get("to"))


def _meta(b):
    return _opt(b, "meta", lambda v: _text(v, 60))


def _empty(e):
    return (
        _keys_only(e, ("title", "text", "mark", "button", "link"))
        and _text(e.get("title"), 60)
        and _opt(e, "text", _text)
        and e.get("mark", "arrow") in ("arrow", "repeat", "dash")
        and _opt(e, "button", _pagelink)
        and _opt(e, "link", _pagelink)
    )


def _header(h):
    return (
        _keys_only(h, ("status", "link", "button"))
        and _opt(h, "status", _chip)
        and _opt(h, "link", _pagelink)
        and _opt(h, "button", _button)
    )


def _button(b):
    return (
        _keys_only(b, ("label", "action"))
        and _text(b.get("label"), 30)
        and _action(b.get("action"))
        and not b["action"].get("args")
    )


def _detail_ok(d):
    # Copy copies `value`: a row that shows `lines` instead must not carry a hidden value to copy.
    if isinstance(d, dict) and d.get("copy") and ("lines" in d or "value" not in d):
        return False
    return (
        _keys_only(d, ("label", "value", "lines", "tone", "copy"))
        and _text(d.get("label"), 30)
        and _opt(d, "value", _text)
        and _opt(d, "tone", _tone)
        and _opt(d, "copy", lambda v: isinstance(v, bool))
        and _opt(d, "lines", lambda v: isinstance(v, list) and len(v) <= 5 and all(_text(x) for x in v))
    )


def _ticket_ref_ok(t):
    return (
        _keys_only(t, ("id", "key", "title", "status"))
        and isinstance(t.get("id"), str)
        and bool(re.match(r"^t_[a-z0-9]{6,16}$", t["id"]))
        and _text(t.get("title"))
        and _opt(t, "key", lambda v: _text(v, 24))
        and _opt(t, "status", _chip)
    )


def _toggle_ok(t):
    return (
        _keys_only(t, ("on", "label", "text", "action"))
        and isinstance(t.get("on"), bool)
        and _text(t.get("label"), 60)
        and ("text" not in t or _text(t.get("text"), 24))
        and _action(t.get("action"))
    )


def _row_action_ok(a):
    return (
        _keys_only(a, ("label", "action", "confirm", "tone"))
        and _text(a.get("label"), 30)
        and _action(a.get("action"))
        and _opt(a, "confirm", lambda v: _text(v, 80))
        and a.get("tone", "neutral") in ("neutral", "bad")
    )


def _accordion_ok(i):
    return (
        _opt(i, "detail", lambda v: isinstance(v, list) and len(v) <= 12 and all(map(_detail_ok, v)))
        and _opt(i, "tickets", lambda v: isinstance(v, list) and len(v) <= 10 and all(map(_ticket_ref_ok, v)))
        and _opt(i, "toggle", _toggle_ok)
        and _opt(i, "actions", lambda v: isinstance(v, list) and len(v) <= 4 and all(map(_row_action_ok, v)))
    )


def _item_ok(it, required, extra):
    return (
        isinstance(it, dict)
        and all(k in it for k in required)
        and _opt(it, "tone", _tone)
        and _opt(it, "link", _link)
        and extra(it)
    )


_SPLIT_ID = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")


def _lines_ok(v, lo, hi):
    return isinstance(v, list) and lo <= len(v) <= hi and all(_text(x) for x in v)


def _confirm_ok(c):
    """Ask once before a split button is sent (a job marked important, ORCH-641): title, lines, Keep label."""
    return (
        _keys_only(c, ("title", "lines", "keep"))
        and _text(c.get("title"), 80)
        and _lines_ok(c.get("lines"), 1, 5)
        and _opt(c, "keep", lambda v: _text(v, 30))
    )


def _split_button_ok(b):
    return (
        _keys_only(b, ("label", "action", "link", "primary", "confirm"))
        and _text(b.get("label"), 30)
        and _opt(b, "action", _action)
        and _opt(b, "link", _link)
        and _opt(b, "primary", lambda v: isinstance(v, bool))
        and _opt(b, "confirm", _confirm_ok)
    )


def _buttons_ok(v, lo, hi):
    return isinstance(v, list) and lo <= len(v) <= hi and all(map(_split_button_ok, v))


def _fact_ok(f):
    return (
        _keys_only(f, ("label", "value", "tone", "link", "switch"))
        and _text(f.get("label"), 30)
        and _opt(f, "value", _text)
        and _opt(f, "tone", _tone)
        and _opt(f, "link", _link)
        and _opt(f, "switch", _toggle_ok)
    )


def _panel_ok(p):
    log, danger = p.get("log"), p.get("danger")
    conf = danger.get("confirm") if isinstance(danger, dict) else None
    return (
        _keys_only(p, ("text", "buttons", "facts", "note", "log", "danger"))
        and _opt(p, "text", _text)
        and _opt(p, "buttons", lambda v: _buttons_ok(v, 0, 4))
        and _opt(p, "facts", lambda v: isinstance(v, list) and len(v) <= 12 and all(map(_fact_ok, v)))
        and _opt(p, "note", _text)
        and (
            log is None
            or (
                _keys_only(log, ("title", "lines", "empty"))
                and _lines_ok(log.get("lines"), 0, 100)
                and _opt(log, "title", lambda v: _text(v, 40))
                and _opt(log, "empty", _text)
            )
        )
        and (
            danger is None
            or (
                _keys_only(danger, ("label", "note", "action", "confirm"))
                and _text(danger.get("label"), 30)
                and _opt(danger, "note", _text)
                and _action(danger.get("action"))
                and _keys_only(conf, ("title", "lines", "keep"))
                and _text(conf.get("title"), 80)
                and _lines_ok(conf.get("lines"), 1, 5)
                and _opt(conf, "keep", lambda v: _text(v, 30))
            )
        )
    )


def _split_item_ok(it):
    q = it.get("question") if isinstance(it, dict) else None
    return (
        _keys_only(it, ("id", "title", "state", "action", "question", "panel"))
        and isinstance(it.get("id"), str)
        and bool(_SPLIT_ID.match(it["id"]))
        and _text(it.get("title"), 80)
        and _chip(it.get("state"))
        and _opt(it, "action", _split_button_ok)
        and (
            q is None
            or (
                _keys_only(q, ("title", "text", "buttons"))
                and _text(q.get("title"), 80)
                and _opt(q, "text", _text)
                and _buttons_ok(q.get("buttons"), 1, 3)
            )
        )
        and isinstance(it.get("panel"), dict)
        and _panel_ok(it["panel"])
    )


def _split_ok(b):
    groups = b.get("groups")
    return (
        _keys_only(b, ("type", "title", "param", "empty", "groups"))
        and _opt(b, "title", lambda v: _text(v, 60))
        and _opt(b, "param", lambda v: isinstance(v, str) and bool(re.match(r"^[a-z]{1,12}$", v)))
        and _opt(b, "empty", _empty)
        and isinstance(groups, list)
        and len(groups) <= 4
        and all(
            _keys_only(g, ("title", "meta", "items"))
            and _text(g.get("title"), 60)
            and _meta(g)
            and isinstance(g.get("items"), list)
            and len(g["items"]) <= 50
            and all(map(_split_item_ok, g["items"]))
            for g in groups
        )
    )


def _by_key(v, ok):
    return isinstance(v, dict) and len(v) <= 6 and all(_KEY.match(str(k)) and ok(x) for k, x in v.items())


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0


def _chart_ok(b):
    labels, series = b.get("labels"), b.get("series")
    return (
        _keys_only(b, ("type", "title", "meta", "span", "labels", "series", "stacked", "empty"))
        and _opt(b, "title", lambda v: _text(v, 60))
        and _meta(b)
        and b.get("span", "half") == "half"
        and _opt(b, "stacked", lambda v: isinstance(v, bool))
        and _opt(b, "empty", _empty)
        and isinstance(labels, list)
        and 1 <= len(labels) <= 31
        and all(_text(x, 16) for x in labels)
        and isinstance(series, list)
        and 1 <= len(series) <= 3
        and all(
            _keys_only(x, ("name", "tone", "values"))
            and _text(x.get("name"), 24)
            and _opt(x, "tone", _tone)
            and isinstance(x.get("values"), list)
            and len(x["values"]) == len(labels)  # one number per label: a short series is not drawn as zeros
            and all(map(_num, x["values"]))
            for x in series
        )
    )


def _flow_item_ok(it):
    return (
        _keys_only(it, ("label", "place", "hint", "tone", "link"))
        and _text(it.get("label"), 24)
        and _opt(it, "place", lambda v: _int(v) and 1 <= v <= 999)
        and _opt(it, "hint", _text)
        and _opt(it, "tone", _tone)
        and _opt(it, "link", _link)
    )


def _flow_stage_ok(s):
    keys = ("label", "value", "text", "tone", "active", "items", "more", "progress", "bars", "bars_label")
    return (
        _keys_only(s, keys)
        and _text(s.get("label"), 30)
        and _text(s.get("value"), 40)
        and _opt(s, "text", _text)
        and _opt(s, "tone", _tone)
        and _opt(s, "active", lambda v: isinstance(v, bool))
        and _opt(s, "items", lambda v: isinstance(v, list) and len(v) <= 30 and all(map(_flow_item_ok, v)))
        and _opt(s, "more", _int)
        and _opt(
            s,
            "progress",
            lambda p: (
                _keys_only(p, ("value", "max", "label"))
                and _num(p.get("value"))
                and _num(p.get("max"))
                and p["max"] > 0
                and _text(p.get("label"))
            ),
        )
        and _opt(
            s,
            "bars",
            lambda v: (
                isinstance(v, list)
                and len(v) <= 24
                and all(
                    _keys_only(x, ("value", "tone", "hint"))
                    and _num(x.get("value"))
                    and _opt(x, "tone", _tone)
                    and _opt(x, "hint", _text)
                    for x in v
                )
            ),
        )
        and _opt(s, "bars_label", _text)
    )


def _flow_ok(b):
    stages = b.get("stages")
    return (
        _keys_only(b, ("type", "title", "link", "meta", "stages"))
        and _text(b.get("title"), 60)
        and _opt(b, "link", _link)
        and _meta(b)
        and isinstance(stages, list)
        and 1 <= len(stages) <= 4
        and all(map(_flow_stage_ok, stages))
    )


def _block_ok(b) -> bool:
    t = b.get("type") if isinstance(b, dict) else None
    if t == "stat":
        v = b.get("value")
        return (
            _text(b.get("label"), 40)
            and (_text(v, 24) or (isinstance(v, (int, float)) and not isinstance(v, bool)))
            and _opt(b, "tone", _tone)
        )
    if t == "list":
        items = b.get("items")
        return (
            _text(b.get("title"), 60)
            and isinstance(items, list)
            and len(items) <= 50
            and _opt(b, "more", _int)
            and _meta(b)
            and _opt(b, "count", _int)
            and b.get("span", "half") == "half"
            and _opt(b, "compact", lambda v: isinstance(v, bool))
            and _opt(b, "above", lambda v: isinstance(v, bool))
            and _opt(b, "empty", _empty)
            and all(
                _item_ok(
                    i,
                    ("title",),
                    lambda i: (
                        _text(i["title"])
                        and _opt(i, "subtitle", _text)
                        and _opt(
                            i, "meta", lambda m: isinstance(m, list) and len(m) <= 3 and all(map(_text, m))
                        )
                        and _opt(
                            i, "chips", lambda c: isinstance(c, list) and len(c) <= 6 and all(map(_chip, c))
                        )
                        and _accordion_ok(i)
                    ),
                )
                for i in items
            )
        )
    if t == "calendar":
        days = b.get("days")
        return (
            _opt(b, "title", lambda v: _text(v, 60))
            and _meta(b)
            and isinstance(days, list)
            and len(days) <= 14
            and all(
                isinstance(d, dict)
                and isinstance(d.get("date"), str)
                and _DATE.match(d["date"])
                and isinstance(d.get("items"), list)
                and len(d["items"]) <= 20
                and all(
                    _item_ok(
                        i,
                        ("title",),
                        lambda i: (
                            _text(i["title"], 80)
                            and _opt(i, "time", lambda v: isinstance(v, str) and bool(_HM.match(v)))
                            and _opt(i, "every", lambda v: _text(v, 24))
                            and _opt(i, "note", lambda v: _text(v, 60))
                        ),
                    )
                    for i in d["items"]
                )
                for d in days
            )
        )
    if t == "timeline":
        items = b.get("items")
        return (
            _opt(b, "title", lambda v: _text(v, 60))
            and _meta(b)
            and isinstance(items, list)
            and len(items) <= 50
            and all(
                _item_ok(
                    i,
                    ("at", "text"),
                    lambda i: isinstance(i["at"], str) and bool(_TIME.match(i["at"])) and _text(i["text"]),
                )
                for i in items
            )
        )
    if t == "chips":
        items = b.get("items")
        return (
            _opt(b, "title", lambda v: _text(v, 60))
            and _meta(b)
            and isinstance(items, list)
            and len(items) <= 30
            and all(map(_chip, items))
        )
    if t == "table":
        cols, rows = b.get("columns"), b.get("rows")
        if not (
            isinstance(cols, list) and 1 <= len(cols) <= 6 and isinstance(rows, list) and len(rows) <= 100
        ):
            return False
        if not (
            _opt(b, "title", lambda v: _text(v, 60))
            and _opt(b, "more", _int)
            and _meta(b)
            and _opt(b, "compact", lambda v: isinstance(v, bool))
            and _opt(b, "filter", lambda v: isinstance(v, str) and bool(_KEY.match(v)))
            and _opt(b, "fold", lambda v: _int(v) and 1 <= v <= 100)
        ):
            return False
        if not all(
            isinstance(c, dict)
            and isinstance(c.get("key"), str)
            and _KEY.match(c["key"])
            and _text(c.get("label"), 24)
            and c.get("type") in COL_TYPES
            for c in cols
        ):
            return False
        return all(
            isinstance(r, dict)
            and isinstance(r.get("cells"), dict)
            and _opt(r, "link", _link)
            and _opt(r, "subtitle", _text)
            and _opt(r, "links", lambda v: _by_key(v, _link))
            and _opt(r, "tones", lambda v: _by_key(v, _tone))
            and _opt(r, "toggle", _toggle_ok)
            and _opt(
                r, "actions", lambda v: isinstance(v, list) and len(v) <= 4 and all(map(_row_action_ok, v))
            )
            and all(
                _KEY.match(str(k))
                and (v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)) or _text(v))
                for k, v in r["cells"].items()
            )
            for r in rows
        )
    if t == "chart":
        return _chart_ok(b)
    if t == "flow":
        return _flow_ok(b)
    if t == "footnote":
        return _keys_only(b, ("type", "text", "link")) and _text(b.get("text")) and _opt(b, "link", _pagelink)
    if t == "settings":
        rows = b.get("rows")
        return (
            _keys_only(b, ("type", "title", "rows"))
            and _text(b.get("title"), 60)
            and isinstance(rows, list)
            and 1 <= len(rows) <= 12
            and all(
                _keys_only(r, ("label", "value", "note", "tone", "button"))
                and _text(r.get("label"), 30)
                and _text(r.get("value"), 120)
                and _opt(r, "note", _text)
                and _opt(r, "tone", _tone)
                and _opt(r, "button", _row_button)
                for r in rows
            )
        )
    if t == "split":
        return _split_ok(b)
    if t == "contacts":
        return _contacts_ok(b)
    if t == "radio":
        opts = b.get("options")
        return (
            _keys_only(b, ("type", "title", "options"))
            and _text(b.get("title"), 60)
            and isinstance(opts, list)
            and 2 <= len(opts) <= 5
            and all(
                _keys_only(o, ("label", "selected", "action", "link"))
                and _text(o.get("label"), 60)
                and isinstance(o.get("selected"), bool)
                and _opt(o, "action", _action)
                and _opt(o, "link", _link)
                for o in opts
            )
        )
    return False


# Contacts with fingerprint and state (ORCH-1203; contracts/addon-view.schema.json $defs/contacts)
_PEER = re.compile(r"^(ws|ph)_[a-z0-9]{10}$")
_FP = re.compile(r"^[0-9A-Z]{4}( [0-9A-Z]{4}){7}$")
TRUST_STATES = ("new_key", "changed", "not_accepted", "not_valid", "withdrawn", "accepted")


def _fp(v):
    return isinstance(v, str) and bool(_FP.match(v))


def _contact_ok(c):
    return (
        _keys_only(
            c,
            (
                "id",
                "name",
                "relay_name",
                "kind",
                "state",
                "fingerprint",
                "old_fingerprint",
                "held",
                "refused",
                "accepted_at",
                "withdrawn_at",
            ),
        )
        and isinstance(c.get("id"), str)
        and bool(_PEER.match(c["id"]))
        and _text(c.get("name"), 60)
        and _opt(c, "relay_name", lambda v: _text(v, 60))
        and c.get("kind") in ("workspace", "phone")
        and c.get("state") in TRUST_STATES
        and _fp(c.get("fingerprint"))
        and _opt(c, "old_fingerprint", _fp)
        and _int(c.get("held"))
        and _opt(c, "refused", _int)
        and all(
            _opt(c, k, lambda v: isinstance(v, str) and bool(_TIME.match(v)))
            for k in ("accepted_at", "withdrawn_at")
        )
    )


def _contacts_ok(b):
    items, own = b.get("items"), b.get("own")
    return (
        _keys_only(b, ("type", "title", "own", "items"))
        and _opt(b, "title", lambda v: _text(v, 60))
        and (
            own is None
            or (
                _keys_only(own, ("name", "fingerprint"))
                and _fp(own.get("fingerprint"))
                and _opt(own, "name", lambda v: _text(v, 60))
            )
        )
        and isinstance(items, list)
        and len(items) <= 200
        and all(map(_contact_ok, items))
    )


def _row_button(b):
    return _keys_only(b, ("label", "action")) and _text(b.get("label"), 30) and _action(b.get("action"))


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


_ZONE = re.compile(r"^[A-Za-z0-9_+/-]{1,64}$")
_ZONE_TID = re.compile(r"^t_[a-z0-9]{1,32}$")


def _zones(z):
    """The repeat window's time zones (ORCH-1861): `new` and `repeats` {ticket id: zone}, IANA names only."""
    reps = z.get("repeats", {}) if isinstance(z, dict) else None
    return (
        _keys_only(z, ("new", "repeats"))
        and _opt(z, "new", lambda v: isinstance(v, str) and bool(_ZONE.match(v)))
        and isinstance(reps, dict)
        and len(reps) <= 500
        and all(
            isinstance(k, str) and _ZONE_TID.match(k) and isinstance(x, str) and _ZONE.match(x)
            for k, x in reps.items()
        )
    )


def check_view(v) -> dict | None:
    """Return the view with unknown block types dropped, or None when it breaks the contract."""
    if not (
        isinstance(v, dict)
        and v.get("schema") == "orch.addon-view/1"
        and isinstance(v.get("generated_at"), str)
        and _TIME.match(v["generated_at"])
        and isinstance(v.get("blocks"), list)
        and len(v["blocks"]) <= 20
        and _opt(v, "notice", _text)
        and _opt(v, "notice_tone", _tone)
        and _opt(v, "button", _button)
        and _opt(v, "header", _header)
        and ("button" not in v or "notice" in v)
    ):
        return None
    blocks = []
    for b in v["blocks"]:
        if isinstance(b, dict) and b.get("type") in BLOCKS:
            if not _block_ok(b):
                return None
            blocks.append(b)
        elif not isinstance(b, dict) or not isinstance(b.get("type"), str):
            return None
    return {
        **{
            k: v[k] for k in ("schema", "generated_at", "notice", "notice_tone", "button", "header") if k in v
        },
        **(
            {"zones": v["zones"]} if "zones" in v and _zones(v["zones"]) else {}
        ),  # a bad one is dropped, not the view
        "blocks": blocks,
    }


_WINDOWS = os.name == "nt"
_run = subprocess.run  # module-local, so a test patches this and never the global subprocess.run


def _group_kw() -> dict:
    """Start the `view` command as the head of its own group, so a kill also reaches what it started."""
    if _WINDOWS:
        return {"creationflags": 0x00000200}  # CREATE_NEW_PROCESS_GROUP: ended as a tree (taskkill /T)
    return {"start_new_session": True}


def _taskkill_exe() -> str | None:
    try:
        from orch.safegit import taskkill_exe  # the core's one lookup: full path in the system folder
    except ImportError:
        return None
    return taskkill_exe()


def _kill_tree(p: subprocess.Popen) -> None:
    """End an add-on's `view` command and what it started; never raises. POSIX: SIGKILL to its own process
    group. Windows has no os.killpg or SIGKILL (ORCH-1796): `taskkill /T /F` while it still runs (a finished
    pid may be reused), then the command alone when taskkill is missing or failed."""
    if not _WINDOWS:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        return
    if p.poll() is not None:
        return
    exe = _taskkill_exe()
    if exe:
        try:
            _run(
                [exe, "/PID", str(p.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                timeout=5,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        if p.poll() is None:
            p.kill()
    except OSError:
        pass


class ViewPuller:
    """One per server. `pull(name)` -> {"state": "ok"|"stale"|"error", "view", "as_of", "message"}."""

    def __init__(self, root: Path, orch_bin: str | None, timeout: float = TIMEOUT):
        self.root, self.orch_bin, self.timeout = root, orch_bin, timeout
        self.last: dict[str, dict] = {}
        self.inflight: dict[str, dict] = {}
        self.lock = threading.Lock()

    def _run(self, name: str):
        if not self.orch_bin:
            return None, "The orch command was not found."
        env = _child_env({**os.environ, "ORCH_ROOT": str(self.root), "ORCH_ADDON": name}, self.orch_bin)
        try:  # own session: on timeout or too much output the whole process group is killed
            p = subprocess.Popen(
                [*_argv0(self.orch_bin), name, "view", "--json"],
                cwd=self.root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                **_group_kw(),
            )
        except OSError:
            return None, "The orch command could not be started."
        chunks: list[bytes] = []
        state = {"n": 0, "big": False}

        def kill():
            _kill_tree(p)

        def read():  # hard cap while reading, not after
            while True:
                data = p.stdout.read1(65536)
                if not data:
                    return
                state["n"] += len(data)
                if state["n"] > MAX_BYTES:
                    state["big"] = True
                    kill()
                    return
                chunks.append(data)

        t = threading.Thread(target=read, daemon=True)
        t.start()
        t.join(self.timeout)
        timed_out = t.is_alive()
        if timed_out:
            kill()
        kill()  # also catches children that outlive the add-on process
        t.join(1)
        p.wait()
        p.stdout.close()
        if state["big"]:
            return None, "The answer was too large."
        if timed_out:
            return None, "It took too long to answer."
        if p.returncode != 0:
            return None, "It could not be read right now."
        try:
            view = check_view(json.loads(b"".join(chunks)))
        except ValueError:
            view = None
        return (view, "") if view else (None, "The answer was not in the expected form.")

    def pull(self, name: str) -> dict:
        """One pull per add-on at a time: concurrent callers wait for the one in flight and share its result."""
        with self.lock:
            flight = self.inflight.get(name)
            mine = flight is None
            if mine:
                flight = self.inflight[name] = {"done": threading.Event(), "result": None}
        if not mine:
            flight["done"].wait(self.timeout + 5)
            return flight["result"] or self._cached(name)
        try:
            flight["result"] = self._pull(name)
        finally:
            with self.lock:
                self.inflight.pop(name, None)
            flight["done"].set()
        return flight["result"]

    def _cached(self, name: str) -> dict:
        with self.lock:
            old = self.last.get(name)
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if old:
            return {
                "state": "stale",
                "view": old["view"],
                "as_of": old["view"]["generated_at"],
                "checked": now,
                "message": "It took too long to answer.",
            }
        return {
            "state": "error",
            "view": None,
            "as_of": None,
            "checked": now,
            "message": "It took too long to answer.",
        }

    def _pull(self, name: str) -> dict:
        view, why = self._run(name)
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.lock:
            if view:
                self.last[name] = {"view": view, "fetched": time.time()}
                return {"state": "ok", "view": view, "as_of": view["generated_at"], "checked": now}
            old = self.last.get(name)
        if old:
            return {
                "state": "stale",
                "view": old["view"],
                "as_of": old["view"]["generated_at"],
                "checked": now,
                "message": why,
            }
        return {"state": "error", "view": None, "as_of": None, "checked": now, "message": why}

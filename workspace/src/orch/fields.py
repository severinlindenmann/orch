"""Add-on fields on a ticket: an add-on's `[ticket_fields]` (section, schema, show_on_card) turned into a
short list of typed fields (text, number, date, choice, url) that people
see and edit under the ticket's Details.

The values live in `ext.<add-on>` and are checked with the add-on's schema on every write (tickets.ext_set).
Only `title`, `type`, `enum` (+ `x-labels`), `format: date|uri`, `minimum`/`maximum`, `maxLength`, `readOnly`
and `x-hidden` of the schema are used here.
"""

from __future__ import annotations

import json
import re
from datetime import date

from orch.errors import Refused
from orch.links import one_line

KEY_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def field_list(schema: dict) -> list[dict]:
    """[{key, title, type, options?, read_only, hidden}] in schema order."""
    out = []
    props = schema.get("properties") if isinstance(schema, dict) else None
    for key, p in (props or {}).items():
        if not (isinstance(p, dict) and KEY_RE.fullmatch(key)):
            continue
        t = p.get("type")
        if isinstance(p.get("enum"), list):
            typ = "choice"
        elif t in ("number", "integer"):
            typ = "number"
        elif t == "string" and p.get("format") == "date":
            typ = "date"
        elif t == "string" and p.get("format") in ("uri", "url"):
            typ = "url"
        elif t == "string":
            typ = "text"
        else:
            continue  # objects, lists, yes/no: kept in the file, not shown as a field
        f = {
            "key": key,
            "title": one_line(p.get("title") or key.replace("_", " ").capitalize(), 40),
            "type": typ,
            "read_only": p.get("readOnly") is True,
            "hidden": p.get("x-hidden") is True,
        }
        if typ == "choice":
            labels = p.get("x-labels") if isinstance(p.get("x-labels"), dict) else {}
            f["options"] = [
                {"value": v, "label": one_line(labels.get(v, v), 40)} for v in p["enum"] if isinstance(v, str)
            ]
        out.append(f)
    return out


def section(m: dict) -> dict | None:
    """The `[ticket_fields]` of a parsed manifest with its fields, or None."""
    tf = m.get("ticket_fields")
    if not tf:
        return None
    schema = json.loads((m["dir"] / tf["schema"]).read_text(encoding="utf-8"))
    return {"section": tf["section"], "show_on_card": tf["show_on_card"], "fields": field_list(schema)}


def parse_value(f: dict, raw: str, schema_prop: dict):
    """A person's text → the stored value, refused in plain words. Empty text = clear the field (None)."""
    v = raw.strip()
    if v == "":
        return None
    name = f["title"]
    if f["type"] == "number":
        try:
            n = float(v.replace("’", "").replace("'", "").replace(",", ""))
        except ValueError:
            raise Refused(f"{name} must be a number.") from None
        if schema_prop.get("type") == "integer" or n.is_integer():
            if schema_prop.get("type") == "integer" and not n.is_integer():
                raise Refused(f"{name} must be a whole number.")
            n = int(n)
        lo, hi = schema_prop.get("minimum"), schema_prop.get("maximum")
        if isinstance(lo, int | float) and n < lo:
            raise Refused(f"{name} must be at least {lo}.")
        if isinstance(hi, int | float) and n > hi:
            raise Refused(f"{name} must be at most {hi}.")
        return n
    if f["type"] == "choice":
        for o in f["options"]:
            if v.lower() in (o["value"].lower(), o["label"].lower()):
                return o["value"]
        picks = ", ".join(o["label"] for o in f["options"])
        raise Refused(f'Can\'t set {name} to "{one_line(v, 60)}". Pick one of: {picks}.')
    if f["type"] == "date":
        try:
            date.fromisoformat(v)
            if not re.fullmatch(r"\d{4}-\d\d-\d\d", v):
                raise ValueError
        except ValueError:
            raise Refused(f"{name} must be a day like 2026-12-01.") from None
        return v
    if f["type"] == "url":
        from orch import links

        try:
            return links.check_url(v)
        except Refused:
            raise Refused(f"{name} must be a web address that starts with https:// or http://.") from None
    v = one_line(v, 2000)  # no control characters (terminal escapes), bidi or invisible ones
    ml = schema_prop.get("maxLength")
    if "\n" in v or (isinstance(ml, int) and len(v) > ml):
        raise Refused(f"{name} is one line of at most {ml if isinstance(ml, int) else 2000} characters.")
    return v


def shown(f: dict, value) -> str:
    """A stored value as a person reads it (choice label, number as written)."""
    if value is None:
        return "-"
    if f["type"] == "choice":
        return next((o["label"] for o in f["options"] if o["value"] == value), one_line(value))
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return one_line(value, 2000)

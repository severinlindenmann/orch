"""Mail and Messages (ORCH-652): what needs the person, from every mailbox and work chat, through ways in.

A source is a way in (ways.py) with part = "mail" or "messages". It may only read and make drafts; one that lists
any other action cannot be turned on (ways.PART_ACTIONS). There is no send anywhere: not in a way in, not in
Personal, not in a rule. Actions (values as JSON on stdin, one JSON object back on stdout):

    accounts  {}                                   -> {"accounts": ["iCloud", ...]}  (Mail app: the person picks)
    list      {"days", "limit", "accounts"}        -> {"items": [ITEM], "more": bool}  newest first
    find      {"words", "limit", "accounts"}       -> {"items": [ITEM], "more": bool}
    show      {"ref", "accounts"}                  -> mail: {"from", "to", "cc", "subject", "when", "text", "link"}
                                                      messages: {"chat", "messages": [{"who", "when", "text",
                                                      "me"}], "link"}
    draft     {"ref", "text", "request", "accounts"} -> {"saved": true, "draft": "<ref>", "link"}  never sent
    ITEM = {"ref", "from", "subject" | "chat", "when", "preview", "unread", "flagged", "to_me", "mention",
            "direct", "link"}

Which mails and chats need the person is decided here, in code, by plain rules (the source only fetches). A source
without a draft action (Teams has no server drafts) gets the reply kept on Personal: "Copy and open in Teams".

    .orch/addons/personal/drafts.json   the replies helpers made: where they went, by whom, for which ticket
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import threading
import time
from datetime import UTC
from pathlib import Path

from . import store
from . import ways as ways_mod
from .store import Refused

PARTS = store.INBOX_PARTS
DAYS = 3
LIST_LIMIT = 50
NEED_LIMIT = 20
MAX_WORDS = 200
MAX_TEXT = 20000
MAX_DRAFT = 8000
MAX_MESSAGES = 30
CACHE_SECONDS = 300
REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@=+/-]{0,255}")
ITEM_ID = re.compile(r"([a-z0-9][a-z0-9-]{0,31})~([A-Za-z0-9][A-Za-z0-9._:@=+/-]{0,255})")
LINK = re.compile(
    r"(https://(outlook\.office\.com|outlook\.office365\.com|outlook\.live\.com|teams\.microsoft\.com)/|msteams:)\S{0,1500}"
)
UNSURE = "Not sure the draft was saved; look in Drafts before you write it again."
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_DRAFTS = threading.Lock()


def _line(v, limit: int) -> str:
    text = "".join(c if c.isprintable() else " " for c in str(v or ""))
    return " ".join(text.split())[:limit]


def _text(v, limit: int) -> str:
    text = "".join(c if c.isprintable() or c == "\n" else " " for c in str(v or "").replace("\r\n", "\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:limit]


def _link(v) -> str | None:
    v = str(v or "")
    return v if LINK.fullmatch(v) else None


def item_id(way: str, ref: str) -> str:
    """The id helpers and the page use: which way in, and the source's own id (account and thread inside)."""
    return f"{way}~{ref}"


def split_id(iid: str) -> tuple[str, str]:
    m = ITEM_ID.fullmatch(iid or "")
    if not m:
        raise Refused(f"There is no mail or chat {iid[:80]!r}. See them: orch personal mail need-me")
    return m.group(1), m.group(2)


# --- sources -------------------------------------------------------------------------------------------------
def sources(root: Path, part: str) -> list[dict]:
    """Every way in for this part, as the page shows it under Sources (on or not)."""
    p = store.settings(root)["parts"].get(part) or {}
    out = []
    for w in ways_mod.status(root):
        if w["part"] != part:
            continue
        out.append(
            {
                **w,
                "helpers": bool(p.get("helpers", {}).get(w["way"])),
                "accounts": p.get("accounts", {}).get(w["way"], []),
                "needs_accounts": "accounts" in w["actions"] and not p.get("accounts", {}).get(w["way"]),
                "drafts_on_source": "draft" in w["actions"],
            }
        )
    return out


def _usable(src: dict) -> bool:
    return src["on"] and src["status"] not in ("permission",) and not src["needs_accounts"]


def _ask(root: Path, src: dict, action: str, values: dict) -> dict:
    vals = {**values}
    if "accounts" in src["actions"]:
        vals["accounts"] = src["accounts"]
    # each item is checked for secrets before a helper sees it (api.py); the person sees their own mail
    text = ways_mod.ask(root, src["way"], action, vals, secrets=False)["text"]
    try:
        data = json.loads(text)
    except ValueError:
        raise Refused(f"{src['name']} did not answer in the agreed form (JSON).") from None
    if not isinstance(data, dict):
        raise Refused(f"{src['name']} did not answer in the agreed form (one JSON object).")
    if data.get("error"):  # the source answered, but cannot do it now (Mail is closed, a mail is gone)
        raise Refused(f"{src['name']}: {_line(data['error'], 200)}")
    return data


def _item(part: str, src: dict, raw) -> dict | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("ref"), str) or not REF.fullmatch(raw["ref"]):
        return None
    preview = _line(raw.get("preview"), 200)
    row = {
        "id": item_id(src["way"], raw["ref"]),
        "way": src["way"],
        "source": src["name"],
        "from": _line(raw.get("from"), 120),
        "when": _line(raw.get("when"), 32),
        "preview": preview,
        "unread": raw.get("unread") is True,
        "flagged": raw.get("flagged") is True,
        "to_me": raw.get("to_me") is True,
        "mention": raw.get("mention") is True,
        "direct": raw.get("direct") is True,
        "question": "?" in preview,
        "link": _link(raw.get("link")),
    }
    if part == "mail":
        row["subject"] = _line(raw.get("subject"), 200) or "(no subject)"
    else:
        row["chat"] = _line(raw.get("chat"), 120) or row["from"] or "Chat"
    return row


def _items(part: str, src: dict, data: dict, limit: int) -> tuple[list[dict], bool]:
    raw = data.get("items") if isinstance(data.get("items"), list) else []
    rows = [r for r in (_item(part, src, x) for x in raw[: limit + 1]) if r]
    return rows[:limit], bool(data.get("more")) or len(raw) > limit


# --- what needs the person: plain rules, in code -------------------------------------------------------------
def _since(days: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400))


def _vip(row: dict, vip: list[str]) -> bool:
    who = row["from"].casefold()
    return any(v.casefold() in who for v in vip if v)


def needs_person(part: str, row: dict, vip: list[str]) -> int:
    """0 = does not need the person; else a score (higher first). Mail: unread or flagged, sent to them or
    flagged, from the last days. Chats: unread, a 1:1 chat or naming them."""
    if row["when"] and _iso(row["when"]) < _since(DAYS) and not row["flagged"]:
        return 0
    if part == "mail":
        if not (row["unread"] or row["flagged"]) or not (row["flagged"] or row["to_me"] or _vip(row, vip)):
            return 0
        return 1 + 4 * row["flagged"] + 3 * _vip(row, vip) + 2 * row["to_me"] + row["question"]
    if not row["unread"] or not (row["direct"] or row["mention"] or _vip(row, vip)):
        return 0
    return 1 + 3 * _vip(row, vip) + 2 * row["mention"] + 2 * row["direct"] + row["question"]


def _iso(when: str) -> str:
    """Times from a source with an offset (2026-11-20T09:12:00+01:00) compare as UTC."""
    from datetime import datetime

    try:
        d = datetime.fromisoformat(when)
    except ValueError:
        return when
    if d.tzinfo is None:
        d = d.astimezone()
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def look(root: Path, part: str, srcs: list[dict], fresh: bool = False) -> dict:
    """Ask every usable source for its recent items. Returns {"items", "checked", "sources": [{way, name, ok,
    problem, more}]}. Kept in memory for a few minutes (never on disk): the tile and the page read it."""
    key = f"{root}\0{part}\0" + ",".join(f"{s['way']}:{','.join(s['accounts'])}" for s in srcs)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and not fresh and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    rows, report = [], []
    for src in srcs:
        if not _usable(src):
            why = (
                "off"
                if not src["on"]
                else "choose which accounts count"
                if src["needs_accounts"]
                else (src["problem"] or src["words"])
            )
            report.append(
                {"way": src["way"], "name": src["name"], "ok": False, "problem": why, "more": False}
            )
            continue
        try:
            data = _ask(root, src, "list", {"days": DAYS, "limit": LIST_LIMIT})
        except Refused as e:
            # a way in that stopped keeps its first reason (the self-check's line), not "ended with code 1"
            st = ways_mod.saved(root).get(src["way"], {})
            why = st.get("problem") if st.get("status") == "stopped" and st.get("problem") else str(e)
            report.append(
                {"way": src["way"], "name": src["name"], "ok": False, "problem": why, "more": False}
            )
            continue
        got, more = _items(part, src, data, LIST_LIMIT)
        rows += got
        report.append({"way": src["way"], "name": src["name"], "ok": True, "problem": None, "more": more})
    rows.sort(key=lambda r: _iso(r["when"]), reverse=True)
    out = {"items": rows, "checked": store.now(), "sources": report}
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), out)
    return out


def need_me(part: str, looked: dict, vip: list[str]) -> dict:
    scored = [(needs_person(part, r, vip), r) for r in looked["items"]]
    hits = [r for s, r in sorted(scored, key=lambda x: (x[0], _iso(x[1]["when"])), reverse=True) if s]
    cut = len(hits) > NEED_LIMIT or any(s["more"] for s in looked["sources"] if s["ok"])
    return {"items": hits[:NEED_LIMIT], "total": len(hits), "cut": cut}


def find(root: Path, part: str, srcs: list[dict], words: str) -> tuple[list[dict], list[dict]]:
    words = " ".join(words.split())
    if not words:
        raise Refused(f'Say what to look for: orch personal {part} find "<words>"')
    if len(words) > MAX_WORDS:
        raise Refused(f"Look for at most {MAX_WORDS} characters.")
    rows, report = [], []
    for src in srcs:
        if not _usable(src):
            continue
        try:
            data = _ask(root, src, "find", {"words": words, "limit": NEED_LIMIT})
        except Refused as e:
            report.append(
                {"way": src["way"], "name": src["name"], "ok": False, "problem": str(e), "more": False}
            )
            continue
        got, more = _items(part, src, data, NEED_LIMIT)
        rows += got
        report.append({"way": src["way"], "name": src["name"], "ok": True, "problem": None, "more": more})
    rows.sort(key=lambda r: _iso(r["when"]), reverse=True)
    return rows, report


def show(root: Path, part: str, src: dict, ref: str) -> dict:
    if not _usable(src):
        raise Refused(f"{src['name']} is not working right now: {src['problem'] or src['words']}")
    data = _ask(root, src, "show", {"ref": ref})
    out = {
        "id": item_id(src["way"], ref),
        "way": src["way"],
        "source": src["name"],
        "link": _link(data.get("link")),
    }
    if part == "mail":
        out.update(
            {
                "from": _line(data.get("from"), 200),
                "to": [_line(x, 200) for x in (data.get("to") or [])[:50] if _line(x, 200)],
                "cc": [_line(x, 200) for x in (data.get("cc") or [])[:50] if _line(x, 200)],
                "subject": _line(data.get("subject"), 300) or "(no subject)",
                "when": _line(data.get("when"), 32),
                "text": _text(data.get("text"), MAX_TEXT),
            }
        )
        out["title"] = out["subject"]
    else:
        msgs = data.get("messages") if isinstance(data.get("messages"), list) else []
        out.update(
            {
                "chat": _line(data.get("chat"), 120) or "Chat",
                "messages": [
                    {
                        "who": _line(m.get("who"), 120),
                        "when": _line(m.get("when"), 32),
                        "text": _text(m.get("text"), 4000),
                        "me": m.get("me") is True,
                    }
                    for m in msgs[-MAX_MESSAGES:]
                    if isinstance(m, dict) and _text(m.get("text"), 4000)
                ],
            }
        )
        out["title"] = out["chat"]
    return out


def as_markdown(part: str, m: dict, note: str) -> str:
    out = [f"<!-- {note} From Personal > {store.PARTS[part]['label']}: {m['id']} -->", ""]
    if part == "mail":
        out += [f"# {m['subject']}", "", f"From {m['from']} · {m['when']} · {m['source']}"]
        if m["to"]:
            out.append("To: " + ", ".join(m["to"]))
        if m["cc"]:
            out.append("Cc: " + ", ".join(m["cc"]))
        out += ["", m["text"]]
    else:
        out += [f"# {m['chat']}", "", m["source"], ""]
        out += [f"{x['who'] or '?'} {x['when']}: {x['text']}" for x in m["messages"]]
    return "\n".join(out) + "\n"


# --- drafts: saved once, never sent --------------------------------------------------------------------------
def _drafts_file(root: Path) -> Path:
    return store.base(root) / "drafts.json"


def drafts(root: Path) -> dict[str, dict]:
    raw = store._read_json(_drafts_file(root), {})
    return {k: v for k, v in raw.items() if re.fullmatch(r"d_[0-9a-f]{16}", k) and isinstance(v, dict)}


def _save_drafts(root: Path, data: dict) -> None:
    keep = dict(sorted(data.items(), key=lambda kv: str(kv[1].get("at") or ""))[-300:])
    store._atomic_write(_drafts_file(root), json.dumps(keep, ensure_ascii=False, indent=2) + "\n")


@contextlib.contextmanager
def _locked(root: Path):
    with ways_mod._file_lock(root, "drafts.lock", _DRAFTS):
        yield


def title_of(part: str, iid: str) -> str:
    """The subject or chat name of an item from the last look (memory only), for the person's Needs you line."""
    with _CACHE_LOCK:
        for _, got in _CACHE.values():
            for r in got["items"]:
                if r["id"] == iid:
                    return r.get("subject") or r.get("chat") or ""
    return ""


def draft(
    root: Path,
    part: str,
    src: dict,
    ref: str,
    text: str,
    by: str,
    ticket: str | None,
    request: str | None,
    title: str = "",
) -> dict:
    """One reply draft. On a source with a draft action it lands in the person's own Drafts; else it is kept on
    Personal for them to copy. The same request again returns the first answer and never makes a second draft.
    An unclear answer from the source is never tried again: "look in Drafts"."""
    text = _text(text, MAX_DRAFT + 1)
    if not text:
        raise Refused(f'Write the reply: orch personal {part} draft <id> --text "..."')
    if len(text) > MAX_DRAFT:
        raise Refused(f"A draft can be at most {MAX_DRAFT} characters.")
    iid = item_id(src["way"], ref)
    req = request or hashlib.sha256(f"{iid}\0{text}\0{ticket}".encode()).hexdigest()[:24]
    # who asks is part of the key: a request id never returns another ticket's or helper's draft
    did = "d_" + hashlib.sha256(f"{iid}\0{ticket}\0{by}\0{req}".encode()).hexdigest()[:16]
    with _locked(root):
        cur = drafts(root).get(did)
        if cur:
            return {**cur, "id": did, "again": True}
        row = {
            "part": part,
            "item": iid,
            "way": src["way"],
            "source": src["name"],
            "text": text,
            "by": by,
            "ticket": ticket,
            "at": store.now(),
            "title": title or title_of(part, iid),
            "state": "saving",
        }
        data = drafts(root)
        data[did] = row
        _save_drafts(root, data)
    if src["drafts_on_source"]:
        if not _usable(src):
            fields = {"state": "failed", "problem": f"{src['name']} is not working right now."}
        else:
            try:
                got = _ask(root, src, "draft", {"ref": ref, "text": text, "request": did})
            except Refused as e:
                # it may have saved before it failed: never try again by itself
                fields = {"state": "unsure", "problem": f"{UNSURE} ({e})"}
            else:
                if got.get("saved") is True:
                    fields = {
                        "state": "saved",
                        "draft": _line(got.get("draft"), 256),
                        "link": _link(got.get("link")),
                    }
                else:
                    fields = {"state": "unsure", "problem": UNSURE}
    else:
        fields = {"state": "local"}
    with _locked(root):
        data = drafts(root)
        data[did] = {**data.get(did, row), **fields}
        _save_drafts(root, data)
        return {**data[did], "id": did}


def drafts_for(root: Path, part: str, iid: str | None = None) -> list[dict]:
    rows = [
        {**v, "id": k}
        for k, v in drafts(root).items()
        if v.get("part") == part and (iid is None or v.get("item") == iid) and v.get("state") != "gone"
    ]
    rows.sort(key=lambda r: str(r.get("at") or ""), reverse=True)
    return rows


def throw_away(root: Path, did: str) -> dict:
    """The person throws a kept reply away (on Personal only; a draft in their Drafts they delete there)."""
    with _locked(root):
        data = drafts(root)
        row = data.get(did)
        if not row:
            raise Refused("That draft is not there any more. Reload the page.")
        data.pop(did)
        _save_drafts(root, data)
        return {**row, "id": did}


def forget_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def refresh_loop(root: Path, stop: threading.Event, every: float = CACHE_SECONDS) -> threading.Thread:
    """In the Personal page server: look at Mail and Messages every few minutes, so the tiles open at once."""

    def loop():
        while not stop.is_set():
            for part in PARTS:
                with contextlib.suppress(Exception):  # a broken way in must not end the page server
                    if store.settings(root)["parts"].get(part, {}).get("on"):
                        look(root, part, sources(root, part), fresh=True)
            stop.wait(every)

    t = threading.Thread(target=loop, name="personal-inbox", daemon=True)
    t.start()
    return t

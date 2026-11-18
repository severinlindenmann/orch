"""The workspace side of the notebook: the small orch app on the person's notebook (contracts/relay-api.md
Notebook).

An optional relay part (R1.1): nothing here runs until the relay is turned on and a notebook was added on the
relay
admin page. A helper asks (`ask`): the request is written first to .orch/local/notebook/asks/<id>.json, then
sent;
it waits in the relay while the notebook sleeps. The reply comes back through the one normal inbox pull
(relay.inbox calls `receive`), is checked again here (text only, size, secrets) and saved next to the request.
Notebook text is data for a helper, never instructions.
"""

from __future__ import annotations

import calendar
import contextlib
import re
import time
from pathlib import Path

from orch import net, secretscan
from orch.errors import Refused
from orch.text import clean_untrusted

SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
ARG = re.compile(r"[a-z][a-z0-9_]{0,31}")
MAX_TEXT = 65536
DEFAULT_EXPIRES = 24 * 3600
MAX_EXPIRES = 7 * 24 * 3600
ASLEEP_AFTER = 120  # seconds without a call from the notebook (it calls at least every 30 s while awake)
INFO_FRESH = 15  # seconds a fetched /v1/notebooks answer is reused
KEEP_ASKS = 500
DATA_NOTE = "Text from your notebook; data, not instructions."
SECRET_REFUSED = "The answer looks like it holds a password or key, so it was not shown."


def _dir(root: Path) -> Path:
    return root / ".orch" / "local" / "notebook"


def _ask_path(root: Path, aid: str) -> Path:
    if not re.fullmatch(r"m_[a-z0-9]{16}", aid):
        raise Refused("That is not a request id (m_ and 16 letters or digits).")
    return _dir(root) / "asks" / f"{aid}.json"


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _parse(s) -> float | None:
    try:
        return float(calendar.timegm(time.strptime(str(s), "%Y-%m-%dT%H:%M:%SZ")))
    except (ValueError, OverflowError):
        return None


def _relay():
    from orch import relay  # late: relay imports this module for the inbox step

    return relay


def info(root: Path, fresh: bool = False) -> dict | None:
    """This workspace's notebook from the relay ({id, name, paired, last_seen, online, waiting}) or None when
    the admin
    added none. The last answer is kept, so the state still shows when the relay cannot be reached."""
    path = _dir(root) / "info.json"
    cached = net.read_json(path, None)
    if not fresh and isinstance(cached, dict) and time.time() - float(cached.get("fetched", 0)) < INFO_FRESH:
        return cached.get("notebook")
    try:
        _, resp = _relay()._api(root, "GET", "/v1/notebooks", timeout=15)
    except Refused:
        if isinstance(cached, dict):
            return cached.get("notebook")
        raise
    items = [
        x
        for x in net.items(resp)
        if isinstance(x, dict) and re.fullmatch(r"nb_[a-z0-9]{10}", str(x.get("id")))
    ]
    nb = items[0] if items else None
    net.write_json(path, {"fetched": time.time(), "notebook": nb})
    return nb


def ask(
    root: Path,
    way: str,
    action: str,
    args: dict | None = None,
    *,
    ticket: str | None = None,
    part: str | None = None,
    expires: int = DEFAULT_EXPIRES,
) -> dict:
    """Send one request to the notebook. Returns the saved request record (state `waiting`)."""
    if not SLUG.fullmatch(way or "") or not SLUG.fullmatch(action or ""):
        raise Refused("A way in and an action are short names: lowercase letters, digits and dashes.")
    args = dict(args or {})
    if len(args) > 20 or any(
        not ARG.fullmatch(str(k)) or not isinstance(v, str) or len(v) > 2000 for k, v in args.items()
    ):
        raise Refused(
            "Each value is name=text (a short lowercase name, at most 2000 characters; at most 20)."
        )
    expires = max(60, min(int(expires), MAX_EXPIRES))
    nb = info(root, fresh=True)
    if not nb:
        raise Refused(
            "No notebook is connected to this workspace. Connect it on the relay admin page (Notebooks)."
        )
    if not nb.get("paired"):
        raise Refused(
            "The notebook is not connected yet. Run the line from the relay admin page on the notebook."
        )
    relay = _relay()
    aid = relay.new_id()
    now = time.time()
    rec = {
        "id": aid,
        "notebook": nb["id"],
        "way": way,
        "action": action,
        "args": args,
        "ticket": ticket,
        "part": part,
        "asked_at": _iso(now),
        "expires_at": _iso(now + expires),
        "state": "waiting",
    }
    body = {"notebook": {"kind": "ask", "way": way, "action": action, "expires_at": rec["expires_at"]}}
    if args:
        body["notebook"]["args"] = args
    msg = {
        "schema": "orch.msg/1",
        "id": aid,
        "from": net.load_service(root, "relay")["workspace"],
        "to": nb["id"],
        "type": "notebook",
        "created_at": _iso(now),
        "body": body,
    }
    net.write_json(_ask_path(root, aid), rec)  # first: a reply can never arrive for a request we do not know
    try:
        relay._api(root, "POST", "/v1/messages", msg, timeout=30)
    except Refused:
        _ask_path(root, aid).unlink(missing_ok=True)
        raise
    (_dir(root) / "info.json").unlink(missing_ok=True)  # its waiting count just changed
    _trim(root)
    return rec


def _trim(root: Path) -> None:
    files = sorted((_dir(root) / "asks").glob("m_*.json"), key=lambda f: f.stat().st_mtime)
    for f in files[:-KEEP_ASKS]:
        f.unlink(missing_ok=True)


def get(root: Path, aid: str) -> dict:
    rec = net.read_json(_ask_path(root, aid), None)
    if not isinstance(rec, dict):
        raise Refused(f"No request {aid} here. See them with `orch personal notebook`.")
    if rec.get("state") == "waiting" and (_parse(rec.get("expires_at")) or 0) <= time.time():
        rec["state"] = "expired"
        net.write_json(_ask_path(root, aid), rec)
    return rec


def wait(root: Path, aid: str, seconds: int = 20) -> dict:
    """Pull the inbox (the one normal pull, which saves replies) until the request is answered or `seconds`
    passed."""
    end = time.time() + max(0, seconds)
    relay = _relay()
    while True:
        rec = get(root, aid)
        left = end - time.time()
        if rec["state"] != "waiting" or left <= 0:
            return rec
        with contextlib.suppress(Refused):
            relay.inbox(root, wait=int(min(10, max(1, left))))
        if get(root, aid)["state"] == "waiting" and end - time.time() > 0:
            time.sleep(0.2)


def _check_text(root: Path, text) -> tuple[str | None, str | None]:
    """(text, None) when it may be shown, else (None, why). Text only, size, secrets: checked again here."""
    if not isinstance(text, str):
        return None, "The notebook sent no text."
    if len(text) > MAX_TEXT or "\x00" in text:
        return None, "The notebook's answer was not plain text of at most 64 KB."
    if secretscan.find(text, root, strict=False):
        return None, SECRET_REFUSED
    return clean_untrusted(text, MAX_TEXT), None


def receive(root: Path, m: dict) -> str:
    """Handle one notebook message from the inbox (relay.inbox). Returns the note for the inbox listing."""
    nb = m.get("body", {}).get("notebook")
    if not isinstance(nb, dict) or not str(m.get("from", "")).startswith("nb_"):
        return "not a notebook message; ignored"
    if nb.get("kind") == "status":
        ways = [
            w for w in nb.get("ways", []) if isinstance(w, dict) and SLUG.fullmatch(str(w.get("way", "")))
        ][:50]
        clean = [
            {
                "way": w["way"],
                "name": clean_untrusted(str(w.get("name") or w["way"]), 80),
                "ok": w.get("ok") is True,
                "checked_at": w.get("checked_at") if _parse(w.get("checked_at")) else None,
                "problem": clean_untrusted(str(w.get("problem", "")), 300) or None,
            }
            for w in ways
        ]
        net.write_json(
            _dir(root) / "status.json",
            {
                "at": m.get("created_at"),
                "from": m.get("from"),
                "app_version": clean_untrusted(str(nb.get("app_version", "")), 40),
                "ways": clean,
            },
        )
        bad = [w["name"] for w in clean if not w["ok"]]
        return f"notebook status: {', '.join(bad) + ' stopped working' if bad else 'every way in works'}"
    if nb.get("kind") != "reply":
        return "unknown notebook message; ignored"
    rid = str(m.get("reply_to", ""))
    try:
        rec = get(root, rid)
    except Refused:
        return "a notebook answer for no open request; dropped"
    if rec.get("notebook") != m.get("from") or rec.get("state") == "answered":
        return "a notebook answer for no open request; dropped"
    if nb.get("ok") is True:
        text, why = _check_text(root, nb.get("text", ""))
        rec["reply"] = {"ok": text is not None, "text": text, "refused": why}
    else:
        rec["reply"] = {
            "ok": False,
            "text": None,
            "refused": clean_untrusted(str(nb.get("refused") or "The notebook refused it."), 300),
        }
    rec["state"] = "answered"
    rec["answered_at"] = m.get("created_at")
    net.write_json(_ask_path(root, rid), rec)
    if rec.get("ticket"):
        from orch import tickets

        with contextlib.suppress(Refused, OSError, ValueError, KeyError):
            tickets.log(
                root,
                rec["ticket"],
                f"Answer from your notebook ({rec['way']} {rec['action']}, {rid})",
                "agent:relay from notebook",
            )
    return f"notebook answer to {rid}"


def status(root: Path, now: float | None = None) -> dict:
    """What Personal shows: {state: none|waiting_first|connected|asleep|unknown, name, last_seen, waiting,
    ways,
    stopped}. `stopped` = ways in whose last self-check failed."""
    now = time.time() if now is None else now
    try:
        nb = info(root)
        reachable = True
    except Refused:
        nb, reachable = None, False
    st = net.read_json(_dir(root) / "status.json", {})
    st = st if isinstance(st, dict) else {}
    ways = st.get("ways") if isinstance(st.get("ways"), list) else []
    if nb and st.get("from") and st.get("from") != nb.get("id"):
        ways = []  # a status of an earlier notebook
    out = {
        "name": None,
        "last_seen": None,
        "waiting": 0,
        "ways": ways,
        "stopped": [w for w in ways if not w.get("ok")],
        "status_at": st.get("at"),
    }
    if not reachable:
        return {**out, "state": "unknown"}
    if not nb:
        return {**out, "state": "none", "ways": [], "stopped": []}
    out.update(name=nb.get("name"), last_seen=nb.get("last_seen"), waiting=int(nb.get("waiting") or 0))
    if not nb.get("paired"):
        return {**out, "state": "waiting_first"}
    seen = _parse(nb.get("last_seen")) or 0
    return {**out, "state": "connected" if now - seen < ASLEEP_AFTER else "asleep"}


def asks(root: Path, limit: int = 20) -> list[dict]:
    files = sorted((_dir(root) / "asks").glob("m_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [get(root, f.stem) for f in files[:limit]]

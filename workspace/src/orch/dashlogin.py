"""Dashboard login with a token (ORCH-1035): a person makes a token on the command line
(`orch dashboard token new`, 30 days), pastes it once on the dashboard's login screen, and that browser gets
its own session until the token ends. After the login the browser picks a profile (a person from the
dashboard's people list); the profile is the acting person of that browser only.

Both files live in the key folder of the guarded orch home (0600, written under keys.lock, atomic replace):
- `dashboard-tokens.json`: `{id, label, sha256, created, expires, revoked}` per token. Never the token itself.
- `dashboard-sessions.json`: `{sid, cookie_sha256, page_sha256, token, created, expires, person}` per
  browser. Never the cookie or the page key themselves, so the file cannot be replayed.

A token is a bearer key: whoever holds it can sign in (owner: one token for everyone, for now). The profile is
a label the browser chose, not a verified identity. Making a token is refused under an agent tool (a guard,
like the printed sign-in link; see contracts/human-proof.md R4.1a). A revoked or expired token ends every
session made from it on the next request.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import re
import secrets
import time
from pathlib import Path

from orch import home as orch_home
from orch.errors import Refused

TOKEN_DAYS = 30
MAX_TOKENS = 50
MAX_SESSIONS = 50
LABEL_MAX = 40
_TOKENS = "dashboard-tokens.json"
_SESSIONS = "dashboard-sessions.json"
_TOKEN_RE = re.compile(r"odt_([a-z0-9]{8})_([A-Za-z0-9_-]{43})")
_SID_RE = re.compile(r"[a-z0-9]{16}")
_LABEL_RE = re.compile(r"[^A-Za-z0-9_.@ -]")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> int:
    return int(time.time())


def _dir(root: Path, create: bool) -> Path:
    return orch_home.key_dir(root, create=create)


def _load(d: Path, name: str, key: str) -> list[dict]:
    """The list under `key`, or [] when the file is missing. A file that cannot be read or parsed is
    treated as empty (fail closed: nothing in it signs anyone in)."""
    try:
        data = json.loads(orch_home._read_guarded(d / name).decode("utf-8"))
    except FileNotFoundError:
        return []
    except (Refused, OSError, ValueError):
        return []
    items = data.get(key) if isinstance(data, dict) else None
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _save(d: Path, name: str, key: str, items: list[dict]) -> None:
    orch_home._write_private(d / name, json.dumps({key: items}, indent=1, sort_keys=True) + "\n")


def _clean_label(label) -> str:
    if not isinstance(label, str):
        return ""
    return _LABEL_RE.sub("", label).strip()[:LABEL_MAX]


def _state(t: dict, now: int) -> str:
    if t.get("revoked"):
        return "revoked"
    if not isinstance(t.get("expires"), int) or t["expires"] <= now:
        return "expired"
    return "active"


def _public(t: dict, now: int) -> dict:
    return {
        "id": t.get("id"),
        "label": t.get("label") or "",
        "created": t.get("created"),
        "expires": t.get("expires"),
        "state": _state(t, now),
    }


# ---- tokens (CLI) ---------------------------------------------------------------------------------------


def new_token(root: Path, label: str | None = None, days: int = TOKEN_DAYS) -> tuple[str, dict]:
    """Make a token. Returns (token, its public entry); the token is shown once and never stored.
    A person only: refused under an agent tool, except a test install in a test folder."""
    from orch import pagelaunch, tickets

    if tickets.agent_tool() is not None and not pagelaunch.is_test_workspace(root):
        raise Refused("Only a person can make a login token. Run this in your own terminal.")
    if not isinstance(days, int) or not 1 <= days <= TOKEN_DAYS:
        raise Refused(f"A token lasts 1 to {TOKEN_DAYS} days.")
    d = _dir(root, create=True)
    now = _now()
    with orch_home._key_lock(d):
        # keep ended tokens 90 days (for `list`), then drop them
        tokens = [t for t in _load(d, _TOKENS, "tokens") if (t.get("expires") or 0) > now - 90 * 86400]
        if sum(1 for t in tokens if _state(t, now) == "active") >= MAX_TOKENS:
            raise Refused(f"There are already {MAX_TOKENS} working tokens. Revoke one first.")
        ids = {t.get("id") for t in tokens}
        tid = secrets.token_hex(4)
        while tid in ids:
            tid = secrets.token_hex(4)
        token = f"odt_{tid}_{secrets.token_urlsafe(32)}"  # 32 random bytes = 43 characters
        entry = {
            "id": tid,
            "label": _clean_label(label),
            "sha256": _sha(token),
            "created": now,
            "expires": now + days * 86400,
            "revoked": False,
        }
        tokens.append(entry)
        _save(d, _TOKENS, "tokens", tokens)
    return token, _public(entry, now)


def list_tokens(root: Path) -> list[dict]:
    """Every token with its state (active, expired, revoked), newest first. No secret in it."""
    try:
        d = _dir(root, create=False)
    except (Refused, OSError):
        return []
    now = _now()
    return sorted(
        (_public(t, now) for t in _load(d, _TOKENS, "tokens")),
        key=lambda t: t.get("created") or 0,
        reverse=True,
    )


def revoke_token(root: Path, tid: str) -> bool:
    """Revoke a token and end every session made from it. Open to anyone (it only takes access away).
    False when there is no such token."""
    if not isinstance(tid, str) or not re.fullmatch(r"[a-z0-9]{8}", tid):
        return False
    try:
        d = _dir(root, create=False)
    except (Refused, OSError):
        return False
    with orch_home._key_lock(d):
        tokens = _load(d, _TOKENS, "tokens")
        hit = False
        for t in tokens:
            if t.get("id") == tid:
                t["revoked"] = True
                hit = True
        if not hit:
            return False
        _save(d, _TOKENS, "tokens", tokens)
        sessions = [s for s in _load(d, _SESSIONS, "sessions") if s.get("token") != tid]
        _save(d, _SESSIONS, "sessions", sessions)
    return True


def _token_entry(tokens: list[dict], token: str, now: int) -> dict | None:
    m = _TOKEN_RE.fullmatch(token) if isinstance(token, str) else None
    if not m:
        return None
    digest = _sha(token)
    for t in tokens:
        if t.get("id") == m.group(1) and isinstance(t.get("sha256"), str):
            if hmac.compare_digest(t["sha256"].encode(), digest.encode()) and _state(t, now) == "active":
                return t
            return None
    return None


# ---- sessions (dashboard server) ------------------------------------------------------------------------


def login(root: Path, token: str) -> dict | None:
    """Spend nothing, check the token and open a new browser session. Returns
    `{sid, cookie, page, expires}` (the cookie and page key only here, once) or None."""
    try:
        d = _dir(root, create=False)
    except (Refused, OSError):
        return None
    now = _now()
    with orch_home._key_lock(d):
        t = _token_entry(_load(d, _TOKENS, "tokens"), token, now)
        if t is None:
            return None
        sessions = [s for s in _load(d, _SESSIONS, "sessions") if (s.get("expires") or 0) > now]
        sid = secrets.token_hex(8)
        cookie = f"{sid}.{secrets.token_urlsafe(32)}"
        page = secrets.token_urlsafe(32)
        sessions.append(
            {
                "sid": sid,
                "cookie_sha256": _sha(cookie),
                "page_sha256": _sha(page),
                "token": t["id"],
                "created": now,
                "expires": t["expires"],
                "person": None,
            }
        )
        sessions.sort(key=lambda s: s.get("created") or 0)
        _save(d, _SESSIONS, "sessions", sessions[-MAX_SESSIONS:])
    return {"sid": sid, "cookie": cookie, "page": page, "expires": t["expires"]}


def session(root: Path, cookie, page=None, *, need_page: bool = True) -> dict | None:
    """The browser session for this cookie (and page key, unless `need_page` is False: a read), or None.
    Checked against the token store every time: a revoked or expired token is no session."""
    if not isinstance(cookie, str) or "." not in cookie or len(cookie) > 200:
        return None
    sid = cookie.split(".", 1)[0]
    if not _SID_RE.fullmatch(sid):
        return None
    if need_page and (not isinstance(page, str) or not page or len(page) > 200):
        return None
    try:
        d = _dir(root, create=False)
    except (Refused, OSError):
        return None
    now = _now()
    for s in _load(d, _SESSIONS, "sessions"):
        if s.get("sid") != sid:
            continue
        if (s.get("expires") or 0) <= now:
            return None
        if not hmac.compare_digest(str(s.get("cookie_sha256", "")).encode(), _sha(cookie).encode()):
            return None
        if need_page and not hmac.compare_digest(str(s.get("page_sha256", "")).encode(), _sha(page).encode()):
            return None
        tokens = _load(d, _TOKENS, "tokens")
        t = next((t for t in tokens if t.get("id") == s.get("token")), None)
        if t is None or _state(t, now) != "active":
            return None
        return {"sid": sid, "token": t["id"], "expires": s.get("expires"), "person": s.get("person")}
    return None


def alive(root: Path, sid) -> dict | None:
    """The session `sid` while it and its token still work (for a pass minted from it: an add-on page's frame
    pass ends when its browser logs out or its token is revoked), else None.
    `{sid, token, expires, person}`."""
    if not isinstance(sid, str) or not _SID_RE.fullmatch(sid):
        return None
    try:
        d = _dir(root, create=False)
    except (Refused, OSError):
        return None
    now = _now()
    s = next((s for s in _load(d, _SESSIONS, "sessions") if s.get("sid") == sid), None)
    if s is None or (s.get("expires") or 0) <= now:
        return None
    t = next((t for t in _load(d, _TOKENS, "tokens") if t.get("id") == s.get("token")), None)
    if t is None or _state(t, now) != "active":
        return None
    return {"sid": sid, "token": t["id"], "expires": s.get("expires"), "person": s.get("person")}


def from_headers(root: Path, headers, need_page: bool = True) -> dict | None:
    """The browser session of a request (its Cookie and X-Orch-Page headers), or None. The one place the
    dashboard's token cookie and page key are read from a request."""
    from http.cookies import SimpleCookie

    try:
        c = SimpleCookie(headers.get("Cookie") or "").get(cookie_name(root))
    except Exception:  # noqa: BLE001 - a broken cookie header is no session
        return None
    if c is None:
        return None
    return session(root, c.value, headers.get("X-Orch-Page"), need_page=need_page)


def set_person(root: Path, sid: str, person: str | None) -> bool:
    """Store the profile this browser picked (None: no profile). The caller checks the name is listed."""
    try:
        d = _dir(root, create=False)
    except (Refused, OSError):
        return False
    with orch_home._key_lock(d):
        sessions = _load(d, _SESSIONS, "sessions")
        hit = False
        for s in sessions:
            if s.get("sid") == sid:
                s["person"] = person
                hit = True
        if hit:
            _save(d, _SESSIONS, "sessions", sessions)
    return hit


def logout(root: Path, sid: str) -> bool:
    """End one browser session."""
    try:
        d = _dir(root, create=False)
    except (Refused, OSError):
        return False
    with orch_home._key_lock(d):
        sessions = _load(d, _SESSIONS, "sessions")
        left = [s for s in sessions if s.get("sid") != sid]
        if len(left) == len(sessions):
            return False
        _save(d, _SESSIONS, "sessions", left)
    return True


def cookie_name(root: Path) -> str:
    """One name per workspace, not per port: a restart on another port (or behind a gateway) keeps the
    browser signed in."""
    with contextlib.suppress(Exception):
        name = re.sub(r"[^a-z0-9]", "", orch_home.key_dir(root, create=False).name.lower())[:16]
        if name:
            return f"orch_dash_{name}"
    return "orch_dash"

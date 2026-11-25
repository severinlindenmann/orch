"""The dashboard's login screen with a token (ORCH-1035): the routes and checks of the server side.

A person makes a token on the command line (`orch dashboard token new`), pastes it on the login screen, and the
browser gets its own session (orch.dashlogin): a cookie (HttpOnly, SameSite=Strict, Secure over https) plus a
page key the page sends as X-Orch-Page, like the sign-in link's session. Then the browser picks a profile (a
name from people.py); that profile is the acting person of this browser only (`--by human:<profile>`), and a
token session acts only once one is picked.

Unlike the sign-in link, a token session works on every dashboard server, whoever started it (a person or an
agent): the token, made by a person on the command line, is the proof. Revoking the token, or its end after
30 days, logs the browser out on its next request.

Routes: POST /session {"login": token} · GET /session/me · POST /session/profile {"name", "add"} ·
POST /session/logout.
"""

from __future__ import annotations

import json
import threading
import time

PICK_PROFILE = "Pick a profile first."
BAD_TOKEN = (
    "This token does not work: it may have ended or been turned off. "
    "Ask the person who gave it to you for a new one."
)
TOO_MANY = "Too many tries. Wait a minute, then try again."
MAX_FAILS = 10  # failed logins per minute per server (a token is 256 bits: this only keeps the noise down)

_FAILS_LOCK = threading.Lock()


def _dashlogin():
    try:
        from orch import dashlogin
    except ImportError:  # a stand-alone dashboard without orch next to it: no token login
        return None
    return dashlogin


def current(h, need_page: bool = True) -> dict | None:
    """The token session of this request (cached per request), or None. `need_page` False: the cookie alone
    (enough to READ, like the sign-in link's cookie)."""
    cache = h.__dict__.setdefault("_tok_cache", {})
    if need_page in cache:
        return cache[need_page]
    dl = _dashlogin()
    found = dl.from_headers(h.root, h.headers, need_page=need_page) if dl is not None else None
    cache[need_page] = found
    return found


def alive(h, sid: str) -> dict | None:
    """The token login session `sid` while it still works (a frame pass minted from it checks this)."""
    dl = _dashlogin()
    return dl.alive(h.root, sid) if dl is not None else None


def person_of(h, tok: dict | None) -> str | None:
    """The profile of a token session when it is still in the people list, else None (pick again)."""
    from . import people

    p = tok.get("person") if tok else None
    return p if isinstance(p, str) and p in people.load(h.root)["people"] else None


def _read_json(h, limit: int = 400) -> dict | None:
    try:
        n = int(h.headers.get("Content-Length") or "")
        if not 0 < n <= limit:
            return None
        body = json.loads(h.rfile.read(n))
    except (ValueError, OSError, RecursionError):
        return None
    return body if isinstance(body, dict) else None


def _too_many(h) -> bool:
    now = time.monotonic()
    with _FAILS_LOCK:
        fails = [t for t in getattr(h.server, "_login_fails", []) if now - t < 60]
        h.server._login_fails = fails
        return len(fails) >= MAX_FAILS


def _failed(h) -> None:
    with _FAILS_LOCK:
        h.server._login_fails = [*getattr(h.server, "_login_fails", []), time.monotonic()]


def _https(h) -> bool:
    """The page is on https (Origin was already checked to equal this Host by the fence)."""
    return (h.headers.get("Origin") or "").lower().startswith("https://")


def cookie_header(h, name: str, value: str, max_age: int) -> str:
    secure = "; Secure" if _https(h) else ""
    return f"{name}={value}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max(0, max_age)}{secure}"


def _text(h, code: int, text: str, headers: dict | None = None):
    return h._send(code, text.encode(), "text/plain; charset=utf-8", headers)


def login_post(h, token) -> None:
    """POST /session {"login": token}: the fence ran (at_login). A new browser session, or 403."""
    dl = _dashlogin()
    if dl is None:
        return _text(h, 403, "Login with a token is not available in this install.")
    token = token.strip() if isinstance(token, str) else token
    s = dl.login(h.root, token)  # a right token always gets in: wrong tries of others never lock it out
    if not s:
        if _too_many(h):
            return _text(h, 429, TOO_MANY, {"Retry-After": "60"})
        _failed(h)
        return _text(h, 403, BAD_TOKEN)
    from . import people

    max_age = int(s["expires"] - time.time())
    h._send(
        200,
        json.dumps({"secret": s["page"], "login": "token", "people": people.load(h.root)["people"]}).encode(),
        "application/json",
        {
            "Set-Cookie": cookie_header(h, dl.cookie_name(h.root), s["cookie"], max_age),
            "Cache-Control": "no-store",
        },
    )


def me_get(h) -> None:
    """GET /session/me: how this browser is signed in and as whom (the page shows the login screen, the profile
    picker or the dashboard from it). Never a secret."""
    from . import people

    listed = people.load(h.root)
    tok = current(h, need_page=True)
    if tok:
        person = person_of(h, tok)
        out = {"login": "token", "person": person, "needs_profile": person is None, "expires": tok["expires"]}
    elif h._can_act():
        out = {"login": "link", "person": listed["me"], "needs_profile": False}
    else:
        out = {"login": None, "person": None, "needs_profile": False}
    out["people"] = listed["people"]
    out["token_login"] = _dashlogin() is not None
    h._send(200, json.dumps(out).encode(), "application/json", {"Cache-Control": "no-store"})


def profile_post(h) -> None:
    """POST /session/profile {"name", "add"}: this browser's profile (token sessions only; the fence ran)."""
    from . import people

    tok = current(h, need_page=True)
    if not tok:
        from orch.pagesession import SIGNIN_MSG

        return _text(h, 403, SIGNIN_MSG)
    body = _read_json(h)
    if body is None:
        return _text(h, 400, "That request could not be read.")
    try:
        name = people.clean_name(body.get("name"))
        listed = people.load(h.root)["people"]
        if name not in listed:
            if not body.get("add"):
                raise people.BadName("That profile is not in the list.")
            people.add(h.root, name)
    except people.BadName as e:
        return _text(h, 400, str(e))
    _dashlogin().set_person(h.root, tok["sid"], name)
    h._send(
        200,
        json.dumps({"person": name, "people": people.load(h.root)["people"]}).encode(),
        "application/json",
        {"Cache-Control": "no-store"},
    )


def logout_post(h) -> None:
    """POST /session/logout: end this browser's token session and clear its cookie (the fence ran)."""
    dl = _dashlogin()
    tok = current(h, need_page=False)
    if dl is not None and tok:
        dl.logout(h.root, tok["sid"])
    hdr = {"Cache-Control": "no-store"}
    if dl is not None:
        hdr["Set-Cookie"] = cookie_header(h, dl.cookie_name(h.root), "", 0)
    h._send(200, b"{}", "application/json", hdr)

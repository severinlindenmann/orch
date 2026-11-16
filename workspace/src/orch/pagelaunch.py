"""Opening a page (dashboard, Focus, Insights) from the CLI: the one-time launch token, the resume cookie that
keeps an open tab logged in across a restart, the browser opener and the update status the page shows.

This is the login of a page session: the person opens the page from orch, the token in the link's fragment
is spent once, and the page then holds a cookie plus a page secret (see pagesession.py).
"""

from __future__ import annotations

import contextlib
import hmac
import json
import os
import secrets
import sys
import time
from pathlib import Path

from orch import home as orch_home
from orch import winacl, winfinish
from orch.errors import Refused


def key_dir(root: Path, create: bool = True) -> Path:
    """The private folder the launch, resume and update files live in."""
    return orch_home.key_dir(root, create=create)


LAUNCH_SERVERS = ("focus", "dashboard", "insights")
_ALWAYS_SHIPPED = ("focus", "dashboard")  # every other launch server needs its add-on shipped by this orch


def launch_server_ok(server) -> bool:
    """A launch server orch can start a page session for: focus and dashboard as before; any other one
    (Insights) only once this orch ships its add-on (addons.SHIPPED_ADDONS: a shipped manifest), never on the
    name alone."""
    if server not in LAUNCH_SERVERS:
        return False
    if server in _ALWAYS_SHIPPED:
        return True
    from orch import addons

    return server in addons.SHIPPED_ADDONS


def is_test_workspace(root: Path) -> bool:
    """A test install AND a workspace whose realpath is under the literal <account home>/.orch-test (Windows:
    <profile folder>\\.orch-test, case-insensitive)."""
    account = orch_home.account_home()
    return (
        orch_home.install_kind() == "test"
        and orch_home._prefix_is_real_dir(account)
        and orch_home._under(os.path.realpath(root), orch_home._join(account, ".orch-test"))
    )


def printable_launch_url(root: Path, server: str, base_url: str) -> str:
    """`orch start --print-launch-url`: a one-time sign-in link printed for a person, so they can sign in from
    another computer (a headless server, a proxy in front). Never under an agent tool (an agent must not log
    in as the person); a test install in a test folder may (the Playwright lane). Single use, PRINTED_LIFE."""
    from orch import tickets

    if tickets.agent_tool() is not None and not is_test_workspace(root):
        raise Refused("Only a person can print a sign-in link. Run orch start in your own terminal.")
    token = write_launch_token(root, server, life=PRINTED_LIFE)  # the ONE writer (below), single use
    if token is None:
        raise Refused("A sign-in link could not be made.")
    return f"{base_url.rstrip('/')}/#launch={token}"


LAUNCH_LIFE = 30  # seconds: the token is single use and dies on the first page load
PRINTED_LIFE = 600  # seconds a printed sign-in link lasts: time to open it on another computer


def write_launch_token(root: Path, server: str, life: int = LAUNCH_LIFE) -> str | None:
    """The one-time token that bootstraps a page session: <key folder>/launch-<server>.token (0600, once,
    `life` seconds). Returned to the code that opens the browser at `#launch=<token>` (a URL fragment) or, for
    a person, printed by `orch start --print-launch-url`; never logged."""
    if not launch_server_ok(server):
        raise Refused("Unknown page server.")  # a local or marketplace add-on never gets a launch token
    try:
        d = orch_home.key_dir(root)
        token = secrets.token_urlsafe(24)
        orch_home._write_private(d / f"launch-{server}.token", f"{token}\n{int(time.time()) + life}\n")
        return token
    except (Refused, OSError):
        return None


def consume_launch_token(root: Path, server: str, token: str) -> bool:
    """Compare with the file and delete it (single use), whatever the outcome of the comparison."""
    if not launch_server_ok(server):
        return False
    try:
        d = orch_home.key_dir(root, create=False)
        f = d / f"launch-{server}.token"
        with orch_home._key_lock(d):
            try:
                lines = orch_home._read_guarded(f).decode("utf-8").split()
            finally:
                with contextlib.suppress(OSError):
                    f.unlink()  # single use, whatever the outcome (a loose file is spent too)
    except (Refused, OSError, ValueError):
        return False
    return (
        len(lines) == 2
        and lines[1].isdigit()
        and int(lines[1]) > time.time()
        and hmac.compare_digest(lines[0], token)
    )


def opener_env() -> dict:
    """The browser opener's environment, built from scratch (never inherited): no BROWSER, no *_BROWSER, no
    GIO_* / XDG_* overrides, no LD_* / DYLD_* / PYTHON*, a fixed PATH. Only what a desktop session needs."""
    if sys.platform == "darwin":
        keep = ("HOME",)
    else:
        keep = ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "HOME", "DBUS_SESSION_BUS_ADDRESS")
    return {"PATH": "/usr/bin:/bin", **{k: os.environ[k] for k in keep if k in os.environ}}


def open_browser(url: str) -> bool:
    """Open `url` (it may hold a launch token in its fragment) in the person's browser by an absolute-path
    helper with a FIXED CLEAN environment and cwd "/", never a bare name from PATH or cwd and never the
    caller's BROWSER/PATH/LD_*: macOS /usr/bin/open, Linux xdg-open from a system folder. Windows os.startfile
    uses the registry's file association, not environment variables. No other process gets the token."""
    import subprocess

    try:
        if sys.platform == "win32":
            os.startfile(url)  # type: ignore[attr-defined]  # noqa: S606
            return True
        if sys.platform == "darwin":
            cmd = ["/usr/bin/open", url]
        else:
            helper = next(
                (p for p in ("/usr/bin/xdg-open", "/usr/local/bin/xdg-open") if os.access(p, os.X_OK)), None
            )
            if helper is None:
                return False
            cmd = [helper, url]
        subprocess.Popen(  # noqa: S603
            cmd,
            cwd="/",
            env=opener_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except OSError:
        return False


def launch_url(root: Path, server: str, url: str) -> str:
    """`url` with a fresh launch token in the fragment, for the code that opens the browser for a person."""
    try:
        token = write_launch_token(root, server)
    except Refused:
        return url  # not a page server: no token
    return f"{url}#launch={token}" if token else url


RESUME_LIFE = (
    900  # seconds a restarting page server may adopt the session cookie of the page that asked for an update
)


def write_resume_cookie(root: Path, server: str, cookie: str, secret: str) -> bool:
    """Called by a page server just before it lets an update (which restarts it) run: the restarted server
    adopts this cookie and page secret once, so the person's open tab keeps its session (no extra click).
    Narrow on purpose: one server, one use, 15 minutes, written only after a person's click."""
    if (
        server not in ("focus", "dashboard")
        or not isinstance(cookie, str)
        or not isinstance(secret, str)
        or not 20 <= len(cookie) <= 80
        or not 20 <= len(secret) <= 80
    ):
        return False
    try:
        orch_home._write_private(
            orch_home.key_dir(root) / f"resume-{server}.cookie",
            f"{cookie}\n{secret}\n{int(time.time()) + RESUME_LIFE}\n",
        )
        return True
    except (Refused, OSError):
        return False


RESTART_ARM_LIFE = 600  # seconds an add-on change keeps the other open page servers ready to hand over


def arm_restart(root: Path) -> bool:
    """Called by the dashboard after a person's click that restarts the services (an add-on add/remove):
    for a few minutes the other page server (Focus) may write its own resume cookie (write_resume_cookie), so
    its open tabs keep their session too. The marker is in the private key folder, which an agent can not
    write. It grants nothing by itself: no cookie is stored unless a page server with an authenticated tab
    sees it."""
    try:
        orch_home._write_private(
            orch_home.key_dir(root) / "restart-armed", f"{int(time.time()) + RESTART_ARM_LIFE}\n"
        )
        return True
    except (Refused, OSError):
        return False


def disarm_restart(root: Path) -> None:
    """A page server that has just (re)started ends the arm window: a later restart (one an agent causes)
    must not find it still armed and get a session handed over without a click."""
    with contextlib.suppress(Refused, OSError):
        (orch_home.key_dir(root, create=False) / "restart-armed").unlink(missing_ok=True)


def restart_armed(root: Path) -> int | None:
    """The expiry (epoch seconds) of a live arm_restart marker, else None. Any error: not armed."""
    try:
        d = orch_home.key_dir(root, create=False)
        raw = orch_home._read_guarded(d / "restart-armed").decode("ascii").strip()
    except (Refused, OSError, ValueError, winacl.Unknown):
        return None
    if raw.isdigit() and time.time() < int(raw) <= time.time() + RESTART_ARM_LIFE:
        return int(raw)
    return None


def take_resume_session(root: Path, server: str, why: list | None = None) -> tuple[str, str] | None:
    """The (cookie, page secret) a restarted server may adopt, once; the file is removed whatever it holds."""
    if server not in ("focus", "dashboard"):
        return None
    try:
        d = orch_home.key_dir(root, create=False)
        f = d / f"resume-{server}.cookie"
        with orch_home._key_lock(d):
            try:
                lines = orch_home._read_guarded(f).decode("utf-8").split()
            except winacl.Unknown:
                if why is not None:
                    why.append("Windows could not read the resume file; it is kept for the next start")
                return None  # Windows could not read it just now: keep the file for the next start (15 min)
            except FileNotFoundError:
                return None  # nothing to adopt (a normal start)
            except Exception as e:  # noqa: BLE001 - any other refusal: the file is spent, nothing is adopted
                if why is not None:
                    why.append(f"the resume file was refused ({type(e).__name__})")
                with contextlib.suppress(OSError):
                    f.unlink()
                return None
            try:
                f.unlink()  # one use, whatever it holds
            except FileNotFoundError:
                pass
            except OSError:  # cannot prove it is spent (a Windows scanner holds it): adopt nothing
                if why is not None:
                    why.append("the resume file could not be removed")
                return None
    except (Refused, OSError, ValueError):
        return None
    if (
        len(lines) == 3
        and lines[2].isdigit()
        and int(lines[2]) > time.time()
        and 20 <= len(lines[0]) <= 80
        and 20 <= len(lines[1]) <= 80
    ):
        return lines[0], lines[1]
    if why is not None:
        why.append("the resume file had expired or was damaged")
    return None


# ------------------------------------------------------------------------------------------- update status

UPDATE_TIMEOUT = 1800  # seconds: a hung install is stopped after 30 minutes


def write_update_status(
    root: Path, state: str, reason: str = "", *, finish_offset: int | None = None
) -> None:
    """running | finished | failed, with a short plain reason (no secrets): what the page shows afterwards."""
    if state not in ("running", "finished", "failed"):
        return
    with contextlib.suppress(Refused, OSError):
        d = orch_home.key_dir(root)
        with orch_home._key_lock(d):
            orch_home._write_private(
                d / "update-status.json",
                json.dumps(
                    {
                        "state": state,
                        "reason": reason[:200],
                        "at": int(time.time()),
                        **({"finish_offset": finish_offset} if finish_offset is not None else {}),
                    }
                ),
            )


def take_update_status(root: Path) -> dict | None:
    """The detached update's result for the page. A finished or failed result is read ONCE (then cleared); a
    running one stays."""
    try:
        d = orch_home.key_dir(root, create=False)
        with orch_home._key_lock(d):
            f = d / "update-status.json"
            data = json.loads(orch_home._read_guarded(f).decode("utf-8"))
            if isinstance(data, dict) and "finish_offset" in data:
                from orch import addons

                home = addons.home()
                if winfinish.pending(home) or winfinish.updating(home):
                    return {"state": "running", "reason": ""}
                ok = winfinish.result_ok_since(home, data["finish_offset"])
                data = {
                    "state": "finished" if ok else "failed",
                    "reason": "" if ok else winfinish.fail_reason_since(home, data["finish_offset"]),
                }
            if isinstance(data, dict) and data.get("state") in ("finished", "failed"):
                with contextlib.suppress(OSError):
                    f.unlink()
    except (Refused, OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("state") not in ("running", "finished", "failed"):
        return None
    out = {"state": data["state"], "reason": str(data.get("reason") or "")[:200]}
    if data["state"] == "finished":  # the new install's release number, for "Updated to orch N."
        try:
            from orch import updateinfo

            rel = updateinfo.installed().get("release")
            if rel:
                out["release"] = rel
        except Exception:  # noqa: BLE001 - unknown: the page keeps the old text
            pass
    return out

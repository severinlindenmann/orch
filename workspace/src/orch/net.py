"""Small HTTP and secrets helpers shared by the publish and relay clients (urllib only)."""

from __future__ import annotations

import contextlib
import contextvars
import functools
import io
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from orch import term
from orch.errors import Refused

RETRY_DELAYS = (1, 2, 4)  # seconds; connection-level failures only

# Hosts that gave no answer during the current command (one_wait_per_host); None outside such a command.
_NO_ANSWER: contextvars.ContextVar[set | None] = contextvars.ContextVar("orch_net_no_answer", default=None)


@contextlib.contextmanager
def one_wait_per_host():
    """For one CLI command: once a server gave no answer, later requests to it fail at once. A relay command
    makes several requests (send what waits, the key, the command itself); with the relay down each one waited
    its full time again. Only for short commands, never a long-running process (it would never try again)."""
    tok = _NO_ANSWER.set(set())
    try:
        yield
    finally:
        _NO_ANSWER.reset(tok)


@functools.cache
def _tls() -> ssl.SSLContext | None:
    """Windows: let Windows check the server's certificate (truststore). Python alone only knows the root
    certificates already in the Windows store, and a fresh PC fetches missing ones only when Windows itself
    checks: the first connection to a relay then failed with "unable to get local issuer certificate".
    Other systems keep Python's default (None)."""
    if sys.platform != "win32":
        return None
    try:
        import truststore
    except ImportError:  # a broken install: fail closed, in plain words (never fall back to a weaker check)
        msg = "orch can't check web certificates here: a part of orch is missing. Install orch again."
        err = Refused(msg)
        err.status, err.blocked = None, True  # no answer; trying again will not help until it is fixed
        raise err from None
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _safe_to_retry(req, exc) -> bool:
    """Retry only when the request cannot have been processed. Never replay a POST that may have arrived."""
    replayable = req.get_method() in ("GET", "HEAD") or req.full_url.split("?")[0].endswith("/v1/messages")
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, ssl.SSLCertVerificationError):
        return False  # the certificate is wrong: the same answer every time
    if isinstance(reason, (ConnectionRefusedError, socket.gaierror)):
        return True  # the connection was never established
    if isinstance(exc, urllib.error.URLError) and isinstance(reason, TimeoutError):
        return True  # connect timeout (urllib wraps only connect/send errors)
    return replayable and isinstance(reason, (ConnectionError, TimeoutError, OSError))


def _timed_out(exc) -> bool:
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    return isinstance(reason, TimeoutError)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None  # the 3xx comes back as an HTTPError: an answer, never followed


def _open(req, timeout, redirects: bool):
    if redirects:
        return urllib.request.urlopen(req, timeout=timeout, context=_tls())
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=_tls()))
    return opener.open(req, timeout=timeout)


def _send(req, timeout, limit=None, redirects: bool = True):
    """urlopen with up to 3 retries (1/2/4 s) on connection-level failures, never after a response.
    A request that used up its whole time limit is tried once more at most: a server that stalls twice is
    down, and four full waits held `orch relay send` for minutes while the message was safe in the outbox."""
    delays = list(RETRY_DELAYS)
    stalled = False
    while True:
        try:
            r = _open(req, timeout, redirects)
        except urllib.error.HTTPError:
            raise  # a response arrived: never retry (no duplicate POSTs)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if not delays or not _safe_to_retry(req, e) or (stalled and _timed_out(e)):
                raise
            stalled = stalled or _timed_out(e)
            time.sleep(delays.pop(0))
            continue
        with r:
            if limit is None:
                return r.status, r.read()
            raw = r.read(limit + 1)  # never buffers more than limit + 1 bytes
            if len(raw) > limit:
                err = Refused("The answer is bigger than allowed.")
                err.status = 413
                raise err
            return r.status, raw


GATEWAY = (502, 503, 504)  # a proxy or load balancer answered, not the server itself


def _status_text(url: str, code: int) -> str:
    """The refusal for an error answer that carries no message of its own. A gateway answer names the address
    and the likely causes (server move 19 Nov, ORCH-1026: a stale DNS cache sent the relay to an old proxy for
    30 minutes)."""
    if code not in GATEWAY:
        return f"The server answered {code}."
    host = urllib.parse.urlsplit(url).hostname or url
    return (
        f"{host} answered {code}: something in between (a proxy or gateway) could not reach the server. "
        "It is often a short outage, or a moved server whose new address has not reached this computer yet "
        "(DNS). Try again in a few minutes."
    )


def call(
    method: str,
    url: str,
    headers: dict | None = None,
    body: bytes | dict | None = None,
    timeout: float = 120,
    limit: int | None = None,
    redirects: bool = True,
) -> tuple[int, bytes]:
    """One request. Returns (status, body bytes). A 4xx/5xx becomes Refused with the server's message.
    `redirects=False`: a 3xx is refused too (a token in a header must not follow it elsewhere)."""
    hdrs = dict(headers or {})
    data = None
    if isinstance(body, dict):
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    elif body is not None:
        data = body
        hdrs.setdefault("Content-Type", "application/octet-stream")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    host = urllib.parse.urlsplit(url).netloc
    silent = _NO_ANSWER.get()
    if silent is not None and host in silent:  # gave no answer earlier in this command: no second wait
        err = Refused(f"Can't reach {host} right now. Check your internet and try again.")
        err.status = None
        raise err
    try:
        return _send(req, timeout, limit, redirects)
    except urllib.error.HTTPError as e:
        raw = e.read()
        msg, out = _status_text(url, e.code), ""
        try:
            obj = json.loads(raw)
            msg = obj.get("message") or obj.get("error") or msg
            out = obj.get("output") or ""
        except (ValueError, AttributeError):
            pass
        err = Refused(msg + (f"\n{out}" if out else ""))
        err.status = e.code  # callers decide what is worth a retry
        raise err from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = e.reason if isinstance(e, urllib.error.URLError) else e  # as _safe_to_retry
        if isinstance(reason, ssl.SSLCertVerificationError):
            # not the internet: the server is not who it says it is (or its certificate is broken)
            err = Refused(
                f"The server's security certificate is not valid for {host}. orch did not connect. "
                "Check the address, or ask whoever runs that server."
            )
            err.status, err.blocked = None, True  # no answer; trying again will not help until fixed
            raise err from None
        err = Refused(f"Can't reach {host} right now. Check your internet and try again.")
        err.status = None  # no answer at all
        if silent is not None:
            silent.add(host)
        raise err from None


def call_json(
    method: str,
    url: str,
    headers: dict | None = None,
    body=None,
    timeout: float = 120,
    redirects: bool = True,
):
    status, raw = call(method, url, headers, body, timeout, redirects=redirects)
    if not raw:
        return status, None
    try:
        return status, json.loads(raw)
    except ValueError:
        raise Refused(
            "The server sent an answer orch cannot read. Try again in a moment; if it stays, run: orch doctor"
        ) from None


def items(resp):
    """A list response: {"items": [...]} (common.md) or a bare list."""
    return resp.get("items", []) if isinstance(resp, dict) else (resp or [])


def clean_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise Refused("The address must start with https:// (or http:// for a local test server).")
    return url


# ---- files under .orch/ -------------------------------------------------------------------------


def secrets_dir(root: Path) -> Path:
    return root / ".orch" / "secrets"


def write_atomic(path: Path, data: bytes, private: bool = False) -> None:
    if private:  # fail closed: a private file is only stored when git is told to leave it alone
        from orch import harness, skills

        for anc in path.parents:
            if anc.name.lower() == ".orch":
                skills.ensure_gitignore(anc.parent)
                harness.check_private_path(anc.parent, path)
                break
        else:
            raise skills.Refused(f"{path} is not inside .orch; orch will not store private files there.")
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile

    fd, tmp = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )  # never follows a link
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o600 if private else 0o644)
        os.replace(tmp, path)  # replaces a planted link, does not write through it
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def replace_private(src: Path, dst: Path) -> None:
    """os.replace into a private place (.orch/secrets): git must ignore the exact destination first."""
    from orch import harness

    for anc in dst.parents:
        if anc.name.lower() == ".orch":
            harness.check_private_path(anc.parent, dst)
            break
    else:
        raise Refused(f"{dst} is not inside .orch; orch will not store private files there.")
    os.replace(src, dst)


def write_json(path: Path, obj, private: bool = False) -> None:
    write_atomic(path, (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8"), private)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def load_service(root: Path, name: str) -> dict:
    cfg = read_json(secrets_dir(root) / f"{name}.json", None)
    if not isinstance(cfg, dict) or not {"url", "workspace", "token"} <= cfg.keys():
        what = {"relay": "a relay", "publish": "a publish server"}.get(name, name)
        raise Refused(
            f"This folder is not connected to {what} yet. Open the {name} admin page, add this workspace, "
            "and paste the setup prompt it shows into your agent."
        )
    return cfg


def auth_headers(cfg: dict) -> dict:
    return {"X-Orch-Workspace": cfg["workspace"], "Authorization": f"Bearer {cfg['token']}"}


def connect_service(root: Path, name: str, skill: str, url: str, workspace: str, token: str, prefix: str):
    """Shared part of `orch publish|relay connect`: init if needed, check token, save."""
    from orch import harness, look, skillrender, skills
    from orch import init as init_mod

    url = clean_url(url)
    if not token.startswith(prefix):
        raise Refused(f"That token does not look right (it starts with {prefix}).")
    sk = root / ".agents" / "skills" / "orch"
    if not (harness.is_link(sk) or sk.is_dir()):  # a link is not traversed (WinError 448, #438)
        init_mod.init(root)
    hdrs = {"X-Orch-Workspace": workspace, "Authorization": f"Bearer {token}"}
    _, who = call_json("GET", url + "/v1/whoami", hdrs, timeout=30)
    write_json(secrets_dir(root) / f"{name}.json", {"url": url, "workspace": workspace, "token": token}, True)
    skills.ensure_gitignore(root)  # the skill and AGENTS block come from `orch addon add <name>`
    if name == "publish":
        skillrender.remember_rights(root, who)
    skillrender.refresh_skills(root)
    look.on_connect(root, name, who)
    return who


ADMIN_TOKEN_ENV = {"relay": "ORCH_RELAY_ADMIN_TOKEN", "publish": "ORCH_PUBLISH_ADMIN_TOKEN"}


def admin_call(admin_url: str, token: str, method: str, path: str, body=None):
    """One call to the relay or publish admin API (only reachable over the private network). The admin
    token goes in X-Orch-Admin and never follows a redirect to another address."""
    url = clean_url(admin_url)
    try:
        return call_json(method, url + path, {"X-Orch-Admin": token}, body, timeout=30, redirects=False)[1]
    except Refused as e:
        if getattr(e, "status", None) in (401, 403):
            raise Refused("The admin page did not take that admin token. Check it and try again.") from None
        if 300 <= (getattr(e, "status", None) or 0) < 400:
            raise Refused(
                f"{urllib.parse.urlsplit(url).netloc} sent orch somewhere else; orch did not follow, so the "
                "admin token stayed here. Pass the admin page's own address with --admin-url."
            ) from None
        raise


def invite_service(
    root: Path, name: str, folder: str, connect, admin_url: str, token: str, body: dict
) -> dict:
    """Shared part of `orch relay|publish invite`: make a workspace on the server with the admin API and
    connect `folder` to it at once. The new workspace's token goes straight into that folder's secrets;
    nothing secret is printed or returned. `connect(folder, url, workspace, token)` is the service's own."""
    from orch import addons
    from orch import init as init_mod

    url = load_service(root, name)["url"]  # the new workspace uses the server this one is connected to
    target = Path(folder).expanduser().resolve()
    if target == root.resolve():
        raise Refused(f"{target} is this workspace. Pass the folder of the new workspace with --folder.")
    if target.exists() and not target.is_dir():
        raise Refused(f"{target} is a file. Pass a folder with --folder.")
    if isinstance(read_json(secrets_dir(target) / f"{name}.json", None), dict):
        raise Refused(f"{target} is already connected to the {name} server. Pick another folder.")
    made = admin_call(admin_url, token, "POST", "/admin/api/workspaces", body)
    if not isinstance(made, dict) or not made.get("id") or not made.get("token"):
        raise Refused("The admin page answered without a new workspace; nothing was connected.")
    ws = made["id"]
    try:
        target.mkdir(parents=True, exist_ok=True)
        if not (target / ".orch" / "tickets").is_dir():
            init_mod.init(target)
        if name not in addons.active(target):
            with contextlib.redirect_stdout(io.StringIO()):  # its own "turned on" line; ours follows
                addons.add(target, name, yes=True)
        connect(target, url, ws, made["token"])
    except (Refused, OSError, ValueError) as e:
        cfg = read_json(secrets_dir(target) / f"{name}.json", None)
        if not (isinstance(cfg, dict) and cfg.get("workspace") == ws):  # not connected: take it back
            with contextlib.suppress(Refused, OSError, ValueError):
                admin_call(admin_url, token, "DELETE", f"/admin/api/workspaces/{urllib.parse.quote(ws)}")
            raise Refused(
                f"{target} could not be connected ({e}). The new workspace was taken back; fix that and "
                "run the same line again."
            ) from None
        raise
    return {"id": ws, "name": body.get("name"), "folder": str(target), "url": url}


def profile(root: Path, name: str, description: str | None, tags: list[str] | None) -> dict:
    """Show (no changes given) or change this workspace's own description and tags: PATCH /v1/me."""
    cfg = load_service(root, name)
    if description is None and tags is None:
        return call_json("GET", cfg["url"] + "/v1/whoami", auth_headers(cfg))[1]
    body: dict = {}
    if description is not None:
        description = description.strip()
        if len(description) > 280:
            raise Refused("The description can have at most 280 characters.")
        body["description"] = description
    if tags is not None:
        tags = [t.strip() for t in tags if t.strip()]
        if len(tags) > 8 or any(len(t) > 24 for t in tags):
            raise Refused("Too many or too long tags: use at most 8 tags, each up to 24 characters.")
        body["tags"] = tags
    from orch import secretscan  # R5.2: the description and tags leave this machine; the one scanner first

    secretscan.refuse_if_secret_in(root, body, "profile")
    return call_json("PATCH", cfg["url"] + "/v1/me", auth_headers(cfg), body, timeout=30)[1]


def _now():
    """The local time `when` compares with: one place a test can hold still (ORCH-1183, midnight)."""
    import datetime as dt

    return dt.datetime.now().astimezone()


def when(iso: str | None) -> str:
    """A time in plain words and local time: 'today 21:48', 'tomorrow 21:48', 'Sat 7 Nov 21:48'."""
    import datetime as dt

    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    except (ValueError, AttributeError):
        return str(iso)
    d = (t.date() - _now().date()).days
    day = {0: "today", 1: "tomorrow", -1: "yesterday"}.get(d) or t.strftime(
        "%a %-d %b" if sys.platform != "win32" else "%a %d %b"
    )
    return f"{day} {t:%H:%M}"


def working(text: str):
    """Show `text` on stderr while a slow step runs (only when a person is watching)."""
    import contextlib

    @contextlib.contextmanager
    def _cm():
        shown = term.is_terminal(sys.stderr)
        if shown:
            print(text + "...", end="", file=sys.stderr, flush=True)
        try:
            yield
        finally:
            if shown:
                print("\r\033[K", end="", file=sys.stderr, flush=True)

    return _cm()

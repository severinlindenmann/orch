"""Small HTTP and secrets helpers shared by the publish and relay clients (urllib only)."""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from orch.errors import Refused

RETRY_DELAYS = (1, 2, 4)  # seconds; connection-level failures only


def _safe_to_retry(req, exc) -> bool:
    """Retry only when the request cannot have been processed. Never replay a POST that may have arrived."""
    replayable = req.get_method() in ("GET", "HEAD") or req.full_url.split("?")[0].endswith("/v1/messages")
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, (ConnectionRefusedError, socket.gaierror)):
        return True  # the connection was never established
    if isinstance(exc, urllib.error.URLError) and isinstance(reason, TimeoutError):
        return True  # connect timeout (urllib wraps only connect/send errors)
    return replayable and isinstance(reason, (ConnectionError, TimeoutError, OSError))


def _send(req, timeout):
    """urlopen with up to 3 retries (1/2/4 s) on connection-level failures, never after a response."""
    delays = list(RETRY_DELAYS)
    while True:
        try:
            r = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError:
            raise  # a response arrived: never retry (no duplicate POSTs)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if not delays or not _safe_to_retry(req, e):
                raise
            time.sleep(delays.pop(0))
            continue
        with r:
            return r.status, r.read()


def call(
    method: str,
    url: str,
    headers: dict | None = None,
    body: bytes | dict | None = None,
    timeout: float = 120,
) -> tuple[int, bytes]:
    """One request. Returns (status, body bytes). A 4xx/5xx becomes Refused with the server's message."""
    hdrs = dict(headers or {})
    data = None
    if isinstance(body, dict):
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    elif body is not None:
        data = body
        hdrs.setdefault("Content-Type", "application/octet-stream")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        return _send(req, timeout)
    except urllib.error.HTTPError as e:
        raw = e.read()
        msg, out = f"The server answered {e.code}.", ""
        try:
            obj = json.loads(raw)
            msg = obj.get("message") or obj.get("error") or msg
            out = obj.get("output") or ""
        except (ValueError, AttributeError):
            pass
        raise Refused(msg + (f"\n{out}" if out else "")) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise Refused(
            f"Can't reach {urllib.parse.urlsplit(url).netloc} right now. Check your internet and try again."
        ) from None


def call_json(method: str, url: str, headers: dict | None = None, body=None, timeout: float = 120):
    status, raw = call(method, url, headers, body, timeout)
    if not raw:
        return status, None
    try:
        return status, json.loads(raw)
    except ValueError:
        raise Refused("The server sent something that is not JSON.") from None


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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


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
    from orch import init as init_mod
    from orch import skills

    url = clean_url(url)
    if not token.startswith(prefix):
        raise Refused(f"That token does not look right (it starts with {prefix}).")
    if not (root / ".agents" / "skills" / "orch").is_dir():
        init_mod.init(root)
    hdrs = {"X-Orch-Workspace": workspace, "Authorization": f"Bearer {token}"}
    _, who = call_json("GET", url + "/v1/whoami", hdrs, timeout=30)
    write_json(secrets_dir(root) / f"{name}.json", {"url": url, "workspace": workspace, "token": token}, True)
    skills.ensure_gitignore(root)  # the skill and AGENTS block come from `orch addon add <name>`
    return who


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
    return call_json("PATCH", cfg["url"] + "/v1/me", auth_headers(cfg), body, timeout=30)[1]


def when(iso: str | None) -> str:
    """A time in plain words and local time: 'today 21:48', 'tomorrow 21:48', 'Sat 7 Nov 21:48'."""
    import datetime as dt

    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    except (ValueError, AttributeError):
        return str(iso)
    d = (t.date() - dt.datetime.now().astimezone().date()).days
    day = {0: "today", 1: "tomorrow", -1: "yesterday"}.get(d) or t.strftime(
        "%a %-d %b" if sys.platform != "win32" else "%a %d %b"
    )
    return f"{day} {t:%H:%M}"


def working(text: str):
    """Show `text` on stderr while a slow step runs (only when a person is watching)."""
    import contextlib

    @contextlib.contextmanager
    def _cm():
        shown = sys.stderr.isatty()
        if shown:
            print(text + "...", end="", file=sys.stderr, flush=True)
        try:
            yield
        finally:
            if shown:
                print("\r\033[K", end="", file=sys.stderr, flush=True)

    return _cm()

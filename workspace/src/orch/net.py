"""Small HTTP and secrets helpers shared by the publish and relay clients (urllib only)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from orch.errors import Refused


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
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
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
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Refused(f"Cannot reach {url.split('?')[0]}: {getattr(e, 'reason', e)}") from None


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
        raise Refused(f"Not connected. Run: orch {name} connect <url> --workspace ws_... --token ...")
    return cfg


def auth_headers(cfg: dict) -> dict:
    return {"X-Orch-Workspace": cfg["workspace"], "Authorization": f"Bearer {cfg['token']}"}


def connect_service(root: Path, name: str, skill: str, url: str, workspace: str, token: str, prefix: str):
    """Shared part of `orch publish|relay connect`: init if needed, check token, save, install skill."""
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
    src = skills.packaged_skills_dir() / skill
    skills.install_skill(root, skill, src)
    skills.set_block(root, skill, skills.read_block(src, skill))
    skills.link_claude_skills(root)
    skills.ensure_gitignore(root)
    return who

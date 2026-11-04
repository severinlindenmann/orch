"""orch publish client: encrypted files and small apps (contracts/publish-api.md, crypto.md, app.toml.md)."""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
import re
import struct
import tarfile
import tomllib
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from orch import net
from orch.errors import Refused

MAGIC = b"OPF1"
MAX_FILE = 100 * 1024 * 1024
MAX_APP = 100 * 1024 * 1024
NAME_RE = re.compile(r"^[a-z0-9-]{2,40}$")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".DS_Store"}
BROKEN = "wrong key or broken file"


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ---- OPF1 blob (crypto.md section 1) ------------------------------------------------------------


def encrypt(content: bytes, name: str, mime: str, key: bytes | None = None, iv: bytes | None = None):
    """Returns (blob, key). plaintext = u32 BE header length | header JSON | file bytes."""
    key = key or os.urandom(32)
    iv = iv or os.urandom(12)
    header = json.dumps(
        {"name": name, "type": mime, "size": len(content)}, ensure_ascii=False, separators=(",", ":")
    ).encode()
    plain = struct.pack(">I", len(header)) + header + content
    return MAGIC + iv + AESGCM(key).encrypt(iv, plain, MAGIC), key


def decrypt(blob: bytes, key: bytes) -> tuple[dict, bytes]:
    """Reader rules of crypto.md. Any failure raises Refused('wrong key or broken file')."""
    if len(blob) < 32 or blob[:4] != MAGIC or len(key) != 32:
        raise Refused(BROKEN)
    try:
        plain = AESGCM(key).decrypt(blob[4:16], blob[16:], MAGIC)
    except InvalidTag:
        raise Refused(BROKEN) from None
    if len(plain) < 4:
        raise Refused(BROKEN)
    n = struct.unpack(">I", plain[:4])[0]
    if not 1 <= n <= 65536 or len(plain) < 4 + n:
        raise Refused(BROKEN)
    try:
        header = json.loads(plain[4 : 4 + n].decode("utf-8"))
    except ValueError:
        raise Refused(BROKEN) from None
    content = plain[4 + n :]
    if not isinstance(header, dict) or header.get("size") != len(content):
        raise Refused(BROKEN)
    return header, content


# ---- commands -----------------------------------------------------------------------------------


def connect(root: Path, url: str, workspace: str, token: str) -> dict:
    return net.connect_service(root, "publish", "orch-publish", url, workspace, token, "orp_")


def _cfg(root: Path) -> dict:
    return net.load_service(root, "publish")


def _api(root: Path, method: str, path: str, body=None):
    cfg = _cfg(root)
    return net.call_json(method, cfg["url"] + path, net.auth_headers(cfg), body)[1]


def whoami(root: Path) -> dict:
    return _api(root, "GET", "/v1/whoami")


def _life(days: int | None, permanent: bool) -> str:
    if permanent and days is not None:
        raise Refused("Use either --days or --permanent, not both.")
    if permanent:
        return "permanent=1"
    if days is not None and not 1 <= days <= 90:
        raise Refused("--days must be between 1 and 90.")
    return f"days={days}" if days is not None else ""


def _keys_path(root: Path) -> Path:
    return net.secrets_dir(root) / "files" / "keys.json"


def share_file(root: Path, path: Path, days: int | None, permanent: bool) -> dict:
    if not path.is_file():
        raise Refused(f"{path} is not a file.")
    if path.stat().st_size > MAX_FILE:
        raise Refused("The file is bigger than 100 MB.")
    q = _life(days, permanent)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    blob, key = encrypt(path.read_bytes(), path.name, mime)
    res = _api(root, "POST", "/v1/files" + (f"?{q}" if q else ""), blob)
    k = b64u(key)
    keys = net.read_json(_keys_path(root), {})
    keys[res["id"]] = k
    net.write_json(_keys_path(root), keys, True)
    res["link"] = f"{res['url']}#k={k}"
    res["name"] = path.name
    return res


def list_all(root: Path) -> dict:
    files = net.items(_api(root, "GET", "/v1/files?limit=100"))
    keys = net.read_json(_keys_path(root), {})
    for f in files:
        if f["id"] in keys:
            f["key"] = keys[f["id"]]
    return {"files": files, "apps": net.items(_api(root, "GET", "/v1/apps"))}


def delete(root: Path, ident: str) -> str:
    if ident.startswith("f_"):
        _api(root, "DELETE", f"/v1/files/{ident}")
        keys = net.read_json(_keys_path(root), {})
        if keys.pop(ident, None) is not None:
            net.write_json(_keys_path(root), keys, True)
        return "file"
    _app_name(ident)
    _api(root, "DELETE", f"/v1/apps/{ident}")
    return "app"


def _app_name(name: str) -> str:
    if not NAME_RE.match(name):
        raise Refused("An app name has 2 to 40 lowercase letters, digits or dashes.")
    return name


def app_action(root: Path, name: str, action: str) -> dict:
    return _api(root, "POST", f"/v1/apps/{_app_name(name)}/{action}")


# ---- apps ---------------------------------------------------------------------------------------


def read_manifest(folder: Path) -> dict:
    mf = folder / "app.toml"
    if not mf.is_file():
        raise Refused(f"{folder} has no app.toml (see app.toml.md).")
    try:
        m = tomllib.loads(mf.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise Refused(f"app.toml is not valid: {e}") from None
    _app_name(str(m.get("name", "")))
    stack = m.get("stack")
    if stack not in ("static", "python", "node"):
        raise Refused("app.toml needs stack = static, python or node.")
    if stack == "static" and (m.get("start") or m.get("health")):
        raise Refused("A static app has no start or health.")
    if stack != "static" and not (m.get("start") and m.get("health")):
        raise Refused(f"A {stack} app needs start and health in app.toml.")
    if m.get("store", "none") not in ("none", "json", "markdown", "sqlite"):
        raise Refused("store must be none, json, markdown or sqlite.")
    return m


def pack(folder: Path, public: bool | None) -> bytes:
    """tar.gz of the folder. `public` overrides the public line of app.toml (None keeps it)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for dirpath, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for f in sorted(files):
                p = Path(dirpath) / f
                rel = p.relative_to(folder).as_posix()
                if p.is_symlink() or f in SKIP_DIRS or not p.is_file():
                    continue
                if rel == "app.toml" and public is not None:
                    text = p.read_text(encoding="utf-8")
                    line = f"public = {'true' if public else 'false'}"
                    text = (
                        re.sub(r"(?m)^public\s*=.*$", line, text)
                        if re.search(r"(?m)^public\s*=", text)
                        else text.rstrip("\n") + "\n" + line + "\n"
                    )
                    raw = text.encode("utf-8")
                    info = tarfile.TarInfo(rel)
                    info.size = len(raw)
                    tar.addfile(info, io.BytesIO(raw))
                else:
                    tar.add(p, arcname=rel, recursive=False)
    data = buf.getvalue()
    if len(data) > MAX_APP:
        raise Refused("The app folder is bigger than 100 MB.")
    return data


def deploy(
    root: Path, folder: Path, days: int | None, permanent: bool, public: bool | None, new_token: bool
) -> dict:
    m = read_manifest(folder)
    q = [x for x in (_life(days, permanent), "new_token=1" if new_token else "") if x]
    res = _api(root, "PUT", f"/v1/apps/{m['name']}" + (f"?{'&'.join(q)}" if q else ""), pack(folder, public))
    if res.get("view_token"):
        res["link"] = f"{res['url']}/?token={res['view_token']}"
    else:
        res["link"] = res["url"]
    return res

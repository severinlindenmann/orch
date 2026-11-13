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


NOTE_MAX = 280


def encrypt(
    content: bytes,
    name: str,
    mime: str,
    key: bytes | None = None,
    iv: bytes | None = None,
    note: str | None = None,
):
    """Returns (blob, key). plaintext = u32 BE header length | header JSON | file bytes.
    `note` (optional, crypto.md) travels inside the ciphertext; the server never sees it."""
    key = key or os.urandom(32)
    iv = iv or os.urandom(12)
    head = {"name": name, "type": mime, "size": len(content)}
    if note:
        head["note"] = note
    header = json.dumps(head, ensure_ascii=False, separators=(",", ":")).encode()
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
    who = _api(root, "GET", "/v1/whoami")
    from orch import skillrender

    skillrender.remember_rights(root, who)  # the skill lists what this workspace may share
    skillrender.refresh_skills(root)
    return who


def profile(root: Path, description: str | None, tags: list[str] | None) -> dict:
    return net.profile(root, "publish", description, tags)


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


def _names_path(root: Path) -> Path:
    return _keys_path(root).with_name("file-names.json")


def _tokens_path(root: Path) -> Path:
    return net.secrets_dir(root) / "apps" / "view-tokens.json"


BUNDLE_TYPE = "application/vnd.orch.bundle"


SECRET_NAMES = re.compile(
    r"(?i)^(id_rsa|id_ed25519|id_ecdsa|id_dsa).*|.*\.(pem|key|p8|p12|pfx|keystore|jks)$|^credentials.*\.json$"
    r"|^secrets?\..*|^service-account.*\.json$"
)


def _bundle_path(rel: str) -> str:
    """Refuses names the viewer would reject (crypto.md reader rules)."""
    try:
        rel.encode("utf-8")
    except UnicodeEncodeError:
        raise Refused(f"Rename {rel!r}: its name is not valid text.") from None
    if "\\" in rel or "\0" in rel or len(rel) > 255 or any(s in ("", ".", "..") for s in rel.split("/")):
        raise Refused(f"Rename {rel!r}: names with \\ or paths over 255 characters can't be shared.")
    return rel


def bundle(folder: Path, report: dict | None = None) -> bytes:
    """Folder -> bundle bytes (crypto.md "Folder bundle"): u32 BE index length, index JSON, files.
    `report` gets "files" (bundled paths) and "skipped" (secret-looking files left out)."""
    if (folder / ".orch").exists():
        raise Refused("This folder is the workspace root. Share a folder inside it.")
    files, skipped = [], []
    for dirpath, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for f in sorted(names):
            p = Path(dirpath) / f
            if p.is_symlink() or f in SKIP_DIRS or f.startswith(".") or not p.is_file():
                continue
            rel = p.relative_to(folder).as_posix()
            if SECRET_NAMES.match(f):
                skipped.append(rel)
                continue
            files.append((_bundle_path(rel), p))
    files.sort()
    if report is not None:
        report["files"], report["skipped"] = [r for r, _ in files], sorted(skipped)
    pages = [r for r, _ in files if r.lower().endswith((".html", ".htm"))]
    if not pages:
        raise Refused("The folder needs at least one .html page to be shared.")
    if len(files) > 2000:
        raise Refused("The folder has more than 2000 files.")
    if sum(p.stat().st_size for _, p in files) > MAX_FILE:
        raise Refused("The folder is bigger than 100 MB.")
    datas = [p.read_bytes() for _, p in files]
    index = {
        "v": 1,
        "entry": "index.html" if "index.html" in pages else pages[0],
        "files": [
            {"path": r, "type": mimetypes.guess_type(r)[0] or "application/octet-stream", "size": len(d)}
            for (r, _), d in zip(files, datas, strict=True)
        ],
    }
    raw = json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode()
    return struct.pack(">I", len(raw)) + raw + b"".join(datas)


def _note(note: str | None) -> str | None:
    note = " ".join((note or "").split())
    if len(note) > NOTE_MAX:
        raise Refused(f"The note is longer than {NOTE_MAX} characters.")
    return note or None


def _file_id(ident: str) -> str:
    if not re.fullmatch(r"f_[a-z0-9]+", ident):
        raise Refused("A file id looks like f_8c2kq0z4m1x7b3na. Find it with: orch publish list")
    return ident


def share_file(
    root: Path,
    path: Path,
    days: int | None,
    permanent: bool,
    note: str | None = None,
    replace: str | None = None,
) -> dict:
    note = _note(note)
    key = None
    if replace:
        _file_id(replace)
        if days is not None or permanent:
            raise Refused("A replaced file keeps its expiry. Use orch publish extend to change it.")
        k = net.read_json(_keys_path(root), {}).get(replace)
        if not k:
            raise Refused(
                f"Can't replace {replace}: its key is only kept on the computer that shared it. "
                "Share the file again instead: orch publish file <path>"
            )
        key = b64u_decode(k)
    if path.is_dir():
        shown: dict = {}
        content, mime = bundle(path, shown), BUNDLE_TYPE
        if len(content) > MAX_FILE:
            raise Refused("The folder is bigger than 100 MB.")
    elif not path.is_file():
        raise Refused(f"{path} is not a file or folder.")
    elif path.stat().st_size > MAX_FILE:
        raise Refused("The file is bigger than 100 MB.")
    else:
        content = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    name = path.resolve().name if path.is_dir() else path.name
    if replace:
        # same key, so the link keeps working; a fresh random IV for the new content
        blob, key = encrypt(content, name, mime, key=key, note=note)
        res = _api(root, "PUT", f"/v1/files/{replace}?size={len(content)}", blob)
    else:
        q = _life(days, permanent)
        blob, key = encrypt(content, name, mime, note=note)
        res = _api(root, "POST", "/v1/files" + (f"?{q}&" if q else "?") + f"size={len(content)}", blob)
    k = b64u(key)
    keys = net.read_json(_keys_path(root), {})
    keys[res["id"]] = k
    net.write_json(_keys_path(root), keys, True)
    names = net.read_json(_names_path(root), {})
    names[res["id"]] = name
    net.write_json(_names_path(root), names, True)
    res["link"] = f"{res['url']}#k={k}"
    res["name"] = name
    if path.is_dir():
        res["files"], res["skipped"] = shown["files"], shown["skipped"]
    return res


def extend(root: Path, ident: str, days: int) -> dict:
    """PATCH /v1/files/<id> {days}. The link stays the same; an expired file is never revived."""
    _file_id(ident)
    try:
        res = _api(root, "PATCH", f"/v1/files/{ident}", {"days": days})
    except Refused as e:
        if getattr(e, "status", None) == 410:
            raise Refused("This link has expired.") from None
        raise
    res["name"] = net.read_json(_names_path(root), {}).get(ident)
    return res


def _all_files(root: Path) -> list:
    files, after = [], None
    for _ in range(1000):  # a hard stop: 100 000 files
        page = _api(root, "GET", "/v1/files?limit=100" + (f"&after={after}" if after else ""))
        files += net.items(page)
        after = page.get("next") if isinstance(page, dict) else None
        if not after:
            break
    return files


def list_all(root: Path) -> dict:
    files = _all_files(root)
    keys = net.read_json(_keys_path(root), {})
    names = net.read_json(_names_path(root), {})
    for f in files:
        if f["id"] in keys:
            f["key"] = keys[f["id"]]
        if f["id"] in names:
            f["name"] = names[f["id"]]
    apps = net.items(_api(root, "GET", "/v1/apps"))
    tokens = net.read_json(_tokens_path(root), {})
    for a in apps:
        if not a.get("public") and a["name"] in tokens:
            a["link"] = f"{a['url']}/?token={tokens[a['name']]}"
    return {"files": files, "apps": apps}


def _plain(text: str, limit: int = 200) -> str:
    """Text for a view block: no < or >, 1-200 characters."""
    t = " ".join(str(text).replace("<", "").replace(">", "").split())[:limit]
    return t or "(unnamed)"


def _expires(iso) -> str:
    """'Expires 13 Dec 2026, 12:47' in local time (the expiry is shown once, never repeated)."""
    import datetime as dt

    try:
        t = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone()
    except ValueError:
        return "Expires later"
    return f"Expires {t.day} {t:%b %Y, %H:%M}"


def view(root: Path) -> dict:
    """`orch publish view --json` (addon-view.schema.json): read-only, links without any key.
    One compact row per shared file: name, who can open it, when it ends, and fixed ops on its id."""
    import datetime as dt

    from orch.cli_clients import _exp

    r = list_all(root)
    cap = 50
    files = [
        {
            "title": _plain(f.get("name") or "(unnamed file)"),
            "meta": [
                "Anyone with the link",
                _expires(f["expires_at"]) if f.get("expires_at") else "Kept until you delete it",
            ],
            "actions": [
                {"label": "Copy link", "action": {"op": "link.copy", "args": {"id": f["id"]}}},
                {"label": "Extend", "action": {"op": "link.extend", "args": {"id": f["id"]}}},
                {"label": "Stop sharing", "action": {"op": "link.stop", "args": {"id": f["id"]}}},
            ],
        }
        for f in r["files"]
        if re.fullmatch(r"f_[a-z0-9]+", str(f.get("id")))
    ]
    apps = [
        {
            "title": _plain(a["name"]),
            "subtitle": _plain(
                f"{a['status']}, {'public' if a['public'] else 'private'}, {_exp(a['expires_at'])}"
            ),
            **({"link": a["url"]} if str(a.get("url", "")).startswith("https://") else {}),
        }
        for a in r["apps"]
    ]
    blocks: list = [
        {
            "type": "list",
            "title": "Shared",
            **({"meta": f"{len(files)} link{'s' if len(files) != 1 else ''}"} if files else {}),
            "compact": True,
            "items": files[:cap],
            "more": max(0, len(files) - cap),
            "empty": {"title": "No shared links", "text": "Share a file to create a private link."},
        }
    ]
    if apps:
        blocks.append({"type": "list", "title": "Apps", "items": apps[:cap], "more": max(0, len(apps) - cap)})
    blocks.append(
        {
            "type": "footnote",
            "text": "Stopping sharing closes the link and keeps your original file.",
            "link": {"label": "Shared link settings", "to": "app:settings/addons"},
        }
    )
    return {
        "schema": "orch.addon-view/1",
        "generated_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "header": {"button": {"label": "Share a file", "action": {"op": "link.share"}}},
        "blocks": blocks,
    }


def delete(root: Path, ident: str) -> str:
    if ident.startswith("f_"):
        _api(root, "DELETE", f"/v1/files/{ident}")
        keys = net.read_json(_keys_path(root), {})
        if keys.pop(ident, None) is not None:
            net.write_json(_keys_path(root), keys, True)
        names = net.read_json(_names_path(root), {})
        if names.pop(ident, None) is not None:
            net.write_json(_names_path(root), names, True)
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
    if (folder / ".orch").exists():
        raise Refused("This folder is the workspace root. Publish an app folder inside it.")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for dirpath, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
            for f in sorted(files):
                p = Path(dirpath) / f
                rel = p.relative_to(folder).as_posix()
                if p.is_symlink() or f in SKIP_DIRS or f.startswith(".") or not p.is_file():
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
    is_public = public if public is not None else bool(m.get("public", False))
    res["private"] = not is_public
    tokens = net.read_json(_tokens_path(root), {})
    if res.get("view_token"):
        tokens[m["name"]] = res["view_token"]
        net.write_json(_tokens_path(root), tokens, True)
    if is_public:
        res["link"] = res["url"]
    elif tokens.get(m["name"]):
        res["link"] = f"{res['url']}/?token={tokens[m['name']]}"
        res["view_token"] = tokens[m["name"]]
    else:
        res["link"] = res["url"]
    return res

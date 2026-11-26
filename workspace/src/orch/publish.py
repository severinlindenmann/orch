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

from orch import net, secretscan
from orch.errors import Refused

MAGIC = b"OPF1"
MAX_FILE = 100 * 1024 * 1024
MAX_APP = 100 * 1024 * 1024
NAME_RE = re.compile(r"^[a-z0-9-]{2,40}$")  # existing apps (stop, remove, ...)
# a NEW app name also starts and ends with a letter or digit (it becomes part of a container image name)
DEPLOY_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".DS_Store"}
BROKEN = "wrong key or broken file"
# The dashboard page (`publish view`) waits 10 s for the whole answer. One request that stalls (a lost
# connection, the server busy) must not use that up: it is cut after VIEW_TIMEOUT and tried again (net retries
# GETs), so a single stall costs about 4 s instead of the page falling back to its old copy (ORCH-403).
VIEW_TIMEOUT = 3.0


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


INVITE_RIGHTS = {"files": True, "apps": True, "permanent": False, "public": False}


def invite(root: Path, name: str, folder: str, admin_url: str, token: str) -> dict:
    """`orch publish invite`: add a workspace on the publish server (admin API) and connect `folder`.
    It may share files and apps; permanent and public stay off until the admin turns them on."""
    if not name.strip():
        raise Refused("Give the new workspace a name.")
    body = {"name": name.strip(), "description": "", "tags": [], "rights": dict(INVITE_RIGHTS)}
    r = net.invite_service(root, "publish", folder, connect, admin_url, token, body)
    return {**r, "rights": body["rights"]}


def _api(root: Path, method: str, path: str, body=None, timeout: float = 120):
    cfg = _cfg(root)
    return net.call_json(method, cfg["url"] + path, net.auth_headers(cfg), body, timeout)[1]


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


def _texts_of(data: bytes) -> list[str]:
    """Every reading of a file that is scanned; always the plain UTF-8 text, so never empty (binary files
    are scanned too). Extra readings: the text with its NUL bytes dropped (ASCII inside UTF-16/32 at any
    alignment, tar and database files with NUL padding) and the byte-order-mark or NUL-parity decode."""
    views = [data.decode("utf-8", "replace")]
    if b"\0" in data:
        views.append(data.replace(b"\0", b"").decode("utf-8", "replace"))
    for bom, codec in (
        (b"\xff\xfe\0\0", "utf-32"),
        (b"\0\0\xfe\xff", "utf-32"),
        (b"\xff\xfe", "utf-16"),
        (b"\xfe\xff", "utf-16"),
    ):
        if data.startswith(bom):
            views.append(data.decode(codec, "replace"))
    head = data[:8192]
    n = len(head) // 2
    if n >= 8:  # BOM-less UTF-16: NULs sit at one parity only (ASCII text)
        even, odd = head[0 : 2 * n : 2].count(0), head[1 : 2 * n : 2].count(0)
        if max(even, odd) >= 0.4 * n and min(even, odd) <= 0.02 * n:
            views.append(data.decode("utf-16-le" if odd > even else "utf-16-be", "replace"))
    return views


CHUNK = secretscan.MAX_BYTES // 2
OVERLAP = 16384  # longer than any token pattern; a PEM block over this is still caught by its header line


def scan_names(root: Path | None, names: list[str], outer: str | None = None, what: str = "file") -> None:
    """R5.2: the names a recipient sees (the shared file, folder or app name and every path inside) go through
    the one scanner before upload. A hit names the kind and where, never the name itself."""
    texts = ([outer] if outer is not None else []) + list(names)
    if not texts:
        return
    starts, lines = [], 1
    for t in texts:
        starts.append(lines)
        lines += t.count("\n") + 1
    try:
        found = secretscan.find("\n".join(texts), root, strict=False)
    except Exception:  # noqa: BLE001 - a scan that cannot run is never a pass
        raise Refused(
            "orch could not check the names for secrets, so nothing was shared. Try again."
        ) from None
    if not found:
        return
    first = found[0]
    idx = max(i for i, s in enumerate(starts) if s <= first["line"])
    kind = secretscan.WORDS.get(first["kind"], "a secret")
    more = f" (and {len(found) - 1} more)" if len(found) > 1 else ""
    where = f"The {what}'s name" if outer is not None and idx == 0 else f"A file or folder name in the {what}"
    raise Refused(f"Nothing was shared: {where} has {kind}{more}. Rename it and share again.")


def scan_files(
    root: Path | None, items: list[tuple[str, bytes]], outer: str | None = None, what: str = "file"
) -> None:
    """Refuse the upload when any name or text file holds a secret (secretscan, the one scanner). Runs on the
    names and plain bytes that are about to be encrypted and sent. Names are checked first, so a content
    refusal only ever quotes a clean name; it names the kind, the file and the line, never the value."""
    scan_names(root, [n for n, _ in items], outer, what)
    hits: dict[tuple[str, int, str], None] = {}
    for name, data in items:
        for blob, labels in secretscan.passes(data):  # a PNG's proven pixel runs skip only the label rules
            for text in _texts_of(blob):
                # chunks with an overlap, so a big file is scanned in full and no token is cut in two
                pos = 0
                while True:
                    end = min(pos + CHUNK, len(text))
                    line0 = text.count("\n", 0, pos)
                    for f in secretscan.find(text[pos:end], root, strict=False, labels=labels):
                        hits[(name, f["line"] + line0, f["kind"])] = None
                    if end >= len(text):
                        break
                    pos = end - OVERLAP
    if not hits:
        return
    name, line, kind = sorted(hits, key=lambda h: (h[0], h[1]))[0]
    more = f" (and {len(hits) - 1} more)" if len(hits) > 1 else ""
    raise Refused(
        f"Nothing was shared: {name!r} has {secretscan.WORDS.get(kind, 'a secret')} on line {line}{more}. "
        "Remove it from the file and share again."
    )


def bundle(folder: Path, report: dict | None = None, root: Path | None = None) -> bytes:
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
            files.append((rel, p))
    # the names first: a refusal below quotes a name, and the folder's own name goes into the file header
    outer = folder.resolve().name
    scan_names(root, [r for r, _ in files], outer, "folder")
    files = sorted((_bundle_path(r), p) for r, p in files)
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
    scan_files(root, [(r, d) for (r, _), d in zip(files, datas, strict=True)], outer, "folder")
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
    if note:  # R5.2: the note leaves inside the file header; the one scanner first, like the file itself
        secretscan.refuse_if_secret_in(root, {"text": note}, "note")
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
        content, mime = bundle(path, shown, root), BUNDLE_TYPE
        if len(content) > MAX_FILE:
            raise Refused("The folder is bigger than 100 MB.")
    elif not path.is_file():
        raise Refused(f"{path} is not a file or folder.")
    elif path.stat().st_size > MAX_FILE:
        raise Refused("The file is bigger than 100 MB.")
    else:
        content = path.read_bytes()
        scan_files(root, [(path.name, content)], path.name)
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


def _all_files(root: Path, timeout: float = 120) -> list:
    files, after = [], None
    for _ in range(1000):  # a hard stop: 100 000 files
        q = "/v1/files?limit=100" + (f"&after={after}" if after else "")
        page = _api(root, "GET", q, timeout=timeout)
        files += net.items(page)
        after = page.get("next") if isinstance(page, dict) else None
        if not after:
            break
    return files


def list_all(root: Path, timeout: float = 120) -> dict:
    files = _all_files(root, timeout)
    keys = net.read_json(_keys_path(root), {})
    names = net.read_json(_names_path(root), {})
    for f in files:
        if f["id"] in keys:
            f["key"] = keys[f["id"]]
        if f["id"] in names:
            f["name"] = names[f["id"]]
    apps = net.items(_api(root, "GET", "/v1/apps", timeout=timeout))
    tokens = net.read_json(_tokens_path(root), {})
    for a in apps:
        if ("auth" in a and a["auth"] or "auth" not in a and not a.get("public")) and a["name"] in tokens:
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

    try:
        net.load_service(root, "publish")
    except Refused:  # no publish server yet: nothing is shared, which is an empty page, not an error
        return {
            "schema": "orch.addon-view/1",
            "generated_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "blocks": [
                {
                    "type": "list",
                    "title": "Shared",
                    "compact": True,
                    "items": [],
                    "more": 0,
                    "empty": {
                        "title": "No shared links yet",
                        "text": "To share a file by private link, this workspace first needs a publish "
                        "server. Ask whoever runs it for a setup prompt and paste it into your agent.",
                    },
                }
            ],
        }
    r = list_all(root, VIEW_TIMEOUT)
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
            "meta": [
                _app_state(a),
                _app_access(a),
                _exp(a["expires_at"]) if a.get("expires_at") else "Kept until you delete it",
            ],
            **(
                {"actions": [{"label": "Open", "link": a["url"]}]}
                if str(a.get("url", "")).startswith("https://") and a.get("status") == "running"
                else {}
            ),
        }
        for a in r["apps"]
    ]
    blocks: list = [
        {
            "type": "list",
            "title": "Files",
            **({"meta": f"{len(files)} link{'s' if len(files) != 1 else ''}"} if files else {}),
            "compact": True,
            "items": files[:cap],
            "more": max(0, len(files) - cap),
            "empty": {"title": "No shared links", "text": "Share a file to create a private link."},
        }
    ]
    if apps:
        blocks.append(
            {
                "type": "list",
                "title": "Apps",
                "compact": True,
                "items": apps[:cap],
                "more": max(0, len(apps) - cap),
            }
        )
    blocks.append(
        {
            "type": "footnote",
            "text": "Stopping sharing closes the link and keeps your original file."
            + (" To stop, restart or delete an app, ask a helper on a ticket." if apps else ""),
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


def _app_name(name: str, new: bool = False) -> str:
    if not (DEPLOY_NAME_RE if new else NAME_RE).match(name):
        raise Refused(
            "An app name has 2 to 40 lowercase letters, digits or dashes"
            + (", and starts and ends with a letter or digit." if new else ".")
        )
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
    _app_name(str(m.get("name", "")), new=True)
    stack = m.get("stack")
    if stack not in ("static", "python", "node", "docker"):
        raise Refused("app.toml needs stack = static, python, node or docker.")
    if stack == "static" and (m.get("start") or m.get("health")):
        raise Refused("A static app has no start or health.")
    if stack == "docker":
        if not m.get("health"):
            raise Refused("A docker app needs health in app.toml.")
        if not (folder / "Dockerfile").is_file():
            raise Refused("A docker app needs a Dockerfile at the top of its folder.")
    elif stack != "static" and not (m.get("start") and m.get("health")):
        raise Refused(f"A {stack} app needs start and health in app.toml.")
    if m.get("store", "none") not in ("none", "json", "markdown", "sqlite"):
        raise Refused("store must be none, json, markdown or sqlite.")
    return m


def _set_line(text: str, key: str, value: str) -> str:
    """Replace the `key = ...` line of a manifest, else add one."""
    line = f"{key} = {value}"
    if re.search(rf"(?m)^{key}\s*=", text):
        return re.sub(rf"(?m)^{key}\s*=.*$", line, text)
    return text.rstrip("\n") + "\n" + line + "\n"


def _override(text: str, reach: str | None, auth: bool | None) -> str:
    if reach is not None:
        text = _set_line(text, "reach", f'"{reach}"')
    if auth is not None:
        # the server refuses `public` together with `auth`: the older line goes
        text = re.sub(r"(?m)^public\s*=.*\n?", "", text)
        text = _set_line(text, "auth", "true" if auth else "false")
    return text


# the manifest's own switches (`auth = true`) are settings, not secrets: blanked before the scan
_MANIFEST_FLAGS = re.compile(
    rb'(?m)^[ \t]*(?:(?:auth|public|reach)[ \t]*=[ \t]*(?:true|false|"public"|"private")'
    # the two comment lines of the app templates, word for word: nothing may follow them
    rb"|# reach: public = on the internet, private = only on the private network"
    rb"|# auth: true = needs the app's private link, false = open to everyone who can reach it)"
    rb"[ \t]*(?=\r?$)"
)


def pack(
    folder: Path,
    reach: str | None = None,
    auth: bool | None = None,
    root: Path | None = None,
    name: str | None = None,
) -> bytes:
    """tar.gz of the folder. `reach` ("public" | "private") and `auth` override app.toml (None keeps it).
    `name`: the app name, scanned with the paths inside."""
    if (folder / ".orch").exists():
        raise Refused("This folder is the workspace root. Publish an app folder inside it.")
    buf = io.BytesIO()
    scanned: list[tuple[str, bytes]] = []
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for dirpath, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
            for f in sorted(files):
                p = Path(dirpath) / f
                rel = p.relative_to(folder).as_posix()
                if p.is_symlink() or f in SKIP_DIRS or f.startswith(".") or not p.is_file():
                    continue
                if rel == "app.toml" and (reach is not None or auth is not None):
                    raw = _override(p.read_text(encoding="utf-8"), reach, auth).encode("utf-8")
                    info = tarfile.TarInfo(rel)
                else:  # read once: the bytes that are scanned are the bytes that are sent
                    raw = p.read_bytes()
                    info = tar.gettarinfo(str(p), arcname=rel)
                info.size = len(raw)
                scanned.append((rel, _MANIFEST_FLAGS.sub(b"", raw) if rel == "app.toml" else raw))
                tar.addfile(info, io.BytesIO(raw))
    scan_files(root, scanned, name, "app")
    data = buf.getvalue()
    if len(data) > MAX_APP:
        raise Refused("The app folder is bigger than 100 MB.")
    return data


def manifest_auth(m: dict) -> bool:
    """auth of a manifest: `auth`, else the older `public` (public = no auth), else true."""
    if "auth" in m:
        return bool(m["auth"])
    return not m["public"] if "public" in m else True


def _app_state(a: dict) -> str:
    return {"running": "Running", "stopped": "Stopped", "failed": "Failed"}.get(
        str(a.get("status")), "Not running"
    )


def _app_access(a: dict) -> str:
    """Who can open an app, in plain words (the reach and the link are one answer, not two)."""
    private = a.get("reach") == "private"
    auth = bool(a["auth"]) if "auth" in a else not a.get("public", False)
    if private:
        return "People on your private network" + (" with the link" if auth else "")
    return "Anyone with the link" if auth else "Anyone"


def describe(a: dict) -> str:
    """Plain words for an app: where it can be reached and whether it needs the link.

    An older server sends only `public`: that means reach public, auth = not public."""
    private = a.get("reach") == "private"
    auth = bool(a["auth"]) if "auth" in a else not a.get("public", False)
    return f"{'private network' if private else 'public'}, {'needs link' if auth else 'open'}"


def deploy(
    root: Path,
    folder: Path,
    days: int | None,
    permanent: bool,
    reach: str | None,
    auth: bool | None,
    new_token: bool,
) -> dict:
    m = read_manifest(folder)
    q = [x for x in (_life(days, permanent), "new_token=1" if new_token else "") if x]
    res = _api(
        root,
        "PUT",
        f"/v1/apps/{m['name']}" + (f"?{'&'.join(q)}" if q else ""),
        pack(folder, reach, auth, root, m["name"]),
    )
    needs_link = auth if auth is not None else manifest_auth(m)
    res.setdefault("reach", reach or m.get("reach", "public"))
    res["auth"] = needs_link
    tokens = net.read_json(_tokens_path(root), {})
    if res.get("view_token"):
        tokens[m["name"]] = res["view_token"]
        net.write_json(_tokens_path(root), tokens, True)
    if not needs_link:
        res["link"] = res["url"]
    elif tokens.get(m["name"]):
        res["link"] = f"{res['url']}/?token={tokens[m['name']]}"
        res["view_token"] = tokens[m["name"]]
    else:
        res["link"] = res["url"]
    return res

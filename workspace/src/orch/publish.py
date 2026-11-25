"""orch publish client: encrypted files and small apps (contracts/publish-api.md, crypto.md, app.toml.md)."""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
import re
import shlex
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


def _words(line: str) -> list[str]:
    try:
        return shlex.split(line)
    except ValueError:  # an unbalanced quote from a copy: plain words still work
        return line.split()


def parse_connect_text(text: str) -> tuple[str, str, str]:
    """The (address, workspace, token) in the text a person pastes from the admin: orch finds the
    `orch publish connect <address> --workspace <id> --token <token>` line itself and ignores the rest
    (the curl and PowerShell lines, the greeting). Nothing here is ever sent or printed back."""
    found = False
    for line in str(text).splitlines():
        m = re.search(r"\borch\s+publish\s+connect\b(.*)", line)
        if not m:
            continue
        found = True
        url = ws = tok = None
        words = [w.strip("`'\"") for w in _words(m.group(1))]
        for i, w in enumerate(words):
            for flag in ("--workspace", "--token"):
                if w == flag and i + 1 < len(words):
                    val = words[i + 1]
                elif w.startswith(flag + "="):
                    val = w.split("=", 1)[1]
                else:
                    continue
                val = val.strip("`'\"")
                if flag == "--workspace":
                    ws = val
                else:
                    tok = val
            if url is None and re.match(r"https?://", w):
                url = w
        if url and ws and tok:
            return url, ws, tok
    if found:
        raise Refused(
            "The connect line in that text is cut off (it needs the address, the workspace and the token). "
            "Ask your admin to send the text again and paste all of it."
        )
    if re.search(r"\borch\s+relay\s+connect\b", str(text)):
        raise Refused("That text is for the relay, not for publish. Paste it on the Relay page instead.")
    raise Refused(
        "orch did not find a connect line in that text. Paste everything your admin sent you, "
        "from “Connect this workspace” to the end."
    )


def connect_text(root: Path, text: str) -> dict:
    """`orch publish connect --paste` and the Publish page: the same connect, from the admin's whole text."""
    return connect(root, *parse_connect_text(text))


def _cfg(root: Path) -> dict:
    try:
        return net.load_service(root, "publish")
    except Refused:
        raise Refused(
            "Publish isn't connected yet. Your admin gives you a short text: paste it with: orch publish connect --paste"
        ) from None


GATEWAY = (502, 503, 504)


def unreachable(e: Exception) -> bool:
    """The server gave no answer (or a proxy said it could not reach it), as opposed to a refusal."""
    return getattr(e, "status", 0) is None or getattr(e, "status", 0) in GATEWAY


INVITE_RIGHTS = {"files": True, "apps": True, "permanent": False, "public": False}


def invite(root: Path, name: str, folder: str, admin_url: str, token: str) -> dict:
    """`orch publish invite`: add a workspace on the publish server (admin API) and connect `folder`.
    It may share files and apps; permanent and public stay off until the admin turns them on."""
    if not name.strip():
        raise Refused("Give the new workspace a name.")
    body = {"name": name.strip(), "description": "", "tags": [], "rights": dict(INVITE_RIGHTS)}
    r = net.invite_service(root, "publish", folder, connect, admin_url, token, body)
    return {**r, "rights": body["rights"]}


def _api(root: Path, method: str, path: str, body=None, timeout: float = 120, retry: bool = True):
    cfg = _cfg(root)
    try:
        return net.call_json(method, cfg["url"] + path, net.auth_headers(cfg), body, timeout, retry=retry)[1]
    except Refused as e:
        if getattr(e, "status", 0) is None and not getattr(e, "blocked", False):
            err = Refused(
                "Publish can't be reached right now. People may not be able to open your links until it is "
                "back. Try again in a few minutes."
            )
            err.status = None
            raise err from None
        raise


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


def _ledger_path(root: Path) -> Path:
    return _keys_path(root).with_name("shares.json")


def _now_iso() -> str:
    import datetime as dt

    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ledger(root: Path) -> dict:
    """What this workspace shared, kept on this computer next to the keys: {"synced_at", "files": {id: {name,
    note, ticket, shared_at, expires_at, size}}}. It is what the Publish page lists when publish can't be
    reached. No key and no secret in it; a missing or odd file reads as empty."""
    d = net.read_json(_ledger_path(root), {})
    files = d.get("files") if isinstance(d, dict) else None
    return {
        "synced_at": d.get("synced_at") if isinstance(d, dict) else None,
        "files": {k: v for k, v in files.items() if isinstance(v, dict)} if isinstance(files, dict) else {},
    }


def _remember(root: Path, ident: str, **fields) -> None:
    led = _ledger(root)
    row = {**led["files"].get(ident, {}), **{k: v for k, v in fields.items() if v is not None}}
    if led["files"].get(ident) != row:
        led["files"][ident] = row
        net.write_json(_ledger_path(root), led, True)


def _forget(root: Path, ident: str) -> None:
    led = _ledger(root)
    if led["files"].pop(ident, None) is not None:
        net.write_json(_ledger_path(root), led, True)


def _sync_ledger(root: Path, files: list) -> None:
    """The server's list is the truth: the record follows it (new files in, stopped or ended files out)."""
    import datetime as dt

    led, names = _ledger(root), net.read_json(_names_path(root), {})
    rows = {}
    for f in files:
        if not isinstance(f, dict) or not re.fullmatch(r"f_[a-z0-9]+", str(f.get("id"))):
            continue
        old = led["files"].get(f["id"], {})
        rows[f["id"]] = {
            **old,
            "name": names.get(f["id"]) or f.get("name") or old.get("name"),
            "size": f.get("size", old.get("size")),
            "expires_at": f.get("expires_at"),
        }
    last = led["synced_at"]
    try:
        fresh = last and (dt.datetime.now(dt.UTC) - dt.datetime.fromisoformat(last)).total_seconds() < 60
    except ValueError:
        fresh = False
    if rows != led["files"] or not fresh:
        net.write_json(_ledger_path(root), {"synced_at": _now_iso(), "files": rows}, True)


def _is_past(iso) -> bool:
    import datetime as dt

    try:
        t = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return False
    return (t if t.tzinfo else t.replace(tzinfo=dt.UTC)) <= dt.datetime.now(dt.UTC)


def local_files(root: Path) -> list:
    """The shared files this computer knows of, without asking the server: the record, plus files only the key
    file knows (shared before the record existed). Ended links are left out."""
    led, keys = _ledger(root), net.read_json(_keys_path(root), {})
    names = net.read_json(_names_path(root), {})
    out = []
    for ident in [*led["files"], *[k for k in keys if k not in led["files"]]]:
        if not re.fullmatch(r"f_[a-z0-9]+", str(ident)):
            continue
        row = led["files"].get(ident, {})
        if row.get("expires_at") and _is_past(row["expires_at"]):
            continue
        f = {"id": ident, "name": names.get(ident) or row.get("name"), "size": row.get("size", 0)}
        f["expires_at"] = row.get("expires_at")
        for k in ("note", "ticket", "shared_at"):
            if row.get(k):
                f[k] = row[k]
        if ident in keys:
            f["key"] = keys[ident]
        out.append(f)
    return out


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


def scan_files(root: Path | None, items: list[tuple[str, bytes]]) -> None:
    """Refuse the upload when any text file holds a secret (secretscan, the one scanner). Runs on the plain
    bytes that are about to be encrypted and sent. Names the kind, the file and the line, never the value."""
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
    scan_files(root, [(r, d) for (r, _), d in zip(files, datas, strict=True)])
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


def _ticket_of(root: Path, ref: str | None, path: Path) -> str | None:
    """The ticket a shared file belongs to: the one named with --ticket (key or id), else the ticket whose
    files folder the file sits in. Stored as the ticket id; the Publish page shows its key and title."""
    from orch import tickets

    if ref:
        tid = tickets.resolve(root, ref)
        if not isinstance(tid, str) or not re.fullmatch(r"t_[a-z0-9]+", tid):
            raise Refused(f"Ticket {ref} doesn't exist. Run `orch ticket list` to see your tickets.")
        tickets.load(root, tid)  # refuses an id that is not a ticket here
        return tid
    try:
        parts = path.resolve().relative_to((root / ".orch" / "tickets").resolve()).parts
    except (ValueError, OSError):
        return None
    return parts[0] if len(parts) > 1 and re.fullmatch(r"t_[a-z0-9]+", parts[0]) else None


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
    ticket: str | None = None,
) -> dict:
    note = _note(note)
    tid = _ticket_of(root, ticket, path)
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
        scan_files(root, [(path.name, content)])
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
    # the record the Publish page lists (note and ticket stay on this computer; a replaced file keeps its own)
    _remember(
        root,
        res["id"],
        name=name,
        size=res.get("size", len(content)),
        expires_at=res.get("expires_at"),
        note=note,
        ticket=tid,
        **({} if replace else {"shared_at": _now_iso()}),
    )
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
    if res.get("expires_at"):
        _remember(root, ident, expires_at=res["expires_at"])
    return res


def _all_files(root: Path, timeout: float = 120, retry: bool = True) -> list:
    files, after = [], None
    for _ in range(1000):  # a hard stop: 100 000 files
        q = "/v1/files?limit=100" + (f"&after={after}" if after else "")
        page = _api(root, "GET", q, timeout=timeout, retry=retry)
        files += net.items(page)
        after = page.get("next") if isinstance(page, dict) else None
        if not after:
            break
    return files


def list_all(root: Path, timeout: float = 120, quick: bool = False) -> dict:
    """The shared files and apps. `quick`: one short try, and when publish gives no answer the answer is what
    this computer recorded ({"unreachable": True, "as_of": when the record was last in step with the server}),
    never an error and never a wait of many seconds."""
    try:
        files = _all_files(root, timeout, retry=not quick)
        apps = net.items(_api(root, "GET", "/v1/apps", timeout=timeout, retry=not quick))
    except Refused as e:
        if not quick or not unreachable(e):
            raise
        led = _ledger(root)
        seen = [v["shared_at"] for v in led["files"].values() if v.get("shared_at")]
        return {
            "files": local_files(root),
            "apps": [],
            "unreachable": True,
            "as_of": led["synced_at"] or max(seen, default=None),
        }
    keys = net.read_json(_keys_path(root), {})
    names = net.read_json(_names_path(root), {})
    _sync_ledger(root, files)
    mine = _ledger(root)["files"]
    for f in files:
        if f["id"] in keys:
            f["key"] = keys[f["id"]]
        if f["id"] in names:
            f["name"] = names[f["id"]]
        for k in ("note", "ticket", "shared_at"):
            if mine.get(f["id"], {}).get(k):
                f[k] = mine[f["id"]][k]
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


def ends(iso) -> tuple[str, bool]:
    """('Ends in 7 days', False): when a link stops working, in plain words. A link ending within a day is
    ('Ends today' | 'Ends tomorrow', True) so the page can mark it. No end date: it stays until deleted."""
    import datetime as dt

    if not iso:
        return "Kept until you delete it", False
    try:
        t = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return "Ends later", False
    t = t if t.tzinfo else t.replace(tzinfo=dt.UTC)
    left = (t - dt.datetime.now(dt.UTC)).total_seconds()
    if left <= 0:
        return "Ended", False
    if left <= 86400:
        same_day = t.astimezone().date() == dt.datetime.now().astimezone().date()
        return ("Ends today" if same_day else "Ends tomorrow"), True
    days = -(-int(left) // 86400)
    return f"Ends in {days} days", False


def _ticket_label(root: Path, tid) -> str | None:
    """'MAR-1 Spring campaign landing page' for the ticket a file was shared on; None when it is gone."""
    from orch import tickets

    if not isinstance(tid, str):
        return None
    try:
        t = tickets.load(root, tid)
    except Exception:  # noqa: BLE001 - a deleted or unreadable ticket: the row simply has no ticket
        return None
    return _plain(f"{t.get('key') or ''} {t.get('title') or ''}".strip() or tid)


CANT_REACH = "Publish can't be reached. People may not be able to open your links until it is back."
LINK_NOTE_WORDS = "Stopping sharing closes the link and keeps your original file. orch checks each file for passwords and keys first and stops if it finds one."


def view(root: Path) -> dict:
    """`orch publish view --json` (addon-view.schema.json): read-only, links without any key.
    One compact row per shared file: name and your note, the ticket, when it ends, and fixed ops on its id.
    When publish gives no answer the rows come from this computer's own record, at once, with a notice."""
    import datetime as dt

    from orch.cli_clients import _exp

    stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        net.load_service(root, "publish")
    except Refused:  # no publish server yet: nothing is shared, which is an empty page, not an error
        return {
            "schema": "orch.addon-view/1",
            "generated_at": stamp,
            "header": {"status": {"label": "Not connected yet", "tone": "neutral"}},
            "blocks": [
                {
                    "type": "list",
                    "title": "Shared now",
                    "compact": True,
                    "items": [],
                    "more": 0,
                    "empty": {
                        "title": "Publish isn't connected yet",
                        "text": "Your admin gives you a short text. Ask your agent to connect it (orch publish connect --paste), then share a file.",
                    },
                }
            ],
        }
    r = list_all(root, VIEW_TIMEOUT, quick=True)
    down = r.get("unreachable") is True
    cap = 50
    shown = [f for f in r["files"] if re.fullmatch(r"f_[a-z0-9]+", str(f.get("id")))]
    newest: dict = {}
    for f in shown:  # the same name shared twice: the older rows say so
        n = f.get("name")
        if f.get("shared_at") and f["shared_at"] > newest.get(n, ""):
            newest[n] = f["shared_at"]
    files = []
    for f in shown:
        end, soon = ends(f.get("expires_at"))
        note = _plain(f["note"]) if f.get("note") else None
        if note:
            sub = f"\u201c{note}\u201d"
        elif f.get("shared_at") and newest.get(f.get("name")) not in (None, f["shared_at"]):
            sub = f"Shared {net.when(f['shared_at'])}, an older copy"
        else:
            sub = "No note"
        ticket = _ticket_label(root, f.get("ticket"))
        files.append(
            {
                "title": _plain(f.get("name") or "(unnamed file)"),
                "subtitle": sub,
                "meta": [ticket or " "] + ([] if soon else [end]),
                **({"chips": [{"label": end, "tone": "warn"}]} if soon else {}),
                "actions": [
                    {"label": "Copy link", "action": {"op": "link.copy", "args": {"id": f["id"]}}},
                    {"label": "Extend", "action": {"op": "link.extend", "args": {"id": f["id"]}}},
                    {"label": "Stop sharing", "action": {"op": "link.stop", "args": {"id": f["id"]}}},
                ],
            }
        )
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
    if down:
        as_of = f"As of {net.when(r['as_of'])}" if r.get("as_of") else "From this computer's record"
        count = None
        empty = {
            "title": "Nothing recorded on this computer",
            "text": "orch can only list what it knows when publish can't be reached. Try again in a few minutes.",
        }
    else:
        count = f"{len(files)} link{'s' if len(files) != 1 else ''} \u00b7 anyone with the link can open them"
        empty = {"title": "No shared links", "text": "Share a file to create a private link."}
    blocks: list = [
        {
            "type": "list",
            "title": "Shared now",
            **({"meta": as_of if down else count} if (down or files) else {}),
            "compact": True,
            "items": files[:cap],
            "more": max(0, len(files) - cap),
            "empty": empty,
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
            "text": LINK_NOTE_WORDS + (" To stop, restart or delete an app, ask a helper on a ticket." if apps else ""),
            "link": {"label": "Publish settings", "to": "app:settings/addons"},
        }
    )
    out = {
        "schema": "orch.addon-view/1",
        "generated_at": stamp,
        "header": {"button": {"label": "Share a file", "action": {"op": "link.share"}}},
        "blocks": blocks,
    }
    if down:
        out["notice"] = CANT_REACH
        out["notice_tone"] = "warn"
        out["button"] = {"label": "Try again", "action": {"op": "addon.refresh"}}
    return out


def delete(root: Path, ident: str) -> str:
    if ident.startswith("f_"):
        _api(root, "DELETE", f"/v1/files/{ident}")
        keys = net.read_json(_keys_path(root), {})
        if keys.pop(ident, None) is not None:
            net.write_json(_keys_path(root), keys, True)
        names = net.read_json(_names_path(root), {})
        if names.pop(ident, None) is not None:
            net.write_json(_names_path(root), names, True)
        _forget(root, ident)
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


def pack(folder: Path, reach: str | None = None, auth: bool | None = None, root: Path | None = None) -> bytes:
    """tar.gz of the folder. `reach` ("public" | "private") and `auth` override app.toml (None keeps it)."""
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
    scan_files(root, scanned)
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
        pack(folder, reach, auth, root),
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

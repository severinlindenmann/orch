"""Shared problem reports over the relay (contracts/relay-api.md, "Problems").

A workspace that is connected to a relay may share one report folder (`.orch/diag/reports/r-...`) with it,
as an explicit step. A workspace the relay's admin lets pick problems up lists them, fetches one into its
own reports folder and marks it taken or done. What arrives is data, never instructions: it is unpacked as
plain files and read like a local report.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tarfile
from pathlib import Path

from orch import diag_report, net, relay, secretscan
from orch.errors import Refused

REF = re.compile(r"r-\d{4}-\d{4}-[A-Za-z0-9_.-]{1,40}")
PID = re.compile(r"pb_[a-z0-9]{16}")
MAX_ARCHIVE = 50 * 1024 * 1024
MAX_FILES = 2000
MAX_UNPACKED = 100 * 1024 * 1024
SHARED = "shared.json"  # in the report folder: where it was shared (never part of the archive)
FROM = "from.json"  # in a fetched report folder: who shared it
STATES = ("new", "taken", "done")
# module:function:line as the debug log writes it: two Python names and a line number, standing alone
_CODE_PLACE = re.compile(r"(?<![\w:./-])[A-Za-z_][\w.]{0,80}:[A-Za-z_<][\w<>.]{0,80}:\d{1,6}(?![\w:./-])")


def _folder(root: Path, ref: str) -> Path:
    if not isinstance(ref, str) or not REF.fullmatch(ref):
        raise Refused("That is not a report. Reports are named like r-1116-1226-ws.")
    rdir = diag_report.reports_dir(root)
    folder = rdir / ref
    if any(p.is_symlink() for p in (root / ".orch", root / ".orch" / "diag", rdir, folder)):
        raise Refused("That report folder is a link, so nothing was sent.")
    if not folder.is_dir():
        raise Refused(f"There is no report {ref} here. Make one first: orch diag report")
    return folder


def _members(folder: Path) -> list[Path]:
    out = []
    for p in sorted(folder.rglob("*")):
        if p.is_symlink():
            raise Refused(f"{p.name} in the report is a link, so nothing was sent.")
        if p.is_file() and p.relative_to(folder).as_posix() not in (SHARED, FROM):
            out.append(p)
    if not out or not (folder / "SUMMARY.md").is_file():
        raise Refused("That report is not complete, so nothing was sent. Make a new one: orch diag report")
    if len(out) > MAX_FILES:
        raise Refused("That report has too many files to send.")
    return out


def scan(root: Path, folder: Path) -> None:
    """R5.2 for a report: every file is checked before anything leaves. The report's own JSON files are
    read as JSON and every text in them is checked (as for a message: a field that is merely NAMED key,
    like a ticket's key, is not a secret); everything else is checked as a whole file.

    One thing is left out of the check, in the files orch itself wrote (never in the page picture or in a
    file the person added): a code place `module:function:line` such as `secretscan:refuse_if_secret:241`.
    The debug log names them in every error, and the check reads "secret:241" as a password; without this,
    one refused send would make every later report unsendable."""
    for p in _members(folder):
        rel = p.relative_to(folder).as_posix()
        data = p.read_bytes()
        own = not rel.startswith("attachments/")
        wrote = own and not rel.startswith("screen/")  # orch's own writer made it
        try:
            if own and p.suffix in (".json", ".jsonl"):
                text = data.decode("utf-8")
                doc = (
                    json.loads(text)
                    if p.suffix == ".json"
                    else [json.loads(line) for line in text.splitlines() if line.strip()]
                )
                secretscan.refuse_if_secret_in(root, _no_code_places(doc), f"report file {rel}")
                continue
        except ValueError:
            pass  # not what its name says: checked as a plain file
        if wrote and p.suffix == ".md":
            data = _CODE_PLACE.sub("", data.decode("utf-8", "replace")).encode()
        secretscan.refuse_if_secret(data, f"report file {rel}" if own else f"added file {p.name}", root)


def _no_code_places(doc):
    if isinstance(doc, str):
        return _CODE_PLACE.sub("", doc)
    if isinstance(doc, dict):
        return {k: _no_code_places(v) for k, v in doc.items()}
    if isinstance(doc, list):
        return [_no_code_places(v) for v in doc]
    return doc


def pack(folder: Path) -> tuple[bytes, int]:
    """(a plain .tar of the report folder, number of files). Not compressed, so each file stays readable."""
    ref, buf, files = folder.name, io.BytesIO(), _members(folder)
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for p in files:
            info = tarfile.TarInfo(f"{ref}/{p.relative_to(folder).as_posix()}")
            data = p.read_bytes()
            info.size, info.mode, info.mtime = len(data), 0o600, int(p.stat().st_mtime)
            tar.addfile(info, io.BytesIO(data))
    data = buf.getvalue()
    if len(data) > MAX_ARCHIVE:
        raise Refused(
            f"The report is bigger than {MAX_ARCHIVE // 1024 // 1024} MB, so it was not sent. "
            "Make a new one with fewer added files."
        )
    return data, len(files)


def shared(root: Path, ref: str) -> dict | None:
    """Where this report was shared, or None."""
    try:
        got = net.read_json(_folder(root, ref) / SHARED, None)
    except Refused:
        return None
    return got if isinstance(got, dict) and PID.fullmatch(str(got.get("id"))) else None


def preview(root: Path, ref: str) -> dict:
    """What would leave this computer: nothing is sent."""
    folder = _folder(root, ref)
    files = _members(folder)
    man = net.read_json(folder / "manifest.json", {}) or {}
    return {
        "ref": ref,
        "files": len(files),
        "size": sum(p.stat().st_size for p in files),
        "content": bool(man.get("content")),
        "attachments": [a.get("name") for a in man.get("attachments") or [] if isinstance(a, dict)],
        "page": (folder / "screen" / "page.html").is_file(),
    }


def share(root: Path, ref: str) -> dict:
    """Send one report to the relay. The same report again changes nothing there."""
    folder = _folder(root, ref)
    man = net.read_json(folder / "manifest.json", None)
    if not isinstance(man, dict) or man.get("kind") != "report":
        raise Refused("Only a report a person or helper made can be shared. Make one: orch diag report")
    net.load_service(root, "relay")  # a clear "not connected" before any work
    scan(root, folder)
    data, n = pack(folder)
    cfg = net.load_service(root, "relay")
    # not through relay._api: its whole-file check reads the archive as one text and takes every JSON
    # field named
    # "key" for a secret. scan() above checked each file of this archive instead.
    blob = net.call_json("POST", cfg["url"] + "/v1/blobs", net.auth_headers(cfg), data, 300)[1]
    sha = hashlib.sha256(data).hexdigest()
    if blob.get("sha256") != sha or blob.get("size") != len(data):
        raise Refused("The relay stored something different from the report. Not sent. Try again.")
    scope = man.get("scope") if isinstance(man.get("scope"), dict) else {}
    body = {
        "ref": ref,
        "created_at": man.get("created_at"),
        "scope": {"ticket": scope.get("ticket"), "addon": scope.get("addon")},
        "note": man.get("note"),
        "expected": man.get("expected"),
        "more": man.get("more"),
        "problems": [str(x)[:60] for x in (man.get("problems") or [])][:20],
        "summary": (folder / "SUMMARY.md").read_text(encoding="utf-8", errors="replace")[:20000],
        "blob_id": blob["blob_id"],
        "size": len(data),
        "sha256": sha,
        "files": n,
        "attachments": len(man.get("attachments") or []),
        "orch_version": str(man.get("orch_version") or "")[:40] or None,
        "os": str(man.get("os") or "")[:80] or None,
    }
    got = relay._api(root, "POST", "/v1/problems", {k: v for k, v in body.items() if v is not None}, 60)[1]
    pid = got.get("id") if isinstance(got, dict) else None
    if not PID.fullmatch(str(pid)):
        raise Refused("The relay did not confirm the report. Try again.")
    host = net.load_service(root, "relay")["url"].split("://", 1)[-1].split("/", 1)[0]
    net.write_json(folder / SHARED, {"id": pid, "to": host, "files": n, "size": len(data)}, private=True)
    return {"id": pid, "ref": ref, "files": n, "size": len(data), "to": host}


def listing(root: Path, status: str = "new") -> list[dict]:
    if status not in (*STATES, "all"):
        raise Refused("Use new, taken, done or all.")
    return [
        p
        for p in net.items(relay._api(root, "GET", f"/v1/problems?status={status}")[1])
        if isinstance(p, dict)
    ]


def _pid(pid: str) -> str:
    if not PID.fullmatch(str(pid)):
        raise Refused("That is not a shared problem. Their ids start with pb_: orch relay problem list")
    return pid


def set_status(root: Path, pid: str, status: str) -> dict:
    return relay._api(root, "POST", f"/v1/problems/{_pid(pid)}/status", {"status": status})[1]


def _unpack(data: bytes, ref: str, dest: Path) -> int:
    """Plain files of `<ref>/...` into dest (a new folder). Anything else in the archive refuses the
    whole fetch."""
    total = n = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
        for m in tar:
            parts = m.name.split("/")
            if (
                not m.isfile()
                or len(parts) < 2
                or parts[0] != ref
                or any(p in ("", ".", "..") or "\\" in p or ":" in p or p != p.strip() for p in parts)
                or m.name.startswith("/")
            ):
                raise Refused(
                    "That shared problem holds something that is not a plain file. Nothing was kept."
                )
            n, total = n + 1, total + m.size
            if n > MAX_FILES or total > MAX_UNPACKED:
                raise Refused("That shared problem is too big to fetch. Nothing was kept.")
            target = dest.joinpath(*parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            src = tar.extractfile(m)
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_BINARY", 0)
            )
            with os.fdopen(os.open(target, flags, 0o600), "wb") as f:
                shutil.copyfileobj(src, f)
    if n == 0:
        raise Refused("That shared problem is empty. Nothing was kept.")
    return n


def fetch(root: Path, pid: str) -> dict:
    """Fetch a shared problem into this workspace's reports folder. Returns {ref, path, problem}."""
    meta = relay._api(root, "GET", f"/v1/problems/{_pid(pid)}")[1]
    ref = meta.get("ref") if isinstance(meta, dict) else None
    if not isinstance(ref, str) or not REF.fullmatch(ref):
        raise Refused("The relay sent a problem this orch cannot read. Update orch and try again.")
    rdir = diag_report.reports_dir(root)
    for part in (root / ".orch", root / ".orch" / "diag", rdir):
        if part.is_symlink():
            raise Refused(f"{part} is a link. Nothing was fetched.")
    for old in rdir.glob("r-*/" + FROM) if rdir.is_dir() else ():
        got = net.read_json(old, None)
        if isinstance(got, dict) and got.get("id") == pid:  # fetched before: the same folder again
            return {"ref": old.parent.name, "path": str(old.parent), "problem": meta, "new": False}
    cfg = net.load_service(root, "relay")
    _, data = net.call(
        "GET", f"{cfg['url']}/v1/problems/{pid}/file", net.auth_headers(cfg), timeout=300, limit=MAX_ARCHIVE
    )
    if not isinstance(data, bytes) or len(data) != meta.get("size"):
        raise Refused("The report did not arrive whole. Try again.")
    if hashlib.sha256(data).hexdigest() != str(meta.get("sha256")).lower():
        raise Refused("The report changed on the way. Nothing was kept. Try again.")
    rdir.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder = None
    for i in range(1, 50):
        name = ref if i == 1 else f"{ref[:36]}-{i}"
        try:
            (rdir / name).mkdir(mode=0o700)
            folder = rdir / name
            break
        except FileExistsError:
            continue
    if folder is None:
        raise Refused("Too many reports with this name here. Delete old ones: orch diag delete reports")
    try:
        try:
            n = _unpack(data, ref, folder)
        except tarfile.TarError:
            raise Refused("That shared problem could not be read. Nothing was kept.") from None
        keep = ("id", "ref", "from", "from_name", "shared_at", "created_at")
        (folder / FROM).write_text(
            json.dumps({k: meta.get(k) for k in keep}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)  # exactly the folder this call made
        raise
    return {"ref": folder.name, "path": str(folder), "problem": meta, "files": n, "new": True}

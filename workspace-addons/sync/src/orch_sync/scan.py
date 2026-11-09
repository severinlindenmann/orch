"""Secret scan for what the sync add-on would commit or accept (git step 2, design D5). Pure: bytes + path in,
findings out, no git and no files. The caller feeds the FULL bytes of each blob (`git cat-file -p`), never a diff.

A finding with needs_click=False stops the whole step. A finding with needs_click=True ("can't check": an
archive or a file that is neither text nor a known media type) is held until a person clicks Allow once for that
file hash. Findings never contain the matched text.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass

# name -> pattern. Run on the raw bytes (also with NUL bytes removed, which exposes UTF-16 text).
PATTERNS = {
    "orp-token": rb"(?<![A-Za-z0-9_])orp_[A-Za-z0-9_-]{20,}",
    "orn-token": rb"(?<![A-Za-z0-9_])orn_[A-Za-z0-9_-]{20,}",
    "private-key": rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----",
    "github-token": rb"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})",
    "api-key": rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}",
    "aws-key": rb"(?<![A-Za-z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Za-z0-9])",
    "slack-token": rb"(?<![A-Za-z0-9])xox[abprs]-[A-Za-z0-9-]{10,}",
}
TICKET_PATTERNS = {"token-field": rb'"token"\s*:\s*"'}  # any ticket JSON

NEVER_DIRS = {"me", "secrets", "chat", "run", "inbox", "addons", "harness"}
_NAME_RE = re.compile(
    r"^(\.env.*|.*\.(pem|key|p8|p12|pfx|kdbx)|id_rsa.*|id_ed25519.*|credentials.*)$", re.IGNORECASE)
_ARCHIVE_EXT = (".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz", ".7z", ".rar", ".jar", ".war", ".apk")
_ARCHIVE_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"\x1f\x8b", b"7z\xbc\xaf\x27\x1c", b"Rar!\x1a\x07", b"BZh", b"\xfd7zXZ\x00")
_MEDIA_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"%PDF-", b"OggS", b"ID3", b"\x1a\x45\xdf\xa3")
_TICKET_RE = re.compile(r"^tickets/t_[a-z0-9]{6,16}\.json$")


@dataclass(frozen=True)
class Finding:
    path: str
    code: str  # "path" | "secret" | "cannot-check"
    rule: str
    needs_click: bool = False
    sha256: str = ""  # cannot-check only: the hash the click approves


def _is_media(data):
    return data.startswith(_MEDIA_MAGIC) or (data[:4] == b"RIFF" and data[8:12] in (b"WEBP", b"WAVE", b"AVI ")) \
        or data[4:8] == b"ftyp"


def _is_text(data):
    if b"\x00" in data[:8192] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False
    for enc in ("utf-8", "utf-16"):
        try:
            data.decode(enc)
            return True
        except UnicodeDecodeError:
            pass
    return False


_IGNORABLE = {0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x3164, 0xFFA0}
_IGNORABLE_RANGES = ((0x180B, 0x180F), (0xFE00, 0xFE0F), (0xE0100, 0xE01EF), (0xFFF0, 0xFFF8))


def _ignorable(c):
    o = ord(c)
    return (unicodedata.category(c) == "Cf" or o in _IGNORABLE
            or any(a <= o <= b for a, b in _IGNORABLE_RANGES))


def norm_segment(seg):
    """The one form every path comparison uses: NFKC, default-ignorable code points (zero-width etc.) removed,
    casefolded. macOS/Windows are case-insensitive and Unicode-normalizing, so `Secrets`, `se\u200bcrets` and
    an NFD spelling all name the same folder there."""
    seg = "".join(c for c in unicodedata.normalize("NFKC", seg) if not _ignorable(c))
    return unicodedata.normalize("NFKC", seg.casefold())


def norm_path(path):
    """Normalized segments (list), or None when the path is unsafe: absolute, backslash, drive letter, empty,
    '.' or '..' segment (also after normalization), or a control character."""
    if (not path or path.startswith(("/", "\\")) or "\\" in path or re.match(r"^[A-Za-z]:", path)
            or any(unicodedata.category(c) in ("Cc", "Zl", "Zp") for c in path)):
        return None
    parts = [norm_segment(p) for p in path.split("/")]
    if any(p in ("", ".", "..") for p in parts) or any(p in ("", ".", "..") for p in path.split("/")):
        return None
    return parts


def scan_path(path):
    """Path rules only. Findings for a path that must never be synced."""
    parts = norm_path(path)
    if parts is None:
        return [Finding(path, "path", "unsafe-path")]
    out = []
    if parts[0] in NEVER_DIRS:
        out.append(Finding(path, "path", "never-synced-folder"))
    if any(_NAME_RE.match(p) for p in parts):
        out.append(Finding(path, "path", "secret-file-name"))
    return out


def scan_blob(path, data):
    """All findings for one blob: path rules, token forms in the full bytes, archives and unreadable files."""
    out = scan_path(path)
    haystacks = [data] + ([data.replace(b"\x00", b"")] if b"\x00" in data else [])
    pats = dict(PATTERNS)
    parts = norm_path(path)
    if parts is not None and _TICKET_RE.match("/".join(parts)):
        pats.update(TICKET_PATTERNS)
    for name in sorted(pats):
        if any(re.search(pats[name], h) for h in haystacks):
            out.append(Finding(path, "secret", name))
    low = path.lower()
    archive = low.endswith(_ARCHIVE_EXT) or data.startswith(_ARCHIVE_MAGIC) or data[257:262] == b"ustar"
    if archive or not (_is_media(data) or _is_text(data)):
        out.append(Finding(path, "cannot-check", "archive" if archive else "unknown-format", True,
                           hashlib.sha256(data).hexdigest()))
    return out


def blocking(findings, allowed_hashes=()):
    """The findings that stop the step: everything except cannot-check ones whose hash a person allowed."""
    return [f for f in findings if not (f.needs_click and f.sha256 in set(allowed_hashes))]

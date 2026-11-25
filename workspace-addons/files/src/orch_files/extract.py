"""What kind a file is, and the plain text inside it for search (standard library only).

Kinds follow the kit's result widgets (results.js TYPES): md, text, code, data, table, page, pdf, picture, video,
audio, change, archive, file. Word and PowerPoint files are read as text from their XML; an Excel sheet as rows.
"""

from __future__ import annotations

import contextlib
import io
import re
import zipfile
import zlib
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

TEXT_LIMIT = 2 * 1024 * 1024  # text is read from the first 2 MB only
NAME_ONLY = 50 * 1024 * 1024  # bigger files are listed by name only
ZIP_MEMBER = 8 * 1024 * 1024  # never inflate more than this from one part of a zip file
MAX_COLS = 200  # columns read from one sheet row
MAX_CELLS = 200_000  # cells read from one sheet

EXT = {
    "md": ("md", "markdown", "mdx"),
    "text": ("txt", "log", "out", "rst", "tex", "srt", "vtt"),
    "code": (
        "py",
        "js",
        "mjs",
        "cjs",
        "ts",
        "tsx",
        "jsx",
        "sh",
        "bash",
        "zsh",
        "ps1",
        "css",
        "scss",
        "sql",
        "rs",
        "go",
        "rb",
        "java",
        "swift",
        "kt",
        "c",
        "h",
        "cpp",
        "hpp",
        "cs",
        "php",
        "toml",
        "ini",
        "cfg",
        "conf",
        "xml",
        "vue",
        "svelte",
        "lua",
        "r",
        "dart",
    ),
    "data": ("json", "jsonl", "yaml", "yml", "ndjson"),
    "table": ("csv", "tsv", "xlsx"),
    "page": ("html", "htm"),
    "pdf": ("pdf",),
    "picture": ("png", "jpg", "jpeg", "gif", "webp", "svg", "avif", "bmp", "ico"),
    "video": ("mp4", "webm", "mov", "m4v", "ogv"),
    "audio": ("mp3", "wav", "m4a", "ogg", "oga", "aac", "flac", "caf"),
    "change": ("diff", "patch"),
    "archive": ("zip", "tar", "gz", "tgz", "7z", "rar", "bz2", "xz"),
    "doc": ("docx", "pptx", "odt"),
}
KIND_OF_EXT = {e: k for k, exts in EXT.items() for e in exts}
CODE_NAMES = {"makefile", "dockerfile", "procfile", "gemfile", "justfile", "license", "readme", "changelog"}
WORDS = {
    "md": "Document",
    "text": "Text",
    "code": "Code",
    "data": "Data",
    "table": "Table",
    "page": "Web page",
    "pdf": "PDF",
    "picture": "Picture",
    "video": "Video",
    "audio": "Audio",
    "change": "Change",
    "archive": "Archive",
    "doc": "Document",
    "file": "Other file",
}
EXT_WORDS = {
    "xlsx": "Excel sheet",
    "docx": "Word document",
    "pptx": "Slides",
    "odt": "Document",
    "svg": "Drawing",
}


def ext_of(name: str) -> str:
    base = name.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base.lstrip(".") else ""


def kind_of(name: str) -> str:
    e = ext_of(name)
    if e in KIND_OF_EXT:
        return KIND_OF_EXT[e]
    if not e and name.rsplit("/", 1)[-1].lower() in CODE_NAMES:
        return "text"
    return "file"


def word_of(name: str, kind: str) -> str:
    return EXT_WORDS.get(ext_of(name)) or WORDS.get(kind, "Other file")


def looks_text(data: bytes) -> bool:
    head = data[:8192]
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError as e:
        return e.start > len(head) - 4  # a character cut at the end of the window


def decode(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8", "replace")


class _HTMLText(HTMLParser):
    SKIP = frozenset({"script", "style", "noscript", "template"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.title: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "title":
            self.in_title = True
        elif tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        elif not self.skip:
            self.out.append(data)


def html_text(src: str) -> tuple[str, str | None]:
    p = _HTMLText()
    with contextlib.suppress(Exception):  # a broken page still gives what was read so far
        p.feed(src)
        p.close()
    text = re.sub(r"[ \t]+", " ", "".join(p.out))
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    title = " ".join("".join(p.title).split()) or None
    return text, title


def _zip_part(z: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > ZIP_MEMBER:
        return None
    with z.open(info) as f:
        return f.read(ZIP_MEMBER + 1)[:ZIP_MEMBER]


def _parse(data: bytes):
    """An Office XML part as a tree. Office files never declare entities: a part that does is refused (no entity
    expansion of any size, on top of expat's own limits)."""
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ET.ParseError("entities are not read")
    return ET.fromstring(data)


def _xml_texts(data: bytes, tag: str, para: str) -> list[str]:
    """The text of every `para` element (joined runs of `tag`), from an Office XML part."""
    try:
        root = _parse(data)
    except ET.ParseError:
        return []
    out = []
    for p in root.iter():
        if p.tag.endswith("}" + para):
            t = "".join(x.text or "" for x in p.iter() if x.tag.endswith("}" + tag))
            if t.strip():
                out.append(t)
    return out


def office_text(data: bytes, ext: str) -> str:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError):
        return ""
    with z:
        if ext == "docx":
            part = _zip_part(z, "word/document.xml")
            return "\n".join(_xml_texts(part, "t", "p")) if part else ""
        if ext == "odt":
            part = _zip_part(z, "content.xml")
            return "\n".join(_xml_texts(part, "span", "p") or _xml_texts(part, "p", "p")) if part else ""
        if ext == "pptx":
            names = sorted(
                (n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)),
            )
            out = []
            for i, n in enumerate(names[:200], 1):
                part = _zip_part(z, n)
                lines = _xml_texts(part, "t", "p") if part else []
                if lines:
                    out.append(f"Slide {i}")
                    out.extend(lines)
            return "\n".join(out)
    return ""


def xlsx_rows(data: bytes, max_rows: int = 500, sheet: int = 1) -> tuple[list[list[str]], list[str]]:
    """The rows of one sheet (strings), at most max_rows, and the sheet names."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError):
        return [], []
    with z:
        shared: list[str] = []
        part = _zip_part(z, "xl/sharedStrings.xml")
        if part:
            try:
                for si in _parse(part):
                    shared.append("".join(x.text or "" for x in si.iter() if x.tag.endswith("}t")))
            except ET.ParseError:
                pass
        names: list[str] = []
        wb = _zip_part(z, "xl/workbook.xml")
        if wb:
            try:
                names = [s.get("name") or "" for s in _parse(wb).iter() if s.tag.endswith("}sheet")]
            except ET.ParseError:
                names = []
        part = _zip_part(z, f"xl/worksheets/sheet{sheet}.xml")
        if not part:
            return [], names
        rows: list[list[str]] = []
        cells = 0
        try:
            root = _parse(part)
        except ET.ParseError:
            return [], names
        for r in root.iter():
            if not r.tag.endswith("}row"):
                continue
            row: list[str] = []
            for c in r:
                if not c.tag.endswith("}c"):
                    continue
                col = _col(c.get("r") or "")
                if col is not None and col >= MAX_COLS:
                    continue  # far-right cells: never padded out to (a crafted sheet could ask for millions)
                while col is not None and len(row) < col:
                    row.append("")
                v = next((x for x in c if x.tag.endswith("}v")), None)
                isv = next((x for x in c if x.tag.endswith("}is")), None)
                if c.get("t") == "s" and v is not None and (v.text or "").isdigit():
                    i = int(v.text)
                    row.append(shared[i] if i < len(shared) else "")
                elif isv is not None:
                    row.append("".join(x.text or "" for x in isv.iter() if x.tag.endswith("}t")))
                else:
                    row.append(v.text or "" if v is not None else "")
            rows.append(row)
            cells += len(row)
            if len(rows) >= max_rows or cells >= MAX_CELLS:
                break
        return rows, names


def _col(ref: str) -> int | None:
    m = re.match(r"([A-Z]{1,3})", ref)
    if not m:
        return None
    n = 0
    for ch in m.group(1):
        n = n * 26 + ord(ch) - 64
    return n - 1


def pdf_text(data: bytes) -> str:
    """The text of a PDF's pages when a PDF reader (pypdf) is installed; else nothing (found by name only)."""
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except ImportError:
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        out = []
        for page in reader.pages[:200]:
            out.append(page.extract_text() or "")
            if sum(map(len, out)) > TEXT_LIMIT:
                break
        return "\n".join(out)
    except Exception:  # noqa: BLE001 - a broken or locked PDF is found by name only
        return ""


ZIP_PARTS = 5000  # parts of one zip file the secret check opens; more than this cannot be checked
ZIP_TOTAL = 256 * 1024 * 1024  # inflated bytes the secret check reads from one zip file
_RUN = re.compile(rb"[\x20-\x7e\t\r\n]{8,}")
_PDF_STREAM = re.compile(rb"<<((?:(?!stream\b).)*?)>>\s*stream\r?\n(.*?)\r?\n?endstream", re.DOTALL)
_PDF_STRING = re.compile(rb"\((?:\\.|[^\\()])*\)", re.DOTALL)
_PDF_UNREADABLE = re.compile(rb"/(?:LZWDecode|ASCII85Decode|ASCIIHexDecode|Crypt)\b|/Encrypt\b")
_XMLISH = (".xml", ".rels", ".vml", ".txt", ".csv", ".json", ".html", ".htm")


def _printable(data: bytes) -> str:
    """The readable runs inside binary bytes (an embedded object, an old Word file): a secret in them is plain."""
    return "\n".join(m.group().decode("ascii") for m in _RUN.finditer(data))


def _part_text(name: str, data: bytes) -> str:
    """Everything a zip part can show: XML parts raw and as their joined text (a key split over several runs is
    whole again), other parts as their readable runs."""
    if not name.lower().endswith(_XMLISH):
        return _printable(data)
    utf16 = data[:2] in (b"\xff\xfe", b"\xfe\xff")
    raw = data.decode("utf-16" if utf16 else "utf-8", "replace")
    if utf16 or b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        return raw
    try:
        joined = "".join(ET.fromstring(data).itertext())
    except ET.ParseError:
        return raw
    return raw + "\n" + joined


def office_scan(data: bytes) -> str | None:
    """All the text of a zip-based Office file for the secret check: every part, no row or paragraph caps. None
    when a part cannot be read (broken, locked, too big): the file is then treated as not checked."""
    if data[:2] != b"PK":
        return _printable(data)  # an old binary Office file: no zip, but its text is read
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError):
        return None
    out = []
    total = 0
    with z:
        infos = z.infolist()
        if len(infos) > ZIP_PARTS:
            return None
        for info in infos:
            if info.is_dir():
                continue
            if info.file_size > ZIP_MEMBER:
                return None
            try:
                with z.open(info) as f:
                    part = f.read(ZIP_MEMBER + 1)
            except Exception:  # noqa: BLE001 - bad CRC, encrypted, unknown compression: not checked
                return None
            total += len(part)
            if len(part) > ZIP_MEMBER or total > ZIP_TOTAL:
                return None
            out.append(_part_text(info.filename, part))
    return "\n".join(out)


def pdf_scan(data: bytes) -> str | None:
    """All the text of a PDF for the secret check: the file's own readable text, every Flate stream inflated (page
    content, object streams, metadata) with its strings joined, and the reader's page text when pypdf is there.
    None when it cannot be read (encrypted, an encoding we do not open, a broken stream)."""
    if not data.lstrip().startswith(b"%PDF") or _PDF_UNREADABLE.search(data):
        return None
    out = [_printable(data)]
    total = 0
    for m in _PDF_STREAM.finditer(data):
        if b"/FlateDecode" not in m.group(1):
            continue
        try:
            d = zlib.decompressobj()
            body = d.decompress(m.group(2), ZIP_MEMBER)
        except zlib.error:
            return None
        total += len(body)
        if d.unconsumed_tail or total > ZIP_TOTAL:
            return None
        out.append(_printable(body))
        strings = b"".join(s[1:-1] for s in _PDF_STRING.findall(body))
        if strings:
            out.append(strings.decode("latin-1"))
    out.append(pdf_text(data))
    return "\n".join(out)


def zip_names(data: bytes, limit: int = 200) -> list[tuple[str, int]]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError):
        return []
    with z:
        return [(i.filename, i.file_size) for i in z.infolist()[:limit]]


def md_title(text: str) -> str | None:
    for line in text.splitlines()[:40]:
        m = re.match(r"\s{0,3}#{1,3}\s+(.+?)\s*#*\s*$", line)
        if m:
            return m.group(1).strip()[:160] or None
    return None


def text_of(name: str, kind: str, data: bytes) -> tuple[str, str, str | None]:
    """(kind, text for search, title or None) from the first bytes of a file. A file of an unknown kind that
    holds plain text is read as text."""
    e = ext_of(name)
    if kind in ("md", "text", "code", "data", "change") or (kind == "table" and e != "xlsx"):
        if not looks_text(data):
            return kind, "", None
        t = decode(data[:TEXT_LIMIT])
        return kind, t, md_title(t) if kind == "md" else None
    if kind == "page":
        t, title = html_text(decode(data[:TEXT_LIMIT]))
        return kind, t, title
    if kind == "doc":
        t = office_text(data, e)[:TEXT_LIMIT]
        first = next((x.strip() for x in t.splitlines() if x.strip() and not x.startswith("Slide ")), "")
        return kind, t, first if 0 < len(first) <= 120 else None
    if e == "xlsx":
        rows, _ = xlsx_rows(data, max_rows=5000)
        return kind, "\n".join("\t".join(r) for r in rows)[:TEXT_LIMIT], None
    if kind == "pdf":
        return kind, pdf_text(data)[:TEXT_LIMIT], None
    if e == "svg":
        return kind, "", None
    if kind == "file" and data and looks_text(data):
        return "text", decode(data[:TEXT_LIMIT]), None
    return kind, "", None


def needs_bytes(kind: str, name: str) -> int:
    """How many bytes the text step must read (whole zip-based files, the head of text files, none for media)."""
    e = ext_of(name)
    if kind in ("doc", "pdf") or e == "xlsx":
        return NAME_ONLY
    if kind in ("picture", "video", "audio", "archive"):
        return 0
    return TEXT_LIMIT

"""A small, cached index of a folder of Markdown notes."""

from __future__ import annotations

import os
import re
import tempfile
import threading
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlencode

from .runfiles import is_link

HELPERS_DIR = "From helpers"
_MAX_BYTES = 1024 * 1024
_LINK = re.compile(r"\[\[([^\]\n]+)\]\]")


class Refused(Exception):
    """An operation the person can fix or choose not to do."""


@dataclass(frozen=True)
class Note:
    id: str
    title: str
    group: str
    changed: float
    links: tuple[str, ...]
    linked_from: tuple[str, ...]


_SHARED: dict[Path, Vault] = {}
_SHARED_LOCK = threading.Lock()


def shared(folder: str | Path) -> Vault:
    """One Vault per folder for the whole process, so the index survives between requests.

    Each call still checks the folder (a stat per file), so a changed, added or removed note shows at once."""
    key = Path(folder).resolve()
    with _SHARED_LOCK:
        vault = _SHARED.get(key)
        if vault is None:
            vault = _SHARED[key] = Vault(key)
    if not key.is_dir():
        raise Refused("This notes folder does not exist; choose an existing folder.")
    return vault


class Vault:
    def __init__(self, folder: str | Path):
        self.folder = Path(folder).resolve()
        if not self.folder.is_dir():
            raise Refused("This notes folder does not exist; choose an existing folder.")
        self._lock = threading.RLock()
        self._folded: dict[str, str] = {}
        self._fingerprint: dict[str, tuple[int, int]] | None = None
        self._notes: dict[str, Note] = {}
        self._texts: dict[str, str] = {}
        self._titles: dict[str, list[str]] = {}

    def _path(self, note_id: str) -> Path:
        parts = note_id.split("/")
        if any(not part or part.startswith(".") or "\\" in part for part in parts):
            raise Refused("This note is outside the notes folder; choose a note inside it.")
        path = self.folder
        for part in (*parts[:-1], parts[-1] + ".md"):
            path = path / part
            if is_link(path):
                raise Refused("This note uses a shortcut; choose a note directly inside the notes folder.")
        if not path.resolve().is_relative_to(self.folder):
            raise Refused("This note is outside the notes folder; choose a note inside it.")
        return path

    def _refresh(self) -> None:
        with self._lock:
            self._refresh_locked()

    def _refresh_locked(self) -> None:
        fingerprint: dict[str, tuple[int, int]] = {}
        changed: dict[str, float] = {}

        def walk(folder: str | Path, prefix: str = "") -> None:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if entry.name.startswith(".") or entry.is_symlink() or is_link(Path(entry.path)):
                        continue
                    relative = prefix + entry.name
                    if entry.is_dir(follow_symlinks=False):
                        walk(entry.path, relative + "/")
                    elif entry.name.endswith(".md") and entry.is_file(follow_symlinks=False):
                        stat = entry.stat(follow_symlinks=False)
                        fingerprint[relative[:-3]] = (stat.st_mtime_ns, stat.st_size)
                        changed[relative[:-3]] = stat.st_mtime

        try:
            walk(self.folder)
            if fingerprint == self._fingerprint:
                return
            texts: dict[str, str] = {}
            notes: dict[str, Note] = {}
            titles: dict[str, list[str]] = {}
            for note_id in sorted(fingerprint):
                if fingerprint[note_id][1] > _MAX_BYTES:
                    continue  # a very large file is not a note to look things up in: skipped, never refused
                with self._path(note_id).open("rb") as stream:
                    data = stream.read(_MAX_BYTES + 1)
                if len(data) > _MAX_BYTES:
                    continue
                texts[note_id] = data.decode("utf-8", errors="replace")
                title = note_id.rsplit("/", 1)[-1]
                group = note_id.split("/", 1)[0] if "/" in note_id else ""
                notes[note_id] = Note(note_id, title, group, changed[note_id], (), ())
                titles.setdefault(title.casefold(), []).append(note_id)
            incoming: dict[str, list[str]] = {note_id: [] for note_id in notes}
            for note_id, body in texts.items():
                links: dict[str, None] = {}
                fence = 0
                for line in body.splitlines():
                    marker = re.match(r"^\s*(`{3,})(.*)$", line)
                    if marker:
                        if not fence:
                            fence = len(marker[1])
                        elif len(marker[1]) >= fence and not marker[2].strip():
                            fence = 0
                        continue
                    if fence:
                        continue
                    for match in _LINK.finditer(line):
                        target = re.split(r"[|#]", match[1], maxsplit=1)[0].strip()
                        candidates = titles.get(target.casefold(), [])
                        resolved = (
                            target if target in notes else candidates[0] if len(candidates) == 1 else None
                        )
                        if resolved is not None:
                            links[resolved] = None
                notes[note_id] = replace(notes[note_id], links=tuple(links))
                for target in links:
                    incoming[target].append(note_id)
            for note_id, sources in incoming.items():
                sources.sort(key=lambda source: (notes[source].title.casefold(), source))
                notes[note_id] = replace(notes[note_id], linked_from=tuple(sources))
            self._folded = {i: (notes[i].title + "\n" + t).casefold() for i, t in texts.items()}
            self._notes, self._texts, self._titles = notes, texts, titles
            self._fingerprint = fingerprint
        except OSError as exc:
            raise Refused(
                "The notes folder could not be read; check that it is available and try again."
            ) from exc

    def notes(self, group: str | None = None) -> list[Note]:
        self._refresh()
        return sorted(
            (note for note in self._notes.values() if group is None or note.group == group),
            key=lambda note: (-note.changed, note.id),
        )

    def groups(self) -> list[tuple[str, int]]:
        self._refresh()
        counts: dict[str, int] = {}
        for note in self._notes.values():
            counts[note.group] = counts.get(note.group, 0) + 1
        return sorted(counts.items())

    def get(self, ref: str) -> Note:
        self._refresh()
        if ref in self._notes:
            return self._notes[ref]
        matches = self._titles.get(ref.casefold(), [])
        if len(matches) == 1:
            return self._notes[matches[0]]
        if matches:
            raise Refused(f"Several notes have this name; choose one of these paths: {', '.join(matches)}.")
        raise Refused("This note was not found; choose an existing note from the folder.")

    def text(self, note_id: str) -> str:
        self._refresh()
        self._path(note_id)
        if note_id not in self._texts:
            raise Refused("This note was not found; choose an existing note from the folder.")
        return self._texts[note_id]

    def find(self, words: str, limit: int = 20) -> list[tuple[Note, str]]:
        self._refresh()
        terms = words.casefold().split()
        if not terms or limit <= 0:
            return []
        found: list[tuple[Note, str]] = []
        for note in self._notes.values():
            if not all(term in self._folded[note.id] for term in terms):
                continue
            body = self._texts[note.id]
            snippet = note.title
            for line in body.splitlines():
                collapsed = " ".join(line.split())
                positions = [collapsed.casefold().find(term) for term in terms]
                hits = [position for position in positions if position >= 0]
                if hits:
                    start = max(0, min(hits) - 60)
                    snippet = collapsed[start : start + 160]
                    break
            found.append((note, snippet[:160]))
        found.sort(
            key=lambda hit: (
                not any(term in hit[0].title.casefold() for term in terms),
                -hit[0].changed,
                hit[0].id,
            )
        )
        return found[:limit]

    def _write(self, path: Path, text: str, *, new: bool) -> None:
        data = text.encode("utf-8")
        if len(data) > _MAX_BYTES:
            raise Refused("This note is larger than 1 MB; shorten it and try again.")
        temporary: str | None = None
        reserved = False
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".note-", delete=False) as stream:
                temporary = stream.name
                stream.write(data)
            if new:
                try:
                    with path.open("x", encoding="utf-8"):
                        pass
                    reserved = True
                except FileExistsError as exc:
                    raise Refused(
                        "A note with this name exists already in From helpers. Choose another name."
                    ) from exc
            os.replace(temporary, path)
            reserved = False
        except OSError as exc:
            raise Refused(
                "This note could not be saved; check the folder is writable and try again."
            ) from exc
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
            if reserved:
                path.unlink(missing_ok=True)

    def write_new(self, title: str, text: str) -> Note:
        title = "".join(
            char for char in title if char not in '/\\:*?"<>|' and unicodedata.category(char) != "Cc"
        )
        title = title.strip().lstrip(".").strip()[:120].rstrip(" .")
        if not title:
            raise Refused("This note needs a name; enter a title with letters or numbers.")
        path = self._path(f"{HELPERS_DIR}/{title}")
        try:
            path.parent.mkdir(exist_ok=True)
        except OSError as exc:
            raise Refused("From helpers could not be opened; choose a writable notes folder.") from exc
        self._write(path, text, new=True)
        return self.get(f"{HELPERS_DIR}/{title}")

    def change(self, note_id: str, text: str) -> Note:
        path = self._path(note_id)
        helpers = self.folder / HELPERS_DIR
        if is_link(helpers) or not path.resolve().is_relative_to(helpers.resolve()):
            raise Refused("Only notes in From helpers can be changed; create a note there instead.")
        self._refresh()
        if note_id not in self._notes:
            raise Refused("This note was not found; choose an existing note from From helpers.")
        self._write(path, text, new=False)
        return self.get(note_id)

    def app_link(self, note_id: str) -> str | None:
        note = self.get(note_id)
        settings = self.folder / ".obsidian"
        if is_link(settings) or not settings.exists():
            return None
        return "obsidian://open?" + urlencode({"vault": self.folder.name, "file": note.id})

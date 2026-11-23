"""Notes work without an installed add-on or a shared conftest."""

import os
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from orch_personal.notes import HELPERS_DIR, Refused, Vault


def put(folder: Path, name: str, text: str = "", changed: float = 1000) -> Path:
    path = folder / (name + ".md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (changed, changed))
    return path


def test_ids_groups_and_order(tmp_path: Path) -> None:
    put(tmp_path, "Projects/Helvetia Logistik", changed=2000)
    put(tmp_path, "Projects/Sub/Überblick")
    put(tmp_path, "Root note")
    vault = Vault(tmp_path)
    assert [note.id for note in vault.notes()] == [
        "Projects/Helvetia Logistik",
        "Projects/Sub/Überblick",
        "Root note",
    ]
    assert vault.groups() == [("", 1), ("Projects", 2)]
    assert len(vault.notes("Projects")) == 2
    assert vault.get("überblick").title == "Überblick"
    assert vault.notes("missing") == []


def test_links_and_backlinks(tmp_path: Path) -> None:
    put(tmp_path, "Projects/Target")
    put(tmp_path, "Hidden link")
    put(tmp_path, "Alpha", "[[Target|alias]] [[Target#heading]] [[Projects/Target]] [[missing]]")
    put(tmp_path, "Zulu", "[[target]]\n```python\n[[Hidden link]]\n```\n[[Alpha]]")
    vault = Vault(tmp_path)
    assert vault.get("Alpha").links == ("Projects/Target",)
    assert vault.get("Zulu").links == ("Projects/Target", "Alpha")
    assert vault.get("Target").linked_from == ("Alpha", "Zulu")
    assert vault.get("Hidden link").linked_from == ()


def test_ambiguous_and_exact_refs(tmp_path: Path) -> None:
    put(tmp_path, "A/Same")
    put(tmp_path, "B/Same")
    put(tmp_path, "Source", "[[Same]] [[A/Same]]")
    vault = Vault(tmp_path)
    with pytest.raises(Refused, match="A/Same.*B/Same"):
        vault.get("same")
    assert vault.get("Source").links == ("A/Same",)
    assert vault.get("A/Same").id == "A/Same"
    with pytest.raises(Refused, match="not found"):
        vault.get("missing")


def test_hidden_paths_and_non_markdown(tmp_path: Path) -> None:
    for name in (".trash/Deleted", ".git/Secret", "A/.hidden/Note", "A/.secret", ".obsidian/Config"):
        put(tmp_path, name)
    put(tmp_path, "Visible")
    (tmp_path / "other.txt").write_text("other", encoding="utf-8")
    assert [note.id for note in Vault(tmp_path).notes()] == ["Visible"]


@pytest.mark.skipif(sys.platform == "win32", reason="Windows symlinks may require administrator rights")
def test_symlinks_skipped_and_refused(tmp_path: Path) -> None:
    folder = tmp_path / "vault"
    folder.mkdir()
    outside = put(tmp_path, "Outside", "private")
    put(folder, "Real", "visible")
    (folder / "Alias.md").symlink_to(outside)
    (folder / "Directory").symlink_to(tmp_path, target_is_directory=True)
    (folder / HELPERS_DIR).symlink_to(tmp_path, target_is_directory=True)
    vault = Vault(folder)
    assert [note.id for note in vault.notes()] == ["Real"]
    with pytest.raises(Refused):
        vault.write_new("New", "text")
    with pytest.raises(Refused):
        vault.change("From helpers/Outside", "changed")
    with pytest.raises(Refused):
        vault.text("Alias")
    assert outside.read_text() == "private"


def test_find_ranking_and_snippets(tmp_path: Path) -> None:
    put(tmp_path, "Needle title", "Some\t spaced   TEXT with needle", changed=1000)
    put(tmp_path, "Recent", "needle text", changed=3000)
    put(tmp_path, "Older", "x" * 200 + " needle text " + "y" * 200, changed=2000)
    put(tmp_path, "Incomplete", "needle", changed=4000)
    vault = Vault(tmp_path)
    results = vault.find("NEEDLE text")
    assert [note.id for note, _ in results] == ["Needle title", "Recent", "Older"]
    assert results[0][1] == "Some spaced TEXT with needle"
    assert "needle" in results[2][1]
    assert all("\n" not in snippet and len(snippet) <= 160 for _, snippet in results)
    assert len(vault.find("needle", limit=1)) == 1
    assert vault.find(" ") == []
    assert vault.find("needle", limit=0) == []


def test_write_new_sanitising_collision_and_folder(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    note = vault.write_new(' .. /\\:*?"<>|Hello\x00 World ', "new text")
    assert note.id == "From helpers/Hello World"
    assert vault.text(note.id) == "new text"
    with pytest.raises(
        Refused, match="A note with this name exists already in From helpers. Choose another name."
    ):
        vault.write_new("Hello World", "replacement")
    assert vault.text(note.id) == "new text"
    assert len(vault.write_new("a" * 200, "").title) == 120
    with pytest.raises(Refused, match="needs a name"):
        vault.write_new("... /\x00", "")
    assert not list((tmp_path / HELPERS_DIR).glob(".note-*"))


def test_change_only_helpers_and_no_traversal(tmp_path: Path) -> None:
    put(tmp_path, "Root", "original")
    put(tmp_path, "From helpers/Sub/Editable", "old")
    vault = Vault(tmp_path)
    assert vault.change("From helpers/Sub/Editable", "new").id == "From helpers/Sub/Editable"
    assert vault.text("From helpers/Sub/Editable") == "new"
    for note_id in ("Root", "From helpers/../Root", "../Root", "/Root", "From helpers/missing"):
        with pytest.raises(Refused):
            vault.change(note_id, "bad")
    assert vault.text("Root") == "original"


def test_cache_invalidation_and_reuse(tmp_path: Path) -> None:
    path = put(tmp_path, "First", "old")
    vault = Vault(tmp_path)
    first = vault.get("First")
    assert vault.get("First") is first
    path.write_text("new body [[Second]]", encoding="utf-8")
    put(tmp_path, "Second")
    assert vault.text("First") == "new body [[Second]]"
    assert vault.get("First").links == ("Second",)
    assert vault.get("First") is not first
    path.unlink()
    assert [note.id for note in vault.notes()] == ["Second"]


def test_size_only_invalidation(tmp_path: Path) -> None:
    path = put(tmp_path, "Note", "a")
    vault = Vault(tmp_path)
    assert vault.text("Note") == "a"
    put(tmp_path, "Note", "longer", changed=path.stat().st_mtime)
    assert vault.text("Note") == "longer"


def test_app_link(tmp_path: Path) -> None:
    put(tmp_path, "Projects/Über uns")
    vault = Vault(tmp_path)
    assert vault.app_link("Projects/Über uns") is None
    (tmp_path / ".obsidian").mkdir()
    link = vault.app_link("Projects/Über uns")
    assert link is not None
    assert parse_qs(urlparse(link).query) == {"vault": [tmp_path.name], "file": ["Projects/Über uns"]}
    assert " " not in link and "Über" not in link


def test_missing_folder_and_size_limits(tmp_path: Path) -> None:
    with pytest.raises(Refused, match="existing folder"):
        Vault(tmp_path / "missing")
    vault = Vault(tmp_path)
    note = vault.write_new("Limit", "a" * (1024 * 1024))
    with pytest.raises(Refused, match="larger than 1 MB"):
        vault.change(note.id, "é" * (512 * 1024 + 1))
    with pytest.raises(Refused, match="larger than 1 MB"):
        vault.write_new("Too big", "a" * (1024 * 1024 + 1))
    assert not (tmp_path / HELPERS_DIR / "Too big.md").exists()
    put(tmp_path, "Oversize", "a" * (1024 * 1024 + 1))
    assert "Oversize" not in {n.id for n in vault.notes()}  # skipped, the rest of the folder still works


def test_replacement_decoding(tmp_path: Path) -> None:
    (tmp_path / "Broken.md").write_bytes(b"hello\xff")
    assert Vault(tmp_path).text("Broken") == "hello\ufffd"


def test_warm_3000_notes_under_300ms(tmp_path: Path) -> None:
    for index in range(3000):
        put(tmp_path, f"Group {index % 10}/Note {index}", "a" * 2048)
    vault = Vault(tmp_path)
    assert len(vault.notes()) == 3000
    started = time.perf_counter()
    notes = vault.notes()
    elapsed = time.perf_counter() - started
    assert len(notes) == 3000
    assert elapsed < 0.3, f"Warm scan took {elapsed:.3f}s"


def test_shared_index_survives_between_requests_and_sees_changes(tmp_path: Path, monkeypatch) -> None:
    from orch_personal import notes as notes_mod

    for n in range(2000):
        put(tmp_path, f"Group {n % 10}/Note {n}", f"text {n} [[Note {(n + 1) % 2000}]]", changed=1000 + n)
    first = notes_mod.shared(tmp_path)
    assert len(first.notes()) == 2000
    opened = []
    real = Path.open
    monkeypatch.setattr(Path, "open", lambda self, *a, **k: (opened.append(self), real(self, *a, **k))[1])
    again = notes_mod.shared(tmp_path)
    assert again is first
    assert len(again.notes()) == 2000
    assert opened == []  # the second request reads no note file again
    put(tmp_path, "Fresh", "brand new", changed=9999)
    assert again.notes()[0].id == "Fresh"  # a changed folder still shows at once
    assert [n.id for n, _ in again.find("brand new")] == ["Fresh"]


def test_find_is_fast_with_2000_notes(tmp_path: Path) -> None:
    for n in range(2000):
        put(tmp_path, f"Note {n}", "lorem ipsum " * 200 + ("needle" if n == 1234 else ""))
    vault = Vault(tmp_path)
    vault.notes()
    start = time.perf_counter()
    hits = vault.find("needle")
    assert [n.id for n, _ in hits] == ["Note 1234"]
    assert time.perf_counter() - start < 1.0

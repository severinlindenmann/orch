"""#922: when the stored keys can't be read, sends skip ONLY the stored-key comparison (with a visible note);
the explicit `orch secret scan` stays strict."""

import io
import json

import pytest

from orch import phone_results, publish, secretscan
from orch.errors import Refused

TOKEN = "ghp_" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0"  # built at run time


@pytest.fixture
def unreadable(monkeypatch):
    monkeypatch.setattr(phone_results, "value_hider", lambda root: None)
    monkeypatch.setattr(secretscan, "_noted", False)


def test_send_goes_through_with_a_note(unreadable, tmp_path, capsys):
    secretscan.refuse_if_secret_in(tmp_path, {"text": "hello there"})
    secretscan.refuse_if_secret(b"plain file", "file", tmp_path)
    publish.scan_files(tmp_path, [("report.pdf", b"%PDF plain")])
    assert secretscan.NOTE_SKIPPED in capsys.readouterr().err


def test_note_reaches_the_debug_log(unreadable, tmp_path, monkeypatch):
    seen = []
    from orch import diag

    monkeypatch.setattr(diag, "log", lambda ev, *a, **k: seen.append(ev))
    secretscan.refuse_if_secret_in(tmp_path, {"text": "hi"})
    assert "secretscan.stored_keys_unreadable" in seen


def test_real_token_still_blocks_when_keys_unreadable(unreadable, tmp_path):
    with pytest.raises(Refused, match="GitHub token"):
        secretscan.refuse_if_secret_in(tmp_path, {"text": f"use {TOKEN}"})
    with pytest.raises(Refused, match="GitHub token"):
        secretscan.refuse_if_secret(f"x\n{TOKEN}".encode(), "file", tmp_path)
    with pytest.raises(Refused, match="GitHub token"):
        publish.scan_files(tmp_path, [("a.txt", TOKEN.encode())])


def test_find_strict_default_still_fails_closed(unreadable, tmp_path):
    assert secretscan.find("hello", tmp_path) == [{"kind": "keys-unreadable", "line": 1}]
    assert secretscan.find("hello", tmp_path, strict=False) == []


def test_explicit_scan_command_is_strict(unreadable, proj, run, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"hello\n"), encoding="utf-8"))
    code, out, err = run("secret", "scan", "--json")
    assert code != 0
    assert json.loads(out)["code"] == "stored_keys_unreadable"
    assert "saved keys" in json.loads(out)["error"]


def test_normal_case_unchanged(tmp_path, capsys):
    secretscan.refuse_if_secret_in(tmp_path, {"text": "hello"})
    assert capsys.readouterr().err == ""


# ORCH-2077: the send-only skip is not for local evidence writes. Isolated stores only (proj/tmp_path).
@pytest.fixture
def store_unavailable(monkeypatch):
    from orch import keystore

    def broken(root):
        raise Refused("These saved keys belong to another folder. Run orch workspace move-here.")

    monkeypatch.setattr(keystore, "all_needles", broken)
    monkeypatch.setattr(secretscan, "_noted", False)


def _evidence_files(proj, tid):
    d = proj / ".orch" / "tickets" / tid / "evidence"
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


def test_evidence_write_refused_when_store_unavailable(store_unavailable, proj, run, new_ticket, capsys):
    tid = new_ticket()
    run("check", "add", tid, "Export")
    path = proj / ".orch" / "tickets" / f"{tid}.json"
    before = path.read_bytes()
    (proj / "plain.txt").write_text("plain words\n")
    for extra in (["--note", "looked fine"], ["--file", "plain.txt"]):
        code, out, err = run("check", "done", tid, "c1", *extra)
        assert code != 0
        assert "saved keys, so nothing was saved" in out + err
        assert "move-here" in out + err  # the way out
        assert secretscan.NOTE_SKIPPED not in err
    assert path.read_bytes() == before
    assert _evidence_files(proj, tid) == []


def test_evidence_file_bytes_strict_leave_no_file(store_unavailable, proj, run, new_ticket, monkeypatch):
    from orch import tickets

    tid = new_ticket()
    run("check", "add", tid, "Export")
    (proj / "plain.txt").write_text("plain words\n")
    monkeypatch.setattr(tickets, "refuse_secret_in_evidence", lambda root, ev: None)  # bytes scan only
    code, out, err = run("check", "done", tid, "c1", "--file", "plain.txt")
    assert code != 0 and "nothing was saved" in out + err
    assert _evidence_files(proj, tid) == []


def test_evidence_write_with_readable_empty_store(proj, run, new_ticket, monkeypatch, capsys):
    from orch import keystore

    monkeypatch.setattr(keystore, "all_needles", lambda root: {})  # readable, no keys
    monkeypatch.setattr(secretscan, "_noted", False)
    tid = new_ticket()
    run("check", "add", tid, "Export")
    (proj / "plain.txt").write_text("plain words\n")
    code, out, err = run("check", "done", tid, "c1", "--note", "looked fine", "--file", "plain.txt")
    assert code == 0, out + err
    assert secretscan.NOTE_SKIPPED not in err
    assert _evidence_files(proj, tid) == ["plain.txt"]


def test_evidence_token_named_before_unavailable_store(store_unavailable, tmp_path):
    with pytest.raises(Refused, match="GitHub token"):
        secretscan.refuse_if_secret_in(tmp_path, {"note": TOKEN}, "evidence", verb="saved", strict=True)
    with pytest.raises(Refused, match="GitHub token"):
        secretscan.refuse_if_secret(TOKEN.encode(), "evidence file", tmp_path, verb="saved", strict=True)


def test_sends_still_continue_with_note_when_store_unavailable(store_unavailable, tmp_path, capsys):
    secretscan.refuse_if_secret_in(tmp_path, {"text": "hello there"})
    secretscan.refuse_if_secret(b"plain file", "file", tmp_path)
    assert secretscan.NOTE_SKIPPED in capsys.readouterr().err

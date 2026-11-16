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
    assert secretscan.find("hello", tmp_path) == [{"kind": "stored-key", "line": 1}]
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

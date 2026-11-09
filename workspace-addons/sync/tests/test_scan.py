import hashlib
import json

import pytest

from orch_sync.scan import blocking, scan_blob, scan_path

TOKEN_P = b"orp_" + b"A1b2C3d4E5f6G7h8I9j0K"
TOKEN_N = b"orn_" + b"A1b2C3d4E5f6G7h8I9j0K"


def codes(path, data):
    return sorted((f.code, f.rule) for f in scan_blob(path, data))


def test_clean_ticket_and_text_artifact_pass():
    assert scan_blob("tickets/t_abc123.json", json.dumps({"title": "Invoice", "token_count": 3}).encode()) == []
    assert scan_blob("tickets/t_abc123/artifacts/notes.md", "Grüsse, Müller\n".encode()) == []


@pytest.mark.parametrize("data,rule", [
    (b"x " + TOKEN_P + b" y", "orp-token"),
    (b"x " + TOKEN_N, "orn-token"),
    (b"-----BEGIN OPENSSH PRIVATE KEY-----\nabc", "private-key"),
    (b"-----BEGIN PRIVATE KEY-----", "private-key"),
    (b"ghp_" + b"a" * 36, "github-token"),
    (b"github_pat_" + b"a" * 40, "github-token"),
    (b"sk-" + b"a1" * 15, "api-key"),
    (b"AKIA" + b"ABCDEFGHIJKLMNOP", "aws-key"),
    (b"xoxb-1234567890-abcdef", "slack-token"),
])
def test_token_forms(data, rule):
    assert ("secret", rule) in codes("tickets/t_abc123/artifacts/n.txt", data)


def test_full_bytes_not_only_the_start_or_text_lines():
    big = b"\x00" * 3_000_000 + TOKEN_P + b"\x00\x01"  # deep inside binary content
    assert ("secret", "orp-token") in codes("tickets/t_abc123/artifacts/blob.bin", big)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100 + TOKEN_N
    assert ("secret", "orn-token") in codes("tickets/t_abc123/artifacts/s.png", png)


def test_utf16_text_is_seen():
    data = ("key " + TOKEN_P.decode()).encode("utf-16")
    assert ("secret", "orp-token") in codes("tickets/t_abc123/artifacts/n.txt", data)


def test_token_field_only_in_ticket_json():
    body = b'{"token": "abc"}'
    assert ("secret", "token-field") in codes("tickets/t_abc123.json", body)
    assert codes("tickets/t_abc123/artifacts/x.json", body) == []


def test_findings_never_carry_the_secret():
    for f in scan_blob("tickets/t_abc123.json", TOKEN_P):
        assert TOKEN_P.decode() not in repr(f)


@pytest.mark.parametrize("path", [
    "tickets/t_abc123/artifacts/.env", "tickets/t_abc123/artifacts/.env.local", "tickets/t_abc123/artifacts/a.pem",
    "tickets/t_abc123/artifacts/x.KEY", "tickets/t_abc123/artifacts/AuthKey.p8", "tickets/t_abc123/artifacts/c.p12",
    "tickets/t_abc123/artifacts/c.pfx", "tickets/t_abc123/artifacts/id_rsa", "tickets/t_abc123/artifacts/id_rsa.pub",
    "tickets/t_abc123/artifacts/id_ed25519", "tickets/t_abc123/artifacts/vault.kdbx",
    "tickets/t_abc123/artifacts/credentials.json", "tickets/t_abc123/artifacts/.envrc/readme.txt",
    "me/settings.toml", "secrets/x", "chat/a.json", "run/sync/state.json", "inbox/m", "addons/x", "harness/y",
])
def test_refused_paths(path):
    assert any(f.code == "path" for f in scan_path(path)) and blocking(scan_blob(path, b"hi")) != []


@pytest.mark.parametrize("path", ["/etc/passwd", "tickets/../me/x", "C:/x", "tickets\\a", "tickets/a\x07b"])
def test_unsafe_paths(path):
    assert [f.rule for f in scan_path(path)] == ["unsafe-path"]


def test_fine_names_not_refused():
    for p in ("tickets/t_abc123/artifacts/environment.md", "tickets/t_abc123/artifacts/keynote.txt",
              "tickets/t_abc123/artifacts/monkey.png", "tickets/t_abc123.json", "ticket-counter.json"):
        assert scan_path(p) == []


@pytest.mark.parametrize("name,data", [
    ("a.zip", b"PK\x03\x04rest"), ("a.tar.gz", b"\x1f\x8b\x08"), ("a.7z", b"7z\xbc\xaf\x27\x1c"), ("a.jar", b"x"),
    ("renamed.txt", b"PK\x03\x04hidden"), ("odd.dat", b"\x00\x01\x02\xff\xfe"),
])
def test_archives_and_unknown_are_cannot_check_and_need_a_click(name, data):
    fs = scan_blob("tickets/t_abc123/artifacts/" + name, data)
    assert len(fs) == 1 and fs[0].code == "cannot-check" and fs[0].needs_click
    assert fs[0].sha256 == hashlib.sha256(data).hexdigest()
    assert blocking(fs) == fs and blocking(fs, [fs[0].sha256]) == []  # a click for THIS hash lets it through
    assert blocking(fs, ["0" * 64]) == fs


def test_click_does_not_unblock_a_secret_inside_an_archive():
    fs = scan_blob("tickets/t_abc123/artifacts/a.zip", b"PK\x03\x04" + TOKEN_P)
    allow = [f.sha256 for f in fs if f.sha256]
    assert any(f.code == "secret" for f in blocking(fs, allow))


def test_known_media_is_fine():
    for data in (b"\x89PNG\r\n\x1a\n\x00\x00", b"\xff\xd8\xff\xe0\x00", b"GIF89a\x00",
                 b"RIFF\x00\x00\x00\x00WEBPVP8 ", b"\x00\x00\x00\x18ftypmp42"):
        assert scan_blob("tickets/t_abc123/artifacts/m.bin", data) == []


@pytest.mark.parametrize("path", [
    "Secrets/x", "SECRETS/x", "CHAT/a.json", "Run/x", "ME/settings.toml", "se\u200bcrets/x", "ch­at/a",
    "s﻿ecrets/x", "ru⁠n/x", "ｓｅｃｒｅｔｓ/x", "sec️retss/x".replace("retss", "rets"),
    "tickets/t_abc123/artifacts/.ENV", "tickets/t_abc123/artifacts/.en\u200bv", "tickets/t_abc123/artifacts/ID_RSA",
    "tickets/t_abc123/artifacts/Key.PEM", "tickets/t_abc123/artifacts/cred\u200bentials.json",
])
def test_normalized_bypass_variants_are_refused(path):
    assert any(f.code == "path" for f in scan_path(path)), path


def test_nfd_spelling_matches_nfc():
    import unicodedata
    nfc, nfd = "tickets/t_abc123/artifacts/café.key", unicodedata.normalize("NFD", "café.key")
    assert scan_path(nfc) and scan_path("tickets/t_abc123/artifacts/" + nfd)


@pytest.mark.parametrize("path", ["tickets//x", "tickets/./x", "tickets/x/", "tickets/.\u200b./x", "tickets/..\u200b/x",
                                  "a/\u200b/b", "tickets/a b"])
def test_empty_dot_dotdot_and_control_segments_are_unsafe(path):
    assert [f.rule for f in scan_path(path)] == ["unsafe-path"]


@pytest.mark.parametrize("path", ["Tickets/T_ABC123.json", "tickets/t_abc\u200b123.json", "tickets/T_abc123.JSON"])
def test_token_field_check_uses_the_normalized_ticket_path(path):
    assert ("secret", "token-field") in codes(path, b'{"token": "x"}')


def test_json_unicode_escapes_do_not_hide_tokens():
    esc = b'{"note": "\\u006frp_' + TOKEN_P[5:] + b'"}'
    assert ("secret", "orp-token") in codes("tickets/t_abc123/artifacts/x.json", esc)
    assert ("secret", "orp-token") in codes("tickets/t_abc123.json", esc)
    assert ("secret", "token-field") in codes("tickets/t_abc123.json", b'{"to\\u006ben": "abc"}')
    assert codes("tickets/t_abc123/artifacts/x.json", b'{"to\\u006ben": "abc"}') == []
    nested = b'{"a": [{"b": "\\u002d----BEGIN PRIVATE KEY-----"}]}'
    assert ("secret", "private-key") in codes("tickets/t_abc123/artifacts/n.json", nested)
    assert scan_blob("tickets/t_abc123/artifacts/deep.json", b"[" * 100000 + b"]" * 100000) == []  # no crash


def test_pdf_and_media_with_hidden_archive_need_a_click():
    for name, data in (("a.pdf", b"%PDF-1.7\n%text only"), ("p.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 50 + b"PK\x03\x04zip"),
                       ("v.mp4", b"\x00\x00\x00\x18ftypmp42" + b"Rar!\x1a\x07\x00")):
        fs = scan_blob("tickets/t_abc123/artifacts/" + name, data)
        assert len(fs) == 1 and fs[0].code == "cannot-check" and fs[0].needs_click, name


@pytest.mark.parametrize("path", ["me./x", "addons /x", "tickets/t_abc123/artifacts/key.pem.",
                                  "tickets/t_abc123/artifacts/a ", "tickets/t_abc123/artifacts/a:stream",
                                  "tickets/t_abc123/artifacts/x.\u200b ", "me\u200b./x"])
def test_windows_trailing_dot_space_and_colon_are_unsafe(path):
    assert [f.rule for f in scan_path(path)] == ["unsafe-path"]


def test_repeated_json_keys_cannot_hide_a_value():
    body = b'{"note": "' + TOKEN_P + b'", "note": "fine"}'
    esc = b'{"n": "\\u006frp_' + TOKEN_P[5:] + b'", "n": "fine"}'
    for path in ("tickets/t_abc123/artifacts/x.json", "tickets/t_abc123.json"):
        assert ("secret", "orp-token") in codes(path, esc)
        assert ("secret", "orp-token") in codes(path, body)
    assert ("secret", "token-field") in codes("tickets/t_abc123.json", b'{"token": "abc", "token": 5}')
    assert ("secret", "token-field") in codes("tickets/t_abc123.json", b'{"tok\\u0065n": "abc", "token": 5}')


@pytest.mark.parametrize("sig", [b"\x1f\x8b\x08\x08", b"\x1f\x8b\x08\x00", b"BZh9", b"\xfd7zXZ\x00"])
def test_embedded_archive_signatures_in_media(sig):
    fs = scan_blob("tickets/t_abc123/artifacts/p.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 20 + sig + b"x")
    assert [(f.code, f.rule) for f in fs] == [("cannot-check", "media-with-archive")]


def test_utf16_without_bom_is_not_text():
    raw = "hello".encode("utf-16-le")  # no BOM, has NUL bytes
    assert [f.rule for f in scan_blob("tickets/t_abc123/artifacts/n.txt", raw)] == ["unknown-format"]
    assert scan_blob("tickets/t_abc123/artifacts/n.txt", "hello".encode("utf-16")) == []

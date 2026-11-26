"""ORCH-1944: false hits of the one secret check, each next to planted real secrets so precision costs no
recall. #963 #1874 #2047 #2261 #2543 #1532 #997 (the sync add-on's #2702 is in its own tests)."""

import random

import pytest

from orch import phone_view, secretscan
from orch.errors import Refused

PW = "hunter2" + "xyz"  # a made-up password, built at run time


def hit(text: str) -> bool:
    return bool(secretscan.find(text))


@pytest.mark.parametrize(
    "text",
    [
        "test_secretscan.py: 325 passed",  # 963: a test file with secret in its name
        "refuse_if_secret_in: refuses a sentence with a field name",  # 963: a function name, then prose
        "see token.py:3 and api_key.py:12",  # 1874: code references
        "workspace/src/orch/secretscan.py:120: the line scrub",
        "R5 (secrets: never in tickets or logs)",  # 1874: prose
        "Saved keys: run orch workspace move-here",
        "workspace_key_moved: the folder moved to a new place",  # 1874: a diag check name and its fact
        "GITHUB_TOKEN\ttoken\tlocal\tready",  # 1874: orch secret list
        "PASS: 20 of 20 checks passed",  # 2047
        "pass: 3 tests passed in 0.2s",
        "Start Chromium with --use-mock-keychain --password-store=basic",  # 2261
        'args: ["--password-store", "basic"]',
        "password_store: keychain",
    ],
)
def test_harmless_text_is_no_secret(text):
    assert not hit(text)
    assert phone_view.redact(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "client_secret: " + PW,  # next to 963
        "token.txt: " + PW,  # a file name with a value that is one word
        "token.py: " + PW,
        "secret: correct horse battery staple",
        "password: correct horse battery staple",  # next to 1874: a passphrase after a password word
        "my password: correct horse battery staple",
        "DB_PASSWORD: correct horse battery staple",
        "Saved keys: " + PW,
        "api_key: " + PW,
        "api_key: " + PW + " (the staging one)",  # a value, then a comment
        "token: Ab12x then more words",
        "t_pw1234: correct horse battery staple",
        "Authorization: Bearer abc def",
        "R5 (secrets: x password=" + PW + ")",  # a pair inside a skipped value is still read
        "PASS: 4711 " + PW,  # next to 2047
        "pass: 12",
        "pass: correct horse battery",
        "PASS: " + PW,
        "chrome --password-store=basic --api-key=" + PW,  # next to 2261
        "--password=" + PW,
        "--password " + PW,
        "--password-file-x " + PW,
    ],
)
def test_planted_secret_is_still_found(text):
    assert hit(text)


# 1532: a password on the line after its label; 2543: one verdict for the CLI and the phone view
NEXT_LINE = [  # (text, the line of the value)
    ("pass:\n" + PW, 2),
    ("  password:\r\n  " + PW + "\r\n", 2),
    ('{\n  "password":\n    "' + PW + '"\n}', 3),
    ("- secret:\n  correct horse battery staple", 2),
    ("notes\nDB_PASSWORD:\n" + PW + "\nmore notes", 3),
    ("passwords:\n  - " + PW, 2),
]
NOT_NEXT_LINE = [
    "if all checks pass it asks the relay for a session:\n`orch relay tunnel` opens it",  # 2543
    "password:\n[hidden]",
    "deploy_key:\n~/.ssh/deploy_rsa",
    "Keys:\n- one key per workspace\n- the dashboard shows them",
    "Session:\n```bash\norch dashboard\n```",
    "password:",
]


@pytest.mark.parametrize("text,line", NEXT_LINE)
def test_a_password_on_the_next_line_is_found(text, line):
    assert secretscan.find(text) == [{"kind": "secret-value", "line": line}]
    with pytest.raises(Refused):
        secretscan.refuse_if_secret_in(None, {"text": text})
    with pytest.raises(Refused):
        secretscan.refuse_if_secret(text.encode())


@pytest.mark.parametrize("text", [t for t, _ in NEXT_LINE] + NOT_NEXT_LINE)
def test_cli_scan_and_phone_view_agree(text):
    assert hit(text) == phone_view._has_secret(text.encode())
    assert phone_view._scan_texts(text.encode(), "note.md")[0] == ("secret" if hit(text) else "ok")


@pytest.mark.parametrize("text", NOT_NEXT_LINE)
def test_prose_before_a_line_is_no_next_line_password(text):
    assert not hit(text)


# 997: binary files. These seeds were refused before the fix (the loose label rules matched by chance).
@pytest.mark.parametrize("seed", [1, 5, 7, 11])
def test_random_bytes_are_no_secret(seed):
    data = random.Random(seed).randbytes(200_000)
    secretscan.refuse_if_secret(data)


@pytest.mark.parametrize(
    "planted",
    [
        b"\nAPI_PASSWORD=" + PW.encode() + b"\n",  # a text line inside the binary
        b"\x00db_password=" + PW.encode() + b"\x00",  # a NUL-ended string, as in a compiled program
        b"\x01\x02 --api-key " + PW.encode() + b"\x03",
        "\x00password: correct horse battery\x00".encode("utf-16-le"),
        b"\x00ghp_" + b"Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0" + b"\x00",  # a token pattern anywhere
    ],
)
def test_a_secret_inside_binary_bytes_is_still_found(planted):
    data = random.Random(1).randbytes(100_000)
    with pytest.raises(Refused):
        secretscan.refuse_if_secret(data[:50_000] + planted + data[50_000:])


def test_a_short_label_line_in_a_latin1_text_file_is_still_found():
    with pytest.raises(Refused):
        secretscan.refuse_if_secret("Grüsse\npw=".encode("latin-1") + PW.encode() + b"\n")

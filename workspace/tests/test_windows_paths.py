"""R1.6 on every OS: a folder with spaces and umlauts, CRLF files, and Windows path comparison."""

import shutil
import subprocess

import pytest

from orch import harness, secretrun, skills

NAME = "Büro Ärger"


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / NAME
    (root / ".orch").mkdir(parents=True)
    return root


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)  # noqa: S603, S607


def test_under_compares_windows_paths_without_case_and_with_either_slash():
    under = lambda p, b: secretrun._under(p, b, windows=True)  # noqa: E731
    assert under("C:\\Users\\Büro Ärger\\tool.exe", "c:/users/büro ärger")
    assert under("C:\\WS", "c:\\ws")
    assert not under("C:\\WS2\\x", "C:\\WS")
    assert not under("D:\\WS\\x", "C:\\WS")


def test_under_posix_stays_case_sensitive():
    assert secretrun._under("/home/a b/x", "/home/a b", windows=False)
    assert not secretrun._under("/home/A b/x", "/home/a b", windows=False)
    assert not secretrun._under("/home/a bc", "/home/a b", windows=False)


def test_block_with_crlf_agents_file_keeps_its_line_endings(ws):
    (ws / "AGENTS.md").write_bytes(b"# Team\r\nrule one\r\n")
    harness.share_on(ws)
    raw = (ws / "AGENTS.md").read_bytes()
    assert b"rule one" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")
    assert harness.share_state(ws)
    harness.share_off(ws)
    assert (ws / "AGENTS.md").read_bytes() == b"# Team\r\nrule one\r\n"


def test_local_file_block_in_crlf_file_is_replaced_not_doubled(ws):
    harness.set_block(ws, "orch", "## Orch\nDo it.")
    (ws / "CLAUDE.local.md").write_bytes(b"mine\r\n")
    (ws / "AGENTS.md").write_text("team\n", encoding="utf-8")
    for _ in range(2):
        assert harness.write_local_file(ws, "CLAUDE.local.md", "@AGENTS.md")
    raw = (ws / "CLAUDE.local.md").read_bytes()
    assert raw.count(harness.LOCAL_MARK[0].encode()) == 1
    assert raw.startswith(b"mine\r\n")
    assert raw.count(b"\n") == raw.count(b"\r\n")


def test_gitignore_and_exclude_with_crlf_in_a_folder_with_umlauts(ws):
    if not shutil.which("git"):
        pytest.skip("git missing")
    _git(ws, "init", "-q")
    exclude = ws / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_bytes(b"# mine\r\n*.log\r\n")
    skills.ensure_gitignore(ws)
    skills.ensure_gitignore(ws)
    raw = exclude.read_bytes()
    assert raw.startswith(b"# mine\r\n*.log\r\n")
    assert raw.count(b"\n") == raw.count(b"\r\n")
    assert raw.count(harness.EXCLUDE_MARK[0].encode()) == 1
    gi = (ws / ".orch" / ".gitignore").read_text(encoding="utf-8")
    assert ".local-id" in gi
    secret = ws / ".orch" / "secrets" / "k.json"
    secret.parent.mkdir(parents=True)
    secret.write_text("{}", encoding="utf-8")
    out = subprocess.run(  # noqa: S603, S607
        ["git", "check-ignore", "-q", ".orch/secrets/k.json"], cwd=ws, capture_output=True
    )
    assert out.returncode == 0


def test_addon_extra_with_crlf_and_umlauts_is_read(ws):
    harness.set_block(ws, "alpha", "## Alpha\r\nA.", addon=True)
    d = ws / ".orch" / "addons" / "alpha"
    d.mkdir(parents=True)
    (d / "AGENTS-extra.md").write_bytes("- Ärger\r\n- Büro\r\n".encode())
    text = harness.combined(ws)
    assert "- Ärger\n- Büro\n" in text
    assert "\r" not in text

"""orch publish new: every template/store combination makes a valid app folder; the servers start and answer."""

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from orch import cli, publish, templates
from orch.errors import Refused

COMBOS = [(s, st) for s in ("python", "node") for st in templates.STORES] + [
    ("static", "none"),
    ("static", "markdown"),
]


@pytest.mark.parametrize(("stack", "store"), COMBOS)
def test_manifest_valid(tmp_path, stack, store):
    folder = tmp_path / "my-app"
    templates.create(stack, store, folder)
    m = publish.read_manifest(folder)
    assert m["name"] == "my-app" and m["stack"] == stack and m["store"] == store and m["public"] is False
    publish.pack(folder, None)
    assert "{{" not in "".join(p.read_text() for p in folder.rglob("*") if p.is_file())


def test_refusals(tmp_path):
    with pytest.raises(Refused):
        templates.create("static", "sqlite", tmp_path / "ab")
    with pytest.raises(Refused):
        templates.create("python", "none", tmp_path / "Bad_Name")
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "x").write_text("x")
    with pytest.raises(Refused):
        templates.create("python", "none", tmp_path / "full")


def test_cli(tmp_path, capsys):
    assert cli.main(["publish", "new", "python", "--store", "json", str(tmp_path / "demo-app")]) == 0
    assert "Created python app demo-app" in capsys.readouterr().out
    assert (tmp_path / "demo-app" / "store.py").is_file()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url: str, tries: int = 100) -> bytes:
    for _ in range(tries):
        try:
            return urllib.request.urlopen(url, timeout=2).read()
        except OSError:
            time.sleep(0.1)
    raise AssertionError(f"{url} did not answer")


def _run(folder: Path, data: Path):
    port = _free_port()
    m = publish.read_manifest(folder)
    env = {
        **os.environ,
        "PORT": str(port),
        "BASE_PATH": f"/a/{m['name']}",
        "DATA_DIR": str(data),
        "STORE": m["store"],
    }
    cmd = m["start"].split()
    if cmd[0] == "python":
        cmd[0] = sys.executable
    proc = subprocess.Popen(cmd, cwd=folder, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc, f"http://127.0.0.1:{port}"


@pytest.mark.slow
@pytest.mark.parametrize("stack", ["python", "node"])
@pytest.mark.parametrize("store", templates.STORES)
def test_server_answers(tmp_path, stack, store):
    if stack == "node" and not shutil.which("node"):
        pytest.skip("node not on PATH")
    folder, data = tmp_path / "app-x", tmp_path / "data"
    data.mkdir()
    templates.create(stack, store, folder)
    proc, base = _run(folder, data)
    try:
        assert _get(base + publish.read_manifest(folder)["health"]) == b"ok"
        assert b"<h1>app-x</h1>" in _get(base + "/")
    finally:
        proc.terminate()
        proc.wait(5)


@pytest.mark.slow
def test_static_markdown_has_pages(tmp_path):
    templates.create("static", "markdown", tmp_path / "notes")
    assert (tmp_path / "notes" / "content" / "welcome.md").is_file()
    assert "content/" in (tmp_path / "notes" / "index.html").read_text()

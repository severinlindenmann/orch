"""orch publish new: each template makes a valid app folder; the servers start and answer."""

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from conftest import turn_on

from orch import cli, publish, templates
from orch.errors import Refused

COMBOS = [(s, st) for s in ("python", "node", "docker") for st in templates.STORES] + [
    ("static", "none"),
    ("static", "markdown"),
]


@pytest.mark.parametrize(("stack", "store"), COMBOS)
def test_manifest_valid(tmp_path, stack, store):
    folder = tmp_path / "my-app"
    templates.create(stack, store, folder)
    m = publish.read_manifest(folder)
    assert m["name"] == "my-app" and m["stack"] == stack and m["store"] == store
    assert m["reach"] == "public" and m["auth"] is True and "public" not in m
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


def test_cli(proj, tmp_path, capsys):
    turn_on(proj, "publish")
    assert cli.main(["publish", "new", "python", "--store", "json", str(tmp_path / "demo-app")]) == 0
    assert "Created a python app" in capsys.readouterr().out
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
    cmd = (m.get("start") or "python3 main.py").split()
    if cmd[0] in ("python", "python3"):  # Windows has no python3 (the publish host, Linux, does)
        cmd[0] = sys.executable
    proc = subprocess.Popen(cmd, cwd=folder, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc, f"http://127.0.0.1:{port}"


@pytest.mark.slow
@pytest.mark.parametrize("stack", ["python", "node", "docker"])
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


def test_python_template_commands_use_python3(tmp_path):
    # the publish server has `python3` only (no `python`)
    folder = tmp_path / "py-app"
    templates.create("python", "sqlite", folder)
    m = publish.read_manifest(folder)
    assert m["start"].startswith("python3 ") and m["test"].startswith("python3 ")


def test_docker_template_files(tmp_path):
    folder = tmp_path / "dock-app"
    templates.create("docker", "json", folder)
    m = publish.read_manifest(folder)
    assert m["stack"] == "docker" and m["health"] == "/health" and "start" not in m
    assert (folder / "Dockerfile").read_text().startswith("FROM python:3.12-slim")
    assert (folder / "README.md").is_file() and (folder / "store.py").is_file()
    assert len((folder / "README.md").read_text().splitlines()) <= 15
    import io
    import tarfile

    with tarfile.open(fileobj=io.BytesIO(publish.pack(folder, None))) as tar:
        assert "Dockerfile" in tar.getnames()


def test_docker_manifest_rules(tmp_path):
    folder = tmp_path / "dock-app"
    templates.create("docker", "none", folder)
    (folder / "Dockerfile").unlink()
    with pytest.raises(Refused, match="Dockerfile"):
        publish.read_manifest(folder)
    (folder / "Dockerfile").write_text("FROM scratch\n")
    publish.read_manifest(folder)  # start is optional
    mf = folder / "app.toml"
    mf.write_text(mf.read_text().replace('health = "/health"\n', ""))
    with pytest.raises(Refused, match="health"):
        publish.read_manifest(folder)
    mf.write_text(mf.read_text() + 'health = "/health"\nstart = "./run"\n')
    assert publish.read_manifest(folder)["start"] == "./run"


def test_python_template_respects_host(tmp_path, monkeypatch):
    folder = tmp_path / "host-app"
    templates.create("python", "none", folder)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.syspath_prepend(str(folder))
    monkeypatch.delitem(sys.modules, "main", raising=False)
    monkeypatch.delitem(sys.modules, "store", raising=False)
    import main

    server = main.make_server(0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()
        sys.modules.pop("main", None)
        sys.modules.pop("store", None)


def test_new_app_names_start_and_end_with_a_letter_or_digit(tmp_path):
    for bad in ("foo-", "-foo", "a"):
        with pytest.raises(Refused):
            templates.create("static", "none", tmp_path / bad)
    assert publish.DEPLOY_NAME_RE.match("a-b") and publish.DEPLOY_NAME_RE.match("ab")
    # existing apps keep the looser rule (stop / remove still work)
    assert publish.NAME_RE.match("foo-")

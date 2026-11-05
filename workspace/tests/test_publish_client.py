import io
import json
import tarfile
from pathlib import Path

from conftest import turn_on
from fakes import WS

from orch import publish
from orch.errors import Refused

VEC = json.loads((Path(__file__).resolve().parents[2] / "contracts/vectors/publish-blob-v1.json").read_text())


def connect(run, srv):
    return run("publish", "connect", srv.url, "--workspace", WS, "--token", srv.token)


def test_vector_decrypts_and_bad_cases_fail():
    good = VEC["good"]
    key = publish.b64u_decode(good["key_b64url"])
    blob = bytes.fromhex(good["blob_hex"])
    header, content = publish.decrypt(blob, key)
    assert header["size"] == len(content)
    for case in VEC["must_fail"]:
        try:
            publish.decrypt(bytes.fromhex(case["blob_hex"]), publish.b64u_decode(case["key_b64url"]))
        except Refused:
            continue
        raise AssertionError(case["name"])


def test_encrypt_matches_the_vector_byte_for_byte():
    good = VEC["good"]
    blob = bytes.fromhex(good["blob_hex"])
    key = publish.b64u_decode(good["key_b64url"])
    header, content = publish.decrypt(blob, key)
    again, _ = publish.encrypt(content, header["name"], header["type"], key=key, iv=blob[4:16])
    assert again == blob


def test_connect_saves_token_and_installs_skill(proj, run, pub):
    code, out, _ = connect(run, pub)
    assert code == 0 and "Pilatus Workspace" in out
    cfg = json.loads((proj / ".orch/secrets/publish.json").read_text())
    assert cfg == {"url": pub.url, "workspace": WS, "token": pub.token}
    assert (proj / ".agents/skills/orch-publish/SKILL.md").is_file()
    assert "<!-- orch:addon:publish -->" in (proj / "AGENTS.md").read_text()
    assert ".orch/secrets/" in (proj / ".gitignore").read_text()


def test_connect_wrong_token_is_refused_and_saves_nothing(proj, run, pub):
    code, _, err = run("publish", "connect", pub.url, "--workspace", WS, "--token", "orp_" + "Z" * 43)
    assert code == 2 and "wrong" in err
    assert not (proj / ".orch/secrets/publish.json").exists()


def test_not_connected(run, proj):
    turn_on(proj, "publish")
    code, _, err = run("publish", "whoami")
    assert code == 2 and "not connected" in err


def test_file_share_roundtrip_and_link(proj, run, pub):
    connect(run, pub)
    f = proj / "report.txt"
    f.write_bytes(b"hello report")
    code, out, _ = run("publish", "file", str(f), "--days", "3", "--json")
    assert code == 0
    res = json.loads(out)
    assert res["link"].startswith(res["url"] + "#k=") and len(res["link"].split("#k=")[1]) == 43
    # the server only ever saw ciphertext, and the key opens it
    blob = pub.files[res["id"]]
    assert b"hello report" not in blob and blob[:4] == b"OPF1"
    header, content = publish.decrypt(blob, publish.b64u_decode(res["link"].split("#k=")[1]))
    assert (header["name"], header["size"], content) == ("report.txt", 12, b"hello report")
    assert any(c[1] == "/v1/files?days=3" for c in pub.calls)
    assert json.loads((proj / ".orch/secrets/files/keys.json").read_text())[res["id"]]


BVEC = json.loads((Path(__file__).resolve().parents[2] / "contracts/vectors/publish-bundle-v1.json").read_text())


def _unbundle(raw: bytes) -> dict:
    import struct

    (m,) = struct.unpack(">I", raw[:4])
    idx, pos, out = json.loads(raw[4 : 4 + m]), 4 + m, {}
    for f in idx["files"]:
        out[f["path"]] = raw[pos : pos + f["size"]]
        pos += f["size"]
    assert pos == len(raw) and idx["entry"] == "index.html" and idx["v"] == 1
    return out


def test_folder_share_packs_a_bundle_matching_the_vector(proj, run, pub):
    connect(run, pub)
    site = proj / "site"
    for f in BVEC["good"]["files"]:
        (site / f["path"]).parent.mkdir(parents=True, exist_ok=True)
        (site / f["path"]).write_text(f["content_utf8"])
    (site / ".env").write_text("SECRET=1")
    (site / "node_modules").mkdir()
    (site / "node_modules/x.js").write_text("x")
    code, out, _ = run("publish", "file", "site", "--json")
    assert code == 0, out
    res = json.loads(out)
    header, content = publish.decrypt(pub.files[res["id"]], publish.b64u_decode(res["link"].split("#k=")[1]))
    assert (header["name"], header["type"], res["name"]) == ("site", publish.BUNDLE_TYPE, "site")
    want = _unbundle(bytes.fromhex(BVEC["good"]["bundle_hex"]))
    assert _unbundle(content) == want


def test_folder_without_index_html_is_refused(proj, run, pub):
    connect(run, pub)
    (proj / "notes").mkdir()
    (proj / "notes/a.txt").write_text("a")
    assert "index.html" in run("publish", "file", "notes")[2]
    assert not pub.files

def test_file_permanent_refused_without_right(proj, run, pub):
    connect(run, pub)
    (proj / "a.txt").write_text("x")
    code, _, err = run("publish", "file", "a.txt", "--permanent")
    assert code == 2 and "permanent" in err


def test_days_and_permanent_conflict(proj, run, pub):
    connect(run, pub)
    (proj / "a.txt").write_text("x")
    assert run("publish", "file", "a.txt", "--days", "0")[0] == 2
    assert run("publish", "file", "a.txt", "--days", "3", "--permanent")[0] == 2


def test_list_and_delete_file(proj, run, pub):
    connect(run, pub)
    (proj / "a.txt").write_text("x")
    fid = json.loads(run("publish", "file", "a.txt", "--json")[1])["id"]
    code, out, _ = run("publish", "list")
    assert fid in out and "a.txt" in out and "key saved" not in out
    assert run("publish", "delete", fid)[0] == 0
    assert run("publish", "list")[1].strip().startswith("Nothing shared yet")


def make_app(proj, public="false"):
    d = proj / "myapp"
    d.mkdir()
    (d / "app.toml").write_text(f'name = "weekly-report"\nstack = "static"\npublic = {public}\n')
    (d / "index.html").write_text("<h1>hi</h1>")
    (d / ".git").mkdir()
    (d / ".git" / "config").write_text("secret")
    return d


def test_app_deploy_private_with_view_token(proj, run, pub):
    connect(run, pub)
    make_app(proj)
    code, out, _ = run("publish", "app", "myapp", "--days", "2")
    assert code == 0 and "?token=apv_" in out
    app = pub.apps["weekly-report"]
    names = tarfile.open(fileobj=io.BytesIO(app["tar"])).getnames()
    assert sorted(names) == ["app.toml", "index.html"]  # .git is left out
    assert app["query"] == {"days": ["2"]}


def test_app_public_flag_rewrites_manifest(proj, run, pub):
    connect(run, pub)
    make_app(proj)
    run("publish", "app", "myapp", "--public", "--permanent")
    tar = tarfile.open(fileobj=io.BytesIO(pub.apps["weekly-report"]["tar"]))
    assert b"public = true" in tar.extractfile("app.toml").read()
    assert pub.apps["weekly-report"]["query"] == {"permanent": ["1"]}


def test_app_manifest_errors(proj, run, pub):
    connect(run, pub)
    (proj / "x").mkdir()
    assert "no app.toml" in run("publish", "app", "x")[2]
    (proj / "x" / "app.toml").write_text('name = "BAD"\nstack = "static"\n')
    assert run("publish", "app", "x")[0] == 2
    (proj / "x" / "app.toml").write_text('name = "ok-app"\nstack = "python"\n')
    assert "start and health" in run("publish", "app", "x")[2]


def test_app_failed_test_shows_output(proj, run, pub):
    connect(run, pub)
    make_app(proj)
    pub.fail_test = True
    code, _, err = run("publish", "app", "myapp")
    assert code == 2 and "test failed" in err and "FAILED x" in err


def test_app_restart_stop_delete(proj, run, pub):
    connect(run, pub)
    make_app(proj)
    run("publish", "app", "myapp")
    assert "stopped" in run("publish", "stop", "weekly-report")[1]
    assert "running" in run("publish", "restart", "weekly-report")[1]
    assert "weekly-report" in run("publish", "list")[1]
    assert run("publish", "delete", "weekly-report")[0] == 0
    assert "weekly-report" not in pub.apps


def test_file_too_big_is_refused_locally(proj, run, pub, monkeypatch):
    connect(run, pub)
    monkeypatch.setattr(publish, "MAX_FILE", 5)
    (proj / "a.txt").write_text("123456")
    assert "100 MB" in run("publish", "file", "a.txt")[2]
    assert not pub.files


def test_pack_skips_dot_entries_and_refuses_workspace_root(tmp_path):
    import io
    import tarfile

    import pytest

    from orch import publish
    from orch.errors import Refused

    app = tmp_path / "app"
    (app / ".orch/secrets").mkdir(parents=True)
    (app / ".claude").mkdir()
    (app / "app.toml").write_text('stack = "static"\n')
    (app / "index.html").write_text("hi")
    (app / ".env.local").write_text("SECRET=1")
    (app / ".claude/x").write_text("x")
    with pytest.raises(Refused, match="workspace root"):
        publish.pack(app, None)
    import shutil

    shutil.rmtree(app / ".orch")
    names = tarfile.open(fileobj=io.BytesIO(publish.pack(app, None))).getnames()
    assert sorted(names) == ["app.toml", "index.html"]


def test_net_retries_connection_failures_only(monkeypatch):
    import urllib.error

    from orch import net
    from orch.errors import Refused

    sleeps, tries = [], []
    monkeypatch.setattr(net.time, "sleep", sleeps.append)

    def refused(req, timeout):
        tries.append(1)
        raise urllib.error.URLError(ConnectionRefusedError("refused"))

    monkeypatch.setattr(net.urllib.request, "urlopen", refused)
    try:
        net.call("POST", "http://x.test/a", body={"a": 1})
        raise AssertionError("expected Refused")
    except Refused as e:
        assert "reach" in str(e)
    assert len(tries) == 4 and sleeps == [1, 2, 4]

    tries.clear()
    sleeps.clear()

    def answered(req, timeout):
        tries.append(1)
        raise urllib.error.HTTPError("http://x.test/a", 500, "err", {}, None)

    monkeypatch.setattr(net.urllib.request, "urlopen", answered)
    try:
        net.call("POST", "http://x.test/a", body={"a": 1})
    except (Refused, Exception):
        pass
    assert len(tries) == 1 and sleeps == []


def test_net_does_not_replay_posts_after_send(monkeypatch):
    from orch import net
    from orch.errors import Refused

    sleeps, tries = [], []
    monkeypatch.setattr(net.time, "sleep", sleeps.append)

    def reset(req, timeout):
        tries.append(1)
        raise ConnectionResetError("reset")  # raised after the request went out

    monkeypatch.setattr(net.urllib.request, "urlopen", reset)
    for method, url, n in (
        ("POST", "http://x.test/v1/files", 1),
        ("GET", "http://x.test/v1/files", 4),
        ("POST", "http://x.test/v1/messages", 4),
    ):
        tries.clear()
        try:
            net.call(method, url, body={"a": 1} if method == "POST" else None)
        except Refused:
            pass
        assert len(tries) == n, (method, url)

import io
import json
import os
import tarfile
from pathlib import Path

import pytest
from conftest import turn_on
from fakes import WS

from orch import publish
from orch.errors import Refused

VEC_DIR = Path(__file__).resolve().parents[2] / "contracts/vectors"
VEC = json.loads((VEC_DIR / "publish-blob-v1.json").read_text())


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
    assert {k: cfg[k] for k in ("url", "workspace", "token")} == {
        "url": pub.url,
        "workspace": WS,
        "token": pub.token,
    }
    assert set(cfg["rights"]) == {
        "files",
        "apps",
        "permanent",
        "public",
    }  # the skill lists what may be shared
    assert (proj / ".agents/skills/orch-publish/SKILL.md").is_file()
    assert "orch-publish" in (proj / ".orch/harness/AGENTS.orch.md").read_text()
    assert "secrets/" in (proj / ".orch/.gitignore").read_text() and not (proj / "AGENTS.md").exists()


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
    assert any(c[1] == "/v1/files?days=3&size=12" for c in pub.calls)
    assert res["size"] == 12
    assert "12 B" in run("publish", "list")[1]
    assert json.loads((proj / ".orch/secrets/files/keys.json").read_text())[res["id"]]


BVEC = json.loads((VEC_DIR / "publish-bundle-v1.json").read_text())


def _unbundle(raw: bytes) -> dict:
    import struct

    (m,) = struct.unpack(">I", raw[:4])
    idx, pos, out = json.loads(raw[4 : 4 + m]), 4 + m, {}
    for f in idx["files"]:
        out[f["path"]] = raw[pos : pos + f["size"]]
        pos += f["size"]
    assert pos == len(raw) and idx["entry"] in out and idx["v"] == 1
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


def test_folder_without_index_html_opens_first_page(proj, run, pub):
    connect(run, pub)
    g = BVEC["good_no_index"]
    for f in g["files"]:
        (proj / "nest" / f["path"]).parent.mkdir(parents=True, exist_ok=True)
        (proj / "nest" / f["path"]).write_text(f["content_utf8"])
    res = json.loads(run("publish", "file", "nest", "--json")[1])
    _, content = publish.decrypt(pub.files[res["id"]], publish.b64u_decode(res["link"].split("#k=")[1]))
    (m,) = __import__("struct").unpack(">I", content[:4])
    assert json.loads(content[4 : 4 + m])["entry"] == g["entry"] == "webpage/about.html"
    assert _unbundle(content) == _unbundle(bytes.fromhex(g["bundle_hex"]))


def test_folder_share_leaves_out_secret_looking_files_and_lists_names(proj, run, pub):
    connect(run, pub)
    site = proj / "site"
    (site / "keys").mkdir(parents=True)
    (site / "index.html").write_text("<h1>hi</h1>")
    for n in (
        "keys/server.pem",
        "id_rsa",
        "id_ed25519.pub",
        "credentials-prod.json",
        "api.key",
        "secrets.toml",
    ):
        (site / n).write_text("SECRET")
    code, out, _ = run("publish", "file", "site")
    assert code == 0, out
    assert "Files: index.html" in out and "Left out (look like secrets):" in out and "keys/server.pem" in out
    res = json.loads(run("publish", "file", "site", "--json")[1])
    assert res["files"] == ["index.html"] and len(res["skipped"]) == 6
    _, content = publish.decrypt(pub.files[res["id"]], publish.b64u_decode(res["link"].split("#k=")[1]))
    assert b"SECRET" not in content


def test_folder_names_the_viewer_rejects_are_refused_before_upload(proj, run, pub):
    connect(run, pub)
    site = proj / "site"
    site.mkdir()
    (site / "index.html").write_text("<h1>hi</h1>")
    if os.sep == "/":  # a \\ in a file name is only possible on Linux/macOS
        (site / "a\\b.css").write_text("x")
        assert "Rename" in run("publish", "file", "site")[2]
        (site / "a\\b.css").unlink()
        deep = site / "/".join(["d" * 60] * 4)  # Windows paths stop at 260 characters
        deep.mkdir(parents=True)
        (deep / "long-name.css").write_text("x")
        assert "255 characters" in run("publish", "file", "site")[2]
    assert not pub.files
    for bad in ("a\\b.css", "x/../y.css", "d" * 256, "bad\udcff.css"):
        with pytest.raises(Refused, match="Rename"):
            publish._bundle_path(bad)


def test_folder_without_index_html_is_refused(proj, run, pub):
    connect(run, pub)
    (proj / "notes").mkdir()
    (proj / "notes/a.txt").write_text("a")
    assert ".html page" in run("publish", "file", "notes")[2]
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


# ---- note, extend, replace, paging, Shared tab (W2-L10) --------------------------------------------


def test_note_vector_decrypts_and_encrypt_matches_it_byte_for_byte():
    good = VEC["good_with_note"]
    blob = bytes.fromhex(good["blob_hex"])
    key = publish.b64u_decode(good["key_b64url"])
    header, content = publish.decrypt(blob, key)
    assert header["note"].startswith("Here is the file") and header["size"] == len(content)
    again, _ = publish.encrypt(
        content, header["name"], header["type"], key=key, iv=blob[4:16], note=header["note"]
    )
    assert again == blob


def test_note_goes_into_the_encrypted_header_only(proj, run, pub):
    connect(run, pub)
    (proj / "a.txt").write_text("hello")
    out = json.loads(run("publish", "file", "a.txt", "--note", "  Here you go.\n— Anna ", "--json")[1])
    blob = pub.files[out["id"]]
    assert b"Here you go" not in blob
    key = publish.b64u_decode(out["link"].split("#k=")[1])
    assert publish.decrypt(blob, key)[0]["note"] == "Here you go. — Anna"
    assert all(b"Anna" not in c[1].encode() for c in pub.calls)


def test_note_too_long_is_refused_before_upload(proj, run, pub):
    connect(run, pub)
    (proj / "a.txt").write_text("x")
    code, _, err = run("publish", "file", "a.txt", "--note", "x" * 281)
    assert code == 2 and "longer than 280" in err
    assert not pub.files


def test_extend_keeps_the_link_and_expired_is_not_revived(proj, run, pub):
    connect(run, pub)
    (proj / "a.txt").write_text("x")
    fid = json.loads(run("publish", "file", "a.txt", "--json")[1])["id"]

    def patch(m, q, body):
        if m.group(1) != fid:
            return 410, {"error": "gone", "message": "gone"}
        assert json.loads(body) == {"days": 14}
        return 200, {"id": fid, "expires_at": "2026-11-23T09:30:00Z"}

    pub.route("PATCH", r"/v1/files/(f_[a-z0-9]+)", patch)
    code, out, _ = run("publish", "extend", fid, "--days", "14")
    assert code == 0 and "a.txt now expires" in out and "Same link." in out
    code, _, err = run("publish", "extend", "f_old000000000000", "--days", "7")
    assert code == 2 and "This link has expired." in err
    assert run("publish", "extend", "not-an-id", "--days", "7")[0] == 2


def test_replace_swaps_content_and_keeps_the_link(proj, run, pub):
    connect(run, pub)
    (proj / "a.txt").write_text("one")
    first = json.loads(run("publish", "file", "a.txt", "--json")[1])
    (proj / "b.txt").write_text("two two")

    def put(m, q, body):
        assert q == {"size": ["7"]}
        pub.files[m.group(1)] = body
        pub.file_sizes[m.group(1)] = int(q["size"][0])
        return 200, {
            "id": m.group(1),
            "url": f"{pub.url}/f/{m.group(1)}",
            "size": pub.file_sizes[m.group(1)],
            "expires_at": None,
        }

    pub.route("PUT", r"/v1/files/(f_[a-z0-9]+)", put)
    again = json.loads(run("publish", "file", "b.txt", "--replace", first["id"], "--note", "v2", "--json")[1])
    assert again["link"] == first["link"] and again["name"] == "b.txt"
    assert again["size"] == 7
    assert any(c[0] == "PUT" and c[1] == f"/v1/files/{first['id']}?size=7" for c in pub.calls)
    key = publish.b64u_decode(first["link"].split("#k=")[1])
    header, content = publish.decrypt(pub.files[first["id"]], key)
    assert content == b"two two" and header["note"] == "v2"
    assert "Replaced b.txt" in run("publish", "file", "b.txt", "--replace", first["id"])[1]
    assert "b.txt" in run("publish", "list")[1]


def test_replace_without_the_key_is_refused_plainly(proj, run, pub):
    connect(run, pub)
    (proj / "a.txt").write_text("x")
    code, _, err = run("publish", "file", "a.txt", "--replace", "f_other000000000000")
    assert code == 2 and "only kept on the computer that shared it" in err
    assert run("publish", "file", "a.txt", "--replace", "f_other000000000000", "--days", "3")[0] == 2


def test_list_follows_paging_beyond_100_files(proj, run, pub):
    connect(run, pub)
    rows = [
        {"id": f"f_{i:016x}", "size": 1, "created_at": "2026-11-04T10:05:00Z", "expires_at": None}
        for i in range(130)
    ]

    def page(m, q, b):
        start = int(q["after"][0]) if q.get("after") else 0
        chunk = rows[start : start + 100]
        return 200, {"items": chunk, "next": str(start + 100) if start + 100 < len(rows) else None}

    pub.routes.insert(0, ("GET", "/v1/files", page))
    out = json.loads(run("publish", "list", "--json")[1])
    assert len(out["files"]) == 130


def test_view_json_lists_files_without_any_key(proj, run, pub):
    connect(run, pub)
    (proj / "a.txt").write_text("hello report")
    link = json.loads(run("publish", "file", "a.txt", "--json")[1])["link"]
    key = link.split("#k=")[1]
    code, out, _ = run("publish", "view", "--json")
    v = json.loads(out)
    assert code == 0 and v["schema"] == "orch.addon-view/1" and key not in out and "#k=" not in out
    files = next(b for b in v["blocks"] if b["type"] == "list" and b["title"] == "Files")
    assert (
        files["items"][0]["title"] == "a.txt" and "link" not in files["items"][0]
    )  # http test server: no https link
    assert "12 B" in files["items"][0]["subtitle"]
    assert "orch publish" in v["notice"]


def test_publish_has_a_shared_tab():
    import tomllib

    toml = Path(publish.__file__).parent / "builtin" / "publish" / "orch-addon.toml"
    assert tomllib.loads(toml.read_text())["dashboard"]["label"] == "Shared"

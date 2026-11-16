"""Sharing a problem report with the relay and picking shared ones up (contracts/relay-api.md, Problems)."""

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
from diag_fixtures import reset_diag, stuck
from fakes import WS

from orch import diag_report, relay_problems
from orch.errors import Refused

PID = "pb_" + "a" * 16


@pytest.fixture
def proj(proj, monkeypatch):
    (proj / ".orch").mkdir(exist_ok=True)
    reset_diag(monkeypatch)
    return proj


@pytest.fixture
def srv(rel, run):
    """The fake relay with the Problems routes: one stored problem list, `reader` says whether this workspace
    may pick problems up."""
    rel.problems, rel.reader = [], True

    def share(m, q, body):
        req = json.loads(body)
        if req["blob_id"] not in rel.blobs or len(rel.blobs[req["blob_id"]]) != req["size"]:
            return 404, {"error": "not_found", "message": "No such file."}
        for p in rel.problems:
            if p["ref"] == req["ref"] and p["from"] == WS:
                return 200, {"id": p["id"]}
        pid = "pb_" + hashlib.sha256(req["ref"].encode()).hexdigest()[:16]
        rel.problems.append(
            {**req, "id": pid, "from": WS, "from_name": "Pilatus", "status": "new", "taken_by": None}
            | {"shared_at": "2026-11-16T12:00:00Z"}
        )
        return 201, {"id": pid}

    def guard(fn):
        def inner(m, q, b):
            if not rel.reader:
                return 403, {
                    "error": "forbidden",
                    "message": "The admin has not let this workspace pick problems up.",
                }
            return fn(m, q, b)

        return inner

    def one(m):
        return next((p for p in rel.problems if p["id"] == m.group(1)), None)

    def status(m, q, body):
        p = one(m)
        p["status"] = json.loads(body)["status"]
        p["taken_by"] = WS if p["status"] != "new" else None
        return 200, p

    rel.route("POST", "/v1/problems", share)
    rel.route(
        "GET",
        "/v1/problems",
        guard(
            lambda m, q, b: (
                200,
                {
                    "items": [p for p in rel.problems if q.get("status", ["new"])[0] in ("all", p["status"])],
                    "next": None,
                },
            )
        ),
    )
    rel.route(
        "GET",
        r"/v1/problems/(pb_[a-z0-9]+)/file",
        guard(lambda m, q, b: (200, None, rel.blobs[one(m)["blob_id"]])),
    )
    rel.route("POST", r"/v1/problems/(pb_[a-z0-9]+)/status", guard(status))
    rel.route(
        "GET",
        r"/v1/problems/(pb_[a-z0-9]+)",
        guard(lambda m, q, b: (200, one(m)) if one(m) else (404, {"error": "not_found", "message": "no"})),
    )
    assert run("relay", "connect", rel.url, "--workspace", WS, "--token", rel.token)[0] == 0
    return rel


def names(data: bytes) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as t:
        return sorted(m.name for m in t)


def make(proj, **kw):
    tid = stuck(proj, title="Send the newsletter")
    return diag_report.make(proj, ticket=tid, note="stuck since 10:00", expected="it is sent", **kw)


def test_report_takes_more_details_and_added_files(proj):
    made = make(
        proj,
        more="It worked yesterday.\nSecond line.",
        files=[("../../shot one.png", b"\x89PNG\x00\xff"), ("shot one.png", b"two"), (".env", b"x")],
    )
    f = Path(made["path"])
    assert (f / "attachments" / "shot one.png").read_bytes() == b"\x89PNG\x00\xff"
    assert (f / "attachments" / "shot one-2.png").read_bytes() == b"two"
    assert (f / "attachments" / "env").read_bytes() == b"x"
    assert sorted(p.name for p in (f / "attachments").iterdir()) == ["env", "shot one-2.png", "shot one.png"]
    man = json.loads((f / "manifest.json").read_text())
    assert man["more"].startswith("It worked yesterday.") and man["expected"] == "it is sent"
    assert [a["name"] for a in man["attachments"]] == ["shot one.png", "shot one-2.png", "env"]
    assert "attachments/shot one.png" in man["files"]
    text = (f / "SUMMARY.md").read_text()
    assert "## More details from the person" in text and "- shot one-2.png" in text


def test_report_refuses_too_many_or_too_big_added_files(proj):
    with pytest.raises(Refused, match="at most 10"):
        make(proj, files=[(f"f{i}", b"x") for i in range(11)])
    with pytest.raises(Refused, match="bigger than 8 MB"):
        make(proj, files=[("big.bin", bytes(diag_report.ATTACH_FILE_BYTES + 1))])
    assert not list(diag_report.reports_dir(proj).glob("r-*"))


def test_report_command_adds_files(proj, run):
    (proj / "note.txt").write_text("hello")
    code, out, err = run("diag", "report", "--more", "extra words", "--file", "note.txt", "--json")
    assert code == 0, err
    f = Path(json.loads(out.splitlines()[0])["path"])
    assert (f / "attachments" / "note.txt").read_text() == "hello"
    code, _, err = run("diag", "report", "--file", "missing.txt")
    assert code == 2 and "is not a file" in err


def test_share_sends_the_whole_folder_once(proj, run, srv):
    made = make(proj, files=[("shot.png", b"\x89PNG")])
    ref = made["ref"]
    code, out, err = run("relay", "problem", "share", ref, "--dry-run")
    assert code == 0 and "Nothing was sent" in out and "1 added file" in out and not srv.problems
    code, out, err = run("relay", "problem", "share", ref)
    assert code == 0, err
    assert f"Shared report {ref}" in out
    p = srv.problems[0]
    got = names(srv.blobs[p["blob_id"]])
    assert (
        f"{ref}/SUMMARY.md" in got and f"{ref}/attachments/shot.png" in got and f"{ref}/manifest.json" in got
    )
    assert all(n.startswith(ref + "/") for n in got) and p["files"] == len(got) and p["attachments"] == 1
    assert (
        p["note"] == "stuck since 10:00"
        and p["expected"] == "it is sent"
        and p["summary"].startswith("# Diag")
    )
    assert relay_problems.shared(proj, ref)["id"] == p["id"]
    # again: the relay keeps one, and the note about where it went never travels
    assert run("relay", "problem", "share", ref)[0] == 0 and len(srv.problems) == 1
    assert f"{ref}/shared.json" not in names(srv.blobs[srv.problems[0]["blob_id"]])


def test_share_refuses_what_is_not_a_report(proj, run, srv):
    assert run("relay", "problem", "share", "../../etc")[0] == 2
    assert run("relay", "problem", "share", "r-1116-1200-nope")[0] == 2
    made = diag_report.make(proj, kind="i", window_s=900)
    assert run("relay", "problem", "share", made["ref"])[0] == 2 and not srv.problems


def test_share_is_stopped_by_a_secret_in_an_added_file(proj, run, srv):
    key = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    made = make(proj, files=[("notes.txt", f"token {key}\n".encode())])
    code, _, err = run("relay", "problem", "share", made["ref"])
    assert code == 2 and "nothing was sent" in err and key not in err and not srv.problems and not srv.blobs


def test_share_needs_a_relay(proj, run):
    made = make(proj)
    code, _, err = run("relay", "problem", "share", made["ref"])
    assert code == 2


def test_pick_up_fetches_into_the_reports_folder(proj, run, srv, tmp_path):
    made = make(proj, files=[("shot.png", b"\x89PNG")])
    ref = made["ref"]
    assert run("relay", "problem", "share", ref)[0] == 0
    pid = srv.problems[0]["id"]
    code, out, _ = run("relay", "problem", "list")
    assert code == 0 and pid in out and "stuck since 10:00" in out
    code, out, err = run("relay", "problem", "get", pid, "--json")
    assert code == 0, err
    got = json.loads(out)
    f = Path(got["path"])
    assert (
        f.parent == diag_report.reports_dir(proj) and f.name == f"{ref}-2"
    )  # the own report keeps its folder
    assert (f / "attachments" / "shot.png").read_bytes() == b"\x89PNG"
    assert json.loads((f / "from.json").read_text())["id"] == pid
    assert srv.problems[0]["status"] == "taken"
    # a second get gives the same folder
    assert json.loads(run("relay", "problem", "get", pid, "--json")[1])["ref"] == f.name
    assert run("relay", "problem", "done", pid)[0] == 0 and srv.problems[0]["status"] == "done"
    assert run("relay", "problem", "back", pid)[0] == 0 and srv.problems[0]["status"] == "new"


def test_pick_up_is_refused_when_the_admin_did_not_allow_it(proj, run, srv):
    srv.reader = False
    code, _, err = run("relay", "problem", "list")
    assert code == 2 and "pick problems up" in err


def bad_tar(members) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for info, data in members:
            t.addfile(info, io.BytesIO(data) if data is not None else None)
    return buf.getvalue()


@pytest.mark.parametrize("kind", ["escape", "other-top", "link", "absolute", "newline", "dot-end"])
def test_fetch_keeps_nothing_of_an_archive_that_is_not_plain_files(proj, run, srv, kind):
    ref = "r-1116-1200-ws"
    ok = tarfile.TarInfo(f"{ref}/SUMMARY.md")
    ok.size = 2
    if kind == "link":
        bad = tarfile.TarInfo(f"{ref}/x")
        bad.type, bad.linkname = tarfile.SYMTYPE, "/etc/passwd"
        members = [(ok, b"hi"), (bad, None)]
    else:
        name = {
            "escape": f"{ref}/../../evil",
            "other-top": "other/evil",
            "absolute": "/tmp/evil",
            "newline": f"{ref}/a\nb",
            "dot-end": f"{ref}/con.",
        }[kind]
        bad = tarfile.TarInfo(name)
        bad.size = 1
        members = [(ok, b"hi"), (bad, b"x")]
    data = bad_tar(members)
    srv.blobs["b_" + "0" * 16] = data
    srv.problems.append(
        {
            "id": PID,
            "ref": ref,
            "from": "ws_other00001",
            "from_name": "Other",
            "status": "new",
            "taken_by": None,
        }
        | {"blob_id": "b_" + "0" * 16, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    )
    code, _, err = run("relay", "problem", "get", PID)
    assert code == 2 and "Nothing was kept" in err
    assert not (diag_report.reports_dir(proj) / ref).exists()
    assert not (proj / "evil").exists() and not (proj.parent / "evil").exists()


def test_fetch_refuses_bytes_that_changed(proj, run, srv):
    data = bad_tar([])
    srv.blobs["b_" + "0" * 16] = data
    srv.problems.append(
        {"id": PID, "ref": "r-1116-1200-ws", "from": "ws_other00001", "status": "new", "taken_by": None}
        | {"blob_id": "b_" + "0" * 16, "size": len(data), "sha256": "0" * 64}
    )
    code, _, err = run("relay", "problem", "get", PID, "--look")
    assert code == 2 and "changed on the way" in err


def test_share_takes_the_page_picture_but_not_a_secret_in_it(proj, run, srv):
    page = "<html><body><h1>Ticket</h1><p>all good</p></body></html>"
    made = make(proj, page=page)
    assert run("relay", "problem", "share", made["ref"])[0] == 0 and len(srv.problems) == 1
    # the check reads the very bytes that are sent: text in the page and in any attribute alike
    for hidden in (
        "<p>password: hunter2-Really-Long-9981</p>",
        '<p data-note="password: hunter2-Really-Long-9981"></p>',
    ):
        bad = make(proj, page=page.replace("<p>all good</p>", hidden))
        code, _, err = run("relay", "problem", "share", bad["ref"])
        assert code == 2 and "screen/page.html" in err and len(srv.problems) == 1, hidden


def test_a_refused_send_does_not_block_the_next_report(proj, run, srv):
    """The refusal is logged with its code place (secretscan:refuse_if_secret:<line>); the next report holds
    that line and must still be sendable. A real secret next to a code place is still caught."""
    bad = make(proj, page="<p>password: hunter2-Really-Long-9981</p>")
    assert run("relay", "problem", "share", bad["ref"])[0] == 2
    nxt = make(proj)
    assert "refuse_if_secret" in (Path(nxt["path"]) / "errors.json").read_text()
    code, _, err = run("relay", "problem", "share", nxt["ref"])
    assert code == 0, err
    worse = make(proj)
    f = Path(worse["path"]) / "errors.json"
    f.write_text(json.dumps([{"sample_frames": ["a:b:1"], "why": "password: hunter2-Really-Long-9981"}]))
    assert run("relay", "problem", "share", worse["ref"])[0] == 2
    # a value that is labelled as a password stays caught even when it is shaped like a code place
    for text in (
        '{"why": "password: admin:hunter:1234"}',
        '[{"sample_frames": ["password=admin:hunter:1234"]}]',
    ):
        shaped = make(proj)
        (Path(shaped["path"]) / "errors.json").write_text(text)
        assert run("relay", "problem", "share", shaped["ref"])[0] == 2, text
    # a real token as one name of something shaped like a code place stays in the text and is caught
    token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    for text in (f'[{{"sample_frames": ["mod:{token}:12"]}}]', f'[{{"sample_frames": ["{token}:fn:12"]}}]'):
        tok = make(proj)
        (Path(tok["path"]) / "errors.json").write_text(text)
        assert run("relay", "problem", "share", tok["ref"])[0] == 2, text
    md = make(proj)
    (Path(md["path"]) / "SUMMARY.md").write_text("# x\n- at secretscan:refuse_if_secret:241\n")
    res = run("relay", "problem", "share", md["ref"])
    assert res[0] == 0, res
    (Path(md["path"]) / "SUMMARY.md").write_text("# x\npassword: admin:hunter:1234\n")
    (Path(md["path"]) / "shared.json").unlink()
    assert run("relay", "problem", "share", md["ref"])[0] == 2

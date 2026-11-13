"""`link.share`: a file picked in the browser goes to `orch publish file` from a private copy that is removed right after."""

import base64
import json
import os
import subprocess
from pathlib import Path

import pytest

from orch_dashboard import actions


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


@pytest.fixture
def shared(tmp_path, monkeypatch):
    """A fake `orch publish file`: records the argv and what the copy held while it ran."""
    seen = {}
    (tmp_path / ".orch").mkdir(exist_ok=True)  # a workspace always has one

    def fake_run(argv, **kw):
        path = argv[argv.index("file") + 1]
        seen.update(argv=argv, content=Path(path).read_bytes(), mode=oct(os.stat(path).st_mode & 0o777))
        out = json.dumps(
            {"id": "f_abc123", "name": path.rsplit("/", 1)[-1], "link": "https://x/f/f_abc123#k=SECRETKEY"}
        )
        return subprocess.CompletedProcess(argv, 0, out, "")

    monkeypatch.setattr(actions, "_run", fake_run)
    monkeypatch.setattr(actions, "publish_connected", lambda root, orch_bin: True)
    return seen


def test_the_file_is_shared_from_a_private_copy_and_the_link_stays_off_the_page(tmp_path, shared):
    code, text, out = actions.share_file(
        tmp_path, "orch", {"name": "report.html", "data": b64(b"<p>hi</p>"), "days": 7}
    )
    assert code == 200 and out == {"id": "f_abc123", "name": "report.html"}  # no link, no key
    assert "SECRETKEY" not in json.dumps(out) + text
    assert shared["content"] == b"<p>hi</p>" and shared["mode"] == "0o600"
    assert shared["argv"][:3] == ["orch", "publish", "file"]
    assert shared["argv"][4:] == ["--days", "7", "--json"]
    assert "/.orch/run/share/" in shared["argv"][3]
    assert not any((tmp_path / ".orch" / "run" / "share").iterdir())  # removed again


@pytest.mark.parametrize(
    "args",
    [
        {"name": "a.txt", "data": b64(b"x"), "extra": 1},
        {"name": "", "data": b64(b"x")},
        {"name": "..", "data": b64(b"x")},
        {"name": "a.txt", "data": "not base64!!"},
        {"name": "a.txt", "data": ""},
        {"name": "a.txt", "data": b64(b"x"), "days": 0},
        {"name": "a.txt", "data": b64(b"x"), "days": 91},
        {"name": "a.txt", "data": b64(b"x"), "days": "7"},
        {"name": "a.txt", "data": b64(b"x" * (actions.SHARE_MAX + 1))},
    ],
)
def test_bad_requests_are_refused_before_anything_is_written(tmp_path, shared, args):
    with pytest.raises(actions.BadRequest):
        actions.share_file(tmp_path, "orch", args)
    assert not shared and not (tmp_path / ".orch" / "run" / "share").exists()


def test_a_path_in_the_name_is_cut_to_the_file_name(tmp_path, shared):
    actions.share_file(tmp_path, "orch", {"name": "../../etc/passwd", "data": b64(b"x")})
    assert shared["argv"][3].endswith("/passwd") and "/.orch/run/share/" in shared["argv"][3]


def test_sharing_must_be_set_up(tmp_path, shared, monkeypatch):
    monkeypatch.setattr(actions, "publish_connected", lambda root, orch_bin: False)
    with pytest.raises(actions.BadRequest, match="not set up"):
        actions.share_file(tmp_path, "orch", {"name": "a.txt", "data": b64(b"x")})
    assert not shared


def test_a_refusal_comes_back_as_plain_words_and_the_copy_is_still_removed(tmp_path, monkeypatch):
    (tmp_path / ".orch").mkdir(exist_ok=True)
    monkeypatch.setattr(actions, "publish_connected", lambda root, orch_bin: True)
    monkeypatch.setattr(
        actions,
        "_run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "Refused: The file is too big.\n"),
    )
    code, text, out = actions.share_file(tmp_path, "orch", {"name": "a.txt", "data": b64(b"x")})
    assert code == 422 and text == "The file is too big." and out is None
    assert not any((tmp_path / ".orch" / "run" / "share").iterdir())


def test_the_op_is_one_of_the_big_ones_and_goes_around_the_argv_table():
    from orch_dashboard import server

    assert "link.share" in server.BIG_OPS and "link.share" not in actions.OPS


def test_a_link_planted_in_the_way_refuses_and_writes_nothing(tmp_path, shared):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / ".orch" / "run").mkdir(parents=True)
    (tmp_path / ".orch" / "run" / "share").symlink_to(elsewhere)
    with pytest.raises(actions.BadRequest):
        actions.share_file(tmp_path, "orch", {"name": "a.txt", "data": b64(b"x")})
    assert not shared and list(elsewhere.iterdir()) == []


def test_stale_copies_are_swept_but_fresh_ones_stay(tmp_path, shared):
    share = tmp_path / ".orch" / "run" / "share"
    share.mkdir(parents=True)
    old, fresh = share / "s-old", share / "s-fresh"
    for d in (old, fresh):
        d.mkdir()
        (d / "x").write_text("x")
    past = __import__("time").time() - 3600
    os.utime(old, (past, past))
    actions.share_file(tmp_path, "orch", {"name": "a.txt", "data": b64(b"x")})
    assert not old.exists() and fresh.exists()


def test_an_unusable_run_folder_fails_closed_in_plain_words(tmp_path, shared, monkeypatch):
    def boom(root, name):
        raise OSError("disk says no")

    monkeypatch.setattr(actions.runfiles, "run_dir", boom)
    with pytest.raises(actions.BadRequest, match="can't be used"):
        actions.share_file(tmp_path, "orch", {"name": "a.txt", "data": b64(b"x")})
    assert not shared

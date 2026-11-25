"""The run folder, site list file and the helper's channel: hand-edited files, odd folder names, dead brokers."""

import json
import os
import shutil
import sys
import tempfile
import threading
import time

import pytest

from orch_browse import channel, paths

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="Unix socket path and 0700 folders")


@pytest.mark.parametrize(
    "text",
    [
        '["example.com"]',  # a plain list, not the {"sites": [...]} file
        '{"sites": "example.com"}',
        '{"sites": ["example.com", 5]}',
        '{"sites": [null]}',
        "null",
    ],
)
def test_a_hand_edited_site_list_of_the_wrong_shape_is_damaged_not_a_crash(ws, text):
    f = paths.sites_file(ws, "t_abc123")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        paths.load_sites(ws, "t_abc123")


def test_site_list_round_trip_in_a_workspace_with_spaces_and_umlauts(tmp_path):
    root = tmp_path / "Mein Ordner Ünterlagen" / "ws"
    paths.save_sites(root, "t_abc123", ["docs.python.org", "example.com", "example.com"])
    assert paths.load_sites(root, "t_abc123") == ["docs.python.org", "example.com"]
    assert not list(paths.sites_file(root, "t_abc123").parent.glob("*.tmp"))
    # Missing is an empty list, never an error.
    assert paths.load_sites(root, "t_other") == []


def test_a_crlf_site_list_from_windows_reads_the_same(ws):
    f = paths.sites_file(ws, "t_abc123")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b'{\r\n "sites": [\r\n  "Example.com"\r\n ]\r\n}\r\n')
    assert paths.load_sites(ws, "t_abc123") == ["example.com"]


def test_a_damaged_state_file_reads_as_no_state(tmp_path):
    assert paths.read_state(tmp_path) == {}
    (tmp_path / "state.json").write_text("{ half", encoding="utf-8")
    assert paths.read_state(tmp_path) == {}
    paths.write_state(tmp_path, {"state": "open", "why": "für Tests"})
    assert paths.read_state(tmp_path) == {"state": "open", "why": "für Tests"}


@posix_only
def test_run_folder_is_private_even_with_spaces_and_umlauts(tmp_path):
    run = paths.run_dir(tmp_path / "Dokumente Müller", "t_abc123")
    assert run.is_dir() and (run.stat().st_mode & 0o777) == 0o700
    shots = paths.shots_dir(tmp_path / "Dokumente Müller", "t_abc123")
    assert (shots.stat().st_mode & 0o777) == 0o700


@posix_only
def test_socket_path_counts_bytes_not_characters(tmp_path, monkeypatch):
    """macOS allows 104 bytes: an umlaut takes two, so a folder short in characters can still be too long."""
    monkeypatch.setattr(paths, "SOCK_MAX", len(os.fsencode(tmp_path)) + 30)
    short_run = tmp_path / "abc"
    assert paths.socket_path(short_run) == short_run / "b.sock"
    run = tmp_path / ("ü" * 14)  # 14 characters but 28 bytes: with "/b.sock" over the limit in bytes only
    assert len(str(run / "b.sock")) <= paths.SOCK_MAX < len(os.fsencode(run / "b.sock"))
    got = paths.socket_path(run)
    assert got.parent == paths.Path(tempfile.gettempdir()) / got.parent.name and got.suffix == ".sock"
    assert paths.socket_path(run) == got  # the same run always gets the same socket


@posix_only
def test_channel_round_trip_from_a_long_umlaut_folder(tmp_path):
    run = paths.run_dir(tmp_path / ("Geschäftsunterlagen Überblick " * 3) / "ws", "t_abc123")
    assert len(os.fsencode(run / "b.sock")) > paths.SOCK_MAX
    listener, _wake = channel.listen(run)
    try:
        assert (run / "channel.json").stat().st_mode & 0o777 == 0o600
        got = []

        def serve():
            got.append(r := channel.accept(listener))
            if r:
                channel.answer(r[0], True, f"{r[1]}:{','.join(r[2])}")

        t = threading.Thread(target=serve)
        t.start()
        assert channel.call(run, "look", ["ä b", "2"], timeout=10) == {"ok": True, "out": "look:ä b,2"}
        t.join(10)
    finally:
        channel.close(listener, run)
        paths.forget_run(run)
    assert not (run / "channel.json").exists()
    assert not paths.socket_path(run).exists()


def test_no_broker_means_no_answer_and_no_watch(tmp_path):
    assert channel.call(tmp_path, "ping", [], timeout=1) is None
    assert list(channel.watch(tmp_path, stop_after=0.1)) == []
    (tmp_path / "channel.json").write_text("{ half", encoding="utf-8")
    assert channel.call(tmp_path, "ping", [], timeout=1) is None
    assert channel.stop(tmp_path, "g1") is None and channel.person(tmp_path, "who", []) is None


@posix_only
def test_a_broker_that_died_leaves_no_hang(tmp_path):
    run = paths.run_dir(tmp_path, "t_abc123")
    listener, _wake = channel.listen(run)
    listener.close()  # the broker is gone; its channel.json stays behind
    assert (run / "channel.json").exists()
    assert channel.call(run, "ping", [], timeout=1) is None
    assert list(channel.watch(run, stop_after=0.1)) == []


@pytest.mark.parametrize(
    "raw",
    [b"not json", b"[1, 2]", b'{"cmd": "look", "args": 5}', b'{"cmd": "wake"}'],
)
def test_odd_or_wake_requests_are_dropped(tmp_path, raw):
    from multiprocessing.connection import Client

    listener, _wake = channel.listen(tmp_path)
    info = json.loads((tmp_path / "channel.json").read_text(encoding="utf-8"))
    got = []
    t = threading.Thread(target=lambda: got.append(channel.accept(listener)))
    t.start()
    try:
        with Client(info["address"], family=info["family"], authkey=bytes.fromhex(info["key"])) as c:
            c.send_bytes(raw)
            t.join(10)
    finally:
        channel.close(listener, tmp_path)
    assert got == [None]


def test_args_are_text_and_capped(tmp_path):
    from multiprocessing.connection import Client

    listener, _wake = channel.listen(tmp_path)
    info = json.loads((tmp_path / "channel.json").read_text(encoding="utf-8"))
    got = []
    t = threading.Thread(target=lambda: got.append(channel.accept(listener)))
    t.start()
    try:
        with Client(info["address"], family=info["family"], authkey=bytes.fromhex(info["key"])) as c:
            c.send_bytes(json.dumps({"cmd": "type", "args": [1, *range(30)]}).encode())
            t.join(10)
            conn, cmd, args = got[0]
            conn.close()
    finally:
        channel.close(listener, tmp_path)
    assert cmd == "type" and len(args) == 20 and args[:2] == ["1", "0"]


def test_a_silent_broker_says_it_did_not_answer_and_the_slow_note_runs_once(tmp_path):
    listener, _wake = channel.listen(tmp_path)
    held = []
    t = threading.Thread(target=lambda: held.append(channel.accept(listener)))
    t.start()
    notes = []
    try:
        t0 = time.monotonic()
        r = channel.call(tmp_path, "look", [], timeout=0.6, slow=(0.2, lambda: notes.append(1)))
        assert time.monotonic() - t0 < 5
    finally:
        t.join(10)
        if held and held[0]:
            held[0][0].close()
        channel.close(listener, tmp_path)
    assert r == {"ok": False, "out": "The browser did not answer in time."} and notes == [1]


def test_wake_unblocks_a_waiting_accept(tmp_path):
    listener, wake = channel.listen(tmp_path)
    got = []
    t = threading.Thread(target=lambda: got.append(channel.accept(listener)))
    t.start()
    wake()
    t.join(10)
    channel.close(listener, tmp_path)
    assert got == [None] and not t.is_alive()


def test_leftover_temp_profile_is_deleted_but_nothing_outside_the_temp_folder(tmp_path):
    run = paths.run_dir(tmp_path, "t_abc123")
    old = tempfile.mkdtemp(prefix="orch-browse-")
    (paths.Path(old) / "Default").mkdir()
    (run / "profile.path").write_text(old + "\n", encoding="utf-8")
    paths.clean_leftovers(run)
    assert not os.path.exists(old) and not (run / "profile.path").exists()

    # A hand-edited or odd path never deletes the person's folders.
    mine = tmp_path / "orch-browse-Meine Dateien"
    mine.mkdir()
    (run / "profile.path").write_text(str(mine), encoding="utf-8")
    paths.clean_leftovers(run)
    assert mine.is_dir() and not (run / "profile.path").exists()
    elsewhere = paths.Path(tempfile.mkdtemp(prefix="not-orch-"))
    try:
        (run / "profile.path").write_text(str(elsewhere), encoding="utf-8")
        paths.clean_leftovers(run)
        assert elsewhere.is_dir()
    finally:
        shutil.rmtree(elsewhere, ignore_errors=True)
    paths.clean_leftovers(run)  # nothing left behind: nothing to do
    paths.forget_run(run)  # and forgetting twice is fine

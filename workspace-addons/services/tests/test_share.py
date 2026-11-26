"""orch services share (ORCH-684): the port pick, the file server and the link check, with real sockets.

The platform driver is the fake one, but its start really runs the folder's server in a thread, so the link check
talks to a real server. Report r-1118-2103-ws: a server listening on every address must never be shared behind.
"""

import json
import socket
import sys
import threading
from contextlib import contextmanager

import pytest
from conftest import FakeDriver, jrun


class RunningDriver(FakeDriver):
    """start/stop really run the share server (in this process) for share services."""

    def __init__(self):
        super().__init__()
        self.servers = {}

    def start(self, spec):
        super().start(spec)
        argv = spec.argv
        if "orch_services.share_server" in argv:
            from orch_services import share_server

            a = dict(zip(argv[argv.index("--dir") :: 2], argv[argv.index("--dir") + 1 :: 2], strict=False))
            try:
                srv = share_server.make(__import__("pathlib").Path(a["--dir"]), int(a["--port"]), a["--mark"])
            except OSError:  # like the real service: the port was taken, the server ends at once
                self.entries[spec.sid]["running"] = False
                return
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.servers[spec.sid] = srv

    def stop(self, spec):
        super().stop(spec)
        srv = self.servers.pop(spec.sid, None)
        if srv:
            srv.shutdown()
            srv.server_close()

    def uninstall(self, spec):
        self.stop(spec) if spec.sid in self.servers else None
        super().uninstall(spec)


@pytest.fixture
def fake(monkeypatch):
    from orch_services import drivers

    d = RunningDriver()
    monkeypatch.setattr(drivers, "get", lambda: d)
    yield d
    for srv in list(d.servers.values()):
        srv.shutdown()
        srv.server_close()


def _free_block(n=4):
    """n consecutive ports nothing uses right now (for the share range)."""
    import random

    for _ in range(200):
        base = random.randrange(40000, 60000)
        socks = []
        try:
            for p in range(base, base + n):
                s = socket.socket()
                s.bind(("0.0.0.0", p))
                socks.append(s)
            return base
        except OSError:
            continue
        finally:
            for s in socks:
                s.close()
    raise RuntimeError("no free ports")


@pytest.fixture
def base(ws):
    b = _free_block()
    (ws / ".orch" / "config.toml").write_text(
        f'[services]\nshare_ports = "{b}-{b + 3}"\nshare_name = "my-server.example"\n', encoding="utf-8"
    )
    return b


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "share mé"
    d.mkdir()
    (d / "index.html").write_text("<h1>hello share</h1>", encoding="utf-8")
    return d


@contextmanager
def listener(host, port, family=socket.AF_INET, v6only=None, reuse=False):
    s = socket.socket(family, socket.SOCK_STREAM)
    if reuse:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if v6only is not None:
        s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1 if v6only else 0)
    s.bind((host, port))
    s.listen()
    try:
        yield s
    finally:
        s.close()


def _get(url):
    import urllib.request

    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(url, timeout=3) as r:
        return r.status, r.headers, r.read().decode()


# ---- the port pick


def test_a_listener_on_every_address_is_skipped(base):
    """THE case of the report: a dashboard on *:<port>; a 127.0.0.1 server could still bind next to it with
    SO_REUSEADDR, and the owner's link reached the dashboard."""
    from orch_services import share

    cfg = {"ports": [base, base + 1], "skip": set()}
    with listener("0.0.0.0", base, reuse=True):
        assert share.port_free(base) is False
        assert share.pick_port(cfg, set()) == base + 1


def test_a_listener_on_loopback_is_skipped(base):
    from orch_services import share

    with listener("127.0.0.1", base):
        assert share.port_free(base) is False


def test_a_dual_stack_listener_on_every_address_is_skipped(base):
    if not socket.has_ipv6:
        pytest.skip("no IPv6 here")
    from orch_services import share

    try:
        cm = listener("::", base, socket.AF_INET6, v6only=False)
        cm.__enter__()
    except OSError:
        pytest.skip("no dual-stack IPv6 here")
    try:
        assert share.port_free(base) is False
    finally:
        cm.__exit__(None, None, None)


def test_a_listener_on_another_single_address_does_not_hold_the_port(base):
    """The forwarder listens on the private network address of each port; the port stays usable for 127.0.0.1."""
    import sys

    if sys.platform == "win32":
        pytest.skip("Windows has no second loopback address by default")
    from orch_services import share

    other = "127.0.0.2"
    try:
        cm = listener(other, base)
        cm.__enter__()
    except OSError:
        pytest.skip("no second loopback address here (macOS without an alias)")
    try:
        assert share.port_free(base) is True
    finally:
        cm.__exit__(None, None, None)


def test_kept_ports_and_ports_of_other_services_are_skipped(base):
    from orch_services import share

    cfg = {"ports": [base, base + 1, base + 2], "skip": {base}}
    assert share.pick_port(cfg, {base + 1}) == base + 2
    assert share.pick_port(cfg, {base + 1, base + 2}) is None


def test_the_server_never_binds_next_to_a_listener_on_every_address(base, folder):
    from orch_services import share_server

    with listener("0.0.0.0", base, reuse=True), pytest.raises(OSError):
        share_server.make(folder, base, "m")


# ---- the command


def test_share_prints_a_working_link_and_keeps_a_service_on_the_ticket(cli, ws, fake, base, folder):
    code, out = jrun(cli, "share", str(folder), "--ticket", "DM1-12")
    assert code == 0, out
    assert out["url"] == f"http://my-server.example:{base}/" and out["port"] == base
    assert out["checked_outside"] is False
    rec = json.loads(
        (ws / ".orch/addons/services/services" / f"{out['service']['id']}.json").read_text("utf-8")
    )
    assert rec["made_by"] == {"ticket": "DM1-12"} and rec["port"] == base
    assert rec["share"]["dir"] == str(folder.resolve())
    assert "127.0.0.1" not in out["url"]
    status, headers, body = _get(f"http://127.0.0.1:{base}/")
    assert status == 200 and "hello share" in body and headers["X-Orch-Share"] == rec["share"]["mark"]


def test_a_share_record_matches_the_schema(cli, ws, fake, base, folder):
    from conftest import CONTRACTS, validator

    code, out = jrun(cli, "share", str(folder), "--ticket", "DM1-12")
    assert code == 0, out
    rec = json.loads(
        (ws / ".orch/addons/services/services" / f"{out['service']['id']}.json").read_text("utf-8")
    )
    v = validator(CONTRACTS / "addons" / "services" / "service.schema.json")
    assert not [e.message for e in v.iter_errors(rec)]


def test_share_skips_a_dashboard_on_every_address(cli, fake, base, folder):
    with listener("0.0.0.0", base, reuse=True):
        code, out = jrun(cli, "share", str(folder), "--ticket", "DM1-12")
    assert code == 0, out
    assert out["port"] == base + 1


def test_share_skips_kept_ports(cli, ws, fake, base, folder):
    cfg = ws / ".orch" / "config.toml"
    cfg.write_text(cfg.read_text("utf-8") + f"share_skip = [{base}, {base + 1}]\n", encoding="utf-8")
    code, out = jrun(cli, "share", str(folder), "--ticket", "DM1-12")
    assert code == 0 and out["port"] == base + 2


def test_share_skips_the_dashboard_port_for_other_computers(cli, ws, fake, base, folder):
    cfg = ws / ".orch" / "config.toml"
    cfg.write_text(cfg.read_text("utf-8") + f"[dashboard]\nlisten_port = {base}\n", encoding="utf-8")
    code, out = jrun(cli, "share", str(folder), "--ticket", "DM1-12")
    assert code == 0 and out["port"] == base + 1


def test_the_same_folder_again_gives_the_same_link(cli, fake, base, folder):
    code, first = jrun(cli, "share", str(folder), "--ticket", "DM1-12")
    code2, again = jrun(cli, "share", str(folder), "--ticket", "DM1-12")
    assert code == code2 == 0 and again["again"] is True and again["url"] == first["url"]
    assert len(fake.servers) == 1


def test_two_folders_get_two_ports(cli, fake, base, folder, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    _, a = jrun(cli, "share", str(folder), "--ticket", "DM1-12")
    _, b = jrun(cli, "share", str(other), "--ticket", "DM1-12")
    assert a["port"] != b["port"]


def test_a_foreign_server_on_the_check_address_fails_and_leaves_nothing(
    cli, ws, fake, base, folder, monkeypatch
):
    """The check must see THIS share's mark: a 200 from another server (a dashboard) is not a working link."""
    from orch_services import share

    monkeypatch.setattr(share, "CHECK_SECONDS", 1.0)
    monkeypatch.setattr(share, "TRIES", 1)
    real = share.check_link

    def other_mark(host, port, mark, running=None, seconds=1.0):
        return real(host, port, "not-" + mark, running, seconds=1.0)

    monkeypatch.setattr(share, "check_link", other_mark)
    code, out = jrun(cli, "share", str(folder), "--ticket", "DM1-12")
    assert code == 2 and "did not work" in out["error"] and "Nothing was left running" in out["error"]
    assert not list((ws / ".orch/addons/services/services").glob("*.json"))
    assert fake.servers == {} and fake.entries == {}


def test_a_port_lost_between_pick_and_start_tries_the_next(cli, fake, base, folder, monkeypatch):
    from orch_services import share

    monkeypatch.setattr(share, "CHECK_SECONDS", 1.0)
    real_free = share.port_free
    grabbed = {}

    def free_then_grab(port):  # says free, then another server takes it before ours starts
        ok = real_free(port)
        if ok and port == base and "s" not in grabbed:
            s = socket.socket()
            s.bind(("127.0.0.1", port))
            s.listen()
            grabbed["s"] = s
        return ok

    monkeypatch.setattr(share, "port_free", free_then_grab)
    try:
        code, out = jrun(cli, "share", str(folder), "--ticket", "DM1-12")
    finally:
        grabbed.get("s") and grabbed["s"].close()
    assert code == 0, out
    assert out["port"] == base + 1


def test_a_taken_port_given_with_port_is_refused(cli, fake, base, folder):
    with listener("0.0.0.0", base, reuse=True):
        code, out = jrun(cli, "share", str(folder), "--ticket", "DM1-12", "--port", str(base))
    assert code == 2 and "taken" in out["error"]


def test_a_port_outside_the_range_is_refused(cli, fake, base, folder):
    code, out = jrun(cli, "share", str(folder), "--ticket", "DM1-12", "--port", "8000")
    assert code == 2 and "share_ports" in out["error"]


def test_not_set_up_says_how(cli, ws, fake, folder):
    code, out = jrun(cli, "share", str(folder), "--ticket", "DM1-12")
    assert code == 2 and "share_name" in out["error"] and "share_ports" in out["error"]


@pytest.mark.parametrize(
    "lines,word",
    [
        ('share_ports = "9000-8000"\nshare_name = "a.example"', "low to high"),
        ('share_ports = "80-90"\nshare_name = "a.example"', "between 1024"),
        ('share_ports = "8780-8799"\nshare_name = "a b/"', "not a computer name"),
        ('share_ports = "8780-8799"\nshare_name = "a.example"\nshare_skip = "8786"', "list of ports"),
    ],
)
def test_bad_settings_are_refused_in_plain_words(cli, ws, fake, folder, lines, word):
    (ws / ".orch" / "config.toml").write_text(f"[services]\n{lines}\n", encoding="utf-8")
    code, out = jrun(cli, "share", str(folder), "--ticket", "DM1-12")
    assert code == 2 and word in out["error"]


def test_wide_or_private_folders_are_refused(cli, ws, fake, base, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    (tmp_path / "home" / ".ssh").mkdir(parents=True)
    for p, word in [
        (tmp_path / "home", "too wide"),
        (tmp_path, "too wide"),
        (ws, ".orch"),
        (ws / ".orch", ".orch"),
        (tmp_path / "home" / ".ssh", "private"),
        (tmp_path / "missing", "does not exist"),
    ]:
        code, out = jrun(cli, "share", str(p), "--ticket", "DM1-12")
        assert code == 2 and word in out["error"], (p, out)


def test_a_ticket_is_required(cli, fake, base, folder):
    with pytest.raises(SystemExit):
        cli("share", str(folder))


def test_the_server_never_serves_files_outside_the_folder(base, folder, tmp_path):
    from orch_services import share_server

    secret = tmp_path / "outside.txt"
    secret.write_text("private", encoding="utf-8")
    try:
        (folder / "link.txt").symlink_to(secret)
        (folder / "up").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("no symlinks here")
    srv = share_server.make(folder, base, "m")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        import urllib.error

        for path in ("link.txt", "up/outside.txt", "../outside.txt", "%2e%2e/outside.txt"):
            with pytest.raises(urllib.error.HTTPError) as e:
                _get(f"http://127.0.0.1:{base}/{path}")
            assert e.value.code == 404, path
        status, headers, _ = _get(f"http://127.0.0.1:{base}/index.html")
        assert status == 200 and headers["X-Orch-Share"] == "m"
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_server_is_read_only(base, folder):
    import urllib.error
    import urllib.request

    from orch_services import share_server

    srv = share_server.make(folder, base, "m")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{base}/x", data=b"1", method="POST")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3)
        assert e.value.code == 405
    finally:
        srv.shutdown()
        srv.server_close()


# ---- after the outside review (Codex): index links, private folders, the real process, a failed clean-up


def _serve(folder, base):
    from orch_services import share_server

    srv = share_server.make(folder, base, "m")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _code(url):
    import urllib.error

    try:
        return _get(url)[0]
    except urllib.error.HTTPError as e:
        return e.code


def test_an_index_page_that_links_outside_is_not_served(base, folder, tmp_path):
    secret = tmp_path / "outside.html"
    secret.write_text("private", encoding="utf-8")
    (folder / "index.html").unlink()
    try:
        (folder / "index.html").symlink_to(secret)
    except OSError:
        pytest.skip("no symlinks here")
    srv = _serve(folder, base)
    try:
        assert _code(f"http://127.0.0.1:{base}/") == 404
    finally:
        srv.shutdown()
        srv.server_close()


def test_private_folders_inside_are_never_served_or_listed(base, folder):
    for name in (".orch", ".ssh", ".git"):
        d = folder / "project" / name
        d.mkdir(parents=True)
        (d / "config").write_text("private", encoding="utf-8")
    (folder / "project" / "page.html").write_text("ok", encoding="utf-8")
    srv = _serve(folder, base)
    try:
        for name in (".orch", ".ssh", ".git", ".ORCH"):
            assert _code(f"http://127.0.0.1:{base}/project/{name}/config") == 404, name
        assert _code(f"http://127.0.0.1:{base}/project/.orch/") == 404
        status, _, listing = _get(f"http://127.0.0.1:{base}/project/")
        assert status == 200 and "page.html" in listing
        assert ".orch" not in listing and ".ssh" not in listing and ".git" not in listing
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_service_keeps_this_python_unresolved(cli, fake, base, folder):
    """A virtual environment's python is a link; its resolved target lacks the add-on (the service then fails)."""
    import os
    import sys

    code, out = jrun(cli, "share", str(folder), "--ticket", "DM1-12")
    assert code == 0, out
    argv = fake.entries[out["service"]["id"]]["spec"].argv
    assert argv[0] == os.path.abspath(sys.executable)
    assert argv[1:5] == ["-I", "-P", "-m", "orch_services.share_server"]


def test_the_real_service_command_serves_the_link(cli, ws, fake, base, folder, monkeypatch):
    """The service's own command line, started as its own process the way the computer's service tool does."""
    import subprocess

    procs = {}

    def start(spec):
        FakeDriver.start(fake, spec)
        procs[spec.sid] = subprocess.Popen(spec.argv, cwd=spec.cwd, stderr=subprocess.PIPE)

    def stop(spec):
        FakeDriver.stop(fake, spec)
        p = procs.pop(spec.sid, None)
        if p:
            p.terminate()
            p.wait(5)

    monkeypatch.setattr(fake, "start", start)
    monkeypatch.setattr(fake, "stop", stop)
    try:
        code, out = jrun(cli, "share", str(folder), "--ticket", "DM1-12")
        assert code == 0, out
        status, _, body = _get(f"http://127.0.0.1:{out['port']}/")
        assert status == 200 and "hello share" in body
    finally:
        for p in procs.values():
            p.terminate()
            p.wait(5)


def test_a_share_that_cannot_be_stopped_keeps_its_record(cli, ws, fake, base, folder, monkeypatch):
    from orch_services import share
    from orch_services.store import Refused

    monkeypatch.setattr(share, "check_link", lambda *a, **k: (False, "nothing answered"))

    def refuse(spec):
        raise Refused("the service tool said no")

    monkeypatch.setattr(fake, "uninstall", refuse)
    code, out = jrun(cli, "share", str(folder), "--ticket", "DM1-12")
    assert code == 2 and "could not be stopped" in out["error"] and "orch services remove" in out["error"]
    assert len(list((ws / ".orch/addons/services/services").glob("*.json"))) == 1


def test_a_start_that_fails_and_cannot_be_undone_says_how_to_end_it(cli, ws, fake, base, folder, monkeypatch):
    # #2301: the start raised, the clean-up failed too, and only the start's error was shown
    from orch_services.store import Refused

    def broken_start(spec):
        raise Refused("The service tool refused to start it.")

    def refuse(spec):
        raise Refused("the service tool said no")

    monkeypatch.setattr(fake, "start", broken_start)
    monkeypatch.setattr(fake, "uninstall", refuse)
    code, out = jrun(cli, "share", str(folder), "--ticket", "DM1-12")
    assert code == 2 and out["error"].startswith("The service tool refused to start it.")
    assert "could not be stopped" in out["error"] and "orch services remove share-" in out["error"]
    assert len(list((ws / ".orch/addons/services/services").glob("*.json"))) == 1


# ---- after the security review: every dot name and key files, in any case; the server checks the folder too


def test_dot_names_and_key_files_are_never_served_or_listed(base, folder):
    for name in (".env.local", ".npmrc", "id_rsa", "id_ed25519.pub", "server.PEM", "tls.key"):
        (folder / name).write_text("private", encoding="utf-8")
    (folder / "page.html").write_text("ok", encoding="utf-8")
    srv = _serve(folder, base)
    try:
        for name in (".env.local", ".npmrc", "id_rsa", "id_ed25519.pub", "server.PEM", "tls.key"):
            assert _code(f"http://127.0.0.1:{base}/{name}") == 404, name
        status, _, listing = _get(f"http://127.0.0.1:{base}/")
        assert status == 200  # index.html
        (folder / "index.html").unlink()
        status, _, listing = _get(f"http://127.0.0.1:{base}/")
        assert status == 200 and "page.html" in listing
        assert not any(n in listing for n in (".env", ".npmrc", "id_rsa", "id_ed25519", ".PEM", "tls.key"))
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.skipif(sys.platform == "win32", reason="file links need admin rights on Windows")
def test_a_link_with_a_private_name_to_an_allowed_file_is_not_served_or_listed(base, folder):
    # #2301: only the resolved file was checked, so a link called .env (or id_rsa) to page.html was served
    (folder / "page.html").write_text("ok", encoding="utf-8")
    for name in (".env", "id_rsa", "secret.key"):
        (folder / name).symlink_to(folder / "page.html")
    (folder / "index.html").unlink(missing_ok=True)
    srv = _serve(folder, base)
    try:
        for name in (".env", "id_rsa", "secret.key"):
            assert _code(f"http://127.0.0.1:{base}/{name}") == 404, name
        assert _code(f"http://127.0.0.1:{base}/page.html") == 200
        _, _, listing = _get(f"http://127.0.0.1:{base}/")
        assert "page.html" in listing and not any(n in listing for n in (".env", "id_rsa", "secret.key"))
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_folder_in_a_dot_folder_is_refused_in_any_case(cli, fake, base, tmp_path):
    for parts in ((".Orch", "x"), (".SSH",), (".config", "site")):
        d = tmp_path.joinpath(*parts)
        d.mkdir(parents=True)
        code, out = jrun(cli, "share", str(d), "--ticket", "DM1-12")
        assert code == 2 and "private" in out["error"], parts


def test_the_server_itself_refuses_a_private_folder(base, tmp_path):
    from orch_services import share_server

    d = tmp_path / ".ssh"
    d.mkdir()
    with pytest.raises(ValueError):
        share_server.make(d, base, "m")


# ---- the server's own start-up errors and names with spaces and umlauts (coverage run)


def test_the_server_start_says_why_it_cannot_run(base, folder, tmp_path, capsys):
    from orch_services import share_server

    assert share_server.main(["--dir", str(tmp_path / "gone ü"), "--port", str(base), "--mark", "m"]) == 2
    assert "does not exist" in capsys.readouterr().err
    private = tmp_path / ".config" / "site"
    private.mkdir(parents=True)
    assert share_server.main(["--dir", str(private), "--port", str(base), "--mark", "m"]) == 2
    assert "never shared" in capsys.readouterr().err
    with listener("127.0.0.1", base):
        assert share_server.main(["--dir", str(folder), "--port", str(base), "--mark", "m"]) == 3
    assert f"Port {base} is taken" in capsys.readouterr().err


def test_names_with_spaces_and_umlauts_are_listed_and_served(base, folder):
    import urllib.parse

    sub = folder / "Bericht März"
    sub.mkdir()
    (sub / "Jörg & Söhne <1>.txt").write_text("grüezi", encoding="utf-8")
    srv = _serve(folder, base)
    try:
        status, headers, listing = _get(f"http://127.0.0.1:{base}/{urllib.parse.quote('Bericht März')}/")
        assert status == 200 and headers["X-Orch-Share"] == "m" and headers["Cache-Control"] == "no-store"
        assert "Jörg &amp; Söhne &lt;1&gt;.txt" in listing  # escaped in the page
        href = listing.split('href="', 1)[1].split('"', 1)[0]
        assert "<" not in href and " " not in href
        status, _, body = _get(f"http://127.0.0.1:{base}/{urllib.parse.quote('Bericht März')}/{href}")
        assert status == 200 and body == "grüezi"
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_folder_that_cannot_be_read_is_not_found(base, folder, monkeypatch):
    from orch_services import share_server

    (folder / "index.html").unlink()

    def denied(path):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(share_server.os, "listdir", denied)
    srv = _serve(folder, base)
    try:
        assert _code(f"http://127.0.0.1:{base}/") == 404
    finally:
        srv.shutdown()
        srv.server_close()

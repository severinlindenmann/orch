"""Meetings 6 (ORCH-1268): orch Companion sends a finished recording to our transcription service and keeps the
transcript with times and me/others; when the service is down the person sees a plain message and the recording is
kept for a retry. The service here is a fake that speaks contracts/transcription-api.md (encrypted jobs)."""

import base64
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from conftest import as_helper, jrun
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

HERE = Path(__file__).parent
SWIFT_DIR = HERE.parents[2] / "companion" / "mac"
TEMPLATE = HERE.parent / "src" / "orch_personal" / "way_templates" / "companion"
TOKEN = "ort_" + "A" * 43
MAC = pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("swiftc"), reason="needs macOS and swiftc"
)


def unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def result_key(job_key):
    return HKDF(hashes.SHA256(), 32, salt=None, info=b"orch-transcription result v1").derive(job_key)


def opf1_open(blob, key):
    plain = AESGCM(key).decrypt(blob[4:16], blob[16:], b"OPF1")
    n = struct.unpack(">I", plain[:4])[0]
    head = json.loads(plain[4 : 4 + n])
    body = plain[4 + n :]
    assert head["size"] == len(body)
    return head, body


def opf1_seal(head, body, key):
    iv = os.urandom(12)
    h = json.dumps(head).encode()
    return b"OPF1" + iv + AESGCM(key).encrypt(iv, struct.pack(">I", len(h)) + h + body, b"OPF1")


def tone(pcm_bytes):
    """Which fake tone a WAV piece holds (440 Hz = the fake microphone, 660 Hz = the fake call sound), and where."""
    import array

    a = array.array("h")
    a.frombytes(pcm_bytes)
    nz = [i for i, v in enumerate(a) if v]
    if not nz:
        return None, 0, 0
    first, last = nz[0], nz[-1]
    crossings = sum(1 for i in range(first + 1, last) if (a[i] >= 0) != (a[i - 1] >= 0))
    secs = (last - first) / 16000
    hz = crossings / 2 / secs if secs else 0
    return (
        (440 if abs(hz - 440) < 30 else 660 if abs(hz - 660) < 30 else round(hz)),
        first / 16000,
        last / 16000,
    )


class FakeService:
    """contracts/transcription-api.md jobs, in memory. mode: ok | refuse (401) | fail (job failed)."""

    def __init__(self, port=0, mode="ok"):
        self.mode = mode
        self.jobs = {}
        self.posts = 0
        self.tries = 0  # every request that reached the service, also refused ones
        self.deleted = []
        self.seen = []  # (name, tone, first, last) per uploaded piece
        svc = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=b"", ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _auth(self):
                svc.tries += 1
                if self.headers.get("Authorization") != f"Bearer {TOKEN}" or svc.mode == "refuse":
                    self._send(401, b'{"error":"unauthorized","message":"x"}')
                    return False
                return True

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if not self._auth():
                    return
                if self.path.startswith("/v1/jobs") and self.path.count("/") == 2:
                    svc.posts += 1
                    key = unb64(self.headers["X-Orch-Job-Key"])
                    head, wav = opf1_open(body, key)
                    assert head["type"] == "audio/wav" and wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
                    hz, first, last = tone(wav[44:])
                    svc.seen.append((head["name"], hz, first, last))
                    jid = f"j{svc.posts}"
                    svc.jobs[jid] = {"key": key, "hz": hz, "first": first, "last": last, "polls": 0}
                    self._send(202, json.dumps({"id": jid, "status": "waiting"}).encode())
                else:
                    self._send(404, b'{"error":"not_found"}')

            def do_GET(self):
                if not self._auth():
                    return
                parts = self.path.split("/")
                job = svc.jobs.get(parts[3]) if len(parts) > 3 else None
                if not job:
                    return self._send(404, b'{"error":"not_found"}')
                if len(parts) == 4:
                    job["polls"] += 1
                    st = "running" if job["polls"] < 2 else ("failed" if svc.mode == "fail" else "done")
                    out = {"id": parts[3], "status": st}
                    if st == "failed":
                        out["error"] = "transcription_failed"
                    return self._send(200, json.dumps(out).encode())
                segs = (
                    []
                    if job["hz"] is None
                    else [{"start": job["first"], "end": job["last"], "text": f" tone {job['hz']} "}]
                )
                res = json.dumps({"text": "", "language": "de", "duration": 1, "segments": segs}).encode()
                blob = opf1_seal(
                    {"name": "transcript.json", "type": "application/json", "size": len(res)},
                    res,
                    result_key(job["key"]),
                )
                self._send(200, blob, "application/octet-stream")

            def do_DELETE(self):
                if not self._auth():
                    return
                jid = self.path.split("/")[3]
                svc.jobs.pop(jid, None)
                svc.deleted.append(jid)
                self._send(204)

        self.server = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def companion_exe(tmp_path_factory):
    out = tmp_path_factory.mktemp("companion-build")
    subprocess.run([str(SWIFT_DIR / "build.sh"), str(out)], check=True, capture_output=True, timeout=600)
    return out / "orch Companion.app" / "Contents" / "MacOS" / "orch-companion"


# The workspace in these runs is the way in template itself: its name in Companion's folder (companion_files.me).
WS = hashlib.sha256(str(TEMPLATE.resolve()).encode()).hexdigest()[:16]


class Companion:
    """orch Companion headless with a fake call (yes at 3 s, call app off at 9 s) and fake audio; the wanted file
    is renewed every second as the workspace would, with the transcription service."""

    def __init__(self, exe, home, port, others=None):
        self.home = home
        self.others = others or {}  # more workspaces that want calls: name -> service
        (home / "wanted").mkdir(parents=True)
        self.keys = home.parent / (home.name + "-keys")
        fake = home.parent / (home.name + ".txt")
        fake.write_text("0 com.microsoft.teams2 on\n3 answer yes\n9 com.microsoft.teams2 off\n")
        self.service = {"url": f"http://127.0.0.1:{port}", "token": TOKEN}
        self.renew()
        env = {
            **os.environ,
            "ORCH_COMPANION_HOME": str(home),
            "ORCH_COMPANION_TEST_KEYS": str(self.keys),
            "ORCH_COMPANION_PIECE_SECONDS": "4",
            "ORCH_COMPANION_RETRY_SECONDS": "1",
            "ORCH_COMPANION_POLL_SECONDS": "0.1",
        }
        argv = [str(exe), "--headless", "--fake-input", str(fake), "--fake-audio"]
        self.p = subprocess.Popen(argv, env=env)
        self.stop_renew = threading.Event()
        threading.Thread(target=self._renew_loop, daemon=True).start()

    def renew(self):
        for name, service in [(WS, self.service), *self.others.items()]:
            p = self.home / "wanted" / f"{name}.json"
            p.write_text(json.dumps({"v": 1, "jobs": ["calls"], "service": service}))
            os.chmod(p, 0o600)

    def _renew_loop(self):
        while not self.stop_renew.wait(1):
            self.renew()

    def transcript(self):
        for d in (self.home / "recordings").glob("*"):
            try:
                return d, json.loads((d / "transcript.json").read_text())
            except (OSError, ValueError):
                pass
        return None, None

    def wait(self, check, secs):
        end = time.time() + secs
        while time.time() < end:
            d, t = self.transcript()
            if t and check(t):
                return d, t
            time.sleep(0.3)
        raise AssertionError(f"waited {secs}s: {self.transcript()[1]}")

    def close(self):
        self.stop_renew.set()
        self.p.terminate()
        self.p.wait(timeout=10)


def digest(d):
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in d.iterdir() if f.suffix == ".ocr"}


@MAC
def test_after_the_call_the_transcript_comes_back_with_times_and_me_and_others(tmp_path, companion_exe):
    svc = FakeService()
    user = tmp_path / "user"  # the person's home: the way in finds Companion's folder there
    c = Companion(companion_exe, user / "Library" / "Application Support" / "orch Companion", svc.port)
    try:
        d, t = c.wait(lambda t: t["state"] == "done", 90)
    finally:
        c.close()
        svc.stop()
    lines = t["lines"]
    assert {x["who"] for x in lines} == {"me", "others"}
    for x in lines:
        assert x["text"] == ("tone 440" if x["who"] == "me" else "tone 660"), (
            x
        )  # each track keeps its speaker
        assert 0 <= x["start"] <= x["end"] <= t["minutes"] * 60 + 30
    assert [x["start"] for x in lines] == sorted(x["start"] for x in lines)
    assert any(x["start"] >= 4 for x in lines)  # later pieces moved onto the recording's timeline
    assert len(svc.seen) >= 4 and {s[0].split("-")[0] for s in svc.seen} == {"me", "others"}
    assert t["language"] == "de" and t["app"] == "Teams" and t["id"] == d.name and "problem" not in t
    assert sorted(svc.deleted) == sorted(f"j{i + 1}" for i in range(svc.posts))  # every job deleted after use
    assert oct((d / "transcript.json").stat().st_mode & 0o777) == "0o600"
    assert not list(d.glob("piece-*")) and (d / "me.ocr").exists() and (d / "others.ocr").exists()
    assert sorted(p.name for p in c.keys.iterdir()) == [d.name]  # job keys are gone, the recording key stays
    # the way in (step 7) lists it as a meeting with Me / Others lines
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(user)}
    run = lambda req: json.loads(
        subprocess.run(
            [sys.executable, "-B", "meetings.py"],
            cwd=TEMPLATE,
            env=env,
            input=json.dumps(req),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    (m,) = run({"action": "meetings", "values": {}})["meetings"]
    assert m["ref"] == d.name
    page = run({"action": "meeting", "values": {"ref": m["ref"], "rev": m["rev"], "cursor": None}})
    assert {x["who"] for x in page["transcript"]} == {"Me", "Others"}


@MAC
def test_service_down_shows_a_plain_message_keeps_the_recording_and_retries(tmp_path, companion_exe):
    port = free_port()
    c = Companion(companion_exe, tmp_path / "home", port)
    svc = None
    try:
        d, t = c.wait(
            lambda t: t["state"] == "waiting" and "cannot be reached" in (t.get("problem") or ""), 60
        )
        assert "The recording is kept." in t["problem"] and "tries again at" in t["problem"]
        now = json.loads((c.home / "now.json").read_text())
        deadline = time.time() + 10
        while "transcript_problem" not in now and time.time() < deadline:
            time.sleep(0.3)
            now = json.loads((c.home / "now.json").read_text())
        assert "cannot be reached" in now["transcript_problem"]
        before = digest(d)
        assert set(before) == {"me.ocr", "others.ocr"} and (c.keys / d.name).exists()
        time.sleep(2.5)  # a few failed tries
        assert digest(d) == before and (c.keys / d.name).exists()  # kept, untouched
        svc = FakeService(port)  # the service is back
        d, t = c.wait(lambda t: t["state"] == "done", 60)
        assert {x["who"] for x in t["lines"]} == {"me", "others"} and "problem" not in t
    finally:
        c.close()
        if svc:
            svc.stop()


@MAC
def test_a_refused_key_is_said_plainly_and_not_tried_again_and_again(tmp_path, companion_exe):
    svc = FakeService(mode="refuse")
    c = Companion(companion_exe, tmp_path / "home", svc.port)
    try:
        d, t = c.wait(lambda t: "did not accept" in (t.get("problem") or ""), 60)
        n = svc.tries
        time.sleep(12)  # more than two passes of the sender (one every 5 s)
        assert svc.tries == n  # not asked again until the setting changes
        assert digest(d) and t["state"] == "waiting"
        svc.mode = "fail"  # a new key: tried again; the service then fails every job
        c.service = {"url": f"http://localhost:{svc.port}", "token": TOKEN}
        c.renew()
        d, t = c.wait(lambda t: t["state"] == "failed", 60)
        assert t["problem"] == "The transcript could not be made. The recording is kept."
        assert digest(d)
    finally:
        c.close()
        svc.stop()


@MAC
def test_two_workspaces_with_different_services_never_pick_one_by_order(tmp_path, companion_exe):
    svc, other = FakeService(), FakeService()
    c = Companion(
        companion_exe,
        tmp_path / "home",
        svc.port,
        others={"ws2": {"url": f"http://127.0.0.1:{other.port}", "token": TOKEN}},
    )
    try:
        # two workspaces used Companion: nothing is sent until the person picks which get the call (ORCH-1269)
        d, t = c.wait(lambda t: "until you pick" in (t.get("problem") or ""), 60)
        assert svc.tries == 0 and other.tries == 0
        (d / "pick.json").write_text(json.dumps({"v": 1, "for": [WS, "ws2"], "at": "2026-11-22T12:00:00Z"}))
        _, t = c.wait(lambda t: "different transcription services" in (t.get("problem") or ""), 60)
        assert t["state"] == "waiting" and svc.tries == 0 and other.tries == 0  # nothing sent anywhere
    finally:
        c.close()
        svc.stop()
        other.stop()


# ---- the workspace side: the service setting and handing it to orch Companion -----------------------------------


@pytest.fixture
def companion_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    return home / "Library" / "Application Support" / "orch Companion"


def test_only_the_person_sets_the_service_and_only_https_or_the_private_network(cli, ws, monkeypatch):
    from orch_personal import meetings_live

    assert jrun(cli, "meetings", "service")[1]["set"] is False
    with pytest.raises(meetings_live.Refused, match="Plain http"):
        meetings_live.check_service_url("http://example.com:8104")
    with pytest.raises(meetings_live.Refused, match="web address"):
        meetings_live.check_service_url("https://user:pw@example.com")
    assert meetings_live.check_service_url("http://127.0.0.1:8104/") == "http://127.0.0.1:8104"
    assert meetings_live.check_service_url("https://t.example:8104") == "https://t.example:8104"
    with pytest.raises(meetings_live.Refused, match="ort_"):
        meetings_live.set_service(ws, "https://t.example", "nope")
    r = meetings_live.set_service(ws, "https://t.example:8104", TOKEN)
    assert r == {"set": True, "url": "https://t.example:8104"}
    f = ws / ".orch" / "secrets" / "transcription.json"
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    shown = jrun(cli, "meetings", "service")[1]
    assert shown["url"] == "https://t.example:8104" and TOKEN not in json.dumps(
        shown
    )  # the key is never shown
    as_helper(monkeypatch)
    assert jrun(cli, "meetings", "service", "--off")[0] != 0
    monkeypatch.delenv("ORCH_RUN")
    monkeypatch.delenv("ORCH_AGENT")
    monkeypatch.delenv("ORCH_TICKET")
    assert jrun(cli, "meetings", "service", "--off")[1]["set"] is False
    assert not f.exists()


def test_the_look_hands_the_service_to_companion_and_shows_its_problem(cli, ws, companion_home):
    from orch_personal import meetings_live

    companion_home.mkdir(parents=True)
    now = {
        "v": 1,
        "state": "idle",
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "instance": "a1",
        "transcript_problem": "Transcript waits: the transcription service cannot be reached.",
    }
    (companion_home / "now.json").write_text(json.dumps(now))
    assert jrun(cli, "add", "meetings")[0] == 0
    assert jrun(cli, "meetings", "companion")[0] == 0
    assert jrun(cli, "ways", "on", "companion")[0] == 0
    meetings_live.look(ws)
    (wanted,) = (companion_home / "wanted").glob("*.json")
    assert "service" not in json.loads(wanted.read_text())  # none set: nothing handed over
    meetings_live.set_service(ws, "https://t.example:8104", TOKEN)
    meetings_live.look(ws)
    assert json.loads(wanted.read_text())["service"] == {"url": "https://t.example:8104", "token": TOKEN}
    assert oct(wanted.stat().st_mode & 0o777) == "0o600"
    live = meetings_live.live(ws)
    assert live["transcript_problem"].startswith("Transcript waits")
    meetings_live.remove_service(ws)
    meetings_live.look(ws)
    assert "service" not in json.loads(wanted.read_text())  # turned off: Companion no longer gets it

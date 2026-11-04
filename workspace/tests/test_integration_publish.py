"""Optional: runs the real orch-publish server binary. ORCH_PUBLISH_BIN=<path to the built binary>."""

import json
import os
import random
import socket
import subprocess
import time
import urllib.request

import pytest

from orch import publish

BIN = os.environ.get("ORCH_PUBLISH_BIN")
pytestmark = pytest.mark.skipif(not BIN, reason="set ORCH_PUBLISH_BIN to run against the real server")


def free_port():
    for _ in range(50):
        p = random.randint(18000, 18999)
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise RuntimeError("no free port")


def test_file_roundtrip_against_real_server(proj, run, tmp_path):
    port, aport, admin = free_port(), free_port(), "adm" + "x" * 40
    env = {
        **os.environ,
        "PUBLISH_DATA_DIR": str(tmp_path / "data"),
        "PUBLISH_ADMIN_TOKEN": admin,
        "PUBLISH_LISTEN": f"127.0.0.1:{port}",
        "PUBLISH_ADMIN_LISTEN": f"127.0.0.1:{aport}",
        "PUBLISH_PUBLIC_URL": f"http://127.0.0.1:{port}",
    }
    proc = subprocess.Popen([BIN], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/health", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        req = urllib.request.Request(
            f"http://127.0.0.1:{aport}/admin/api/workspaces",
            method="POST",
            data=json.dumps(
                {
                    "name": "T",
                    "description": "t",
                    "tags": [],
                    "rights": {"files": True, "apps": True, "permanent": True, "public": False},
                }
            ).encode(),
            headers={"X-Orch-Admin": admin, "Content-Type": "application/json"},
        )
        ws = json.load(urllib.request.urlopen(req))
        assert run("publish", "connect", base, "--workspace", ws["id"], "--token", ws["token"])[0] == 0
        (proj / "r.txt").write_bytes(b"real server roundtrip")
        res = json.loads(run("publish", "file", "r.txt", "--json")[1])
        blob = urllib.request.urlopen(f"{base}/f/{res['id']}/blob").read()
        header, content = publish.decrypt(blob, publish.b64u_decode(res["link"].split("#k=")[1]))
        assert content == b"real server roundtrip" and header["name"] == "r.txt"
        assert run("publish", "delete", res["id"])[0] == 0
    finally:
        proc.terminate()
        proc.wait(timeout=10)

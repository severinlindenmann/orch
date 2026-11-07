"""Make two relay workspaces that may text and send files to each other, for the Windows relay round trip.

    python3 relay-pair.py <relay admin url> <admin token file> <relay public url> <out folder> [<url Windows dials>]

Creates "Windows smoke" and "Pilatus" in one new group (members may talk, see contracts/relay-api.md) and writes
  <out>/windows.env   E2E_RELAY_URL, E2E_RELAY_WS, E2E_RELAY_TOKEN, E2E_RELAY_PEER  (for run-as-standard-user.ps1 -EnvFile)
                      E2E_RELAY_URL is <url Windows dials> when given (a winvm guest reaches the Mac only through a
                      host forward, e.g. http://10.0.2.2:18470), else the public url
  <out>/pilatus.json  {url, workspace, token, peer}                             (for the Mac side, relay-peer.py)
Both files are 0600 and hold tokens: keep them in a temp folder and delete it after the run. Nothing is printed but ids.
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path


def call(admin: str, token: str, method: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(
        admin.rstrip("/") + path,
        data=json.dumps(body).encode(),
        method=method,
        headers={"X-Orch-Admin": token, "Content-Type": "application/json"},  # the relay admin header
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")


def write_private(p: Path, text: str) -> None:
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def main() -> int:
    if len(sys.argv) not in (5, 6):
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    admin, token_file, public, out = sys.argv[1:5]
    dial = sys.argv[5] if len(sys.argv) == 6 else public
    token = Path(token_file).read_text(encoding="utf-8").strip()
    group = f"Windows smoke {time.strftime('%H%M%S')}"  # group names are unique per relay
    w = call(admin, token, "POST", "/admin/api/workspaces",
             {"name": "Windows smoke", "description": "Windows standard user smoke test", "tags": [], "new_group": group})
    p = call(admin, token, "POST", "/admin/api/workspaces",
             {"name": "Pilatus", "description": "Mac test workspace for the Windows smoke", "tags": [], "group": w["group"]})
    o = Path(out)
    o.mkdir(parents=True, exist_ok=True)
    write_private(o / "windows.env", "".join(f"{k}={v}\n" for k, v in [
        ("E2E_RELAY_URL", dial), ("E2E_RELAY_WS", w["id"]), ("E2E_RELAY_TOKEN", w["token"]), ("E2E_RELAY_PEER", p["id"])]))
    write_private(o / "pilatus.json", json.dumps({"url": public, "workspace": p["id"], "token": p["token"], "peer": w["id"]}))
    print(f"windows {w['id']}  pilatus {p['id']}  group {w['group']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

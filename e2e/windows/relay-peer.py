"""The Pilatus side of the Windows relay round trip: answers the Windows workspace once, then ends.

    python3 relay-peer.py <workspace folder> [seconds]     (default 300)

The folder is a connected Pilatus workspace (orch init, orch addon add relay, orch relay connect ...; isolated
HOME under env -i). It pulls the inbox until the peer (E2E_RELAY_PEER, the "peer" of pilatus.json) sent
"windows ping <nonce>" and a file; it answers "pong <nonce>" (as a reply) and sends the file back as is.
Prints one "ok:"/"FAIL:" line per step; exit 0 when both answers went out, 1 on timeout or error.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def orch(ws: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["orch", *args], cwd=ws, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120
    )


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    ws = Path(sys.argv[1]).resolve()
    until = time.time() + (int(sys.argv[2]) if len(sys.argv) == 3 else 300)
    peer = os.environ.get("E2E_RELAY_PEER", "")
    if not peer:
        print("FAIL: set E2E_RELAY_PEER (the Windows workspace id)")
        return 2
    nonce = text_done = file_done = None
    seen: set[str] = set()
    while time.time() < until and not (text_done and file_done):
        orch(ws, "relay", "inbox", "--wait", "20")
        for f in sorted((ws / ".orch" / "inbox").glob("m_*.json")):
            m = json.loads(f.read_text(encoding="utf-8"))
            if m["id"] in seen or m.get("from") != peer:
                continue
            seen.add(m["id"])
            body = m.get("body") or {}
            if m.get("type") == "text" and (
                hit := re.search(r"windows ping ([a-z0-9]{8})", body.get("text", ""))
            ):
                nonce = hit.group(1)
                r = orch(ws, "relay", "send", peer, f"pong {nonce}", "--reply-to", m["id"])
                print(
                    ("ok: " if r.returncode == 0 else "FAIL: ") + f"answered the text ({nonce})",
                    r.stdout.strip()[-200:],
                )
                text_done = r.returncode == 0
            elif m.get("type") == "file":
                r = orch(ws, "relay", "download", m["id"])
                saved = re.search(r"Saved (.+)", r.stdout)
                if r.returncode != 0 or not saved:
                    print(f"FAIL: download {body.get('name')}: {(r.stdout + r.stderr).strip()[-200:]}")
                    return 1
                back = orch(ws, "relay", "send", peer, "your file back", "--file", saved.group(1).strip())
                print(
                    ("ok: " if back.returncode == 0 else "FAIL: ")
                    + f"sent the file back ({body.get('name')})"
                )
                file_done = back.returncode == 0
    if not (text_done and file_done):
        print(f"FAIL: no text and file from {peer} in time (text {bool(text_done)}, file {bool(file_done)})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

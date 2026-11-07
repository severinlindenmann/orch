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


def say(line: str) -> None:
    print(line, flush=True)  # run in the background: every line at once


def orch(ws: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["orch", *args], cwd=ws, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120
    )


def tail(r: subprocess.CompletedProcess) -> str:
    return (r.stdout + r.stderr).strip().replace("\n", " | ")[-300:]


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    ws = Path(sys.argv[1]).resolve()
    until = time.time() + (int(sys.argv[2]) if len(sys.argv) == 3 else 300)
    peer = os.environ.get("E2E_RELAY_PEER", "")
    if not peer:
        say("FAIL: set E2E_RELAY_PEER (the Windows workspace id)")
        return 2
    nonce = text_done = file_done = None
    inbox = ws / ".orch" / "inbox"
    seen = {f.stem for f in inbox.glob("m_*.json")}  # only messages that arrive after the start count
    while time.time() < until and not (text_done and file_done):
        orch(ws, "relay", "inbox", "--wait", "20")
        for f in sorted(inbox.glob("m_*.json")):
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
                say(("ok: " if r.returncode == 0 else "FAIL: ") + f"answered the text ({nonce}) {tail(r)}")
                text_done = r.returncode == 0
            elif m.get("type") == "file":
                r = orch(ws, "relay", "download", m["id"])
                saved = re.search(r"Saved (.+)", r.stdout)
                if r.returncode != 0 or not saved:
                    say(f"FAIL: download {body.get('name')}: {tail(r)}")
                    return 1
                back = orch(ws, "relay", "send", peer, "your file back", "--file", saved.group(1).strip())
                say(("ok: " if back.returncode == 0 else "FAIL: ") + f"sent the file back {tail(back)}")
                file_done = back.returncode == 0
    if not (text_done and file_done):
        say(f"FAIL: no text and file from {peer} in time (text {bool(text_done)}, file {bool(file_done)})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

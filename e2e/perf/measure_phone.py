"""The phone's share of a relay inbox pull at size (ORCH-518), without a relay: one fake paired phone, and the
relay's send step replaced by a counter (without a relay set up the sends are refused, so the payload is
the size of the snapshots the first pull would send). Times relay.sync_phone_views (it runs on every inbox pull) twice:
the first pull (every open ticket gets its chat) and a quiet one right after (nothing changed), and counts the
bytes that would have gone to the relay.

usage: python e2e/perf/measure_phone.py <seeded workspace>   (throwaway ORCH_HOME, ORCH_HOME_STRICT=1)
Prints one JSON line. It writes the phone state under the workspace's .orch/secrets (throwaway workspace).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    ws = Path(sys.argv[1]).resolve()
    if os.environ.get("ORCH_HOME_STRICT") != "1":
        raise SystemExit("Run it with ORCH_HOME=<throwaway folder> and ORCH_HOME_STRICT=1.")
    if not (ws / ".orch" / "seeded.json").is_file():
        raise SystemExit("Refused: not a workspace made by e2e/perf/seed.py.")
    from orch import relay, tickets

    sent = {"messages": 0, "bytes": 0}

    def fake_post(root, raw):
        sent["messages"] += 1
        sent["bytes"] += len(raw)

    reads = {"list_all": 0}
    real_list_all = tickets.list_all

    def counting_list_all(*a, **k):
        reads["list_all"] += 1
        return real_list_all(*a, **k)

    relay._post_message = fake_post
    relay._read_dir = lambda root: {"phones": [{"id": "ph_perfprobe1", "name": "Test phone"}]}
    tickets.list_all = counting_list_all
    out = {"tickets": len(list((ws / ".orch" / "tickets").glob("t_*.json")))}
    for name in ("first pull", "quiet pull"):
        sent.update(messages=0, bytes=0)
        reads["list_all"] = 0
        t0 = time.monotonic()
        relay.sync_phone_views(ws)
        out[name] = {"seconds": round(time.monotonic() - t0, 2), "messages": sent["messages"],
                     "bytes": sent["bytes"], "full_reads": reads["list_all"]}  # fmt: skip
    # what the first pull carries to a phone: the snapshot of the OPEN_MAX newest open tickets (sends above are
    # refused without a relay set up, so their size is taken from the views themselves)
    from orch import phone_view

    t0 = time.monotonic()
    recent = [t for t in real_list_all(ws) if phone_view._is_recent(t, time.time())]
    recent.sort(key=lambda t: str(t.get("created_at", "")), reverse=True)
    # phone_view.build is what view_for sends; view_for itself gives None when the saved keys cannot be read
    # (a throwaway home has none), and it would upload proof files
    views = [phone_view.build(ws, t, []) for t in recent[: phone_view.OPEN_MAX]]
    out["first pull views"] = {"tickets": len(views), "bytes": sum(len(json.dumps(v)) for v in views if v),
                               "seconds": round(time.monotonic() - t0, 2)}  # fmt: skip
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

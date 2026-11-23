"""Restart the running services a moment after an add-on add/remove ended (addons._restart_later).

`python -I -P -m orch.restartlater <workspace> <pid> [add-on ...] [--job=<id>]`: waits until <pid> (the orch
command that changed the add-ons, started by the dashboard) has exited, then one more second so the dashboard
has sent its answer, then restarts what runs, like `orch update` does, and starts the add-ons just added.
With --job the add-on job (addonjob) is marked finished afterwards, or failed when a service did not come
back."""

from __future__ import annotations

import sys
import time
from pathlib import Path

WAIT = 120  # seconds: the command ends right after it started this helper


def main(argv: list[str]) -> int:
    from orch import addonjob, addons, services

    job = next((a.split("=", 1)[1] for a in argv[2:] if a.startswith("--job=")), None)
    root, pid = Path(argv[0]), int(argv[1])
    deadline = time.time() + WAIT
    while services.pid_alive(pid) and time.time() < deadline:
        time.sleep(0.2)
    time.sleep(1)
    try:
        lines = addons._restart_updated(root)
        lines += addons._start_added(root, [n for n in argv[2:] if addons.NAME_RE.fullmatch(n)])
    except Exception:
        if job:
            addonjob.restarted(["Could not start the services again"], job)
        raise
    if job:
        addonjob.restarted(lines, job)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (IndexError, ValueError):
        sys.exit(2)

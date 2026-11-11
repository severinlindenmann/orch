---
name: orch-sync
description: Inspect local sync settings and prepare a private state repository.
---
Use `orch sync status --json` to inspect this machine's settings and saved status.
Use `orch sync set --mode off|local --interval 5|15|60` when the person asks.
Remote mode requires the process environment ORCH_SYNC_REMOTE_PREVIEW=1.
This version prepares repositories only; it does not commit, sync, or run a loop.
Team mode and adoption/Move consent flows are unavailable and refused.

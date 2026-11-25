"""Self-check: exit 0 when orch Companion runs, 3 when it is not installed yet (the person's step), else 1."""

import sys

import companion_files

sys.stdin.read()
companion_files.want()
state = companion_files.read_now()["state"]
if state == "missing":
    print("Install and open orch Companion on this Mac.")
    sys.exit(3)
if state == "unavailable":
    print("orch Companion is not running. Open it on your Mac.")
    sys.exit(1)

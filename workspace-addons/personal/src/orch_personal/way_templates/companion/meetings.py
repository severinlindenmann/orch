"""Actions meetings / meeting: recorded calls arrive once orch Companion records (a later step); none yet."""

import json
import sys

req = json.loads(sys.stdin.read() or "{}")
if req.get("action") == "meeting":
    print("That meeting is not in orch Companion.", file=sys.stderr)
    sys.exit(1)
print(json.dumps({"meetings": []}))

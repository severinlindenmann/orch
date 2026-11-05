"""e2e fixture: `orch hello-world [hello|view] [--json]`. `view` sleeps when .orch/addons/hello-world/slow exists."""
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

args = sys.argv[1:]
js = "--json" in args
cmd = next((a for a in args if not a.startswith("-")), "hello")
root = Path(os.environ.get("ORCH_ROOT", "."))
if cmd == "view":
    if (root / ".orch" / "addons" / "hello-world" / "slow").exists():
        time.sleep(6)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(json.dumps({"schema": "orch.addon-view/1", "generated_at": now, "blocks": [
        {"type": "stat", "label": "Greetings", "value": 3, "tone": "good"},
        {"type": "list", "title": "Says", "items": [{"title": "Hello from the fixture"}], "more": 0}]}))
elif cmd == "hello":
    print(json.dumps({"hello": "world"}) if js else "Hello from the fixture add-on.")
else:
    msg = "Unknown command."
    print(json.dumps({"error": msg}) if js else f"Refused: {msg}", file=None if js else sys.stderr)
    sys.exit(2)

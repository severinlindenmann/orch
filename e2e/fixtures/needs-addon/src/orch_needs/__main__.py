"""e2e fixture: `orch needs-addon needs --json` prints rows.json of the workspace; mode.txt = broken makes it fail."""
import json
import os
import sys
from pathlib import Path

root = Path(os.environ.get("ORCH_ROOT", "."))
if sys.argv[1:2] == ["needs"]:
    mode = (root / "mode.txt").read_text().strip() if (root / "mode.txt").exists() else "ok"
    if mode == "broken":
        print("not json")
        sys.exit(1)
    rows = root / "rows.json"
    print(rows.read_text() if rows.exists() else "[]")

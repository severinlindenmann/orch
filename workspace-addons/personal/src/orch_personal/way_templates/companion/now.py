"""Action now: renew this workspace's wanted file (with the transcription service, when Personal hands one over)
and answer Companion's state as one JSON object."""

import json
import sys

import companion_files

try:
    req = json.loads(sys.stdin.read() or "{}")
except ValueError:
    req = {}
values = req.get("values") if isinstance(req, dict) and isinstance(req.get("values"), dict) else {}
companion_files.want(values.get("service"))
print(json.dumps(companion_files.read_now()))

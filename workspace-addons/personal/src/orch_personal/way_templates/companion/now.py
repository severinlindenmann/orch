"""Action now: renew this workspace's wanted file and answer Companion's state as one JSON object."""

import json
import sys

import companion_files

sys.stdin.read()
companion_files.want()
print(json.dumps(companion_files.read_now()))

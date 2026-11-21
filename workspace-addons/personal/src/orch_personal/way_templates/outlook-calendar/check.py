"""Self-check of the Outlook calendar way in: can it read today? Exit 0 works, 1 stopped (one sentence on stderr)."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # a __pycache__ in this folder would change it and stop the way in
import read  # the read.py next to this file

try:
    read.read({"from": dt.date.today().isoformat(), "days": 1}, Path(__file__).resolve().parent)
except read.Stop as e:
    print(str(e), file=sys.stderr)
    sys.exit(1)

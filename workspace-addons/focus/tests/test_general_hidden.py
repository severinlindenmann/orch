"""The hidden General ticket of the phone conversation never shows in Focus."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from orch_focus import cli, livedata  # noqa: E402


def _ticket(root, tid, **kw):
    d = root / ".orch" / "tickets"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{tid}.json").write_text(json.dumps({"id": tid, "key": kw.pop("key", None), **kw}))


def test_by_key_ignores_general(tmp_path):
    _ticket(tmp_path, "t_gen001", key="GEN-1", general=True)
    _ticket(tmp_path, "t_real01", key="REAL-1")
    assert cli._by_key(tmp_path, "gen-1") == "gen-1"
    assert cli._by_key(tmp_path, "real-1") == "t_real01"


def test_records_skip_general(tmp_path):
    _ticket(tmp_path, "t_gen001", general=True)
    _ticket(tmp_path, "t_real01")
    d = tmp_path / ".orch" / "run" / "tickets"
    d.mkdir(parents=True)
    for tid in ("t_gen001", "t_real01"):
        (d / f"{tid}.json").write_text(
            json.dumps({"ticket": tid, "run": "r_1", "pid": 1, "renewed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        )
    got = {r["ticket"] for r in livedata.records(tmp_path)}
    assert "t_gen001" not in got

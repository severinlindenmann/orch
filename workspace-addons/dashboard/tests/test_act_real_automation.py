"""addon.act against the REAL automation CLI (not a fake add-on that accepts anything): the argv the dashboard builds must be
accepted by `orch automation act`. Only `orch` itself is faked (ticket list, ext set/unset, run start); the add-on is real."""

import json
import shutil
import stat
import sys
import threading
from pathlib import Path

import pytest

from orch_dashboard import actions
from orch_dashboard.server import make_server

from .test_act import post

AUTOMATION = Path(__file__).resolve().parents[2] / "automation"

FAKE = """#!{py}
import json, os, subprocess, sys
from pathlib import Path
d = Path(__file__).parent
a = sys.argv[1:]
with open(d / "calls.jsonl", "a") as f:
    f.write(json.dumps(a) + "\\n")
if a[:2] == ["addon", "list"]:
    print(json.dumps([{{"name": "automation", "active": True}}])); sys.exit(0)
if a[:1] == ["automation"]:
    env = {{**os.environ, "ORCH_BIN": __file__}}
    sys.exit(subprocess.run(["uv", "run", "--project", {proj!r}, "python", "-m", "orch_automation.cli", "--dir", os.getcwd(), *a[1:]],
                            env=env).returncode)
if a[:2] == ["ticket", "new"]:
    print(json.dumps({{"id": "t_new0001", "title": a[-1]}})); sys.exit(0)
if a[:2] == ["ticket", "list"]:
    print(json.dumps([{{"id": "t_abcdef", "title": "Weekly", "status": "open", "revision": 1,
                        "ext": {{"automation": {{"recurring": True, "cron": "0 8 * * *"}}}}}}])); sys.exit(0)
print("{{}}")
"""


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")
def test_run_toggle_and_delete_are_accepted_by_the_real_automation_cli(ws, tmp_path):
    d = tmp_path / "realorch"
    d.mkdir()
    orch = d / "orch"
    orch.write_text(FAKE.format(py=sys.executable, proj=str(AUTOMATION)))
    orch.chmod(orch.stat().st_mode | stat.S_IXUSR)
    srv = make_server(ws, 0, orch_bin=str(orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    me = actions.actor()
    try:
        for verb in ("toggle", "run", "delete", "repeat", "copy"):
            code, text, _ = post(
                base,
                {
                    "op": "addon.act",
                    "args": {
                        "addon": "automation",
                        "verb": verb,
                        "target": "t_abcdef",
                        **({"value": "every day at 9"} if verb == "repeat" else {}),
                    },
                },
            )
            assert code == 200, (verb, text)
        calls = [json.loads(x) for x in (d / "calls.jsonl").read_text().splitlines()]
        inner = [c for c in calls if c[0] in ("ext", "run")]
        assert [c[:2] for c in inner] == [
            ["ext", "set"],
            ["run", "start"],
            ["ext", "set"],
            ["ext", "unset"],
            ["ext", "set"],
        ]  # Run now also records the last run
        assert all(c[c.index("--by") + 1] == me for c in inner), inner  # the person, not the scheduler
    finally:
        srv.shutdown()
        srv.server_close()

"""The Factory idea box through the dashboard against the REAL factory CLI: the argv `addon.act` builds must be accepted
by `orch factory act idea`, the new order is recorded as the person, and the page gets the order back. Only `orch`
itself is faked (addon list, ticket new, ext set, run start)."""

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

FACTORY = Path(__file__).resolve().parents[2] / "factory"

FAKE = """#!{py}
import json, os, subprocess, sys
from pathlib import Path
d = Path(__file__).parent
a = sys.argv[1:]
with open(d / "calls.jsonl", "a") as f:
    f.write(json.dumps(a) + "\\n")
if a[:2] == ["addon", "list"]:
    print(json.dumps([{{"name": "factory", "active": True}}])); sys.exit(0)
if a[:1] == ["factory"]:
    env = {{**os.environ, "ORCH_BIN": __file__}}
    sys.exit(subprocess.run(["uv", "run", "--project", {proj!r}, "python", "-m", "orch_factory", "--dir", os.getcwd(), *a[1:]],
                            env=env).returncode)
if a[:2] == ["ticket", "new"]:
    print(json.dumps({{"id": "t_new0001", "title": a[2], "revision": 1, "ext": {{}}}})); sys.exit(0)
print("{{}}")
"""


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")
def test_idea_box_files_the_order_as_the_person_through_the_real_factory_cli(ws, tmp_path):
    d = tmp_path / "realorch"
    d.mkdir()
    orch = d / "orch"
    orch.write_text(FAKE.format(py=sys.executable, proj=str(FACTORY)))
    orch.chmod(orch.stat().st_mode | stat.S_IXUSR)
    srv = make_server(ws, 0, orch_bin=str(orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    me = actions.actor()
    try:
        body = {
            "op": "addon.act",
            "args": {"addon": "factory", "verb": "idea", "target": "A page with our opening hours"},
        }
        code, text, _ = post(base, body)
        assert code == 200, text
        answer = json.loads(text)["act_answer"]
        assert answer["addon"] == "factory" and answer["answer"]["order"] == "t_new0001"
        calls = [json.loads(x) for x in (d / "calls.jsonl").read_text().splitlines()]
        assert [
            "factory",
            "act",
            "idea",
            "--by",
            me,
            "--json",
            "--",
            "A page with our opening hours",
        ] in calls
        inner = [c for c in calls if c[:2] in (["ticket", "new"], ["ext", "set"], ["run", "start"])]
        assert [c[:2] for c in inner] == [["ticket", "new"], ["ext", "set"], ["run", "start"]]
        assert all(c[c.index("--by") + 1] == me for c in inner), inner  # the person, not agent:factory
    finally:
        srv.shutdown()
        srv.server_close()


def test_idea_act_is_never_free():
    """Only a page with the person's session may run it (an agent's scripted request is watch-only)."""
    assert actions.needs_session("addon.act")

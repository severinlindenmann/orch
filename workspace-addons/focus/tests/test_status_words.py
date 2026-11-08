import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src/orch_focus/web/focus.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("status,word", [
    ("open", "Not started"), ("ready", "Not started"), ("active", "Working"),
    ("waiting", "Needs you"), ("review", "Ready for review"),
    ("done", "Done"), ("dropped", "Dropped"),
])
@pytest.mark.parametrize("started", [None, False, True, 1])
def test_status_words_started(status, word, started):
    source = WEB.read_text()
    declarations = "\n".join(re.findall(r"  const (?:STATUS_WORD|statusWord) = [^\n]+", source))
    script = declarations + "\nconsole.log(JSON.stringify(statusWord(...JSON.parse(process.argv[1]))));"
    result = subprocess.run(["node", "-e", script, json.dumps([status, started])],
                            capture_output=True, text=True, check=True)
    expected = "Paused" if status in ("open", "ready") and started is True else word
    assert json.loads(result.stdout) == expected


@pytest.mark.parametrize("started", [None, False, True])
def test_shape_carries_started(started):
    from orch_focus.server import Tracker

    ticket = {"status": "ready"}
    if started is not None:
        ticket["started"] = started
    view = Tracker._shape(ticket, {}, {}, {}, [], False)
    assert view["ticket"]["started"] is (started is True)

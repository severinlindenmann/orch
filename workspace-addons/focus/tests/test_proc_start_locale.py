import os

import pytest

from orch_focus import runfiles


@pytest.mark.skipif(os.name == "nt", reason="ps is POSIX")
def test_process_start_is_the_same_text_in_every_language(monkeypatch):
    """fb20 / fb31: a service started under one Mac language and checked or stopped under another got a
    different start text for the same process, so `orch stop` said "nothing was running", deleted the
    records and left the service running."""
    seen = set()
    for loc in ("de_CH.UTF-8", "en_US.UTF-8", "en_GB.UTF-8", "C"):
        monkeypatch.setenv("LC_ALL", loc)
        monkeypatch.setenv("LANG", loc)
        seen.add(runfiles.proc_start(os.getpid()))
    assert len(seen) == 1 and None not in seen


def test_the_three_copies_of_proc_start_are_the_same_code():
    """The Focus, dashboard and automation add-ons each carry their own runfiles.py (they install apart)."""
    import inspect
    import re
    from pathlib import Path

    here = Path(__file__).resolve().parents[2]

    def body(text):
        m = re.search(r"def proc_start\(.*?(?=\ndef |\Z)", text, re.DOTALL)
        return m.group(0)

    mine = inspect.getsource(runfiles.proc_start)
    for other in ("dashboard/src/orch_dashboard", "automation/src/orch_automation"):
        assert body((here / other / "runfiles.py").read_text()).strip() == mine.strip(), other

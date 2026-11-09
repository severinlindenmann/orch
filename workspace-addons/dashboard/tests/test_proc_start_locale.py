import os

import pytest

from orch_dashboard import runfiles


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

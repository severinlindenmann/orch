import sys

import pytest

from orch_dashboard import actions, reffiles


def test_ref_file_without_orch_answers_503(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "orch.safefile", None)  # import raises ImportError
    code, body, ctype = reffiles.read(tmp_path, "t_weekly01", "1")
    assert code == 503 and ctype == "text/plain"
    assert b"orch" in body and b"not available" in body


def test_human_env_without_orch_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "orch.adapters", None)
    with pytest.raises(actions.Unavailable):
        actions.human_env(tmp_path, "orch")


def test_human_env_with_a_broken_adapter_list_still_drops_the_agent(monkeypatch, tmp_path):
    import orch.adapters

    monkeypatch.setattr(orch.adapters, "human_environ", lambda environ: (_ for _ in ()).throw(RuntimeError("bad")))
    monkeypatch.setenv("CLAUDECODE", "1")
    env = actions.human_env(tmp_path, "orch")
    assert "CLAUDECODE" not in env and env["ORCH_VIA"] == "dashboard"

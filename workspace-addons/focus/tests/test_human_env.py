"""Review #287 (new F1): a click in Focus is the person's, even when an agent started the Focus server."""

from pathlib import Path

from orch_focus import actions


def test_orch_calls_leave_the_agent_variables_out(monkeypatch, tmp_path):
    for k, v in {"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli", "CODEX_HOME": "/x", "ORCH_AGENT": "claude",
                 "ORCH_RUN": "r_abcdefgh", "ORCH_TICKET": "t_abcdef", "KEEP_ME": "yes"}.items():
        monkeypatch.setenv(k, v)
    got = {}

    def fake_run(argv, **kw):
        got.update(kw["env"])

        class R:
            returncode, stdout, stderr = 0, "{}", ""

        return R()

    monkeypatch.setattr(actions.subprocess, "run", fake_run)
    actions.orch(Path(tmp_path), "/bin/orch", ["ticket", "list"])
    for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CODEX_HOME", "ORCH_AGENT", "ORCH_RUN", "ORCH_TICKET"):
        assert k not in got, k
    assert got["KEEP_ME"] == "yes" and got["ORCH_VIA"] == "focus" and got["ORCH_BIN"] == "/bin/orch"

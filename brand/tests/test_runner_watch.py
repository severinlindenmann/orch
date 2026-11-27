"""The runner watch (ORCH-1932 follow-up): jobs that wait for offline runners fall back to GitHub's machines."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import runner_watch as rw

EDGE = ["self-hosted", "Linux", "ARM64", "orch-edge"]
MAC = ["self-hosted", "macOS", "ARM64", "orch-mac"]


def runner(name, labels, status="online", busy=False):
    return {"name": name, "status": status, "busy": busy, "labels": [{"name": x} for x in labels]}


def job(name, labels, status="queued"):
    return {"name": name, "status": status, "labels": labels}


def test_only_queued_self_hosted_jobs_count():
    jobs = [job("a", EDGE), job("b", ["ubuntu-latest"]), job("c", EDGE, "in_progress"), job("runner-watch", EDGE)]
    assert [j["name"] for j in rw.waiting_self_hosted(jobs, "runner-watch")] == ["a"]


def test_a_busy_runner_still_counts_as_there():
    assert rw.stuck([job("a", EDGE)], [runner("e1", EDGE, busy=True)]) == []


def test_an_offline_runner_or_another_label_does_not():
    runners = [runner("e1", EDGE, "offline"), runner("m", MAC)]
    assert [j["name"] for j in rw.stuck([job("a", EDGE), job("b", MAC)], runners)] == ["a"]


def test_falls_back_only_after_ten_minutes_in_a_row():
    w = rw.Watch(grace=600)
    off = [runner("e1", EDGE, "offline")]
    jobs = [job("contracts / validate", EDGE)]
    assert w.step(0, jobs, off) == []
    assert w.step(599, jobs, off) == []
    assert [j["name"] for j in w.step(600, jobs, off)] == ["contracts / validate"]


def test_one_online_answer_starts_the_count_again():
    w = rw.Watch(grace=600)
    jobs = [job("a", EDGE)]
    w.step(0, jobs, [runner("e1", EDGE, "offline")])
    w.step(300, jobs, [runner("e1", EDGE)])  # the API flips back to online for one read
    assert w.step(700, jobs, [runner("e1", EDGE, "offline")]) == []
    assert w.step(1300, jobs, [runner("e1", EDGE, "offline")]) != []


def test_no_waiting_job_never_falls_back():
    w = rw.Watch(grace=0)
    assert w.step(10_000, [job("a", EDGE, "completed")], []) == []


def test_done_when_every_other_job_finished():
    jobs = [job("a", EDGE, "completed"), job("runner-watch", ["ubuntu-latest"], "in_progress")]
    assert rw.others_done(jobs, "runner-watch")
    assert not rw.others_done([*jobs, job("b", EDGE)], "runner-watch")


def _wf(name):
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def _job(text, name):
    """The text of one top-level job in a workflow (plain text: brand's CI job has no YAML library)."""
    start = text.index(f"\n  {name}:\n")
    rest = text[start + 1 :]
    nxt = re.search(r"\n  [a-z][\w-]*:\n", rest[1:])
    return rest if nxt is None else rest[: nxt.start() + 1]


def test_ci_wires_the_watch_outside_the_gate():
    ci = _wf("ci.yml")
    watch = _job(ci, "runner-watch")
    assert "runs-on: ubuntu-latest" in watch  # never on the runners it watches
    assert "runner-watch" not in _job(ci, "gate")  # never turns a run red
    # the script comes from the base branch, never from the pull request, next to the runner-list secret
    assert "ref: ${{ github.event_name == 'pull_request' && github.base_ref || github.sha }}" in watch
    assert "name: runner-fallback" in watch and "gh run cancel" in watch


def test_fallback_reruns_only_runs_the_watch_cancelled():
    wf = _wf("runner-fallback.yml")
    assert "workflows: [ci]" in wf and "types: [completed]" in wf
    assert "conclusion == 'cancelled'" in wf and "run_attempt < 3" in wf
    assert "name=runner-fallback" in wf and "gh run rerun" in wf and "--failed" not in wf
    assert "checkout" not in wf.split("jobs:", 1)[1]

"""perf / limits compares like with like (ORCH-2399, ORCH-2388 c2).

GitHub's machines differ up to 2x in speed: on a slow one every page was 30 to 100% "slower than develop" with no
change in orch. scripts/perf_calibrate.py measures a fixed piece of work on every perf run and rewrites develop's
times for the runner at hand before e2e/perf/check_limits.py compares (only for a slower runner, at most 3x).
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cal = load("perf_calibrate", ROOT / "scripts" / "perf_calibrate.py")
sys.path.insert(0, str(ROOT / "e2e" / "perf"))
import check_limits  # noqa: E402  (the comparison itself, unchanged)

DEVELOP = {
    "commands": {"ticket list": 0.5, "needs": 0.6},
    "dash": {"rows": [
        {"page": "Home", "ms": 900, "reads": [["/api/x", 10, 800]]},
        {"page": "Tickets", "ms": 1200},
        {"page": "Review", "ms": None, "err": "did not load"},
        {"page": "Idle Home 60 s", "enc": 100_000, "ms": 5},
    ]},
    "too_slow": [],
}  # fmt: skip


def slower(numbers: dict, f: float) -> tuple[dict, dict]:
    """(commands, dash) of a run on a runner f times slower, with no change in orch."""
    got = cal.scaled(numbers, f)
    return got["commands"], got["dash"]


def test_the_fixed_work_gives_a_time_and_the_file_says_which_work(tmp_path):
    out = tmp_path / "out" / "calibration.json"
    assert cal.main(["measure", str(out)]) == 0
    got = json.loads(out.read_text())
    assert got["work"] == cal.WORK and got["rounds"] == cal.ROUNDS and 0 < got["seconds"] < 120


def test_a_runner_twice_as_slow_no_longer_fails_every_row(tmp_path):
    cmds, dash = slower(DEVELOP, 2.0)
    assert len(check_limits.regressions(cmds, dash, DEVELOP)[1]) == 4  # today: every command and page "regressed"
    dev = tmp_path / "perf-develop"
    dev.mkdir()
    (dev / "limits.json").write_text(json.dumps(DEVELOP))
    (dev / "calibration.json").write_text(json.dumps({"work": cal.WORK, "seconds": 1.0}))
    here = tmp_path / "calibration.json"
    here.write_text(json.dumps({"work": cal.WORK, "seconds": 2.0}))
    assert cal.main(["scale", str(dev / "limits.json"), str(here)]) == 0
    rewritten = json.loads((dev / "limits.json").read_text())
    assert rewritten["runner_factor"] == 2.0
    assert check_limits.regressions(cmds, dash, rewritten)[1] == []
    # a real slowdown on top of the slow runner still fails: Tickets 60% slower than the runner explains
    dash["rows"][1]["ms"] = 1200 * 2.0 * 1.6
    bad = check_limits.regressions(cmds, dash, rewritten)[1]
    assert len(bad) == 1 and bad[0].startswith("Tickets:")


def test_only_times_are_rewritten_never_the_idle_bytes_or_a_failed_page():
    got = cal.scaled(DEVELOP, 2.0)
    assert got["commands"] == {"ticket list": 1.0, "needs": 1.2}
    rows = {r["page"]: r for r in got["dash"]["rows"]}
    assert rows["Home"]["ms"] == 1800 and rows["Home"]["reads"] == [["/api/x", 10, 800]]
    assert rows["Review"] == DEVELOP["dash"]["rows"][2]
    assert rows["Idle Home 60 s"] == DEVELOP["dash"]["rows"][3]  # bytes, not time
    assert DEVELOP["commands"]["needs"] == 0.6  # the input is not changed
    assert cal.scaled({"commands": None, "dash": None}, 2.0) == {"commands": None, "dash": None}


def test_the_factor_only_helps_a_slower_runner_and_has_a_ceiling():
    def f(here, develop):
        return cal.factor(
            None if here is None else {"work": cal.WORK, "seconds": here},
            None if develop is None else {"work": cal.WORK, "seconds": develop},
        )

    assert f(2.0, 1.0)[0] == 2.0 and "count 2.00x" in f(2.0, 1.0)[1]
    assert f(1.0, 2.0)[0] == 1.0 and "not slower" in f(1.0, 2.0)[1]  # a faster runner: never stricter than before
    assert f(1.0, 1.0)[0] == 1.0
    assert f(9.0, 1.0)[0] == cal.MAX_FACTOR
    assert f(None, 1.0) == (1.0, "No runner speed for this run: develop's times are compared as they are.")
    assert f(2.0, None)[0] == 1.0 and "develop's run" in f(2.0, None)[1]  # an older develop run without it
    assert cal.factor({"work": cal.WORK, "seconds": 2.0}, {"work": cal.WORK + 1, "seconds": 1.0})[0] == 1.0
    assert cal.factor({"work": cal.WORK, "seconds": 2.0}, {"work": cal.WORK, "seconds": 0})[0] == 1.0
    assert cal.factor({"work": cal.WORK, "seconds": 2.0}, {"work": cal.WORK, "seconds": "1"})[0] == 1.0


def test_without_develop_numbers_or_its_runner_speed_nothing_is_rewritten(tmp_path, capsys):
    here = tmp_path / "calibration.json"
    here.write_text(json.dumps({"work": cal.WORK, "seconds": 2.0}))
    assert cal.main(["scale", str(tmp_path / "none" / "limits.json"), str(here)]) == 0
    assert "No develop numbers" in capsys.readouterr().out
    dev = tmp_path / "perf-develop" / "limits.json"
    dev.parent.mkdir()
    dev.write_text(json.dumps(DEVELOP))
    assert cal.main(["scale", str(dev), str(here)]) == 0  # develop's run has no calibration.json yet
    assert json.loads(dev.read_text()) == DEVELOP
    assert "No runner speed for develop's run" in capsys.readouterr().out
    assert cal.main([]) == 2 and cal.main(["scale", str(dev)]) == 2


def test_perf_yml_measures_every_run_and_rewrites_develops_times_before_the_comparison():
    wf = (ROOT / ".github" / "workflows" / "perf.yml").read_text()
    step = 'python3 scripts/perf_calibrate.py measure "$PERF_BASE/out/calibration.json"'
    scale = 'python3 scripts/perf_calibrate.py scale "$AGAINST" "$PERF_BASE/out/calibration.json"'
    assert step in wf and scale in wf
    # after develop's numbers are fetched, before the measuring; and the file is part of the kept numbers
    assert wf.index("gh run download") < wf.index(step) < wf.index(scale) < wf.index("e2e/perf/check_limits.py \"$PERF_BASE\"")
    assert "path: ${{ env.PERF_BASE }}/out" in wf
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "'scripts/perf_calibrate.py'" in next(x for x in ci.splitlines() if x.strip().startswith("perf: ["))

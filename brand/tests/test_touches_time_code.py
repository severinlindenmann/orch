"""A pull request that changes time code also runs the whole suites at a fake hour (scripts/touches_time_code.py,
ORCH-451); every other pull request leaves them to the merge queue group and the nightly run."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import touches_time_code as t  # noqa: E402


def diff(path: str, *lines: str) -> str:
    body = "\n".join(lines)
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n{body}\n"


def hits(text: str) -> list[str]:
    return t.reasons(t.parse(text))


def test_the_lines_behind_the_night_reds_run_the_clock_job():
    # 17/18 Nov: a run id took the UTC day twice; a page test expected "today" for a stamp made "now"
    assert hits(
        diff("workspace/tests/test_cli_secret.py", '+    day = time.strftime("%Y%m%d", time.gmtime())')
    )
    assert hits(
        diff(
            "workspace-addons/services/tests/test_view.py",
            '+    assert f["State"] == "Running since today 10:00"',
        )
    )
    assert hits(
        diff(
            "workspace-addons/dashboard/src/orch_dashboard/web/helpers.js",
            "+    if (diff === 1) return 'yesterday ' + time;",
        )
    )


def test_local_days_formats_and_zones_run_the_clock_job():
    for path, line in (
        ("workspace/src/orch/triage.py", '+    day = at.astimezone().strftime("%-d %b")'),
        ("workspace/src/orch/phone_alerts.py", "+def text(a: dict, tz: tzinfo | None = None) -> str:"),
        ("workspace/src/orch/x.py", "+    start = date.today() - timedelta(days=7)"),
        ("workspace-addons/dashboard/src/orch_dashboard/web/app.js", "+  const h = new Date(v).getHours();"),
        ("workspace-addons/dashboard/tests/x.test.js", "+  d.setHours(23, 59, 0, 0);"),
        ("workspace/src/orch_ui/static/review.js", "+  return d.toLocaleDateString('en-GB');"),
        (
            "workspace-addons/sync/tests/test_act.py",
            "+    # after midnight\n+    assert label(at) == 'tomorrow 09:00'",
        ),
    ):
        assert hits(diff(path, line)), line


def test_the_clock_files_themselves_run_it():
    for path in (
        "scripts/at-clock.sh",
        ".github/workflows/clock.yml",
        "workspace/tests/testclock.py",
        "workspace/tests/testclock.cjs",
        "workspace/src/orch_ui/static/date.js",
    ):
        assert hits(f"diff --git a/{path} b/{path}\n"), path


def test_plain_now_durations_and_prose_do_not():
    # the false alarms of the night's replay: durations, stamps and words in a sentence
    for path, line in (
        (
            "workspace-addons/dashboard/src/orch_dashboard/web/app.js",
            "+  const justStarted = id => Date.now() - (startedAt.get(id) || 0) < 60000;",
        ),
        ("workspace/tests/test_sessions.py", '+    rec["live"] = {"since": runs._iso(time.time() - 3600)}'),
        (
            "workspace/src/orch/ghlimit.py",
            "+def take(kind, wait=WAIT_SECS, sleep=time.sleep, clock=time.time):",
        ),
        ("workspace/src/orch/x.py", "+    started = datetime.now(UTC)"),
        (
            "workspace-addons/dashboard/src/orch_dashboard/web/pages/live.js",
            "+  h('a', {}, 'Back to today’s ' + label)",
        ),
        (
            "workspace-addons/dashboard/src/orch_dashboard/web/pages/live.js",
            "+  'Today orch picks a model per ticket'",
        ),
    ):
        assert not hits(diff(path, line)), line


def test_mockups_click_throughs_comments_and_imports_do_not():
    assert not hits(diff("workspace-addons/dashboard/mockup/factory/factory.js", "+  d.setHours(9);"))
    assert not hits(diff("workspace-addons/dashboard/clickthrough/features/l-phone.cjs", "+  d.setHours(9);"))
    assert not hits(
        diff(
            "workspace/src/orch/x.py",
            "+    # strftime would be wrong here",
            "+from datetime import timezone, tzinfo",
        )
    )
    assert not hits(diff("docs/time.md", "+today 10:00"))

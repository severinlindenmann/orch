"""e2e/fixtures/pull-requests-page.json (the dashboard screenshots of the Pull requests page) is what the add-on's
code makes now. After a change to the page: uv run python tests/dash_fixture.py"""

import dash_fixture


def test_dashboard_fixture_is_current():
    assert dash_fixture.OUT.read_text(encoding="utf-8") == dash_fixture.render(), (
        "e2e/fixtures/pull-requests-page.json is out of date: run uv run python tests/dash_fixture.py"
    )

"""Owner feedback 14 Nov (W12): no publish server means an empty Shared links page, not an error."""

import json

from orch import publish


def test_view_without_a_publish_server_is_the_plain_empty_page(proj, run):
    assert run("init")[0] == 0
    v = publish.view(proj)
    assert v["schema"] == "orch.addon-view/1"
    assert "header" not in v  # "Share a file" would only fail without a server
    first = v["blocks"][0]
    assert first["type"] == "list" and first["items"] == []
    assert first["empty"]["title"] == "No shared links yet"
    assert "publish server" in first["empty"]["text"]
    json.dumps(v)


def test_the_cli_view_answers_instead_of_refusing(proj, run):
    assert run("init")[0] == 0
    assert run("addon", "add", "publish", "--yes")[0] == 0
    code, out, err = run("publish", "view", "--json")
    assert code == 0, (out, err)
    assert json.loads(out)["blocks"][0]["empty"]["title"] == "No shared links yet"

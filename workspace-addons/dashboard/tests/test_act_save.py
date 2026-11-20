"""Save of an add-on page's editor (Skills, ORCH-840): `addon.act` verb `save` carries the text, which reaches the
add-on only on stdin (never in the argv, the act log or an answer); size, shape and character refusals."""

import json
import threading

import pytest

from orch_dashboard import actions

from .test_act import acts, post

REV = "a" * 64
TARGET = "e_" + "0123456789abcdef01234567"


@pytest.fixture
def base(act_orch, ws):
    from orch_dashboard.server import make_server

    src = act_orch.read_text().replace(
        'if a[:2] in (["addon", "list"]',
        'if a[:2] == ["addon", "list"]:\n    print(json.dumps([{"name": "skills", "active": True}]))\n    sys.exit(0)\n'
        'if a[1:3] == ["act", "save"]:\n    (d / "stdin.txt").write_bytes(sys.stdin.buffer.read())\n'
        '    print(json.dumps({"saved": True, "revision": "b" * 64, "changed": True}))\n    sys.exit(0)\n'
        'if a[:2] in (["addon", "list"]',
    )
    act_orch.write_text(src)
    srv = make_server(ws, 0, orch_bin=str(act_orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _save(base, text, **over):
    args = {"addon": "skills", "verb": "save", "target": TARGET, "value": REV, "text": text}
    args.update(over)
    return post(base, {"op": "addon.act", "args": args}, headers={"X-Orch-Op": "addon.act"})


def test_the_text_goes_on_stdin_and_never_in_the_argv(base, act_orch):
    text = json.dumps({"text": "# Rules\n<script>alert(1)</script>\nÜnïcode ✓\n" + "x" * 30_000})
    code, body, _ = _save(base, text)
    assert code == 200, body
    argv = acts(act_orch)[-1]
    assert argv == [
        "skills",
        "act",
        "save",
        f"--value={REV}",
        "--by",
        actions.actor(),
        "--json",
        "--",
        TARGET,
    ]
    assert (act_orch.parent / "stdin.txt").read_bytes() == text.encode("utf-8")
    assert "<script>" not in json.dumps(argv)
    state = json.loads(body)
    assert state["act_answer"]["answer"]["revision"] == "b" * 64


def test_a_long_text_fits_in_a_bigger_body_only_for_addon_clicks(base, act_orch):
    text = json.dumps({"text": "\n".join(['a line with "quotes" and \\ slashes'] * 2500)})
    assert len(text) > 64 * 1024
    code, body, _ = _save(base, text)
    assert code == 200, body
    # other ops keep the small limit
    big = {"op": "log", "args": {"ticket": "t_abcdef", "text": "x" * 20_000}}
    assert post(base, big, headers={"X-Orch-Op": "log"})[0] == 400


@pytest.mark.parametrize(
    "over",
    [
        {"text": ""},
        {"text": 5},
        {"text": None},
        {"text": "a\x00b"},
        {"text": "x" * (160 * 1024 + 1)},
        {"value": "nothex"},
        {"value": "A" * 64},
        {"verb": "on"},  # only Save sends a text
        {"review": True},
        {"target": "--evil"},
        {"target": "e_1\n"},
    ],
)
def test_refusals_run_nothing(base, act_orch, over):
    n = len(acts(act_orch))
    code, text, _ = _save(base, **{"text": '{"text": "x"}', **over})
    assert code == 400, (over, text)
    assert len(acts(act_orch)) == n


def test_save_without_a_text_is_refused(base, act_orch):
    args = {"addon": "skills", "verb": "save", "target": TARGET, "value": REV}
    assert post(base, {"op": "addon.act", "args": args})[0] == 400
    assert acts(act_orch) == []


def test_a_lone_surrogate_is_refused():
    with pytest.raises(actions.BadRequest):
        actions.save_input({"verb": "save", "text": "a\ud800b"})


def test_a_stale_save_answers_409(base, act_orch):
    (act_orch.parent / "mode.txt").write_text("conflict")
    src = act_orch.read_text().replace('if a[1:3] == ["act", "save"]:', "if False:")
    act_orch.write_text(src)
    code, text, _hdr = _save(base, '{"text": "x"}')
    assert code == 409, text

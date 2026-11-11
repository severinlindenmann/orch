import pytest

from orch import phone_view


@pytest.mark.parametrize(
    "by",
    [
        "agent:relay from ph_abc",
        " Agent:Relay from ph_abc ",
        "agent:phone",
        "agent:ph_abc",
        "agent: relay from ph_abc",
        "agent:\u200brelay from ph_abc",
        "agent:Severin Lindenmann",
    ],
)
def test_raw_phone_labels_never_render_as_people(proj, by, monkeypatch):
    def no_phone_lookup(*args):
        pytest.fail("Raw history labels must not resolve phone names")

    monkeypatch.setattr("orch.relay.name_of", no_phone_lookup)
    assert not phone_view.is_agent_history_author(by)
    assert phone_view._who(by)[1] == "agent"
    ticket = {
        "id": "t_abc123",
        "history": [{"at": "2026-11-09T09:00:00Z", "by": by, "text": "Approved", "via": "phone"}],
    }
    history = phone_view.build(proj, ticket, [])["history_tail"]
    assert len(history) == 1
    assert history[0]["role"] == "agent"
    assert history[0]["text"] == "Approved"


def test_plain_local_relay_history_renders_as_agent(proj):
    ticket = {
        "id": "t_abc123",
        "history": [{"at": "2026-11-09T09:00:00Z", "by": "agent:relay", "text": "Workspace update"}],
    }
    assert phone_view.build(proj, ticket, [])["history_tail"] == [
        {"at": "2026-11-09T09:00:00Z", "who": "Relay", "role": "agent", "text": "Workspace update"}
    ]


@pytest.mark.parametrize(
    "by",
    [
        "agent:claude",
        "agent:sync",
        "agent:codex",
        "agent:automation",
        "agent:focus",
        "agent:my-agent_1.2",
        "ａｇｅｎｔ:ＣＯＤＥＸ",
    ],
)
def test_local_agent_ids_remain_agent_authors(by):
    assert phone_view.is_agent_history_author(by)
    assert phone_view._who(by)[1] == "agent"

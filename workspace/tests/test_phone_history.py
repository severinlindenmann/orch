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
        "AGENT:CODEX",
    ],
)
def test_local_agent_ids_remain_agent_authors(by):
    assert phone_view.is_agent_history_author(by)
    assert phone_view._who(by)[1] == "agent"


@pytest.mark.parametrize("by", ["agent：severin", "agent﹕x", "ａｇｅｎｔ:ＣＯＤＥＸ"])
def test_non_ascii_agent_labels_are_not_trusted(by):
    assert not phone_view.is_agent_history_author(by)


def test_chat_lines_carry_chat_id_and_typed_name(proj):
    """A chat line reaches the phone's ticket chat as a message: flagged, with its stable id and typed name."""
    ticket = {
        "id": "t_abc123",
        "history": [
            {"at": "2026-11-21T09:00:00Z", "by": "agent:claude", "text": "Finished a task: Draft", "via": "cli"},
            {
                "at": "2026-11-21T09:01:00Z",
                "by": "you",
                "via": "dashboard",
                "text": "Keep the old colours",
                "chat_message": True,
                "id": "m_a1b2c3d4e5f6g7h8",
                "by_name": "  Nina   Weber ",
            },
            {
                "at": "2026-11-21T09:02:00Z",
                "by": "agent:claude",
                "text": "Will do",
                "chat_message": True,
                "id": "not-an-id",
            },
            {
                "at": "2026-11-21T09:03:00Z",
                "by": "you",
                "text": "Too long a name",
                "chat_message": True,
                "by_name": "x" * 200,
            },
        ],
    }
    tail = phone_view.build(proj, ticket, [])["history_tail"]
    assert "chat" not in tail[0] and "name" not in tail[0] and "id" not in tail[0]
    assert tail[1]["chat"] is True
    assert tail[1]["id"] == "m_a1b2c3d4e5f6g7h8"
    assert tail[1]["name"] == "Nina Weber"
    assert tail[2]["chat"] is True and "id" not in tail[2] and "name" not in tail[2]
    assert tail[3]["chat"] is True and "name" not in tail[3]


def test_chat_lines_stay_in_the_window_after_many_plain_lines(proj):
    """A helper writing many plain lines does not push the ticket's chat messages out of the phone's window."""
    chat = [
        {"at": f"2026-11-21T08:0{i}:00Z", "by": "you", "text": f"chat {i}", "chat_message": True, "id": f"m_{i:016d}"}
        for i in range(3)
    ]
    plain = [
        {"at": f"2026-11-21T09:{i:02d}:00Z", "by": "agent:claude", "text": f"Step {i}", "via": "cli"} for i in range(40)
    ]
    tail = phone_view.build(proj, {"id": "t_abc123", "history": chat + plain}, [])["history_tail"]
    assert len(tail) == phone_view.HISTORY
    assert [t["text"] for t in tail[:3]] == ["chat 0", "chat 1", "chat 2"]
    assert tail[-1]["text"] == "Step 39"
    assert [t["at"] for t in tail] == sorted(t["at"] for t in tail)

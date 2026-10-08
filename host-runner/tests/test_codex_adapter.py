import pytest
from ai_station_runner.codex_adapter import proposal_result
from ai_station_runner.coding import CodingUnavailable


def test_codex_completed_proposal_keeps_thread_and_usage():
    text, metadata = proposal_result(
        [
            {"type": "thread.started", "thread_id": "thread"},
            {"type": "item.completed", "item": {"type": "error", "message": "Nonfatal CLI warning"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": '{"files":[]}'}},
            {"type": "turn.completed", "usage": {"output_tokens": 10}},
        ]
    )
    assert text == '{"files":[]}'
    assert metadata["thread_id"] == "thread" and metadata["usage"]["output_tokens"] == 10


@pytest.mark.parametrize(
    "action", ["command_execution", "file_change", "mcp_tool_call", "web_search", "future_tool"]
)
def test_codex_rejects_any_tool_action_even_after_success(action):
    with pytest.raises(CodingUnavailable):
        proposal_result(
            [
                {"type": "item.started", "item": {"type": action}},
                {"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}},
                {"type": "turn.completed"},
            ]
        )


@pytest.mark.parametrize(
    "events", [[], [{"type": "turn.failed"}], [{"type": "turn.completed"}], [{"type": "error"}]]
)
def test_codex_requires_confirmed_success_and_text(events):
    with pytest.raises(CodingUnavailable):
        proposal_result(events)

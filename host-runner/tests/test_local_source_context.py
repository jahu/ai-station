import json

import pytest
from ai_station_runner.coding_files import apply_proposal, parse_proposal, proposal_prompt, read_selected
from ai_station_runner.coding_source_window import source_window
from ai_station_runner.local_model import CodingCompletion, Completion
from pydantic import ValidationError


def fixture_source(tmp_path):
    text = "".join(f"# retained line {i}\n" for i in range(7500)) + "original_target = 1\n"
    (tmp_path / "large.py").write_text(text)
    return text, read_selected(tmp_path, ["large.py"], local_context=True)


def test_full_local_source_and_snippet_edit_keep_external_context_unchanged(tmp_path):
    before, selected = fixture_source(tmp_path)
    assert 100000 < len(before.encode()) < 256000
    with pytest.raises(ValueError):
        read_selected(tmp_path, ["large.py"])
    with pytest.raises(ValueError):
        proposal_prompt(prompt="Edit", selected=selected, guidance="")
    prompt = proposal_prompt(prompt="Edit", selected=selected, guidance="", local_context=True)
    assert "original_target = 1" in prompt and len(prompt.encode()) > 100000
    proposal = parse_proposal(
        json.dumps(
            {
                "summary": "Target only",
                "files": [
                    {
                        "path": "large.py",
                        "replacements": [{"old": "original_target = 1", "new": "original_target = 2"}],
                    }
                ],
            }
        ),
        selected,
        local_context=True,
    )
    report = apply_proposal(tmp_path, selected, proposal, local_context=True)
    assert (tmp_path / "large.py").read_text() == before.replace("original_target = 1", "original_target = 2")
    assert report["files"][0]["insertions"] == 1 and report["files"][0]["deletions"] == 1


def test_local_large_edits_reject_full_rewrite_and_stale_snapshot(tmp_path):
    before, selected = fixture_source(tmp_path)
    with pytest.raises(ValueError, match="unique snippet"):
        parse_proposal(
            json.dumps({"summary": "Rewrite", "files": [{"path": "large.py", "content": "small"}]}),
            selected,
            local_context=True,
        )
    proposal = parse_proposal(
        json.dumps(
            {
                "summary": "Edit",
                "files": [
                    {
                        "path": "large.py",
                        "replacements": [{"old": "original_target = 1", "new": "original_target = 2"}],
                    }
                ],
            }
        ),
        selected,
        local_context=True,
    )
    (tmp_path / "large.py").write_text(before + "# concurrent edit\n")
    with pytest.raises(ValueError, match="changed"):
        apply_proposal(tmp_path, selected, proposal, local_context=True)
    assert (tmp_path / "large.py").read_text() == before + "# concurrent edit\n"


def test_local_source_and_projected_aggregate_stay_bounded(tmp_path):
    (tmp_path / "first.py").write_text("a" * 150000)
    (tmp_path / "second.py").write_text("b" * 150000)
    with pytest.raises(ValueError, match="256,000"):
        read_selected(tmp_path, ["first.py", "second.py"], local_context=True)
    (tmp_path / "first.py").write_text("a" * 250000)
    selected = read_selected(tmp_path, ["first.py", "new.py"], local_context=True)
    with pytest.raises(ValueError, match="Projected selected"):
        parse_proposal(
            json.dumps({"summary": "No", "files": [{"path": "new.py", "content": "b" * 7000}]}),
            selected,
            local_context=True,
        )
    (tmp_path / "first.py").write_text("a" * 256001)
    with pytest.raises(ValueError):
        read_selected(tmp_path, ["first.py"], local_context=True)


@pytest.mark.parametrize("start,count", [(0, 10), (True, 10), (1, 0), (1, 201), (1, False)])
def test_line_windows_reject_invalid_arguments(start, count):
    with pytest.raises(ValueError):
        source_window({"path": "file.py", "content": "text"}, start_line=start, max_lines=count)


def test_line_windows_limit_unicode_bytes_and_reach_later_lines():
    text = "".join(f"line {i}\n" for i in range(1000))
    result = source_window({"path": "file.py", "content": text}, start_line=900, max_lines=3)
    assert result["content"] == "line 899\nline 900\nline 901\n" and result["next_line"] == 903
    assert result["truncated"] and not result["last_line_truncated"]
    result = source_window({"path": "file.py", "content": "ą" * 20000})
    assert len(result["content"].encode()) <= 16000 and result["last_line_truncated"]


def test_typed_coding_bridge_keeps_chat_limits_and_excludes_images_history_reasoning():
    body = {
        "model": "fixture",
        "messages": [{"role": "user", "content": "x" * 150000}],
        "temperature": 0.1,
        "max_tokens": 8192,
        "stream": True,
        "json_output": True,
    }
    assert len(CodingCompletion.model_validate(body).messages[0].content) == 150000
    with pytest.raises(ValidationError):
        Completion.model_validate(body)
    for invalid in (
        {**body, "messages": body["messages"] * 2},
        {**body, "messages": [{"role": "system", "content": "text"}]},
        {**body, "messages": [{"role": "user", "content": "ą" * 200000}]},
        {
            **body,
            "messages": [{"role": "user", "content": [{"type": "text", "text": "image parts prohibited"}]}],
        },
        {**body, "reasoning": {"enabled": False}},
    ):
        with pytest.raises(ValidationError):
            CodingCompletion.model_validate(invalid)


def test_owned_coding_route_retains_identity_and_private_transport(monkeypatch, tmp_path):
    from uuid import uuid4

    from ai_station_runner import llama_runtime
    from ai_station_runner.app import app
    from fastapi.testclient import TestClient
    from starlette.responses import JSONResponse

    identity = str(uuid4())
    body = {
        "model": identity,
        "messages": [{"role": "user", "content": "x" * 150000}],
        "temperature": 0.1,
        "max_tokens": 8192,
        "stream": True,
        "json_output": True,
    }
    monkeypatch.setattr(llama_runtime, "manifest", lambda _: {"desired": "running", "projector": None})
    monkeypatch.setattr(llama_runtime, "socket_path", lambda _: tmp_path / "private.sock")
    calls = []

    async def forward(body, incoming, url, client, headers):
        calls.append((body.model, url, headers, len(body.messages[0].content)))
        await client.aclose()
        return JSONResponse({"accepted": True})

    monkeypatch.setattr(llama_runtime, "forward_completion", forward)
    with TestClient(app) as client:
        route = "/v1/llama/" + identity
        assert client.post(route + "/chat/completions", json=body).status_code == 422
        assert (
            client.post(route + "/coding/completions", json={**body, "model": str(uuid4())}).status_code
            == 409
        )
        assert client.post(route + "/coding/completions", json=body).json() == {"accepted": True}
        monkeypatch.setattr(llama_runtime, "manifest", lambda _: {"desired": "stopped"})
        assert client.post(route + "/coding/completions", json=body).status_code == 409
    assert calls == [(identity, "http://llama/v1", {}, 150000)]


def test_external_exploration_adapter_may_prepare_an_empty_context_placeholder():
    # Cursor/Codex prepare their isolated provider workspace before replacing the
    # placeholder prompt with a typed discovery operation. Actual selection still
    # requires one to ten paths in read_selected; there is no source to disclose.
    message = proposal_prompt(prompt="Task", selected=[], guidance="")
    assert '"selected_files": []' in message

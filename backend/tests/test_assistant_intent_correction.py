"""Rejected semantic candidates remain inspectable and correction sees its actual input."""

import json

import pytest
from app.local_provider import LocalChatProvider
from app.models import Run, StudioMaterial
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_assistant_controller import submit
from test_studio_assistant import advance, owned
from test_studio_assistant import director as director
from test_studio_assistant import generators as generators
from test_studio_assistant import movie as movie
from test_studio_assistant import ready as ready


@pytest.mark.parametrize("repaired", [True, False])
def test_bounded_intent_correction_retains_candidate_and_precise_schema_diagnostics(
    accounts,
    director,
    movie,
    monkeypatch,
    repaired,
):
    _, alice, bob = accounts
    original = LocalChatProvider.stream
    calls = []
    bad = {
        "reason": "Interpret current request",
        "immediate": [
            {
                "kind": "studio_material",
                "description": "private-candidate-sentinel",
                "studio": {"audio": "voice", "narration_words": {"minimum": True}},
            }
        ],
        "automations": [],
    }
    good = {
        "reason": "Produce the requested film",
        "immediate": [{"kind": "studio_material", "description": "Film", "studio": {"audio": "voice"}}],
        "automations": [],
    }

    async def stream(self, **params):
        messages = params["messages"]
        if messages[0]["content"].startswith("Infer the user's requested outcomes"):
            calls.append(messages)
            if len(calls) == 2:
                assert messages[-3] == {"role": "assistant", "content": json.dumps(bad)}
                assert "immediate.0.studio.narration_words.minimum" in messages[-2]["content"]
                assert json.loads(messages[-1]["content"])["instruction"] == "Make a complete voiced film"
            yield json.dumps(good if repaired and len(calls) == 2 else bad)
        else:
            async for token in original(self, **params):
                yield token

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    result = submit(alice, "Make a complete voiced film")
    advance(movie)
    assert len(calls) == 2
    with owned(alice) as db:
        root = db.get(Run, result["run"]["id"])
        decision = db.scalar(
            select(Run)
            .where(Run.executor_type == "assistant_decision", Run.parent_run_id == root.id)
            .order_by(Run.created_at)
        )
        assert decision.parameters["intent_attempts"][0]["response"] == json.dumps(bad)
        assert len(decision.parameters["intent_attempts"]) == 2
        assert decision.status == ("succeeded" if repaired else "failed")
        if repaired:
            assert len(list(db.scalars(select(StudioMaterial)))) == 1
        else:
            assert "immediate.0.studio.narration_words.minimum" in decision.error_message
            assert "private-candidate-sentinel" not in decision.error_message
            assert not list(db.scalars(select(StudioMaterial)))
        identity = decision.id
    assert bob.get("/api/runs/" + identity).status_code == 404
    events = alice.get("/api/runs/" + identity + "/events").json()
    rejected = [e for e in events if e["event_type"] == "assistant.intent.rejected"]
    assert len(rejected) == (1 if repaired else 2)
    assert "private-candidate-sentinel" not in json.dumps(rejected)

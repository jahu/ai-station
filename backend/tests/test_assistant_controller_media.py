"""Generated video becomes an owned input to the next sound/mix tool."""

import pytest
from app.api import app
from app.db import session_factory
from app.models import Artifact, Run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_assistant_controller import drain, finish, root_state, submit, tool
from test_assistant_controller import model as model
from test_conversation_effects import film_bridge as film_bridge
from test_conversation_effects import mix_bridge as mix_bridge
from test_conversation_effects import sound_bridge as sound_bridge


@pytest.mark.parametrize("duration", [5, 20])
def test_generated_video_sound_mix_chain_binds_the_actual_video_result(model, film_bridge, duration):
    model["outcomes"] = [
        {"kind": "video", "count": 1, "description": "A generated forest film"},
        {"kind": "audio", "count": 1, "description": "Rain sounds mixed into that film"},
    ]
    model["decisions"] = [
        tool("video.generate", instruction="A calm forest in the rain", images=[], duration_seconds=duration),
        tool("audio.effects", instruction="Rain falling on leaves", video="step:1:video:1"),
        finish(1, 2),
    ]
    with TestClient(app) as api:
        result = submit(api, f"Create a {duration}-second forest film and add rain sounds")
        drain()
        state = root_state(result)
        assert [step["tool"] for step in state["controller_steps"]] == ["video.generate", "audio.effects"]
        assert all(step["observation"]["status"] == "succeeded" for step in state["controller_steps"])
        assert "audio" in state["controller_steps"][1]["observation"]["produced_types"]
        assert "video" in state["controller_steps"][1]["observation"]["produced_types"]

        if duration == 20:
            published = state["controller_steps"][0]["artifacts"]
            assert len(published) == 1, "Only the full film is a published next-tool input"
            with session_factory()() as db:
                final = db.get(Artifact, published[0]["snapshot"]["id"])
                assert final.metadata_json["frames"] == 480
                raw = list(
                    db.scalars(
                        select(Artifact)
                        .join(Run, Artifact.run_id == Run.id)
                        .where(Run.executor_type.in_(["wan_video", "media_compose"]))
                    )
                )
                assert len(raw) > 1, "The fixture must exercise real segment/composition publication"

"""Enhancement uses the same account-bound sources, output and review authority."""

import json

from app.db import control_session_factory
from app.engine import tick
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_media_translation import settings


def test_private_prompt_and_review_cannot_cross_users(accounts, monkeypatch):
    _, alice, bob = accounts
    calls = []

    async def complete(session, params):
        calls.append(params)
        fields = json.loads(params["messages"][-1]["content"])
        yield json.dumps({key: value + ", soft daylight" for key, value in fields.items()})

    monkeypatch.setattr("app.media_translation.completion_stream", complete)
    settings(alice, enabled=False)
    response = alice.post(
        "/api/images/runs",
        json={
            "mode": "t2i",
            "backend": "qwen",
            "prompt": "Alice private landscape",
            "translation": {"mode": "off", "enhance": True, "review": True},
        },
    )
    assert response.status_code == 202, response.text
    root = response.json()
    prep = root["metadata"]["prompt_translation"]["preparation_run_id"]
    with control_session_factory()() as db:
        assert tick(db, "private-enhancement") == prep
    view = alice.get("/api/runs/" + root["id"]).json()
    review = view["metadata"]["prompt_translation"]["review_run_id"]
    assert len(calls) == 1 and "Alice private landscape" in calls[0]["messages"][-1]["content"]
    assert bob.get("/api/runs/" + prep).status_code == 404
    assert bob.get("/api/runs/" + review).status_code == 404
    forbidden = bob.post(
        "/api/generation/translations/" + review + "/review",
        json={"expected_hash": "0" * 64, "effective": {"prompt": "Bob replacement"}},
    )
    assert forbidden.status_code == 404, forbidden.text
    assert alice.get("/api/runs/" + root["id"]).json()["parameters"]["prompt"] == "Alice private landscape"

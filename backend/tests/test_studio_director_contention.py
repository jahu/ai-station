"""A busy database phase retains the original director claim and inference."""

import asyncio
import json
import sqlite3
from datetime import datetime
from functools import partial

import pytest
from app import studio_director
from app.api import app
from app.db import session_factory
from app.models import Run
from app.run_transactions import RunStopped
from app.runs import request_cancel
from fastapi.testclient import TestClient
from test_assistant_decision_binding import decision
from test_studio_director import local_model as local_model
from test_studio_director import request, step
from test_studio_materials import material
from test_worker_database_busy import error


@pytest.mark.parametrize("code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_BUSY_SNAPSHOT, sqlite3.SQLITE_LOCKED])
def test_busy_binding_and_publication_keep_one_inference_and_one_revision(local_model, monkeypatch, code):
    calls, _ = local_model
    bind, publish = studio_director.completion_stream, studio_director.publish_revision
    bindings, publications = [], []

    def contended_binding(*args):
        bindings.append(True)
        if len(bindings) < 3:
            raise error(code)
        return bind(*args)

    def contended_publication(*args, **kwargs):
        publications.append(True)
        if len(publications) == 1:
            raise error(code)
        return publish(*args, **kwargs)

    monkeypatch.setattr(studio_director, "completion_stream", contended_binding)
    monkeypatch.setattr(studio_director, "publish_revision", contended_publication)
    with TestClient(app) as api:
        row = material(api)
        url = "/api/studio/materials/" + row["id"]
        queued = api.post(url + "/plan", json=request()).json()
        step()
        done = api.get("/api/runs/" + queued["id"]).json()
        assert done["status"] == "succeeded", done["error_message"]
        assert len(calls) == 1 and len(bindings) == 3 and len(publications) == 2
        assert len(api.get(url + "/revisions").json()) == 1


@pytest.mark.parametrize("changed_claim", [False, True])
def test_stop_or_replaced_claim_during_binding_backoff_never_starts_provider(monkeypatch, changed_claim):
    attempts = []
    with session_factory()() as db:
        run = decision(db)
        executor = studio_director.StudioDirector()
        database = partial(
            executor.database,
            db,
            run,
            claim=(run.worker_id, run.claimed_at),
            deadline=datetime.fromisoformat(run.parameters["execution_deadline_at"]),
        )
        rid = run.id

        def bind(*args):
            attempts.append(True)
            raise error(sqlite3.SQLITE_BUSY)

        async def change(seconds):
            with session_factory()() as peer:
                current = peer.get(Run, rid)
                if changed_claim:
                    current.worker_id = "another-worker"
                else:
                    request_cancel(peer, current)
                peer.commit()

        monkeypatch.setattr(studio_director, "completion_stream", bind)
        monkeypatch.setattr(studio_director.asyncio, "sleep", change)
        with pytest.raises(RunStopped):
            asyncio.run(executor.consume(db, run, [], database))
        assert attempts == [True]
        assert run.status == ("running" if changed_claim else "canceled")


def test_busy_cancellation_poll_keeps_the_same_partially_received_stream(local_model, monkeypatch):
    calls, responses = local_model
    started, injected, closed = [], [], []
    original_stopped = studio_director.StudioDirector.stopped

    async def stream(self, **params):
        calls.append(params)
        text = responses[0]
        try:
            started.append(True)
            yield text[: len(text) // 2]
            yield text[len(text) // 2 :]
        finally:
            closed.append(True)

    def poll(db, run):
        if started and not injected:
            injected.append(True)
            raise error(sqlite3.SQLITE_BUSY_SNAPSHOT)
        return original_stopped(db, run)

    monkeypatch.setattr(studio_director.StudioDirector, "stopped", staticmethod(poll))
    from app.local_provider import LocalChatProvider

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    with TestClient(app) as api:
        row = material(api)
        url = "/api/studio/materials/" + row["id"]
        queued = api.post(url + "/plan", json=request()).json()
        step()
        assert api.get("/api/runs/" + queued["id"]).json()["status"] == "succeeded"
        assert len(calls) == len(injected) == len(closed) == 1
        saved = api.get(url + "/revisions").json()
        assert len(saved) == 1 and saved[0]["storyboard"]["title"] == json.loads(responses[0])["title"]

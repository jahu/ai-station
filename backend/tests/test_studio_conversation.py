"""A source alias requires a real owned completed tool graph, not copied IDs."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.db import utcnow
from app.models import Artifact, Conversation, Run, StudioMaterial, StudioRevision
from app.studio_conversation import material_catalog, public_materials, source_material
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_assistant_controller import submit
from test_creative_projects import create
from test_studio_assistant import advance, owned
from test_studio_assistant import director as director
from test_studio_audio_production import generators as generators
from test_studio_production import movie as movie
from test_studio_render import ready as ready


@pytest.fixture
def completed(accounts, director, movie, request):
    director["studio"]["audio"] = getattr(request, "param", "silent")
    _, alice, bob = accounts
    result = submit(alice, "Make a complete film explaining a prism")
    advance(movie)
    with owned(alice) as db:
        root = db.get(Run, result["run"]["id"])
        assert root.status == "succeeded"
        catalog = material_catalog(
            db, owner_id=root.owner_id, conversation_id=root.conversation_id, location="local"
        )
        assert len(catalog) == 1
        return alice, bob, root.owner_id, root.conversation_id, catalog


def test_only_verified_material_is_exposed_and_private_provenance_stays_private(completed):
    alice, _, owner, conversation, catalog = completed
    alias, frozen = next(iter(catalog.items()))
    assert alias == "material:" + frozen["material_id"]
    public = public_materials(catalog)
    assert set(public[alias]) == {"title", "revision", "project", "options"}
    assert public[alias]["title"] == "A prism film"
    public[alias]["options"]["audio"] = "voice"
    assert frozen["public"]["options"]["audio"] == "silent"
    with owned(alice) as db:
        material, revision, render = source_material(db, frozen, owner_id=owner, conversation_id=conversation)
        assert material.id == frozen["material_id"]
        assert revision.id == render.parameters["studio_revision_id"] == frozen["revision_id"]


def test_other_account_or_conversation_cannot_use_or_discover_the_source(completed):
    alice, bob, owner, conversation, catalog = completed
    frozen = next(iter(catalog.values()))
    with owned(bob) as db:
        other = bob.get("/api/auth").json()["user"]["id"]
        assert material_catalog(db, owner_id=other, conversation_id=conversation, location="local") == {}
        with pytest.raises(ValueError, match="this conversation"):
            source_material(db, frozen, owner_id=other, conversation_id=conversation)
    with owned(alice) as db:
        assert material_catalog(db, owner_id=owner, conversation_id=str(uuid4()), location="local") == {}
        with pytest.raises(ValueError, match="this conversation"):
            source_material(db, frozen, owner_id=owner, conversation_id=str(uuid4()))


@pytest.mark.parametrize("change", ["version", "storyboard", "trash", "archive"])
def test_changed_or_unavailable_parent_cannot_authorize_new_publication(completed, change):
    alice, _, owner, conversation, catalog = completed
    frozen = next(iter(catalog.values()))
    with owned(alice) as db:
        if change == "version":
            db.get(StudioMaterial, frozen["material_id"]).version += 1
        elif change == "storyboard":
            revision = db.get(StudioRevision, frozen["revision_id"])
            revision.storyboard = {**revision.storyboard, "title": "Changed old record"}
        elif change == "trash":
            db.get(Artifact, frozen["export_artifact_id"]).trashed_at = utcnow()
        else:
            db.get(StudioMaterial, frozen["material_id"]).archived_at = utcnow()
        db.commit()
        from fastapi import HTTPException

        with pytest.raises((ValueError, HTTPException)):
            source_material(db, frozen, owner_id=owner, conversation_id=conversation)
        if change in {"trash", "archive"}:
            assert material_catalog(db, owner_id=owner, conversation_id=conversation, location="local") == {}


@pytest.mark.parametrize("completed", ["silent", "voice_music"], indirect=True)
@pytest.mark.parametrize("different_brand", [False, True])
def test_followup_plans_a_parented_revision_or_linked_brand_copy_without_overwriting_history(
    completed, director, movie, generators, different_brand
):
    from sqlalchemy import select

    alice, _, _, conversation, catalog = completed
    alias, frozen = next(iter(catalog.items()))
    generated_before = (len(generators[0]), len(generators[1]))
    director["revise_from_parent"] = True
    studio = {"source_material": alias, "project_resolution": "inherit"}
    brand = None
    if different_brand:
        brand = create(
            alice,
            name="Another identity",
            defaults={"format": "reel", "aspect": "portrait", "audio": "music", "duration_seconds": 30},
        )
        studio.update(project_resolution="selected", project="brand:" + brand["id"])
    director["studio"] = studio
    with owned(alice) as db:
        original = db.get(StudioRevision, frozen["revision_id"]).storyboard
        version = db.get(Conversation, conversation).settings_version
    result = submit(
        alice,
        "Change the first title, keeping the rest of this film",
        conversation_id=conversation,
        selection=None,
        expected_settings_version=version,
    )
    advance(movie)
    with owned(alice) as db:
        root = db.get(Run, result["run"]["id"])
        assert root.status == "succeeded", root.error_message
        assert len(list(db.scalars(select(Run).where(Run.executor_type == "photo_pipe")))) == 1
        wrapper = db.get(Run, root.metadata_json["controller_steps"][0]["run_id"])
        assert wrapper.status == "succeeded", (wrapper.error_message, director["plans"][-1])
        assert (len(generators[0]), len(generators[1])) == generated_before
        assert wrapper.metadata_json["studio_source_material_id"] == frozen["material_id"]
        target = db.get(StudioMaterial, wrapper.metadata_json["studio_material_id"])
        assert (target.id != frozen["material_id"]) == different_brand
        assert target.options == frozen["public"]["options"]
        assert target.creative_project_id == (brand["id"] if brand else None)
        old = db.get(StudioRevision, frozen["revision_id"])
        assert old.storyboard == original
        assert db.get(StudioMaterial, frozen["material_id"]).creative_project_id is None
        revisions = list(
            db.scalars(
                select(StudioRevision)
                .where(StudioRevision.material_id == target.id)
                .order_by(StudioRevision.position)
            )
        )
        newest = revisions[-1]
        assert newest.parent_revision_id == revisions[-2].id
        assert newest.storyboard["scenes"][0]["title"] == "Look at it differently"
        assert newest.project_snapshot.get("id") == (brand["id"] if brand else None)
        assert director["plans"][-1]["prior_storyboard"] == original


def test_external_provider_receives_no_catalog_and_performs_no_private_query():
    def forbidden(*args, **kwargs):
        pytest.fail("An external provider must not query private Studio work")

    assert (
        material_catalog(
            SimpleNamespace(scalars=forbidden), owner_id="owner", conversation_id="chat", location="external"
        )
        == {}
    )


def followup(alice, conversation):
    with owned(alice) as db:
        version = db.get(Conversation, conversation).settings_version
    return submit(
        alice,
        "Change only this film's first caption",
        conversation_id=conversation,
        selection=None,
        expected_settings_version=version,
    )["run"]["id"]


def reach_wrapper(identity, movie):
    from app.db import control_session_factory
    from app.engine import tick

    for i in range(30):
        with control_session_factory()() as db:
            tick(db, f"revision-dispatch-{i}", executors=movie)
            steps = db.get(Run, identity).metadata_json.get("controller_steps", [])
            if steps:
                return steps[0]["run_id"]
    pytest.fail("The revision did not dispatch its Studio wrapper")


@pytest.mark.parametrize("after_dispatch", [False, True])
def test_stale_source_closes_outcome_without_recreating_whole_workflow(
    completed, director, movie, after_dispatch
):
    from sqlalchemy import select

    alice, _, _, conversation, catalog = completed
    alias, frozen = next(iter(catalog.items()))
    director["studio"] = {"source_material": alias, "project_resolution": "inherit"}
    identity = followup(alice, conversation)
    if after_dispatch:
        reach_wrapper(identity, movie)
    with owned(alice) as db:
        db.get(StudioMaterial, frozen["material_id"]).version += 1
        db.commit()
    advance(movie)
    with owned(alice) as db:
        root = db.get(Run, identity)
        assert root.status == "succeeded", root.error_message
        steps = root.metadata_json["controller_steps"]
        assert len(steps) == 1
        wrapper = db.get(Run, steps[0]["run_id"])
        assert wrapper.status == "failed" and wrapper.error_type == "StudioSourceUnavailable"
        assert "changed" in wrapper.error_message
        assert steps[0]["observation"]["studio_attempt_exhausted"] is True
        assert len(list(db.scalars(select(StudioRevision)))) == 1
        assert db.get(Run, frozen["export_run_id"]).status == "succeeded"


def test_stopping_revision_never_cancels_completed_source_tasks(completed, director, movie):
    from app.task_control import cancel_task

    alice, _, _, conversation, catalog = completed
    alias, frozen = next(iter(catalog.items()))
    director["studio"] = {"source_material": alias, "project_resolution": "inherit"}
    identity = followup(alice, conversation)
    wrapper_id = reach_wrapper(identity, movie)
    with owned(alice) as db:
        cancel_task(db, db.get(Run, identity).task)
        db.commit()
    advance(movie)
    with owned(alice) as db:
        assert db.get(Run, identity).status == db.get(Run, wrapper_id).status == "canceled"
        assert db.get(Run, frozen["export_run_id"]).status == "succeeded"
        assert db.get(Run, frozen["wrapper_id"]).status == "succeeded"
        assert db.get(Artifact, frozen["export_artifact_id"]).trashed_at is None

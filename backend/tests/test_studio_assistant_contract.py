"""No language inference/GPU: owner-scoped brand context and closed coordinates."""

import json

import pytest
from app.data_access import DataScope, ScopedSession
from app.db import get_engine, utcnow
from app.models import Artifact, CreativeProject
from app.studio_assistant_contract import (
    StudioCall,
    StudioIntent,
    project_catalog,
    public_projects,
    reference_ids,
    selected_context,
)
from fastapi import HTTPException
from pydantic import ValidationError
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_account_private_api import upload
from test_creative_projects import create


def test_catalog_is_owned_bounded_and_never_read_for_external_provider(accounts):
    _, alice, bob = accounts
    mine = create(alice, name="Northwind courses", aliases=["northwind.example"])
    create(bob, name="Private other brand")
    user = alice.get("/api/auth").json()["user"]["id"]
    with ScopedSession(bind=get_engine(), scope=DataScope(user), expire_on_commit=False) as db:
        catalog = project_catalog(db, owner_id=user, location="local")
        alias = "brand:" + mine["id"]
        assert list(catalog) == [alias]
        assert catalog[alias]["snapshot"]["id"] == mine["id"]
        public = public_projects(catalog)
        assert public[alias]["name"] == "Northwind courses"
        assert public[alias]["aliases"] == ["northwind.example"]
        assert "id" not in public[alias] and "logo_artifact_id" not in public[alias]
        assert len(json.dumps(public, ensure_ascii=False).encode()) <= 24000

    class NoQuery:
        def scalars(self, *args):
            raise AssertionError("External context must not read private projects")

    assert project_catalog(NoQuery(), owner_id=user, location="external") == {}


def test_frozen_selected_identity_and_explicit_options_have_one_authoritative_source(accounts):
    _, alice, _ = accounts
    brand = create(alice, name="A business", aliases=["brand.example"])
    user = alice.get("/api/auth").json()["user"]["id"]
    with ScopedSession(bind=get_engine(), scope=DataScope(user), expire_on_commit=False) as db:
        catalog = project_catalog(db, owner_id=user, location="local")
        alias = "brand:" + brand["id"]
        original = catalog[alias]["snapshot"]["identity"]
        row = db.get(CreativeProject, brand["id"])
        row.identity = {**row.identity, "tone": "A later change"}
        db.commit()
        chosen = selected_context(
            db,
            catalog,
            StudioIntent(
                project=alias,
                project_resolution="selected",
                format="reel",
                aspect="portrait",
                audio="music",
                duration_seconds=25,
            ),
        )
        assert chosen["creative_project_id"] == brand["id"]
        assert chosen["project_snapshot"]["identity"] == original
        assert chosen["options"] == {
            "format": "reel",
            "aspect": "portrait",
            "audio": "music",
            "duration_seconds": 25,
        }
        with pytest.raises(ValueError, match="supplied"):
            selected_context(db, catalog, StudioIntent(project=brand["id"], project_resolution="selected"))
        row.archived_at = utcnow()
        db.commit()
        with pytest.raises(HTTPException):
            selected_context(db, catalog, StudioIntent(project=alias, project_resolution="selected"))


@pytest.mark.parametrize(
    "payload",
    [
        {"project": "made-up"},
        {"project_resolution": "selected"},
        {"project": "brand:1", "project_resolution": "clarify"},
        {"format": "whatever"},
        {"audio": "none"},
        {"duration_seconds": True},
        {"command": ["id"]},
        {"path": "/etc/passwd"},
    ],
)
def test_typed_intent_does_not_grant_unreviewed_operations(payload):
    with pytest.raises(ValidationError):
        StudioIntent.model_validate(payload)


def test_standalone_defaults_and_unresolved_brand_are_distinct():
    intent = StudioIntent(audio="silent", format="presentation", aspect="landscape")
    value = selected_context(None, {}, intent)
    assert value["creative_project_id"] is None and value["options"]["audio"] == "silent"
    with pytest.raises(ValueError, match="Clarify"):
        selected_context(None, {}, StudioIntent(project_resolution="clarify"))
    with pytest.raises(ValidationError):
        StudioCall(instruction="Make a film", references=["input:image:1"] * 2)
    with pytest.raises(ValidationError):
        StudioCall(instruction="Make a film", shell="id")


def test_reference_aliases_preserve_order_and_reject_foreign_or_changed_media(accounts):
    _, alice, bob = accounts
    first, _ = upload(alice, "blue")
    second, _ = upload(alice, "red")
    foreign, _ = upload(bob, "green")
    owner = alice.get("/api/auth").json()["user"]["id"]
    with ScopedSession(bind=get_engine(), scope=DataScope(owner), expire_on_commit=False) as db:
        entries = {}
        for alias, identity in (("input:image:1", first), ("input:image:2", second)):
            item = db.get(Artifact, identity)
            entries[alias] = {
                "type": "image",
                "snapshot": {
                    "id": item.id,
                    "relative_path": item.relative_path,
                    "sha256": item.sha256,
                    "size_bytes": item.size_bytes,
                },
            }
        assert reference_ids(
            db, owner_id=owner, entries=entries, aliases=["input:image:2", "input:image:1"]
        ) == [second, first]
        with pytest.raises(ValueError, match="supplied"):
            reference_ids(db, owner_id=owner, entries=entries, aliases=[first])
        entries["foreign"] = {"type": "image", "snapshot": {"id": foreign}}
        with pytest.raises(ValueError, match="owner"):
            reference_ids(db, owner_id=owner, entries=entries, aliases=["foreign"])
        entries["input:image:1"]["snapshot"]["sha256"] = "0" * 64
        with pytest.raises(ValueError, match="changed"):
            reference_ids(db, owner_id=owner, entries=entries, aliases=["input:image:1"])


def test_unicode_brand_context_stays_within_the_model_prompt_budget(accounts):
    from app.creative_projects import Defaults

    _, alice, _ = accounts
    owner = alice.get("/api/auth").json()["user"]["id"]
    with ScopedSession(bind=get_engine(), scope=DataScope(owner), expire_on_commit=False) as db:
        for i in range(25):
            db.add(
                CreativeProject(
                    name=str(i) + "🧠" * 140,
                    description="🧠" * 400,
                    aliases=["🧠" * 100] * 6,
                    identity={"tone": "🧠" * 200},
                    defaults=Defaults().model_dump(),
                )
            )
        db.commit()
        catalog = project_catalog(db, owner_id=owner, location="local")
        assert 0 < len(catalog) <= 20
        assert len(json.dumps(public_projects(catalog), ensure_ascii=False).encode()) <= 24000


@pytest.mark.parametrize("label", ["brand:known", "a learning brand", "  LEARN.EXAMPLE  "])
def test_interpretation_canonicalizes_exact_advertised_labels_not_keywords(label):
    from app.assistant_intents import validate_plan

    context = {
        "creative_projects": {"brand:known": {"name": "A learning brand", "aliases": ["learn.example"]}},
        "inputs_and_results": [],
    }
    result = validate_plan(
        json.dumps(
            {
                "reason": "Create the requested film",
                "immediate": [
                    {
                        "kind": "studio_material",
                        "description": "An educational film",
                        "studio": {"project": label, "project_resolution": "selected"},
                    }
                ],
                "automations": [],
            }
        ),
        context,
    )
    assert result.outcomes[0].studio.project == "brand:known"


@pytest.mark.parametrize("label", ["unknown.example", "learning", "brand:foreign", "shared.example"])
def test_unknown_partial_or_ambiguous_project_labels_grant_no_scope(label):
    from app.studio_assistant_contract import resolve_project_alias

    catalog = {
        "brand:first": {"name": "A learning brand", "aliases": ["shared.example"]},
        "brand:second": {"name": "Another brand", "aliases": ["shared.example"]},
    }
    with pytest.raises(ValueError, match="unambiguous"):
        resolve_project_alias(label, catalog)

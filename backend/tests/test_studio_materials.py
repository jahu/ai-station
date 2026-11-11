from uuid import uuid4

import pytest
from app.data_access import DataAccessError, DataScope, ScopedSession
from app.db import get_engine
from app.models import StudioMaterial, StudioRevision
from app.studio_schema import Storyboard
from pydantic import ValidationError
from sqlalchemy import select
from test_account_private_api import accounts, private_app, upload  # noqa: F401, F811
from test_creative_projects import create as project

BASE = "/api/studio/materials"


def material(browser, **extra):
    response = browser.post(
        BASE,
        json={
            "client_request_id": str(uuid4()),
            "brief": "Explain a useful idea through cinematic original visuals.",
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def board(audio="voice_music", **extra):
    return {
        "title": "A useful idea",
        "concept": "A clear visual explanation",
        "hook": "A concrete surprising visual",
        "audio": audio,
        "music_brief": "Warm restrained instrumental electronic score",
        "scenes": [
            {
                "purpose": "An opening contrast",
                "duration_frames": 120,
                "visual_kind": "video",
                "visual_brief": "Macro glass prism turns slowly as a narrow light beam separates into a spectrum.",
                "narration": "A small change can reveal a hidden pattern."
                if audio in {"voice", "voice_music"}
                else "",
            }
        ],
        **extra,
    }


def test_materials_are_private_project_optional_and_creation_is_idempotent(accounts):  # noqa: F811
    admin, alice, bob = accounts
    brand = project(alice)
    created = material(alice, creative_project_id=brand["id"])
    assert created["options"]["format"] == "presentation" and created["options"]["aspect"] == "landscape"
    assert alice.get(BASE).json() == [created]
    assert bob.get(BASE).json() == admin.get(BASE).json() == []
    assert bob.get(BASE + "/" + created["id"]).status_code == 404
    assert admin.get(BASE + "/" + created["id"]).status_code == 404
    assert (
        admin.get(BASE + "/" + created["id"], headers={"X-AI-Station-Inspect-All": "true"}).status_code == 200
    )
    assert (
        bob.post(
            BASE,
            json={"client_request_id": str(uuid4()), "brief": "test", "creative_project_id": brand["id"]},
        ).status_code
        == 404
    )
    request = {"client_request_id": str(uuid4()), "brief": "A standalone material"}
    first = alice.post(BASE, json=request).json()
    assert alice.post(BASE, json=request).json() == first
    assert alice.post(BASE, json={**request, "brief": "A different instruction"}).status_code == 409
    assert material(bob)["creative_project_id"] is None


def test_revisions_freeze_brand_brief_and_audio_without_overwriting_history(accounts):  # noqa: F811
    _, alice, bob = accounts
    brand = project(alice)
    created = material(alice, creative_project_id=brand["id"])
    url = BASE + "/" + created["id"]
    request = {"client_request_id": str(uuid4()), "expected_version": 1, "storyboard": board()}
    reply = alice.post(url + "/revisions", json=request)
    assert reply.status_code == 201, reply.text
    first = reply.json()
    assert first["project_snapshot"]["version"] == 1 and first["position"] == 1
    assert first["options"]["audio"] == "voice_music"
    assert alice.post(url + "/revisions", json=request).json() == first
    assert (
        alice.post(url + "/revisions", json={**request, "client_request_id": str(uuid4())}).status_code == 409
    )
    assert bob.get(url + "/revisions").status_code == 404
    changed = alice.patch(
        url, json={"expected_version": 2, "brief": "A new request", "options": {"audio": "silent"}}
    )
    assert changed.status_code == 200, changed.text
    second = alice.post(
        url + "/revisions",
        json={
            "client_request_id": str(uuid4()),
            "expected_version": 3,
            "parent_revision_id": first["id"],
            "storyboard": board("silent"),
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["parent_revision_id"] == first["id"]
    assert alice.get(url + "/revisions/" + first["id"]).json() == first
    assert alice.get(url).json()["version"] == 4
    archived = alice.patch(url, json={"expected_version": 4, "archived": True})
    assert archived.status_code == 200
    assert (
        alice.get(BASE).json() == [] and alice.get(BASE + "?archived=true").json()[0]["id"] == created["id"]
    )
    assert (
        alice.post(
            url + "/revisions", json={**request, "client_request_id": str(uuid4()), "expected_version": 5}
        ).status_code
        == 409
    )
    assert alice.get(url + "/revisions/" + first["id"]).status_code == 200


def test_foreign_library_sources_and_parent_versions_cannot_cross_materials(accounts):  # noqa: F811
    _, alice, bob = accounts
    owned = material(alice)
    foreign = material(bob)
    picture, _ = upload(bob, "blue")
    storyboard = board(
        scenes=[
            {
                "purpose": "Show the supplied reference",
                "duration_frames": 90,
                "visual_kind": "library",
                "source_artifact_id": picture,
                "narration": "A clear example.",
            }
        ]
    )
    response = alice.post(
        BASE + "/" + owned["id"] + "/revisions",
        json={"client_request_id": str(uuid4()), "expected_version": 1, "storyboard": storyboard},
    )
    assert response.status_code == 422, response.text
    own = alice.post(
        BASE + "/" + owned["id"] + "/revisions",
        json={"client_request_id": str(uuid4()), "expected_version": 1, "storyboard": board()},
    ).json()
    response = bob.post(
        BASE + "/" + foreign["id"] + "/revisions",
        json={
            "client_request_id": str(uuid4()),
            "expected_version": 1,
            "parent_revision_id": own["id"],
            "storyboard": board(),
        },
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"scenes": [{"purpose": "A fake finished source", "duration_frames": 90, "visual_kind": "library"}]},
        {
            "scenes": [
                {
                    "purpose": "A command",
                    "duration_frames": 90,
                    "visual_kind": "image",
                    "visual_brief": "a scene",
                    "command": ["sh"],
                }
            ]
        },
        {
            "scenes": [
                {
                    "purpose": "A fake image",
                    "duration_frames": 90,
                    "visual_kind": "image",
                    "visual_brief": "scene",
                    "source_artifact_id": str(uuid4()),
                }
            ]
        },
        {
            "audio": "silent",
            "scenes": [
                {
                    "purpose": "A scene",
                    "duration_frames": 90,
                    "visual_kind": "image",
                    "visual_brief": "An actual visual",
                    "narration": "Do not silently drop this narration.",
                }
            ],
        },
        {"music_brief": ""},
        {
            "scenes": [
                {
                    "purpose": "Fake empty slide",
                    "duration_frames": 90,
                    "visual_kind": "graphics",
                    "layout": "statement",
                }
            ]
        },
    ],
)
def test_editorial_schema_never_becomes_shell_or_silently_drops_requested_media(change):
    with pytest.raises(ValidationError):
        Storyboard.model_validate(board(**change))


def test_orm_enforces_material_and_revision_ownership(accounts):  # noqa: F811
    _, alice, bob = accounts
    own = material(alice)
    request = {"client_request_id": str(uuid4()), "expected_version": 1, "storyboard": board()}
    saved = alice.post(BASE + "/" + own["id"] + "/revisions", json=request).json()
    from app.db import control_session_factory
    from app.models import User

    with control_session_factory()() as control:
        uid = control.scalar(select(User.id).where(User.username == "Bob"))
    with ScopedSession(bind=get_engine(), scope=DataScope(uid)) as session:
        assert session.get(StudioMaterial, own["id"]) is None
        assert session.get(StudioRevision, saved["id"]) is None
        session.add(
            StudioRevision(
                material_id=own["id"],
                client_request_id=str(uuid4()),
                request_sha256="a" * 64,
                position=2,
                storyboard=board(),
                sources={},
                project_snapshot={},
                options={},
                brief="foreign",
            )
        )
        with pytest.raises(DataAccessError):
            session.flush()

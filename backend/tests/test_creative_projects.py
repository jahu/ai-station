"""Creative identities are private, versioned and frozen beside ordinary Runs."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from app.data_access import DataAccessError, DataScope, ScopedSession
from app.db import control_session_factory, get_engine, migrate, reset_engine
from app.models import CreativeProject, CreativeSession, Run, Task
from sqlalchemy import select
from test_account_private_api import accounts, private_app, upload  # noqa: F401
from test_creative_sessions import generator, send  # noqa: F401

BASE = "/api/creative/projects"


def definition(name="A learning brand", **kwargs):
    return {
        "name": name,
        "description": "Practical learning, explained clearly",
        "aliases": ["example.org", "Example learning"],
        "identity": {
            "colors": ["#4631D8", "#FAFAFC", "#151321"],
            "typography": "editorial",
            "tone": "Warm, concrete, confident",
            "audience": "People learning a new subject",
            "language": "Polish",
        },
        "defaults": {"format": "presentation", "aspect": "landscape", "audio": "voice_music"},
        **kwargs,
    }


def create(browser, **kwargs):
    response = browser.post(BASE, json=definition(**kwargs))
    assert response.status_code == 201, response.text
    return response.json()


def workspace(browser, project=None):
    response = browser.post(
        "/api/creative/sessions",
        json={
            "capability": "images",
            "title": "A new material",
            "creative_project_id": project,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_identity_is_private_and_archive_preserves_membership(accounts):  # noqa: F811
    admin, alice, bob = accounts
    project = create(alice)
    material = workspace(alice, project["id"])
    workspace(alice)
    workspace(bob)
    url = BASE + "/" + project["id"]
    assert alice.get(BASE).json()[0]["identity"]["colors"] == ["#4631D8", "#FAFAFC", "#151321"]
    assert bob.get(BASE).json() == admin.get(BASE).json() == []
    assert bob.get(url).status_code == admin.get(url).status_code == 404
    assert admin.get(url, headers={"X-AI-Station-Inspect-All": "true"}).json()["id"] == project["id"]
    assert bob.put(url, json={**definition(), "expected_version": 1}).status_code == 404
    assert alice.get("/api/creative/sessions?creative_project_id=" + project["id"]).json() == [material]
    assert bob.get("/api/creative/sessions?creative_project_id=" + project["id"]).status_code == 404
    assert (
        bob.post(
            "/api/creative/sessions",
            json={
                "capability": "video",
                "creative_project_id": project["id"],
            },
        ).status_code
        == 404
    )
    assert alice.patch(url + "/archive", json={"expected_version": 1, "archived": True}).status_code == 200
    assert alice.get(BASE).json() == []
    assert alice.get(BASE + "?archived=true").json()[0]["id"] == project["id"]
    assert alice.get("/api/creative/sessions/" + material["id"]).status_code == 200
    assert (
        alice.post(
            "/api/creative/sessions",
            json={
                "capability": "video",
                "creative_project_id": project["id"],
            },
        ).status_code
        == 409
    )
    assert alice.delete(url).status_code == 405
    assert alice.patch(url + "/archive", json={"expected_version": 2, "archived": False}).status_code == 200
    reset_engine()
    migrate()
    assert alice.get(url).json()["version"] == 3


def test_parallel_style_edits_have_one_winner_and_preserve_version(accounts):  # noqa: F811
    _, alice, _ = accounts
    project = create(alice)
    url = BASE + "/" + project["id"]

    def save(name):
        return alice.put(url, json={**definition(name=name), "expected_version": 1})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(save, ["First edit", "Second edit"]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    saved = alice.get(url).json()
    assert saved["version"] == 2 and saved["name"] in {"First edit", "Second edit"}


def test_each_new_generation_keeps_its_original_identity_snapshot(accounts, generator):  # noqa: F811
    _, alice, _ = accounts
    project = create(alice)
    material = workspace(alice, project["id"])
    request_id = str(uuid4())
    first = send(alice, material["id"], client_request_id=request_id).json()
    changed = definition(identity={"colors": ["#125533"], "tone": "Different tone"})
    assert alice.put(BASE + "/" + project["id"], json={**changed, "expected_version": 1}).status_code == 200
    second = send(alice, material["id"]).json()
    again = send(alice, material["id"], client_request_id=request_id)
    assert again.status_code == 202 and again.json()["run_id"] == first["run_id"]
    with control_session_factory()() as session:
        one, two = [session.get(Run, t["run_id"]) for t in [first, second]]
        assert one.metadata_json["creative_project"]["version"] == 1
        assert one.metadata_json["creative_project"]["identity"]["colors"] == [
            "#4631D8",
            "#FAFAFC",
            "#151321",
        ]
        assert two.metadata_json["creative_project"]["version"] == 2
        assert two.metadata_json["creative_project"]["identity"]["colors"] == ["#125533"]
        assert (
            session.get(Task, one.task_id).metadata_json["creative_project"]
            == one.metadata_json["creative_project"]
        )
    assert len(generator) == 2


def test_archiving_during_material_work_does_not_replay_or_create_more_work(accounts, generator):  # noqa: F811
    _, alice, _ = accounts
    project = create(alice)
    material = workspace(alice, project["id"])
    request_id = str(uuid4())
    first = send(alice, material["id"], client_request_id=request_id).json()
    alice.patch(BASE + "/" + project["id"] + "/archive", json={"expected_version": 1, "archived": True})
    assert send(alice, material["id"]).status_code == 409
    assert send(alice, material["id"], client_request_id=request_id).json()["run_id"] == first["run_id"]
    assert len(generator) == 1


def test_foreign_logo_and_direct_orm_membership_cannot_cross_accounts(accounts):  # noqa: F811
    _, alice, bob = accounts
    foreign_logo, _ = upload(bob, "blue")
    assert alice.post(BASE, json=definition(logo_artifact_id=foreign_logo)).status_code == 404
    own_logo, _ = upload(alice, "red")
    project = create(alice, logo_artifact_id=own_logo)
    owner = bob.get("/api/auth").json()["user"]["id"]
    with ScopedSession(bind=get_engine(), scope=DataScope(owner)) as session:
        session.add(CreativeSession(capability="video", title="Forbidden", creative_project_id=project["id"]))
        with pytest.raises(DataAccessError):
            session.flush()
    assert (
        bob.patch(
            BASE + "/" + project["id"] + "/archive", json={"expected_version": 1, "archived": True}
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"name": " "},
        {"identity": {"colors": ["url(https://example.org)"]}},
        {"identity": {"typography": "<script>"}},
        {"defaults": {"duration_seconds": 100000}},
        {"defaults": {"duration_seconds": True}},
        {"aliases": [" "]},
        {"repo_path": "/home/other"},
        {"defaults": {"command": "sh"}},
    ],
)
def test_invalid_identity_never_creates_runs_or_projects(accounts, payload):  # noqa: F811
    _, alice, _ = accounts
    response = alice.post(BASE, json={**definition(), **payload})
    assert response.status_code == 422, response.text
    assert alice.get(BASE).json() == []
    with control_session_factory()() as session:
        assert session.scalar(select(CreativeProject)) is None
        assert session.scalar(select(Run)) is None


def test_aliases_are_deduplicated_without_changing_display_names(accounts):  # noqa: F811
    _, alice, _ = accounts
    project = create(alice, aliases=["example.org", "Example.org", " My brand "])
    assert project["aliases"] == ["example.org", "My brand"]

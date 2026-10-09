import json

import pytest
from ai_station_runner import app as app_module
from ai_station_runner import station_image as module
from ai_station_runner.app import app
from fastapi.testclient import TestClient

TAG_ID = "sha256:" + "a" * 64
OLD_ID = "sha256:" + "b" * 64
CID = "c" * 12


def container(
    *, image=module.IMAGE, image_id=TAG_ID, service="ai-station", project="ai-station", status="running"
):
    return {
        "Id": "c" * 64,
        "Name": "/ai-station-ai-station-1",
        "Image": image_id,
        "Config": {
            "Image": image,
            "Labels": {
                "com.docker.compose.service": service,
                "com.docker.compose.project": project,
            },
        },
        "State": {"Status": status},
    }


def test_refuses_argv_outside_inspect():
    with pytest.raises(RuntimeError, match="Refusing"):
        module.docker(["build", "-t", module.IMAGE, "."])
    with pytest.raises(RuntimeError, match="Refusing"):
        module.docker(["tag", module.IMAGE, "ai-station:next"])
    with pytest.raises(RuntimeError, match="Refusing"):
        module.docker(["stop", CID])
    with pytest.raises(RuntimeError, match="Refusing"):
        module.docker(["inspect", "--type", "container", "not an id", "--format", "{{json .}}"])


def test_missing_docker_stays_inspect_only(monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    body = module.inspect_station_image()
    assert body["docker"] == "unavailable"
    assert body["image_rollout"] == "unpublished"
    assert body["matches_running"] is False
    assert body["containers"] == []


def test_missing_tag_and_matching_running_containers(monkeypatch):
    calls = []

    def docker(args, missing_ok=False):
        calls.append(tuple(args))
        if args[:2] == ["image", "inspect"]:
            return None if missing_ok else (_ for _ in ()).throw(RuntimeError("missing"))
        if args[0] == "ps":
            return CID
        if args[0] == "inspect":
            return json.dumps(container())
        raise AssertionError(args)

    monkeypatch.setattr(module, "docker", docker)
    missing = module.inspect_station_image()
    assert missing["tag"]["present"] is False
    assert missing["matches_running"] is False
    assert missing["image_rollout"] == "unpublished"
    assert any(call[:3] == ("image", "inspect", module.IMAGE) for call in calls)

    def present(args, missing_ok=False):
        if args[:2] == ["image", "inspect"]:
            return json.dumps({"Id": TAG_ID, "Created": "2026-10-09T00:00:00Z", "RepoTags": [module.IMAGE]})
        if args[0] == "ps":
            return CID
        if args[0] == "inspect":
            return json.dumps(container())
        raise AssertionError(args)

    monkeypatch.setattr(module, "docker", present)
    matched = module.inspect_station_image()
    assert matched["tag"]["id"] == TAG_ID
    assert matched["matches_running"] is True
    assert matched["containers"][0]["service"] == "ai-station"
    assert matched["image_rollout"] == "unpublished"


def test_stale_running_image_does_not_match_rebuilt_tag(monkeypatch):
    def docker(args, missing_ok=False):
        if args[:2] == ["image", "inspect"]:
            return json.dumps({"Id": TAG_ID, "Created": "2026-10-09T00:00:00Z"})
        if args[0] == "ps":
            return CID
        if args[0] == "inspect":
            return json.dumps(container(image_id=OLD_ID))
        raise AssertionError(args)

    monkeypatch.setattr(module, "docker", docker)
    body = module.inspect_station_image()
    assert body["matches_running"] is False
    assert body["containers"][0]["matches_tag"] is False
    assert body["image_rollout"] == "unpublished"


def test_ignores_unrelated_compose_projects_and_images(monkeypatch):
    def docker(args, missing_ok=False):
        if args[:2] == ["image", "inspect"]:
            return json.dumps({"Id": TAG_ID})
        if args[0] == "ps":
            return CID
        if args[0] == "inspect":
            return json.dumps(container(project="other-app", image="other:latest", image_id=OLD_ID))
        raise AssertionError(args)

    monkeypatch.setattr(module, "docker", docker)
    body = module.inspect_station_image()
    assert body["containers"] == []
    assert body["matches_running"] is False


def test_http_inspect_does_not_offer_rollout(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "inspect_station_image",
        lambda: {
            "docker": "available",
            "tag": {"name": module.IMAGE, "present": True, "id": TAG_ID, "created": None},
            "containers": [],
            "matches_running": False,
            "image_rollout": "unpublished",
            "restore": "unpublished",
            "summary": "inspect-only",
        },
    )
    client = TestClient(app)
    body = client.get("/v1/station-image").json()
    assert body["image_rollout"] == "unpublished"
    assert client.post("/v1/station-image", json={}).status_code == 405

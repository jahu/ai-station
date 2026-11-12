"""Fixed job orchestration with synthetic Docker; no package/network installation."""

import copy
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote
from uuid import uuid4

import httpx
import pytest
from ai_station_runner import motion_install_job as job
from ai_station_runner.config import Settings, clear_settings_cache
from ai_station_runner.motion_prepare_plan import BASES, manifest
from ai_station_runner.runtime_install import atomic_json, directory, load_json


class Docker:
    def __init__(self):
        self.calls, self.containers = [], {}
        self.fail_runtime = self.stop_sdk = False
        self.identity = None
        self.image_config = None
        self.missing_bases = set()
        self.registry_error = False
        self.pulls = []

    def response(self, code, data=None, content=None):
        return httpx.Response(
            code,
            json=data if content is None else None,
            content=content,
            request=httpx.Request("GET", "http://docker"),
        )

    def base(self, stage):
        return {
            "Id": "sha256:" + ("b" if stage == "sdk" else "d") * 64,
            "RepoDigests": [BASES[stage]],
            "Os": "linux",
            "Architecture": "amd64",
            "Config": {"Env": ["PATH=/usr/bin:/bin"], "User": "", "Entrypoint": None},
        }

    def get(self, path, **kwargs):
        if path == "/info":
            return self.response(200, {"ID": "daemon"})
        path = unquote(path)
        for stage, reference in BASES.items():
            if path == "/images/" + reference + "/json":
                return (
                    self.response(404, {})
                    if stage in self.missing_bases
                    else self.response(200, self.base(stage))
                )
        coordinate = path.removeprefix("/containers/").removesuffix("/json")
        for value in self.containers.values():
            if coordinate in (value["Id"], value["Name"].lstrip("/")):
                return self.response(200, copy.deepcopy(value))
        return self.response(404, {})

    def post(self, path, *, params=None, json=None, timeout=None):
        self.calls.append(("POST", path))
        if path == "/containers/create":
            stage = json["Labels"]["ai-station.motion.prepare.stage"]
            base = self.base(stage)
            value = {
                "Id": ("1" if stage == "sdk" else "2") * 64,
                "Name": "/" + params["name"],
                "Image": base["Id"],
                "Config": {**base["Config"], **{k: v for k, v in json.items() if k != "HostConfig"}},
                "HostConfig": copy.deepcopy(json["HostConfig"]),
                "Mounts": [],
                "State": {"Status": "created", "Running": False},
            }
            self.containers[stage] = value
            return self.response(201, {"Id": value["Id"]})
        if path == "/commit":
            assert timeout is not None and 30 < timeout.read <= 600
            self.image_config = json
            return self.response(201, {"Id": "sha256:" + "f" * 64})
        for stage, value in self.containers.items():
            if path == "/containers/" + value["Id"] + "/start":
                value["State"] = {
                    "Running": False,
                    "Status": "exited",
                    "ExitCode": 1 if stage == "runtime" and self.fail_runtime else 0,
                }
                if stage == "sdk" and self.stop_sdk:
                    folder = directory(self.identity)
                    saved = load_json(folder / "motion-setup.json")
                    saved["cancel_requested"] = True
                    atomic_json(folder, "motion-setup.json", saved)
                return self.response(204, {})
        raise AssertionError(path)

    def put(self, path, *, params, content, headers):
        self.calls.append(("PUT", path))
        if not isinstance(content, bytes):
            assert b"".join(content)
        return self.response(200, {})

    def stream(self, method, path, *, params):
        if method == "POST":
            assert path == "/images/create"
            stage = next(
                name
                for name, reference in BASES.items()
                if reference == params["fromImage"] + "@" + params["tag"]
            )
            assert params["platform"] == "linux/amd64"
            self.pulls.append(stage)
            if not self.registry_error:
                self.missing_bases.discard(stage)
            payload = (
                b'{"error":"synthetic registry failure"}\n'
                if self.registry_error
                else b'{"status":"Pull complete"}\n'
            )
            return nullcontext(self.response(200, content=payload))
        assert method == "GET" and path.endswith("/archive")
        return nullcontext(self.response(200, content=b"synthetic archive bytes; not renderer qualification"))

    def delete(self, path, *, params):
        self.calls.append(("DELETE", path))
        assert params == {"force": "false", "v": "false"}
        stage = next(s for s, v in self.containers.items() if path == "/containers/" + v["Id"])
        del self.containers[stage]
        return self.response(204, {})


@pytest.fixture
def installation(tmp_path, monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("AI_STATION_DATA_HOST_PATH", str(tmp_path))
    clear_settings_cache()
    identity = str(uuid4())
    api = Docker()
    api.identity = identity
    monkeypatch.setattr(job, "client", lambda *_: nullcontext(api))
    monkeypatch.setattr(job, "require_scope", lambda *_: {"maximum_ram_mib": 256})
    monkeypatch.setattr(job, "image_observation", lambda *_: {})
    request = {
        "run_id": identity,
        "profile": "hyperframes-cpu-linux-amd64-v1",
        "deadline_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    }
    recipe = {
        "preparation_mode": "owned_containers",
        "preparation_manifest": manifest(),
        "renderer_recipe_sha256": job.recipe(),
    }
    saved = {
        "request": request,
        "request_hash": job.fingerprint(request),
        "recipe": recipe,
        "manifest_sha256": job.fingerprint(recipe),
        "installation": True,
        "daemon": {"id": "daemon", "socket": "/fixture.sock"},
    }
    atomic_json(directory(identity), "motion-setup.json", saved)
    yield identity, api, saved
    clear_settings_cache()


def test_fixed_job_assembles_one_nonroot_image_and_removes_only_owned_stages(installation):
    identity, api, saved = installation
    assert job.run(identity) == 0
    result = load_json(directory(identity) / "motion-install-result.json")
    assert result["request_hash"] == saved["request_hash"]
    assert not api.containers
    assert api.image_config["User"] == "1000:1000" and api.image_config["Cmd"] == []
    assert api.image_config["Labels"]["ai-station.motion.preparation.run"] == identity
    assert sum(path == "/commit" for _, path in api.calls) == 1


def test_stop_after_sdk_never_launches_runtime_or_commits(installation):
    identity, api, _ = installation
    api.stop_sdk = True
    with pytest.raises(job.Stopped):
        job.run(identity)
    assert not api.containers and api.image_config is None
    assert sum(path == "/containers/create" for _, path in api.calls) == 1


def test_failed_component_cleans_stages_and_never_publishes_ready(installation):
    identity, api, _ = installation
    api.fail_runtime = True
    with pytest.raises(ValueError, match="component preparation failed"):
        job.run(identity)
    assert not api.containers and api.image_config is None
    assert not (directory(identity) / "motion-install-result.json").exists()


def test_changed_manifest_is_refused_before_any_docker_action(installation):
    identity, api, saved = installation
    saved["recipe"]["preparation_manifest"]["policy_sha256"] = "e" * 64
    saved["manifest_sha256"] = job.fingerprint(saved["recipe"])
    atomic_json(directory(identity), "motion-setup.json", saved)
    with pytest.raises(ValueError, match="source identity changed"):
        job.run(identity)
    assert api.calls == []


def test_expired_deadline_does_not_create_a_stage(installation):
    identity, api, saved = installation
    saved["request"]["deadline_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    saved["request_hash"] = job.fingerprint(saved["request"])
    atomic_json(directory(identity), "motion-setup.json", saved)
    with pytest.raises(TimeoutError):
        job.run(identity)
    assert api.calls == []


def test_missing_official_bases_use_only_the_fixed_manifest_pull(installation):
    identity, api, _ = installation
    api.missing_bases = set(BASES)
    assert job.run(identity) == 0
    assert api.pulls == ["sdk", "runtime"]
    assert not api.containers


def test_failed_registry_transfer_never_creates_a_preparation_container(installation):
    identity, api, _ = installation
    api.missing_bases = {"sdk"}
    api.registry_error = True
    with pytest.raises(ValueError, match="base transfer failed"):
        job.run(identity)
    assert not api.containers and api.image_config is None
    assert not any(path == "/containers/create" for _, path in api.calls)

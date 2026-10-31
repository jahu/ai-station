"""No image downloads or runtime mutation; normal tests use synthetic inspection."""

import json

import pytest
from ai_station_runner import llama_runtime, runtime_setup
from fastapi import HTTPException


def selection():
    return runtime_setup.RuntimeSelection(profile="llamacpp-cuda-linux-amd64-v1")


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(runtime_setup.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runtime_setup.platform, "machine", lambda: "x86_64")


def observed():
    return {
        "Os": "linux",
        "Architecture": "amd64",
        "Id": "sha256:" + "a" * 64,
        "RepoDigests": [runtime_setup.REFERENCE],
    }


def test_only_fixed_read_only_inspection_is_used_and_presence_is_not_runtime_readiness(linux, monkeypatch):
    calls = []

    def inspect(*args, **kwargs):
        calls.append((args, kwargs))
        return json.dumps(observed())

    monkeypatch.setattr(llama_runtime, "docker", inspect)
    result = runtime_setup.inspect_image(selection())
    assert result["image"] == {"status": "available", "present": True, "id": observed()["Id"]}
    assert result["platform_supported"]
    assert not result["installation_available"] and not result["inference_tested_now"]
    assert calls == [
        (("image", "inspect", runtime_setup.REFERENCE, "--format", "{{json .}}"), {"missing_ok": True})
    ]
    assert result["manifest_sha256"] == runtime_setup.fingerprint(result["recipe"])


@pytest.mark.parametrize(
    "change",
    [
        {"profile": "arbitrary"},
        {"url": "https://example.com"},
        {"command": "docker pull anything"},
        {"image_reference": "private/image:latest"},
    ],
)
def test_callers_cannot_select_images_urls_or_commands(change):
    with pytest.raises(ValueError):
        runtime_setup.RuntimeSelection.model_validate({"profile": "llamacpp-cuda-linux-amd64-v1", **change})


@pytest.mark.parametrize(
    "change",
    [
        {"Os": "windows"},
        {"Architecture": "arm64"},
        {"Id": "sha256:wrong"},
        {"RepoDigests": []},
        {"RepoDigests": None},
    ],
)
def test_mismatched_or_unconfirmed_local_identity_is_never_available(linux, monkeypatch, change):
    monkeypatch.setattr(llama_runtime, "docker", lambda *args, **kwargs: json.dumps({**observed(), **change}))
    assert runtime_setup.inspect_image(selection())["image"]["status"] == "unknown"


def test_missing_image_is_distinct_from_an_unreachable_daemon(linux, monkeypatch):
    monkeypatch.setattr(llama_runtime, "docker", lambda *args, **kwargs: None)
    assert runtime_setup.inspect_image(selection())["image"]["status"] == "unavailable"

    def unreachable(*args, **kwargs):
        raise HTTPException(503, "Synthetic Docker failure")

    monkeypatch.setattr(llama_runtime, "docker", unreachable)
    assert runtime_setup.inspect_image(selection())["image"]["status"] == "unknown"


@pytest.mark.parametrize("system,machine", [("Darwin", "arm64"), ("Windows", "AMD64"), ("Linux", "aarch64")])
def test_other_platforms_do_not_inherit_a_cuda_qualification(linux, monkeypatch, system, machine):
    monkeypatch.setattr(runtime_setup.platform, "system", lambda: system)
    monkeypatch.setattr(runtime_setup.platform, "machine", lambda: machine)
    monkeypatch.setattr(
        llama_runtime,
        "docker",
        lambda *args, **kwargs: pytest.fail("No Docker operation on an unsupported profile"),
    )
    result = runtime_setup.inspect_image(selection())
    assert not result["platform_supported"] and not result["image"]["present"]


@pytest.mark.parametrize("owned,present", [(False, False), (True, True), (True, False)])
def test_configured_images_are_preserved_and_only_owned_models_use_a_prepared_pin(
    monkeypatch, owned, present
):
    from ai_station_runner.config import Settings, clear_settings_cache

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("AI_STATION_LLAMA_IMAGE", "operator/configured:reviewed")
    clear_settings_cache()
    calls = []

    def inspect(*args, **kwargs):
        calls.append(args)
        return "sha256:" + "a" * 64 if present else None

    monkeypatch.setattr(llama_runtime, "docker", inspect)
    monkeypatch.setattr(runtime_setup, "inspect_image", lambda _: {"image": {"present": True}})
    try:
        result = runtime_setup.image_reference(app_owned=owned)
        assert result == (
            runtime_setup.REFERENCE if owned and not present else "operator/configured:reviewed"
        )
        assert len(calls) == int(owned)
        assert all(call[:2] == ("image", "inspect") for call in calls)
    finally:
        clear_settings_cache()


def test_prepared_pin_also_serves_discovered_models_with_a_missing_default_image(monkeypatch):
    from ai_station_runner.config import Settings, clear_settings_cache

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("AI_STATION_LLAMA_IMAGE", "ghcr.io/ggml-org/llama.cpp:server-cuda")
    clear_settings_cache()
    monkeypatch.setattr(llama_runtime, "docker", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime_setup, "inspect_image", lambda _: {"image": {"present": True}})
    try:
        assert runtime_setup.image_reference(app_owned=False) == runtime_setup.REFERENCE
    finally:
        clear_settings_cache()

"""Image catalog/preparation stays unavailable until real inference qualifies."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from ai_station_runner import (
    image_setup,
    managed_image_job,
    runtime_install,
    runtime_install_job,
    runtime_setup,
)
from fastapi import HTTPException
from test_runtime_install import setup as setup


def request():
    frozen = image_setup.recipe()
    return runtime_install.Prepare(
        profile=managed_image_job.PROFILE,
        run_id=uuid4(),
        manifest_sha256=runtime_setup.fingerprint(frozen),
        deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        permissions=sorted(runtime_install.PERMISSIONS),
    )


def test_qualification_toggle_does_not_change_sources_or_parent_child_fingerprints(monkeypatch):
    first = image_setup.recipe()
    monkeypatch.setattr(managed_image_job, "QUALIFIED", not managed_image_job.QUALIFIED)
    assert image_setup.recipe() == first
    assert runtime_setup.recipe(runtime_setup.RuntimeSelection(profile=managed_image_job.PROFILE)) == first
    assert len(first["inputs"]) == 5 and all(v["kind"] == "model" for v in first["inputs"])
    assert first["model_manifest_sha256"] == managed_image_job.fingerprint(managed_image_job.recipe())


def test_unqualified_profile_cannot_start_native_transfer_even_with_correct_manifest(setup, monkeypatch):
    monkeypatch.setattr(managed_image_job, "QUALIFIED", False)
    with pytest.raises(HTTPException) as error:
        runtime_install.prepare(request())
    assert error.value.status_code == 409
    assert not setup.state["starts"] and not setup.state["calls"]


def test_native_pull_child_uses_identical_frozen_source_after_parent_qualification_override(
    setup, monkeypatch
):
    monkeypatch.setattr(managed_image_job, "QUALIFIED", True)
    frozen = image_setup.recipe()
    setup.frozen.clear()
    setup.frozen.update(frozen)
    setup.image["RepoDigests"] = [frozen["image_reference"]]
    body = request()
    result = runtime_install.prepare(body)
    assert result["alive"] and len(setup.state["starts"]) == 1
    monkeypatch.setattr(managed_image_job, "QUALIFIED", False)
    # Equivalent to a fresh child importing the real recipe rather than the
    # parent's temporary qualification policy: source fingerprints stay stable.
    assert runtime_install_job.run(str(body.run_id)) == 0
    setup.state["processes"][str(body.run_id)].update(alive=False, status="exited", exit_code=0)
    result = runtime_install.snapshot(str(body.run_id), runtime_install.read(body.run_id))
    assert result["status"] == "succeeded" and result["image"]["reference"] == frozen["image_reference"]
    assert len(setup.state["starts"]) == 1


@pytest.fixture
def catalog(setup, monkeypatch):
    settings = SimpleNamespace(host_data_dir=lambda: setup.root, photo_python="", photo_script="")
    monkeypatch.setattr(image_setup, "get_settings", lambda: settings)
    monkeypatch.setattr(
        image_setup,
        "collect",
        lambda _: {
            "gpus": [{"index": index, "memory_total_mib": 12288} for index in (7, 9)],
            "memory": {"total_mib": 32768},
        },
    )
    monkeypatch.setattr(runtime_install, "inspect_image", lambda *args: None)
    return settings


def test_viewing_the_catalog_does_not_download_or_enable_the_candidate(setup, catalog, monkeypatch):
    monkeypatch.setattr(managed_image_job, "QUALIFIED", False)
    result = image_setup.catalog()
    assert not result["installation_available"] and "qualified" in result["installation_notice"]
    assert not result["existing_images"]["available"] and not result["image_inference_tested_now"]
    assert not setup.state["starts"]


def test_two_gpu_candidate_does_not_promise_readiness_on_a_single_gpu(setup, catalog, monkeypatch):
    monkeypatch.setattr(managed_image_job, "QUALIFIED", True)
    monkeypatch.setattr(image_setup, "collect", lambda _: {"gpus": [{"index": 7, "memory_total_mib": 12288}]})
    result = image_setup.catalog()
    assert not result["installation_available"] and not result["existing_images"]["available"]
    assert not setup.state["starts"]


@pytest.mark.parametrize("qualified", [False, True])
def test_existing_configured_pipeline_keeps_priority(setup, catalog, monkeypatch, qualified):
    monkeypatch.setattr(managed_image_job, "QUALIFIED", qualified)
    python = setup.root / "configured-python"
    python.write_text("fixture")
    python.chmod(0o700)
    script = setup.root / "configured-photo.py"
    script.write_text("# fixture")
    catalog.photo_python, catalog.photo_script = str(python), str(script)
    result = image_setup.catalog()
    assert result["existing_images"] == {"source": "configured", "available": True}
    assert result["installation_available"] is qualified


def test_partial_external_configuration_does_not_silently_choose_managed(setup, catalog):
    catalog.photo_script = "/configured/missing.py"
    result = image_setup.catalog()
    assert result["existing_images"] == {"source": "configured", "available": False}


def test_bad_docker_or_insufficient_storage_is_not_presented_as_ready(setup, catalog, monkeypatch):
    monkeypatch.setattr(managed_image_job, "QUALIFIED", True)

    def missing():
        raise HTTPException(503, "fixture unavailable")

    monkeypatch.setattr(runtime_install, "daemon", missing)
    result = image_setup.catalog()
    assert not result["installation_available"] and "Docker storage" in result["installation_notice"]

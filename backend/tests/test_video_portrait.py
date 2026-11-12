"""Native portrait is finite, advertised, and retains existing managed budgets."""

import pytest
from app.video import managed_parameters, memory_reservation
from app.video_schema import VideoRequest
from fastapi import HTTPException
from pydantic import ValidationError


def profile(portrait=True, managed=False):
    return {
        "available": True,
        "configuration_source": "managed" if managed else "configured",
        "managed_runtime": {
            "profile": "wan22-5b-linux-x86-64-python312-v1",
            "manifest_sha256": "a" * 64,
            "environment_id": "b" * 64,
        },
        "eligible_gpu_indices": [7],
        "memory_profiles": [
            {
                "id": "bounded_11g",
                "available": True,
                "ram_mib": 11264,
                "resolutions": [{"width": 704, "height": 1280}] if portrait else [],
            }
        ],
    }


@pytest.mark.parametrize("managed", [False, True])
def test_portrait_requires_matching_runner_advertisement_and_keeps_memory_bound(managed):
    body = VideoRequest(
        prompt="A clear vertical composition", memory_profile="bounded_11g", width=704, height=1280
    )
    assert memory_reservation(body, profile(managed=managed)) == 11264
    with pytest.raises(HTTPException, match="advertise native portrait"):
        memory_reservation(body, profile(portrait=False, managed=managed))
    if managed:
        assert managed_parameters(body, profile(managed=True))["memory_profile"] == "bounded_11g"
        with pytest.raises(HTTPException, match="GPU compatible"):
            managed_parameters(body.model_copy(update={"gpu": "0"}), profile(managed=True))


def test_legacy_landscape_does_not_require_new_metadata_and_square_stays_unqualified():
    body = VideoRequest(prompt="Landscape", memory_profile="bounded_11g")
    assert memory_reservation(body, profile(portrait=False)) == 11264
    with pytest.raises(ValidationError):
        VideoRequest(prompt="Square", memory_profile="bounded_11g", width=768, height=768)

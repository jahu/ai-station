"""Whole publisher identity and hardware estimates, never real transfers."""

from copy import deepcopy

import pytest
from app.gguf_bindings import OwnedBundle, checked_proof, fitted_context
from app.hub_model_parts import annotate
from app.hub_split_candidates import HubSplitCandidate, candidate_from_profile, recommendation
from app.model_setup import fingerprint
from pydantic import ValidationError
from test_model_variant_advice import source

GiB = 1024**3


def observation(size=4 * GiB):
    report = source()
    report["files"] = [
        {
            "filename": f"Q4/Coder.Q4_K_M-{index:05d}-of-00002.gguf",
            "format": "gguf",
            "sha256": str(index) * 64,
            "size_bytes": size,
            "identity_available": True,
        }
        for index in (1, 2)
    ]
    report["model_bundles"] = annotate(report["files"])
    return report


def candidate(report=None, index=0):
    report = observation() if report is None else report
    return candidate_from_profile(report, report["files"][index]["filename"], report["language_profile"])


def hardware(*sizes):
    return {
        "host": {"system": "Linux"},
        "memory": {"total_mib": 32768},
        "gpus": [{"index": index + 3, "memory_total_mib": size} for index, size in enumerate(sizes)],
    }


def test_nonfirst_link_freezes_all_parts_and_preserves_physical_primary_size():
    report = observation()
    expected = candidate(report)
    report["files"] = report["files"][1:]
    entry = candidate(report)
    assert entry == expected and entry.filename.endswith("00001-of-00002.gguf")
    assert entry.total_size_bytes == 8 * GiB and entry.file.size_bytes == 4 * GiB
    assert entry.origin == "hub_split" and entry.id.startswith("hub-bundle-")
    assert HubSplitCandidate.model_validate(entry.model_dump(mode="json")) == entry


@pytest.mark.parametrize("change", ["missing", "order", "alias", "revision", "source", "primary", "extra"])
def test_tampered_or_incomplete_coordinates_refuse(change):
    payload = candidate().model_dump(mode="json")
    if change == "missing":
        payload["parts"].pop()
    elif change == "order":
        payload["parts"].reverse()
    elif change == "alias":
        payload["parts"][1]["file"]["sha256"] = payload["file"]["sha256"]
    elif change == "revision":
        payload["parts"][1]["file"]["urls"][0] = payload["parts"][1]["file"]["urls"][0].replace(
            "a" * 40, "e" * 40
        )
    elif change == "source":
        payload["parts"][1]["file"]["urls"][0] = "https://example.com/model.gguf"
    elif change == "primary":
        payload["file"]["size_bytes"] += 1
    else:
        payload["parts"][1]["command"] = "shell"
    # Recomputing a recipe identity cannot make a malformed part set valid.
    payload["id"] = "hub-bundle-" + fingerprint(payload["parts"])[:24]
    with pytest.raises(ValidationError):
        HubSplitCandidate.model_validate(payload)


def test_snapshot_group_and_profile_must_match():
    report = observation()
    for change in ["size", "total", "profile", "pipeline"]:
        changed = deepcopy(report)
        if change == "size":
            changed["model_bundles"][0]["parts"][1]["size_bytes"] += 1
        elif change == "total":
            changed["model_bundles"][0]["total_size_bytes"] = 1
        elif change == "profile":
            changed["language_profile"]["source_revision"] = "f" * 40
        else:
            changed["pipeline_hint"] = "text-to-image"
        with pytest.raises(ValueError):
            candidate(changed)


def test_hardware_estimate_uses_complete_weights_and_individual_gpu_capacity():
    entry = candidate(observation(8 * GiB))
    assert not recommendation(entry, hardware(12288))["fits"]
    # Pooled capacity is large, but the second device cannot hold its equal share.
    assert not recommendation(entry, hardware(16384, 2048))["fits"]
    fitted = recommendation(candidate(), hardware(12288, 12288))
    assert fitted["fits"] and fitted["context_size"] >= 4096
    assert fitted["cache_type"] == "q8_0"
    assert not recommendation(entry, {**hardware(24576), "memory": {"total_mib": 4096}})["fits"]


def test_missing_hardware_sensors_stay_unknown_and_graphics_setup_is_explicit():
    from app.hub_split_candidates import assessment

    entry = candidate()
    for machine in [{}, {"memory": {"total_mib": 32768}, "gpus": [{"index": 3}]}]:
        assert (
            assessment(entry, machine, {"free_bytes": 100 * GiB, "headroom_bytes": GiB})["hardware_status"]
            == "unknown"
        )
    waiting = recommendation(entry, {**hardware(12288), "container_gpu_ready": False})
    assert not waiting["fits"] and "Graphics setup" in waiting["reason"]


def test_frozen_owned_binding_proof_covers_the_entire_part_set():
    bundle = OwnedBundle(
        parts=[{"sha256": str(index) * 64, "size_bytes": index * 100, "mtime": 123.0} for index in (1, 2)]
    )
    proof = {
        "kind": "gguf_split",
        "bundle_id": fingerprint(bundle.model_dump(mode="json")),
        "part_count": 2,
        "size_bytes": 300,
        "structurally_verified": True,
    }
    assert checked_proof(bundle, proof) == proof
    with pytest.raises(ValueError):
        checked_proof(bundle, {**proof, "size_bytes": 100})
    changed = bundle.model_dump(mode="json")
    changed["parts"][1]["sha256"] = "f" * 64
    with pytest.raises(ValueError):
        checked_proof(OwnedBundle.model_validate(changed), proof)


def test_context_fit_uses_exact_native_placement_and_full_kv_on_each_gpu():
    proof = {
        "size_bytes": 16 * GiB,
        "largest_layer_bytes": GiB,
        "shared_tensor_bytes": GiB,
        "context_profile": {"state_reserve_mib": 0, "trained_context": 32768, "q8_kv_bytes_per_token": 65536},
    }
    assert fitted_context(proof, [12288, 12288], 131072) == 16384
    assert fitted_context(proof, [12288, 4096], 131072) < 4096
    with pytest.raises(ValueError):
        fitted_context(proof, [float("nan")], 32768)

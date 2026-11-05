"""Recommendations compare supported geometry, useful context and actual resources."""

from copy import deepcopy

import pytest
from app.hub_candidates import LanguageProfile
from app.model_variant_advice import assess_variant, rank_variants


def test_an_optional_onnx_file_does_not_hide_supported_language_variants(monkeypatch):
    import asyncio

    from app import hub_embedding_candidates, model_variant_advice
    from app.hub_candidates import LanguageProfile

    report = source()
    profile = LanguageProfile.model_validate(report.pop("language_profile"))
    report.update(architecture_hint="qwen3", pipeline_hint="text-generation", base_models=[])
    report["files"].append({"filename": "optional.onnx", "format": "onnx"})

    async def unrelated(*args):
        raise ValueError("Not an E5 encoder")

    async def language(*args):
        return profile

    monkeypatch.setattr(hub_embedding_candidates, "resolve_profile", unrelated)
    monkeypatch.setattr(model_variant_advice, "resolve_profile", language)
    asyncio.run(model_variant_advice.enrich_source(report, lambda: None))
    assert report["language_profile"] == profile.model_dump(mode="json")
    assert "requirements_error" not in report


GiB = 1024**3


def source():
    repository, revision = "publisher/new-model", "a" * 40
    return {
        "repository": repository,
        "revision": revision,
        "license": "apache-2.0",
        "source_url": f"https://huggingface.co/{repository}/tree/{revision}",
        "license_url": f"https://huggingface.co/{repository}/blob/{revision}/README.md",
        "language_profile": LanguageProfile(
            source_repository=repository,
            source_revision=revision,
            configuration_repository="publisher/base",
            configuration_revision="c" * 40,
            configuration_sha256="d" * 64,
            config_url="https://huggingface.co/publisher/base/resolve/" + "c" * 40 + "/config.json",
            architecture="qwen3",
            trained_context=131072,
            attention_layers=36,
            kv_heads=8,
            key_length=128,
            value_length=128,
            state_reserve_mib=0,
        ).model_dump(mode="json"),
        "files": [
            {
                "filename": f"new-model.{quant}.gguf",
                "format": "gguf",
                "identity_available": True,
                "size_bytes": size * GiB,
                "sha256": str(index) * 64,
                "source_url": f"https://huggingface.co/{repository}/resolve/{revision}/new-model.{quant}.gguf",
            }
            for index, (quant, size) in enumerate((("Q8_0", 10), ("Q6_K", 8), ("Q4_K_M", 5), ("Q2_K", 3)), 1)
        ],
    }


def assess(report, *, gpus=2, storage=None, context_target=32768):
    hardware = {
        "memory": {"total_mib": 65536},
        "gpus": [
            {"index": 7 + i * 12, "memory_total_mib": 12288, "memory_used_mib": 8192} for i in range(gpus)
        ],
    }
    storage = {"free_bytes": 100 * GiB, "headroom_bytes": GiB} if storage is None else storage
    for file in report["files"]:
        file["assessment"] = assess_variant(file, report, hardware, storage, context_target=context_target)
    rank_variants(report, context_target=context_target)
    return report["files"]


def test_new_variants_share_geometry_and_keep_useful_context_ahead_of_size():
    files = assess(source())
    recommended = [file for file in files if file["assessment"]["variant_advice"]["recommended"]]
    assert len(recommended) == 1
    choice = recommended[0]
    assert choice["filename"].endswith("Q4_K_M.gguf")
    plan = choice["assessment"]["profiles"][0]
    assert plan["recommendation"]["gpus"] == [7]
    assert plan["recommendation"]["context_size"] == 32768
    assert plan["occupancy"] == "in_use" and not plan["locally_qualified"]
    # Q6 needs a GPU pair for the requested cache, even though its weights fit one GPU.
    q6 = next(f for f in files if f["filename"].endswith("Q6_K.gguf"))
    assert q6["assessment"]["profiles"][0]["recommendation"]["gpus"] == [7, 19]


def test_long_context_target_is_not_claimed_when_only_short_cache_fits():
    files = assess(source(), gpus=1, context_target=131072)
    assert not any(f["assessment"]["variant_advice"]["recommended"] for f in files)
    assert all(not f["assessment"]["variant_advice"]["meets_context_target"] for f in files)


@pytest.mark.parametrize("storage", [{}, {"free_bytes": 100, "headroom_bytes": GiB}])
def test_unknown_or_insufficient_disk_never_earns_a_recommendation(storage):
    files = assess(source(), storage=storage)
    assert not any(f["assessment"]["variant_advice"]["recommended"] for f in files)


def test_missing_gpu_or_unknown_recipe_is_not_a_fit():
    report = source()
    files = assess(report, gpus=0)
    assert all(f["assessment"]["hardware_status"] == "not_recommended" for f in files)
    del report["language_profile"]
    files = assess(report)
    assert all(f["assessment"]["hardware_status"] == "unknown" for f in files)
    assert not any(f["assessment"]["variant_advice"]["recommended"] for f in files)


def test_low_bit_one_gpu_does_not_beat_useful_balanced_two_gpu_profile():
    report = source()
    report["files"] = [f for f in report["files"] if not f["filename"].endswith("Q4_K_M.gguf")]
    files = assess(report)
    assert files[0]["filename"].endswith("Q6_K.gguf")
    assert files[0]["assessment"]["variant_advice"]["recommended"]
    q2 = next(f for f in files if f["filename"].endswith("Q2_K.gguf"))
    assert q2["assessment"]["variant_advice"]["precision_tradeoff"]


def test_supported_config_does_not_admit_projector_or_incomplete_shards():
    report = source()
    for filename in ("mmproj.gguf", "model-00001-of-00002.gguf"):
        file = deepcopy(report["files"][0])
        file["filename"] = filename
        assert not assess_variant(file, report, {}, {})["profiles"]


@pytest.mark.parametrize("bad_capacity", [None, False, float("nan"), -1])
def test_invalid_native_telemetry_remains_unknown_not_zero_or_free(bad_capacity):
    report = source()
    file = report["files"][0]
    result = assess_variant(
        file,
        report,
        {
            "memory": {"total_mib": 65536},
            "gpus": [{"index": 7, "memory_total_mib": bad_capacity}],
        },
        {"free_bytes": 100 * GiB, "headroom_bytes": GiB},
    )
    assert result["hardware_status"] == "unknown"
    assert result["profiles"][0]["fit"] == "unknown"
    assert not result["profiles"][0]["recommendation"]["fits"]


def test_source_advice_does_not_recommend_unequal_gpus_as_pooled_vram():
    report = source()
    file = report["files"][0]
    file["size_bytes"] = 15698534208
    report["files"] = [file]
    hardware = {
        "memory": {"total_mib": 32768},
        "gpus": [
            {"index": 3, "memory_total_mib": 16384},
            {"index": 8, "memory_total_mib": 8192},
        ],
    }
    file["assessment"] = assess_variant(
        file, report, hardware, {"free_bytes": 100 * GiB, "headroom_bytes": GiB}
    )
    rank_variants(report)
    assert file["assessment"]["hardware_status"] == "not_recommended"
    assert not file["assessment"]["variant_advice"]["recommended"]
    assert not file["assessment"]["profiles"][0]["recommendation"]["fits"]

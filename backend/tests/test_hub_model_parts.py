"""Complete declared part sets inform storage; no fragment gains execution authority."""

import copy

import pytest
from app import hub_model_parts, hub_sources
from app.hub_candidates import candidate_from_profile, resolve_candidate
from app.model_variant_advice import assess_variant, rank_variants
from test_hub_sources import document
from test_model_variant_advice import source as language_source

GiB = 1024**3


def part(index, *, count=2, prefix="Q4/Coder.Q4_K_M", size=8 * GiB, sha=None):
    return {
        "rfilename": f"{prefix}-{index:05d}-of-{count:05d}.gguf",
        "size": size,
        "lfs": {"size": size, "sha256": sha or f"{index:064x}"},
    }


async def inspect(monkeypatch, rows, filename=None):
    calls = []

    async def metadata(url, check):
        calls.append(url)
        check()
        return document(id="publisher/new-model", siblings=rows)

    monkeypatch.setattr(hub_sources, "metadata_json", metadata)
    source = (
        "publisher/new-model"
        if filename is None
        else "https://huggingface.co/publisher/new-model/blob/main/" + filename
    )
    report = await hub_sources.inspect_source(hub_sources.parse_source(source), lambda: None)
    assert len(calls) == 1 and "/api/models/" in calls[0]
    return report


@pytest.mark.asyncio
async def test_nonfirst_part_link_captures_all_required_identities_from_same_revision(monkeypatch):
    rows = [part(2), part(1), part(1, prefix="other/Coder.Q4_K_M"), part(1, prefix="Q6/Coder.Q6_K")]
    report = await inspect(monkeypatch, rows, rows[0]["rfilename"])
    assert len(report["files"]) == len(report["model_bundles"]) == 1
    selected = report["files"][0]
    bundle = hub_model_parts.for_file(report, selected)
    assert selected["filename"] == rows[0]["rfilename"]
    assert bundle["status"] == "complete_metadata" and bundle["total_size_bytes"] == 16 * GiB
    assert [p["index"] for p in bundle["parts"]] == [1, 2]
    assert not bundle["native_verified"] and not bundle["installation_available"]
    again = await inspect(monkeypatch, list(reversed(rows)), rows[0]["rfilename"])
    assert again["model_bundles"] == report["model_bundles"]


@pytest.mark.asyncio
async def test_full_model_size_not_fragment_drives_disk_and_never_creates_a_runtime_recommendation(
    monkeypatch,
):
    report = await inspect(monkeypatch, [part(1), part(2)])
    report["language_profile"] = language_source()["language_profile"]
    hardware = {
        "memory": {"total_mib": 32768},
        "gpus": [{"index": 7, "memory_total_mib": 12288, "memory_used_mib": 0}],
    }
    for file in report["files"]:
        file["assessment"] = assess_variant(
            file, report, hardware, {"free_bytes": 10 * GiB, "headroom_bytes": GiB}
        )
        assert file["assessment"]["disk"]["model_bundle_bytes"] == 16 * GiB
        assert file["assessment"]["disk"]["status"] == "insufficient"
        assert file["assessment"]["hardware_status"] == "unknown" and not file["assessment"]["profiles"]
        with pytest.raises(ValueError, match="split GGUFs"):
            candidate_from_profile(report, file["filename"], report["language_profile"])
    rank_variants(report)
    assert not any(file["assessment"]["variant_advice"]["recommended"] for file in report["files"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows,status,missing",
    [
        ([part(1, count=3), part(3, count=3)], "missing_parts", [2]),
        ([part(0), part(1)], "invalid_parts", [2]),
        ([part(1), part(2, sha=f"{1:064x}")], "unverified_identities", []),
        ([part(1), part(2, sha="not-a-hash")], "unverified_identities", []),
        ([part(1, count=99999)], "unsupported_part_count", []),
        ([part(1), part(2), part(1, count=3)], "conflicting_counts", []),
    ],
)
async def test_incomplete_or_conflicting_groups_never_claim_total_size_or_fit(
    monkeypatch, rows, status, missing
):
    report = await inspect(monkeypatch, rows, rows[0]["rfilename"])
    bundle = report["model_bundles"][0]
    assert bundle["status"] == status and bundle["total_size_bytes"] is None
    assert bundle["missing_parts"] == missing
    assessment = assess_variant(
        report["files"][0], report, {"gpus": []}, {"free_bytes": 1000 * GiB, "headroom_bytes": GiB}
    )
    assert assessment["disk"]["status"] == assessment["hardware_status"] == "unknown"
    assert not assessment["profiles"]
    assert len(bundle["parts"]) <= 64


@pytest.mark.asyncio
async def test_quantizations_and_directories_keep_independent_complete_groups(monkeypatch):
    report = await inspect(
        monkeypatch,
        [
            part(1),
            part(2),
            part(1, prefix="Q6/Coder.Q6_K"),
            part(2, prefix="Q6/Coder.Q6_K"),
            part(1, prefix="other/Coder.Q4_K_M"),
        ],
    )
    assert len(report["model_bundles"]) == 3
    assert sorted(b["status"] for b in report["model_bundles"]) == [
        "complete_metadata",
        "complete_metadata",
        "missing_parts",
    ]
    assert len({f["bundle_id"] for f in report["files"]}) == 3


@pytest.mark.asyncio
async def test_single_file_observation_is_unchanged_and_missing_selected_part_still_refuses(monkeypatch):
    normal = document()["siblings"]
    report = await inspect(monkeypatch, [*normal, part(1), part(2)], "weights.gguf")
    assert "model_bundles" not in report and "bundle_id" not in report["files"][0]
    assert len(report["files"]) == 1
    with pytest.raises(ValueError, match="absent"):
        await inspect(monkeypatch, [part(1)], part(2)["rfilename"])
    rows = [part(1), copy.deepcopy(part(1))]
    with pytest.raises(ValueError, match="Ambiguous"):
        await inspect(monkeypatch, rows)


@pytest.mark.asyncio
async def test_split_media_profile_cannot_bypass_complete_bundle_refusal(monkeypatch):
    from app import hub_image_candidates

    rows = [part(1), part(2)]
    report = await inspect(monkeypatch, rows)
    report["image_profile"] = {"unreviewed": True}
    monkeypatch.setattr(
        hub_image_candidates,
        "candidate_from_profile",
        lambda *a: pytest.fail("No media candidate may admit a fragment"),
    )
    with pytest.raises(ValueError, match="complete compatible bundle plan"):
        await resolve_candidate(report, rows[0]["rfilename"], lambda: None)

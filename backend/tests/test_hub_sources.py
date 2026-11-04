"""Public metadata discovery uses fake responses, never real model weights."""

from contextlib import asynccontextmanager

import httpx
import pytest
from app import hub_sources as hub
from app.model_hardware import assess_file
from app.setup_models import CANDIDATES


@pytest.mark.parametrize(
    "link",
    [
        "publisher/model",
        "https://huggingface.co/publisher/model",
        "https://huggingface.co/publisher/model/tree/main",
        "https://huggingface.co/publisher/model/blob/main/sub/model-Q4.gguf",
        "https://huggingface.co/publisher/model/resolve/main/model.gguf?download=true",
    ],
)
def test_public_repository_and_file_links(link):
    source = hub.parse_source(link)
    assert source.repository == "publisher/model" and source.revision == "main"


@pytest.mark.parametrize(
    "link",
    [
        "http://huggingface.co/a/b",
        "https://127.0.0.1/a/b",
        "https://huggingface.co.evil/a/b",
        "https://user:pass@huggingface.co/a/b",
        "https://huggingface.co:443/a/b",
        "https://huggingface.co/a/b?token=secret",
        "https://huggingface.co/a/b#x",
        "https://huggingface.co/a/b/resolve/main/../private.gguf",
        "https://huggingface.co/a/b/resolve/main/%2e%2e/private.gguf",
        "https://huggingface.co/a/b/resolve/main/a%2fb.gguf",
        "https://huggingface.co/a/b/resolve/main/a%252fb.gguf",
        "https://huggingface.co/a/b/blob/main/%00bad.gguf",
        "https://huggingface.co/a/b/blob/main/a\\b.gguf",
        "https://huggingface.co/a/b/resolve/main",
        "https://huggingface.co/a/b/tree/main/sub",
        "a/b/c",
        "a/..",
        "https://huggingface.co/a/b\n",
    ],
)
def test_no_arbitrary_host_credentials_paths_or_tokens(link):
    with pytest.raises(ValueError):
        hub.parse_source(link)


def document(**updates):
    return {
        "id": "publisher/model",
        "sha": "a" * 40,
        "private": False,
        "siblings": [{"rfilename": "weights.gguf", "size": 100, "lfs": {"size": 100, "sha256": "b" * 64}}],
        "cardData": {"license": "apache-2.0"},
        **updates,
    }


@pytest.mark.asyncio
async def test_freezes_commit_and_sha_without_fetching_weights(monkeypatch):
    calls = []

    async def metadata(url, check):
        calls.append(url)
        check()
        return document()

    monkeypatch.setattr(hub, "metadata_json", metadata)
    report = await hub.inspect_source(hub.parse_source("publisher/model"), lambda: None)
    assert len(calls) == 1 and "/api/models/" in calls[0]
    assert report["revision"] == "a" * 40 and report["files"][0]["sha256"] == "b" * 64
    assert "/resolve/" + "a" * 40 in report["files"][0]["source_url"]
    assert report["metadata_only"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"id": "different/repo"},
        {"sha": "main"},
        {"private": True},
        {"siblings": [{}]},
        {"siblings": [{"rfilename": "../bad.gguf"}]},
        {"siblings": [{"rfilename": "weights.gguf"}] * 2},
        {"siblings": []},
    ],
)
async def test_rejects_wrong_identity_unsafe_files_duplicates_and_missing_selected(monkeypatch, change):
    async def metadata(*args):
        return document(**change)

    monkeypatch.setattr(hub, "metadata_json", metadata)
    with pytest.raises(ValueError):
        await hub.inspect_source(
            hub.parse_source("https://huggingface.co/publisher/model/blob/main/weights.gguf"), lambda: None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lfs",
    [
        {},
        {"size": 100, "sha256": "bad"},
        {"size": True, "sha256": "b" * 64},
        {"size": 101, "sha256": "b" * 64},
    ],
)
async def test_absent_or_inconsistent_hash_never_authorizes_install(monkeypatch, lfs):
    async def metadata(*args):
        return document(siblings=[{"rfilename": "weights.gguf", "size": 100, "lfs": lfs}])

    monkeypatch.setattr(hub, "metadata_json", metadata)
    report = await hub.inspect_source(hub.parse_source("publisher/model"), lambda: None)
    assert report["files"][0]["sha256"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body,headers",
    [
        (401, b"{}", {}),
        (403, b"{}", {}),
        (404, b"{}", {}),
        (429, b"{}", {}),
        (200, b"not json", {}),
        (200, b"{}", {"content-encoding": "gzip"}),
        (200, b"{}", {"content-length": str(hub.MAX_BYTES + 1)}),
        (200, b" " * (hub.MAX_BYTES + 1), {}),
    ],
)
async def test_metadata_is_bounded_and_access_errors_actionable(monkeypatch, status, body, headers):
    @asynccontextmanager
    async def response(url, offset, check):
        check()
        yield httpx.Response(
            status, headers=headers, stream=httpx.ByteStream(body), request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(hub, "response", response)
    with pytest.raises(ValueError):
        await hub.metadata_json("https://huggingface.co/api/models/publisher/model", lambda: None)


def station(*totals):
    return {
        "memory": {"total_mib": 65536},
        "gpus": [
            {"index": 7 + i * 3, "memory_total_mib": n, "memory_used_mib": 0} for i, n in enumerate(totals)
        ],
    }


def test_unknown_image_gguf_does_not_inherit_llm_or_pooled_gpu_capacity():
    file = {"size_bytes": 18 * 1024**3, "format": "gguf", "sha256": "a" * 64, "identity_available": True}
    report = assess_file(
        file, station(12288, 12288), {"free_bytes": 100 * 1024**3, "headroom_bytes": 256 * 1024**2}
    )
    assert report["hardware_status"] == "unknown" and not report["profiles"]
    assert report["runtime_status"] == "needs_compatible_recipe"
    assert report["disk"]["status"] == "file_fits"
    assert report["automatic_ram_offload"] is report["automatic_cloud_fallback"] is False


def test_exact_llm_identity_reuses_existing_fitter_and_reports_busy_separately():
    entry = CANDIDATES[0]
    file = {"size_bytes": entry.file.size_bytes, "sha256": entry.file.sha256, "identity_available": True}
    hardware = station(12288)
    hardware["gpus"][0]["memory_used_mib"] = 8000
    report = assess_file(file, hardware, None)
    gpu = next(p for p in report["profiles"] if p["recommendation"].get("gpus"))
    assert gpu["fit"] == "estimated_fit" and gpu["occupancy"] == "in_use"
    assert gpu["recommendation"]["gpus"] == [7]
    assert gpu["recommendation"]["context_size"] >= 4096
    assert not gpu["locally_qualified"] and report["disk"]["status"] == "unknown"


@pytest.mark.parametrize("free", [None, float("nan"), True, -1])
def test_missing_or_invalid_storage_never_looks_free(free):
    assert (
        assess_file({"size_bytes": 100}, {}, {"free_bytes": free, "headroom_bytes": 1})["disk"]["status"]
        == "unknown"
    )


def test_linux_recommendations_do_not_offer_mac_only_runtime_profiles():
    entry = CANDIDATES[0]
    report = assess_file(
        {"size_bytes": entry.file.size_bytes, "sha256": entry.file.sha256, "identity_available": True},
        {**station(12288), "host": {"system": "Linux"}},
        None,
    )
    assert report["profiles"]
    assert all("darwin" not in (p["recommendation"].get("runtime_profile") or "") for p in report["profiles"])


def test_disk_headroom_included_and_empty_gpu_hardware_not_a_gpu_fit():
    entry = CANDIDATES[0]
    file = {"size_bytes": entry.file.size_bytes, "sha256": entry.file.sha256, "identity_available": True}
    report = assess_file(
        file, station(), {"free_bytes": entry.file.size_bytes, "headroom_bytes": 256 * 1024**2}
    )
    assert report["disk"]["status"] == "insufficient"
    assert all(not p["recommendation"].get("gpus") for p in report["profiles"] if p["fit"] == "estimated_fit")


@pytest.mark.asyncio
async def test_search_is_bounded_and_does_not_treat_popularity_as_compatibility(monkeypatch):
    calls = []

    async def metadata(url, check):
        calls.append(url)
        return [{"id": "publisher/model", "downloads": 12000, "pipeline_tag": "text-to-image"}]

    monkeypatch.setattr(hub, "metadata_json", metadata)
    report = await hub.search_models("new image & model", lambda: None)
    assert len(calls) == 1 and "limit=12" in calls[0] and "%26" in calls[0]
    assert report["items"][0]["compatibility"] == "not_inspected"
    assert report["files"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [{}, [{"id": "p/m"}] * 13, [{"id": "https://localhost/evil"}]])
async def test_search_rejects_unbounded_or_invalid_repository_results(monkeypatch, raw):
    async def metadata(*args):
        return raw

    monkeypatch.setattr(hub, "metadata_json", metadata)
    with pytest.raises(ValueError):
        await hub.search_models("model", lambda: None)

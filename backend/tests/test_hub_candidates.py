"""New GGUF plans use immutable publisher data; no weights or custom code."""

import pytest
from app import hub_candidates as plans
from app.hub_sources import inspect_source, parse_source
from app.setup_models import CANDIDATES


def config(**changes):
    return {
        "architectures": ["Qwen3ForCausalLM"],
        "model_type": "qwen3",
        "num_hidden_layers": 36,
        "hidden_size": 2560,
        "num_attention_heads": 32,
        "num_key_value_heads": 8,
        "head_dim": 128,
        "max_position_embeddings": 262144,
        **changes,
    }


def observation():
    return {
        "repository": "publisher/new-model",
        "revision": "a" * 40,
        "files": [
            {
                "filename": "new-model.Q4_K_M.gguf",
                "format": "gguf",
                "sha256": "b" * 64,
                "size_bytes": 1000,
                "identity_available": True,
            }
        ],
    }


@pytest.fixture
def publisher(monkeypatch):
    from app import hub_sources

    state = {"config": config(), "bases": ["publisher/base"], "architecture": "qwen3", "calls": []}

    async def metadata(url, check):
        check()
        state["calls"].append(url)
        if url.endswith("/config.json"):
            return state["config"]
        if "/publisher/base/" in url:
            return {"id": "publisher/base", "sha": "c" * 40}
        return {
            "id": "publisher/new-model",
            "sha": "a" * 40,
            "gguf": {"architecture": state["architecture"]},
            "cardData": {"base_model": state["bases"], "license": "apache-2.0"},
            "siblings": [
                {
                    "rfilename": "new-model.Q4_K_M.gguf",
                    "size": 1000,
                    "lfs": {"sha256": "b" * 64, "size": 1000},
                }
            ],
        }

    monkeypatch.setattr(plans, "metadata_json", metadata)
    monkeypatch.setattr(hub_sources, "metadata_json", metadata)
    return state


@pytest.mark.asyncio
async def test_new_model_plan_freezes_source_configuration_and_identity_without_weights(publisher):
    original = observation()
    entry = await plans.resolve_candidate(original, original["files"][0]["filename"], lambda: None)
    assert entry.origin == "hub" and entry.architecture == "qwen3" and entry.quantization == "Q4_K_M"
    assert entry.repository == "publisher/new-model" and entry.revision == "a" * 40
    assert entry.configuration_revision == "c" * 40 and entry.configuration_sha256
    assert entry.config_url.endswith("/" + "c" * 40 + "/config.json")
    assert entry.attention_layers == 36 and entry.kv_heads == 8 and entry.context_ceiling == 131072
    assert len(publisher["calls"]) == 3 and all(
        "/api/models/" in u or u.endswith("/config.json") for u in publisher["calls"]
    )
    assert plans.download_candidate(entry.model_dump(mode="json")) == entry
    legacy = CANDIDATES[0]
    assert plans.download_candidate(legacy.model_dump(mode="json")) == legacy


@pytest.mark.parametrize(
    "change",
    [
        {"num_hidden_layers": True},
        {"num_hidden_layers": 513},
        {"num_key_value_heads": 100},
        {"head_dim": 0},
        {"hidden_size": None},
        {"max_position_embeddings": float("nan")},
        {"model_type": "unknown_remote_code"},
        {"architectures": ["Qwen3ForSequenceClassification"]},
    ],
)
def test_bad_or_unknown_geometry_is_not_a_fit(change):
    with pytest.raises(ValueError):
        plans.geometry(config(**change), "qwen3")


def test_qwen35_uses_full_attention_and_explicit_state_reserve():
    result = plans.geometry(
        {
            "architectures": ["Qwen3_5ForConditionalGeneration"],
            "model_type": "qwen3_5",
            "text_config": config(
                model_type="qwen3_5_text",
                num_hidden_layers=64,
                full_attention_interval=4,
                head_dim=256,
                architectures=None,
            ),
        },
        "qwen35",
    )
    assert result["attention_layers"] == 16 and result["state_reserve_mib"] == 512


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("bases", ["publisher/base", "other/model"]), ("architecture", "clip")]
)
async def test_ambiguous_base_and_non_llm_architecture_require_recipe(publisher, field, value):
    publisher[field] = value
    original = observation()
    with pytest.raises(ValueError):
        await plans.resolve_candidate(original, original["files"][0]["filename"], lambda: None)


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["mmproj-model.gguf", "model-00001-of-00003.gguf"])
async def test_companion_or_incomplete_shard_cannot_be_installed_as_a_whole_llm(publisher, filename):
    original = observation()
    original["files"][0]["filename"] = filename
    with pytest.raises(ValueError):
        await plans.resolve_candidate(original, filename, lambda: None)
    assert not publisher["calls"]


@pytest.mark.asyncio
async def test_changed_source_hash_cannot_change_the_plan(publisher):
    original = observation()
    original["files"][0]["sha256"] = "d" * 64
    with pytest.raises(ValueError, match="identity changed"):
        await plans.resolve_candidate(original, original["files"][0]["filename"], lambda: None)


@pytest.mark.asyncio
async def test_candidate_cannot_redirect_to_another_object_or_config(publisher):
    original = observation()
    entry = await plans.resolve_candidate(original, original["files"][0]["filename"], lambda: None)
    for update in (
        {"filename": "other.gguf"},
        {"repository": "elsewhere/model"},
        {"config_url": "https://evil.example/config.json"},
        {"runtime_profile": "llamacpp-cpu-linux-amd64-v1"},
    ):
        with pytest.raises(ValueError):
            plans.HubCandidate.model_validate({**entry.model_dump(mode="json"), **update})


@pytest.mark.asyncio
async def test_saved_repository_observation_can_be_reinspected_for_base_provenance(publisher):
    inspected = await inspect_source(parse_source("publisher/new-model"), lambda: None)
    assert inspected["base_models"] == ["publisher/base"] and inspected["architecture_hint"] == "qwen3"

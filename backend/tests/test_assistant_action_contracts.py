"""Model-bound schema projection and repair, without execution authority."""

import asyncio
import json

import pytest
from app.assistant_action_contracts import feedback_excerpt, parameter_schema, repair_context
from app.assistant_controller_tools import ImageOperation
from app.assistant_react import ClosedToolMetadata, take_action
from app.image_control_contract import validate_controls


def context(default="qwen"):
    return {
        "instruction": "Two separate new views of this cabinet",
        "tools": {"image.recompose": {}},
        "image_contract_version": "configured-default-v2",
        "image_models": {
            "defaults": {"choices": {"t2i": default, "img2img": default, "recompose": default}},
            "models": {
                "qwen": {"backend": "qwen", "modes": ["t2i", "img2img", "recompose"]},
                "installed-krea": {"backend": "krea2", "modes": ["t2i", "img2img", "recompose"]},
            },
        },
        "observations": [],
    }


def test_framework_keeps_closed_model_conditions_in_the_actual_tool_prompt():
    captured = []

    async def invoke(messages):
        captured.extend(messages)
        return 'Thought: Make the first view.\nAction: image_recompose\nAction Input: {"instruction":"A side view of the same cabinet","images":["input:image:1"]}'

    result = asyncio.run(take_action(context(), invoke))
    assert result["tool"] == "image.recompose"
    wire = captured[0]["content"]
    assert '"additionalProperties": false' in wire and '"allOf"' in wire
    assert "Configured recompose default: qwen" in wire
    assert "Internal reference placement never determines output count" in wire
    schema = parameter_schema(context(), "image.recompose", ImageOperation)
    qwen = next(
        item
        for item in schema["allOf"]
        if item["if"].get("properties", {}).get("image_model", {}).get("const") == "qwen"
    )
    krea = next(
        item
        for item in schema["allOf"]
        if item["if"].get("properties", {}).get("image_model", {}).get("const") == "installed-krea"
    )
    assert qwen["then"]["properties"]["reference_layout"] == {"type": "null"}
    assert krea["then"]["required"] == ["reference_layout"]
    assert krea["then"]["properties"]["reference_layout"]["enum"] == ["aligned", "beside"]
    metadata = ClosedToolMetadata(
        name="image_recompose", description="Image", fn_schema=ImageOperation, parameters=schema
    )
    projected = metadata.get_parameters_dict()
    projected["allOf"].clear()
    assert metadata.get_parameters_dict()["allOf"]


@pytest.mark.parametrize("default", ["qwen", "installed-krea"])
def test_default_and_named_models_have_independent_constraints(default):
    schema = parameter_schema(context(default), "image.recompose", ImageOperation)
    fallback = schema["allOf"][-1]["then"]
    assert ("reference_layout" in fallback.get("required", [])) == (default == "installed-krea")
    generation = parameter_schema(context(default), "image.generate", ImageOperation)
    assert all(
        item["then"]["properties"]["reference_layout"] == {"type": "null"} for item in generation["allOf"]
    )
    validate_controls("qwen", "recompose", {}, required=True)
    with pytest.raises(ValueError, match="only to Krea2"):
        validate_controls("qwen", "recompose", {"reference_layout": "beside"}, required=True)
    with pytest.raises(ValueError, match="Choose reference_layout explicitly"):
        validate_controls("krea2", "recompose", {}, required=True)
    validate_controls("krea2", "recompose", {"reference_layout": "beside"}, required=True)
    # Result-bound agents keep the existing source-inheritance exemption.
    validate_controls("krea2", "recompose", {}, required=False)


def test_repair_binds_the_rejected_proposal_without_replacing_the_instruction():
    original = context()
    proposed = {
        "kind": "tool",
        "tool": "image.recompose",
        "arguments": {
            "instruction": "Keep all source details",
            "images": ["input:image:1"],
            "reference_layout": "beside",
        },
    }
    feedback = repair_context(original, proposed, "Reference controls apply only to Krea2 Edit or Recompose")
    assert feedback["selected_model_contract"]["model"] == "qwen"
    assert feedback["selected_model_contract"]["supported_controls"] == {}
    assert feedback["selected_model_contract"]["unsupported_controls"] == ["reference_layout"]

    async def invoke(messages):
        current = json.loads(messages[-1]["content"].split("\n", 1)[1])
        assert current["instruction"] == original["instruction"]
        assert current["validation_feedback"]["rejected_action"] == proposed
        return 'Thought: Use the same model without the unsupported hint.\nAction: image_recompose\nAction Input: {"instruction":"Keep all source details","images":["input:image:1"]}'

    result = asyncio.run(take_action(original, invoke, feedback))
    assert result["arguments"] == {"instruction": "Keep all source details", "images": ["input:image:1"]}


def test_repair_is_defensive_and_bounds_only_repeated_proposal_excerpts():
    c = context()
    for value in (
        None,
        [],
        {"tool": []},
        {"tool": "image.recompose", "arguments": {"image_model": {"bad": True}}},
    ):
        assert repair_context(c, value, "Bad argument")["validation"] == "Bad argument"
    feedback = repair_context(
        c, {"tool": "image.recompose", "arguments": {"instruction": "x" * 10000}}, "Bad hint"
    )
    excerpt = feedback_excerpt(feedback)
    assert len(excerpt["rejected_action"]["arguments"]["instruction"]) == 1200
    assert len(feedback["rejected_action"]["arguments"]["instruction"]) == 10000


def test_result_bound_agent_does_not_guess_source_controls_from_workspace_default():
    from app.assistant_controller_tools import MediaAgentDraft

    c = context("installed-krea")
    c["missing_outcomes"] = [
        {"kind": "agent_draft", "agent_media_kind": "image", "automation": {"image_source": "latest_result"}}
    ]
    schema = parameter_schema(c, "agent.create", MediaAgentDraft)
    assert len(schema["allOf"]) == 2  # Named choices only, not an inherited default guess.
    proposed = {
        "kind": "tool",
        "tool": "agent.create",
        "arguments": {
            "instruction": "Future cabinet views",
            "images": ["step:1:image:1"],
            "reference_layout": "beside",
        },
    }
    feedback = repair_context(c, proposed, "Unsupported source control")
    assert "selected_model_contract" not in feedback
    assert "actual source/result model" in feedback["source_model_policy"]


def test_proposal_diagnostics_remain_valid_json_for_invalid_numeric_arguments():
    result = repair_context(
        context(),
        {"kind": "tool", "tool": "image.recompose", "arguments": {"unknown": float("nan")}},
        "Invalid parameter",
    )
    assert (
        json.loads(json.dumps(result, allow_nan=False))["rejected_action"]["arguments"]["unknown"]
        == "[invalid non-finite number]"
    )


def test_model_schema_advertises_actual_reference_and_generation_limits():
    c = context()
    c["image_models"]["models"]["installed-krea"]["maximum_references"] = 2
    for tool, maximum, minimum in [("image.generate", 0, 0), ("image.edit", 1, 1), ("image.recompose", 2, 1)]:
        schema = parameter_schema(c, tool, ImageOperation)
        choice = next(
            rule
            for rule in schema["allOf"]
            if rule["if"].get("properties", {}).get("image_model", {}).get("const") == "installed-krea"
        )
        assert choice["then"]["properties"]["images"] == {"maxItems": maximum, "minItems": minimum}

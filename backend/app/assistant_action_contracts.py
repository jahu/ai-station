"""Closed model-aware affordances derived only from a captured image catalog."""

from copy import deepcopy
from math import isfinite

from app.image_control_contract import CONTROL_FIELDS, control_schema

IMAGE_MODES = {"image.generate": "t2i", "image.edit": "img2img", "image.recompose": "recompose"}


def image_options(context, name):
    if not isinstance(name, str):
        return None
    verified = name == "image.edit" and context.get("verified_image_edit")
    mode = "recompose" if verified else IMAGE_MODES.get(name)
    inherited = name == "agent.create"
    if inherited:
        goal = next(
            (
                item
                for item in context.get("missing_outcomes", [])
                if item["kind"] == "agent_draft" and item.get("agent_media_kind") == "image"
            ),
            None,
        )
        if not goal:
            return None
        automation = goal.get("automation") or {}
        mode = (
            "recompose"
            if automation.get("image_source") in {"supplied", "latest_result"} or goal.get("source_inputs")
            else "t2i"
        )
    catalog = context.get("image_models") or {}
    if not mode or not catalog.get("models"):
        return None
    choices = {key: value for key, value in catalog["models"].items() if mode in value.get("modes", [])}
    default = (catalog.get("defaults", {}).get("choices") or {}).get("img2img" if verified else mode)
    return {"mode": mode, "models": choices, "default": default, "inherited": inherited}


def _controls_clause(item, mode, required, *, bind_images=False):
    controls = control_schema(item["backend"], mode)
    properties = {field: controls.get(field, {"type": "null"}) for field in CONTROL_FIELDS}
    if not required:
        properties = {
            field: {"anyOf": [schema, {"type": "null"}]} if field in controls else schema
            for field, schema in properties.items()
        }
    if bind_images:
        maximum = (
            0 if mode == "t2i" else min(item.get("maximum_references", 8), 1 if mode == "img2img" else 8)
        )
        properties["images"] = {"maxItems": maximum, "minItems": 0 if mode == "t2i" else 1}
    clause = {"properties": properties}
    if required and controls:
        clause["required"] = list(controls)
    return clause


def parameter_schema(context, name, base):
    schema = deepcopy(base.model_json_schema())
    options = image_options(context, name)
    if options is None or not CONTROL_FIELDS.intersection(schema.get("properties", {})):
        return schema
    current = context.get("image_contract_version") == "configured-default-v2"
    required = (
        current
        and not options["inherited"]
        and not (name == "image.edit" and context.get("verified_image_edit"))
    )
    choices = options["models"]
    if not choices:
        return schema
    schema["properties"]["image_model"] = {
        "anyOf": [{"type": "string", "enum": list(choices)}, {"type": "null"}],
        "default": None,
        "description": f"Exact captured model alias. Configured {options['mode']} default: {options['default']}. Omit to preserve that choice (or the source model for a result-bound agent); do not switch models to bypass validation.",
    }
    schema["properties"]["reference_layout"]["description"] += (
        " This is an internal reference control, never output count or a collage request. "
        "Use it only when the selected model's conditional schema permits it; otherwise omit it."
    )
    conditions = [
        {
            "if": {"properties": {"image_model": {"const": alias}}, "required": ["image_model"]},
            "then": _controls_clause(item, options["mode"], required, bind_images=not options["inherited"]),
        }
        for alias, item in choices.items()
    ]
    if current and not options["inherited"] and options["default"] in choices:
        conditions.append(
            {
                "if": {
                    "anyOf": [
                        {"not": {"required": ["image_model"]}},
                        {"properties": {"image_model": {"type": "null"}}, "required": ["image_model"]},
                    ]
                },
                "then": _controls_clause(
                    choices[options["default"]], options["mode"], required, bind_images=True
                ),
            }
        )
    schema["allOf"] = conditions
    return schema


def _trace_value(value, depth=0):
    if depth >= 12:
        return "[nested proposal omitted]"
    if isinstance(value, float) and not isfinite(value):
        return "[invalid non-finite number]"
    if isinstance(value, dict):
        return {key: _trace_value(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [_trace_value(item, depth + 1) for item in value]
    return value


def repair_context(context, proposed, diagnostic):
    """Describe the rejected operation; never replace the original request."""
    result = {"validation": diagnostic[:1800]}
    if not isinstance(proposed, dict):
        return result
    action = _trace_value({key: proposed[key] for key in ("kind", "tool", "arguments") if key in proposed})
    result["rejected_action"] = action
    options = image_options(context, proposed.get("tool"))
    arguments = proposed.get("arguments")
    if options and isinstance(arguments, dict):
        if options["inherited"] and arguments.get("image_model") is None:
            result["source_model_policy"] = (
                "Preserve the actual source/result model, not the workspace default. Remove unsupported controls described by validation; do not guess or switch the inherited model."
            )
            return result
        selected = arguments.get("image_model") or options["default"]
        item = options["models"].get(selected) if isinstance(selected, str) else None
        if item:
            supported = control_schema(item["backend"], options["mode"])
            result["selected_model_contract"] = {
                "model": selected,
                "operation": options["mode"],
                "supported_controls": supported,
                "unsupported_controls": [
                    key for key in CONTROL_FIELDS if arguments.get(key) is not None and key not in supported
                ],
                "correction": "Remove unsupported controls, preserve the selected model, original instruction and reference aliases. Supply missing supported required controls. Never replace multiple requested outputs with a collage or ask the user to resolve an internal validation error.",
            }
    return result


def feedback_excerpt(feedback):
    """Bound repeated proposal details; the original instruction stays intact."""
    result = deepcopy(feedback)
    args = (result.get("rejected_action") or {}).get("arguments")
    if isinstance(args, dict):
        for key, value in list(args.items()):
            if isinstance(value, str) and len(value) > 1200:
                args[key] = value[:1200]
                result["proposal_excerpt_truncated"] = True
    return result

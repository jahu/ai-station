"""Constrain owned-model output shape; checked file application remains authoritative."""

from ai_station_runner.coding_files import MAX_FILE, MAX_REPLACEMENTS


def proposal_schema(paths):
    path = {"type": "string", "enum": paths}

    def record(properties):
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }

    return record(
        {
            "summary": {"type": "string", "maxLength": 4000},
            "files": {
                "type": "array",
                "minItems": 1,
                "maxItems": 10,
                "items": {
                    "oneOf": [
                        record({"path": path, "content": {"type": "string", "maxLength": MAX_FILE}}),
                        record(
                            {
                                "path": path,
                                "replacements": {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": MAX_REPLACEMENTS,
                                    "items": record(
                                        {
                                            "old": {"type": "string", "minLength": 1},
                                            "new": {"type": "string"},
                                        }
                                    ),
                                },
                            }
                        ),
                        record({"path": path, "delete": {"const": True}}),
                    ]
                },
            },
        }
    )

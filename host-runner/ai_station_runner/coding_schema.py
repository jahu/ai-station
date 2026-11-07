"""Constrain owned-model output shape; checked file application remains authoritative."""

from ai_station_runner.coding_files import MAX_FILE, MAX_REPLACEMENTS


def record(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def proposal_schema(paths):
    path = {"type": "string", "enum": paths}

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


def exploration_schema(tools):
    path = {"type": "string", "minLength": 1, "maxLength": 300}
    prefix = {"type": "string", "maxLength": 300}
    fields = {
        "list_files": [{"prefix": prefix, "offset": {"type": "integer", "minimum": 0}}],
        "read_file": [
            {"path": path},
            {
                "path": path,
                "start_line": {"type": "integer", "minimum": 1},
                "max_lines": {"type": "integer", "minimum": 1, "maximum": 200},
            },
        ],
        "search_files": [{"query": {"type": "string", "minLength": 1, "maxLength": 200}, "prefix": prefix}],
        "finish": [{"files": {"type": "array", "minItems": 1, "maxItems": 10, "items": path}}],
        "fetch_url": [{"url": {"type": "string", "minLength": 1, "maxLength": 2000}}],
        "web_search": [{"query": {"type": "string", "minLength": 1, "maxLength": 500}}],
    }
    return {
        "oneOf": [record({"tool": {"const": tool}, **variant}) for tool in tools for variant in fields[tool]]
    }

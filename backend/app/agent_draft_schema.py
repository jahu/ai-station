"""Project the existing draft schema onto a previously inferred media goal."""


def proposal_schema(proposal_type, tools, media_kind=None):
    schema = proposal_type.model_json_schema()
    schema["properties"]["tools"]["items"] = {"type": "string", "enum": list(tools)}
    if media_kind is None:
        return schema
    definitions = schema.get("$defs", {})
    names = [
        name
        for name, value in definitions.items()
        if value.get("properties", {}).get("kind", {}).get("const") == media_kind
        and "request" in value.get("properties", {})
    ]
    if len(names) != 1:
        raise ValueError("This agent media kind has no qualified draft schema")
    schema["properties"]["media"] = {"$ref": "#/$defs/" + names[0]}
    schema["required"] = [*schema.get("required", []), "media"]

    # Unrelated workload schemas distract small local models and waste context.
    # Keep the exact original validation schema for every reachable field.
    def references(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "$ref" and isinstance(item, str) and item.startswith("#/$defs/"):
                    yield item.removeprefix("#/$defs/")
                else:
                    yield from references(item)
        elif isinstance(value, list):
            for item in value:
                yield from references(item)

    needed, pending = set(), list(references({key: value for key, value in schema.items() if key != "$defs"}))
    while pending:
        name = pending.pop()
        if name not in needed:
            needed.add(name)
            pending.extend(references(definitions[name]))
    schema["$defs"] = {name: value for name, value in definitions.items() if name in needed}
    return schema

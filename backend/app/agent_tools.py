"""Only tools implemented for the local agent execution boundary are advertised."""

import json

from app.tools import TOOLS, ToolSpec, get_tool

CALLABLE_TOOLS = frozenset({"system_snapshot", "memory_search", "web_search", "http_fetch"})
MAX_TOOL_ROUNDS = 4
MAX_CALLS_PER_ROUND = 3

AGENT_TOOLS = {
    "system_snapshot": ToolSpec(
        name="system_snapshot",
        description="Read current host hardware telemetry through the Host Runner.",
        risk_level="low",
        required_permissions=("filesystem_read",),
        timeout=8,
        execution_target="host",
        operational=True,
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object"},
    ),
    "remember_report": ToolSpec(
        name="remember_report",
        description="Save successful reports as observations in this agent's own memory, with source Run provenance. Nothing is saved on failure or cancellation.",
        risk_level="low",
        required_permissions=("memory_write",),
        timeout=5,
        execution_target="container",
        operational=True,
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={
            "type": "object",
            "properties": {"memory_id": {"type": "string"}, "excerpted": {"type": "boolean"}},
        },
    ),
    "memory_search": ToolSpec(
        name="memory_search",
        description="Retrieve enabled memories from this agent's own scope.",
        risk_level="low",
        required_permissions=(),
        timeout=5,
        execution_target="container",
        operational=True,
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object"},
    ),
}
for key, label in [
    ("browser", "Browser automation"),
    ("read_file", "Host file reading"),
]:
    AGENT_TOOLS[key] = ToolSpec(
        name=key,
        description=f"{label} is not implemented for agents.",
        risk_level="medium",
        required_permissions=(),
        timeout=0,
        execution_target="container",
        operational=False,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )


def effective_permissions(tools):
    return sorted({permission for name in tools for permission in AGENT_TOOLS[name].required_permissions})


AGENT_TOOLS["web_search"] = TOOLS["web_search"]
AGENT_TOOLS["http_fetch"] = TOOLS["http_fetch"]


def agent_tool(name):
    return get_tool(name) if name in {"web_search", "http_fetch"} else AGENT_TOOLS[name]


def calling_tools(definition) -> list[dict]:
    tools = []
    for name in definition.tools:
        if name not in CALLABLE_TOOLS:
            continue
        spec = agent_tool(name)
        if not spec.operational:
            continue
        if name == "web_search":
            if not definition.search_query:
                continue
            parameters = {"type": "object", "properties": {}, "additionalProperties": False}
        elif name == "http_fetch":
            if not definition.fetch_urls:
                continue
            parameters = {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "enum": list(definition.fetch_urls),
                        "description": "One reviewed URL from this agent. Omit to fetch all reviewed pages.",
                    }
                },
                "additionalProperties": False,
            }
        else:
            parameters = spec.input_schema
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": parameters,
                },
            }
        )
        if len(tools) == 6:
            break
    return tools


def parse_tool_call(definition, raw) -> tuple[str, dict, str]:
    if not isinstance(raw, dict):
        raise ValueError("Tool call must be an object")
    extra = set(raw) - {"id", "name", "arguments", "type"}
    if extra:
        raise ValueError("Refusing an invented tool-call field")
    name = raw.get("name")
    call_id = raw.get("id") or ""
    if not isinstance(call_id, str) or len(call_id) > 80:
        raise ValueError("Tool call id is invalid")
    if not isinstance(name, str) or name not in CALLABLE_TOOLS:
        raise ValueError(f"Refusing an invented or unauthorized tool call: {name}")
    if name not in definition.tools or not agent_tool(name).operational:
        raise ValueError(f"Refusing an invented or unauthorized tool call: {name}")
    arguments_raw = raw.get("arguments") if raw.get("arguments") is not None else "{}"
    if not isinstance(arguments_raw, str) or len(arguments_raw) > 4000:
        raise ValueError("Tool call arguments must be JSON text")
    try:
        arguments = json.loads(arguments_raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Tool call arguments must be JSON") from exc
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ValueError("Tool call arguments must be an object")
    if name in {"system_snapshot", "memory_search"}:
        if arguments:
            raise ValueError("This tool does not accept model-selected arguments")
    elif name == "web_search":
        unexpected = set(arguments) - {"query"}
        if unexpected:
            raise ValueError("Refusing unexpected tool arguments")
        query = arguments.get("query")
        if query is not None and query != definition.search_query:
            raise ValueError("The model cannot choose a search query")
    elif name == "http_fetch":
        unexpected = set(arguments) - {"url"}
        if unexpected:
            raise ValueError("Refusing unexpected tool arguments")
        url = arguments.get("url")
        if url is not None and url not in definition.fetch_urls:
            raise ValueError("The model cannot choose HTTP URLs")
    return name, arguments, call_id

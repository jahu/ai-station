"""Only tools implemented for the local agent execution boundary are advertised."""

import json

from app.tools import TOOLS, ToolSpec, get_tool

CALLABLE_TOOLS = frozenset({"system_snapshot", "memory_search", "project_memory", "web_search", "http_fetch"})
RETENTION_TOOLS = frozenset({"remember_report", "remember_workflow"})
WORKFLOW_MEMORY_TOOLS = frozenset({"system_snapshot", "web_search", "http_fetch", "browser"})
MAX_TOOL_ROUNDS = 4
MAX_CALLS_PER_ROUND = 3

AGENT_TOOLS = {
    "market_watch": ToolSpec(
        name="market_watch",
        description="Observe reviewed Coinbase BTC/ETH pairs, compare numeric thresholds and create deduplicated in-app alerts. Optional email requires separately approved agent/recipient scope. No model or trading.",
        risk_level="low",
        required_permissions=("network_read",),
        timeout=90,
        execution_target="container",
        operational=True,
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object"},
    ),
    "python_data": ToolSpec(
        name="python_data",
        description="Analyze reviewed CSV/XLSX files with a local model and offline Python. Creates an owned workspace, preserves original files and returns an answer/table/download. No networking or package installation inside generated code.",
        risk_level="medium",
        required_permissions=(
            "filesystem_read",
            "workspace_write",
            "git_read",
            "git_write",
            "network_read",
            "python_execute",
        ),
        timeout=3600,
        execution_target="container",
        operational=True,
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object"},
    ),
    "github_read": ToolSpec(
        name="github_read",
        description="Read repository details and bounded open issue/PR titles from the explicitly reviewed GitHub connector, using the host gh session. Sends no source files or writes. The report uses only the selected local model.",
        risk_level="low",
        required_permissions=("network_read", "github_read"),
        timeout=60,
        execution_target="host",
        operational=True,
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object"},
    ),
    "coding_local": ToolSpec(
        name="coding_local",
        description="Build or change the linked project with Local AI in a fresh owned worktree. Runs exploration, proposal and configured validation; preserves the diff for review. Never commits, publishes or edits the original checkout. May combine with HTTP fetch of explicitly reviewed public URLs before coding.",
        risk_level="medium",
        required_permissions=(
            "filesystem_read",
            "workspace_write",
            "git_read",
            "git_write",
            "network_read",
            "shell_project_commands",
        ),
        timeout=3600,
        execution_target="host",
        operational=True,
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object"},
    ),
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
    "remember_workflow": ToolSpec(
        name="remember_workflow",
        description="Save successful workflow step observations (telemetry, public search, HTTP fetch, rendered pages) in this agent's own memory, with source Run provenance. memory_search is not copied. Nothing is saved on failure or cancellation.",
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
    "project_memory": ToolSpec(
        name="project_memory",
        description="Read enabled memories from this agent's explicitly linked project, with source provenance. No other projects, global memory, files or Git access. Select a project before enabling.",
        risk_level="low",
        required_permissions=("project_memory_read",),
        timeout=5,
        execution_target="container",
        operational=True,
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object"},
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


for _provider in ("cursor", "codex"):
    _name = "coding_" + _provider
    AGENT_TOOLS[_name] = ToolSpec(
        name=_name,
        description=f"Use external {_provider.title()} to change the linked project in a fresh owned worktree. Sends the goal, reviewed guidance and bounded project source to the external provider. Existing CLI login only. Preserves proposals and configured validation for review; never commits, publishes or edits the original checkout. Select alone with the explicit external coding permission profile.",
        risk_level="high",
        required_permissions=(*AGENT_TOOLS["coding_local"].required_permissions, "external_ai"),
        timeout=3600,
        execution_target="host",
        operational=True,
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object"},
    )


def effective_permissions(tools):
    return sorted({permission for name in tools for permission in AGENT_TOOLS[name].required_permissions})


AGENT_TOOLS["web_search"] = TOOLS["web_search"]
AGENT_TOOLS["http_fetch"] = TOOLS["http_fetch"]
AGENT_TOOLS["browser"] = TOOLS["browser"]


def agent_tool(name):
    return get_tool(name) if name in {"web_search", "http_fetch", "browser"} else AGENT_TOOLS[name]


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
    if name in {"system_snapshot", "memory_search", "project_memory"}:
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

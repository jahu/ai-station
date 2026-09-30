"""Only tools implemented for the local agent execution boundary are advertised."""

from app.tools import TOOLS, ToolSpec, get_tool

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
    ("http_fetch", "HTTP fetching"),
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


def agent_tool(name):
    return get_tool(name) if name == "web_search" else AGENT_TOOLS[name]

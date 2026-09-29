"""Tool registry. Only implemented tools are operational."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk_level: str
    required_permissions: tuple[str, ...]
    timeout: int
    execution_target: str
    operational: bool
    input_schema: dict
    output_schema: dict


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


TOOLS: dict[str, ToolSpec] = {
    "read_file": ToolSpec(
        name="read_file",
        description="Read a file inside the allocated worktree.",
        risk_level="low",
        required_permissions=("filesystem_read",),
        timeout=20,
        execution_target="host",
        operational=True,
        input_schema=_schema({"path": {"type": "string"}}, ["path"]),
        output_schema=_schema({"content": {"type": "string"}}, ["content"]),
    ),
    "list_directory": ToolSpec(
        name="list_directory",
        description="List a directory inside the allocated worktree.",
        risk_level="low",
        required_permissions=("filesystem_read",),
        timeout=20,
        execution_target="host",
        operational=True,
        input_schema=_schema({"path": {"type": "string"}}, ["path"]),
        output_schema=_schema({"entries": {"type": "array"}}, ["entries"]),
    ),
    "search_files": ToolSpec(
        name="search_files",
        description="Search file contents inside the allocated worktree.",
        risk_level="low",
        required_permissions=("filesystem_read",),
        timeout=30,
        execution_target="host",
        operational=True,
        input_schema=_schema({"query": {"type": "string"}}, ["query"]),
        output_schema=_schema({"matches": {"type": "array"}}, ["matches"]),
    ),
    "write_file": ToolSpec(
        name="write_file",
        description="Write a file inside the allocated worktree.",
        risk_level="medium",
        required_permissions=("workspace_write",),
        timeout=20,
        execution_target="host",
        operational=True,
        input_schema=_schema(
            {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]
        ),
        output_schema=_schema({"ok": {"type": "boolean"}}, ["ok"]),
    ),
    "apply_patch": ToolSpec(
        name="apply_patch",
        description="Apply a unified diff inside the allocated worktree.",
        risk_level="medium",
        required_permissions=("workspace_write",),
        timeout=20,
        execution_target="host",
        operational=True,
        input_schema=_schema({"diff": {"type": "string"}}, ["diff"]),
        output_schema=_schema({"ok": {"type": "boolean"}}, ["ok"]),
    ),
    "git_status": ToolSpec(
        name="git_status",
        description="Show git status for the allocated worktree.",
        risk_level="low",
        required_permissions=("git_read",),
        timeout=20,
        execution_target="host",
        operational=True,
        input_schema=_schema({}, []),
        output_schema=_schema({"status": {"type": "string"}}, ["status"]),
    ),
    "git_diff": ToolSpec(
        name="git_diff",
        description="Show the git diff for the allocated worktree.",
        risk_level="low",
        required_permissions=("git_read",),
        timeout=20,
        execution_target="host",
        operational=True,
        input_schema=_schema({}, []),
        output_schema=_schema({"diff": {"type": "string"}}, ["diff"]),
    ),
    "run_project_command": ToolSpec(
        name="run_project_command",
        description="Run a command that is already configured on the project.",
        risk_level="medium",
        required_permissions=("shell_project_commands",),
        timeout=600,
        execution_target="host",
        operational=True,
        input_schema=_schema({"kind": {"type": "string"}}, ["kind"]),
        output_schema=_schema({"exit_code": {"type": "integer"}}, ["exit_code"]),
    ),
    "http_fetch": ToolSpec(
        name="http_fetch",
        description="Fetch a public HTTP URL. Private and loopback addresses are blocked.",
        risk_level="medium",
        required_permissions=("network_read",),
        timeout=30,
        execution_target="container",
        operational=True,
        input_schema=_schema({"url": {"type": "string"}}, ["url"]),
        output_schema=_schema(
            {"status": {"type": "integer"}, "body": {"type": "string"}}, ["status", "body"]
        ),
    ),
    "web_search": ToolSpec(
        name="web_search",
        description="Opt-in public web search with auditable sources through configured SearXNG.",
        risk_level="medium",
        required_permissions=("network_read",),
        timeout=30,
        execution_target="container",
        operational=False,
        input_schema=_schema({"query": {"type": "string", "minLength": 1, "maxLength": 500}}, ["query"]),
        output_schema=_schema(
            {
                "query": {"type": "string"},
                "sources": {"type": "array"},
                "partial": {"type": "boolean"},
                "searched_at": {"type": "string"},
                "provider": {"type": "string"},
            },
            ["query", "sources", "partial", "searched_at", "provider"],
        ),
    ),
    "browser": ToolSpec(
        name="browser",
        description="Browser automation. Not implemented.",
        risk_level="high",
        required_permissions=("browser",),
        timeout=60,
        execution_target="host",
        operational=False,
        input_schema=_schema({"url": {"type": "string"}}, ["url"]),
        output_schema=_schema({}, []),
    ),
}


def list_tools() -> list[ToolSpec]:
    return [configured(tool) for tool in TOOLS.values()]


def configured(tool: ToolSpec) -> ToolSpec:
    from app.config import get_settings

    return (
        replace(tool, operational=bool(get_settings().web_search_url)) if tool.name == "web_search" else tool
    )


def get_tool(name: str) -> ToolSpec | None:
    tool = TOOLS.get(name)
    return configured(tool) if tool else None

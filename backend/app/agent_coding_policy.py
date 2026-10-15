"""Explicit provider selection for the shared isolated agent coding workflow."""

CODING_TOOLS = {"coding_local": "local", "coding_cursor": "cursor", "coding_codex": "codex"}


def coding_provider(tools):
    if not isinstance(tools, (list, tuple)) or any(not isinstance(name, str) for name in tools):
        return None
    selected = [name for name in tools if name in CODING_TOOLS]
    if len(selected) != 1:
        return None
    if len(tools) == 1 or selected == ["coding_local"] and set(tools) <= {"coding_local", "http_fetch"}:
        return CODING_TOOLS[selected[0]]
    return None


def external_coding(tools):
    return coding_provider(tools) in {"cursor", "codex"}


def auto_local_coding(tools, model):
    return coding_provider(tools) == "local" and model == "auto"

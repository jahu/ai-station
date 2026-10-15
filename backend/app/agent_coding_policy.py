"""Explicit provider selection for the shared isolated agent coding workflow."""

CODING_TOOLS = {"coding_local": "local", "coding_cursor": "cursor", "coding_codex": "codex"}


def coding_provider(tools):
    if not isinstance(tools, (list, tuple)) or len(tools) != 1 or not isinstance(tools[0], str):
        return None
    return CODING_TOOLS.get(tools[0])


def external_coding(tools):
    return coding_provider(tools) in {"cursor", "codex"}


def auto_local_coding(tools, model):
    return coding_provider(tools) == "local" and model == "auto"

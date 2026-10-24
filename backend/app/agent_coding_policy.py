"""Explicit provider selection for the shared isolated agent coding workflow."""

LOCAL_RESEARCH_TOOLS = frozenset({"web_search", "search_pages", "http_fetch"})

CODING_TOOLS = {
    "coding_local": "local",
    "coding_cursor": "cursor",
    "coding_codex": "codex",
    "python_data": "local",
}


def coding_provider(tools):
    if not isinstance(tools, (list, tuple)) or any(not isinstance(name, str) for name in tools):
        return None
    selected = [name for name in tools if name in CODING_TOOLS]
    if len(selected) != 1:
        return None
    if (
        len(tools) == 1
        or selected[0] in {"coding_local", "python_data"}
        and set(tools) <= {selected[0]} | LOCAL_RESEARCH_TOOLS
    ):
        return CODING_TOOLS[selected[0]]
    return None


def external_coding(tools):
    return coding_provider(tools) in {"cursor", "codex"}


def auto_local_coding(tools, model):
    return coding_provider(tools) == "local" and model == "auto"


def coding_research_steps(tools):
    return [name for name in ("web_search", "search_pages", "http_fetch") if name in tools]

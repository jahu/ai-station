"""Default Web availability does not choose or block a Work task."""

WEB_ACTIONS = frozenset({"chat", "page.describe", "image.generate", "image.generate_video", "clarify"})


def default_web(options):
    """Accept raw forms or their server-owned contextual search snapshots."""
    return (
        options.get("enabled") is True
        and not options.get("render_pages")
        and (options.get("contextual") is True or not options.get("query", "").strip())
    )


def available_for_work(params):
    mode = params.get("policy_mode")
    if mode is None:
        mode = "work" if params.get("execution_mode") in {"work", "orchestrator"} else "chat"
    return mode == "work" and default_web(params.get("web_search") or {})


def prepare_turn(body, mode):
    if mode not in {"work", "orchestrator"} or not default_web(body.web_search.model_dump()):
        return body
    from app.assistant import explicit_plan
    from app.web_search import SearchOptions

    # The saved legacy orchestrator mode has the same server-owned Work policy.
    # Provider preflight must see that policy for ambiguous image requests too.
    body = body.model_copy(update={"execution_mode": "work"})
    plan = explicit_plan({**body.model_dump(mode="json", exclude={"attachments"}), "policy_mode": "work"})
    if plan is not None and plan.action not in WEB_ACTIONS:
        return body.model_copy(update={"web_search": SearchOptions(enabled=False)})
    return body

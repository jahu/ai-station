"""Source-bound recurring media drafts: owned results, fixed profiles and cadence."""

from app.assistant_intents import AutomationIntent
from app.models import Artifact, Run


def capture(session, root, args, entries):
    from app.assistant_controller import missing_outcomes
    from app.assistant_image_profiles import request_profile, source_profile

    pending = missing_outcomes(
        [
            step["observation"]
            for step in root.metadata_json.get("controller_steps", [])
            if step.get("observation")
        ],
        root.metadata_json.get("controller_outcomes", []),
    )
    outcome = next((item for item in pending if item["kind"] == "agent_draft"), None)
    raw = outcome.get("automation") if outcome else None
    if raw is None:
        if args.images or args.interval_seconds is not None or args.reference_layout is not None:
            raise ValueError(
                "Recurring references/cadence require the independently planned automation scope"
            )
        return None
    plan = AutomationIntent.model_validate(raw)
    if plan.media_kind != "image" and (args.image_model or args.reference_layout is not None):
        raise ValueError("Image reference controls require a planned image agent")
    if args.interval_seconds is not None and (
        plan.schedule.trigger != "interval" or args.interval_seconds != plan.schedule.interval_seconds
    ):
        raise ValueError("Preserve the requested recurring interval, not a new default")
    aliases = list(args.images)
    expected = list(plan.source_images)
    if plan.image_source == "latest_result":
        if any(item["kind"] == "image" for item in pending):
            raise ValueError("Complete the requested image transformation before binding its future agent")
        candidates = [
            item
            for item in entries.values()
            if item["type"] == "image" and item.get("origin") == "current_result"
        ]
        if candidates:
            latest = max(item["source_step"] for item in candidates)
            candidates = [item for item in candidates if item["source_step"] == latest]
        else:
            candidates = [
                item
                for item in entries.values()
                if item["type"] == "image" and item.get("origin") == "previous_result"
            ]
        if not candidates:
            raise ValueError("A completed image result is required; do not substitute the original reference")
        permitted = {item["alias"] for item in candidates}
        if aliases and not set(aliases) <= permitted:
            raise ValueError(
                "This future agent must use the changed image result, not an original attachment"
            )
        expected = aliases or [candidates[-1]["alias"]]
    elif plan.image_source == "supplied":
        if expected and aliases and aliases != expected:
            raise ValueError("Preserve the requested ordered recurring reference images")
        expected = expected or aliases
        if not expected:
            raise ValueError("Choose the supplied recurring image references")
    elif aliases:
        raise ValueError("The requested automation did not select image references")
    refs = []
    for alias in expected:
        item = entries.get(alias)
        if item is None or item["type"] != "image":
            raise ValueError("Choose a supplied image alias for recurring media")
        refs.append({"alias": alias, "snapshot": item["snapshot"]})
    if len({item["snapshot"]["id"] for item in refs}) != len(refs):
        raise ValueError("Recurring image references must not be duplicated")
    ids = [item["snapshot"]["id"] for item in refs]
    profile = (
        request_profile(
            session,
            root,
            args,
            "recompose" if refs else "t2i",
            ids,
            inherit_source=plan.image_source == "latest_result",
        )
        if plan.media_kind == "image"
        else {}
    )
    if refs and not profile:
        profile = {key: value for key, value in source_profile(session, ids).items() if key != "source_mode"}
    return {
        "version": 1,
        "controller_id": root.id,
        "owner_id": root.owner_id,
        "conversation_id": root.conversation_id,
        "plan": plan.model_dump(mode="json"),
        "images": refs,
        "profile": profile,
    }


def verified(session, run):
    from app.assistant_controller import verify_wrapper

    source = run.parameters.get("media_agent_scope")
    if source is None:
        return None
    parent = session.get(Run, run.parent_run_id)
    if parent is None or parent.executor_type != "orchestrator":
        raise ValueError("Recurring media draft has no originating controller tool")
    verify_wrapper(session, parent)
    if (
        source != parent.parameters.get("controller_agent_scope")
        or source.get("version") != 1
        or source["owner_id"] != run.owner_id
        or source["conversation_id"] != run.conversation_id
        or source["controller_id"] != parent.parameters.get("controller_parent_id")
    ):
        raise ValueError("The recurring media draft lost its frozen source binding")
    AutomationIntent.model_validate(source["plan"])
    for item in source["images"]:
        expected = item["snapshot"]
        artifact = session.get(Artifact, expected["id"])
        if (
            artifact is None
            or artifact.owner_id != run.owner_id
            or artifact.trashed_at is not None
            or artifact.artifact_type != "image"
            or {key: getattr(artifact, key) for key in ("id", "relative_path", "sha256", "size_bytes")}
            != expected
        ):
            raise ValueError("A recurring source image changed or became unavailable")
    return source


def check_files(source):
    from app.python_execution import read_owned_file

    for item in source["images"]:
        image = item["snapshot"]
        read_owned_file(
            image["relative_path"], image["size_bytes"], image["sha256"], limit=67108864, binary=True
        )


def image_definition(source, model):
    from app.agent_media_schema import AgentImageScope
    from app.agent_schema import AgentSettings
    from app.image_schema import ImageRequest

    plan = AutomationIntent.model_validate(source["plan"])
    if plan.media_kind != "image":
        raise ValueError("This definition requires a planned image output")
    mode = "recompose" if source["images"] else "t2i"
    request = ImageRequest.model_validate(
        {
            **source["profile"],
            "mode": mode,
            "prompt_style": "instruction" if source["images"] else "prompt",
            "prompt": plan.goal,
            "edit_prompt": "",
            "gpu": "auto",
            "input_artifact_ids": [item["snapshot"]["id"] for item in source["images"]],
        }
    )
    media = AgentImageScope(
        kind="image", request=request, description_source="goal", vary_scenes=plan.vary_results
    )
    return AgentSettings(
        name=plan.name or plan.goal[:120],
        description=plan.goal,
        goal=plan.goal,
        tools=["web_search", "create_media"] if plan.public_query else ["create_media"],
        search_query=plan.public_query,
        model=model,
        media=media,
        trigger=plan.schedule.trigger,
        interval_seconds=plan.schedule.interval_seconds,
        cron_expr=plan.schedule.cron_expr,
        run_at=plan.schedule.run_at,
        schedule_timezone=plan.schedule.timezone,
        maximum_runtime=plan.maximum_runtime or 1800,
        enabled=False,
        permission_profile="agent_local",
    )


def apply_cadence(settings, source):
    if source is None:
        return settings
    from app.agent_schema import AgentSettings

    plan = AutomationIntent.model_validate(source["plan"])
    values = settings.model_dump(mode="json")
    values.update(
        trigger=plan.schedule.trigger,
        interval_seconds=plan.schedule.interval_seconds,
        cron_expr=plan.schedule.cron_expr,
        run_at=plan.schedule.run_at,
        schedule_timezone=plan.schedule.timezone,
        enabled=False,
    )
    if plan.maximum_runtime is not None:
        values["maximum_runtime"] = plan.maximum_runtime
    return AgentSettings.model_validate(values)

"""Server-owned conversation capability policy, independent of model suggestions."""

import re

from fastapi import HTTPException

CHAT_ACTIONS = {
    "auto",
    "chat",
    "page.describe",
    "github.inspect",
    "clarify",
    "image.describe",
    "image.generate",
    "image.edit",
    "image.recompose",
    "image.upscale",
    "image.generate_video",
    "audio.speech",
    "audio.music",
    "data.analyze",
    "audio.transcribe",
    "audio.analyze",
    "avatar.animate",
    "video.generate",
}
POLICY_VERSION = 1


def policy_mode(mode):
    return "assistant" if mode == "assistant" else "work" if mode in {"work", "orchestrator"} else "chat"


def agent_draft_requested(params):
    """Only the current instruction can authorize drafting; activation stays separate."""
    text = params.get("content", "").strip()
    if params.get("action") == "agent.create":
        return True
    mention = re.search(r"\bagent", text, re.I)
    if mention and re.search(r"\b(?:not|never|don't|nie)\b", text[: mention.start()], re.I):
        return False
    if re.match(
        r"^(?:i (?:want|need)|chc[eę]|potrzebuj[eę])\s+(?:to (?:know|understand|learn)|wiedzie[ćc]|dowiedzie[ćc]|zrozumie[ćc]|nauczy[ćc])\b",
        text,
        re.I,
    ):
        return False
    return bool(
        re.search(
            r"^(?:(?:please|prosz[eę])\s+|(?:can|could)\s+you\s+|czy\s+mo[zż]esz\s+)?"
            r"(?:create|make|(?:i\s+)?want|(?:i\s+)?need|stw[oó]rz|utw[oó]rz|zbuduj|chc[eę]|potrzebuj[eę])\b.{0,80}\bagent",
            text,
            re.I,
        )
    )


def requires_orchestration(body):
    from app.assistant import explicit_plan

    params = {**body.model_dump(mode="json", exclude={"attachments"}), "policy_mode": "assistant"}
    plan = explicit_plan(params)
    if plan is not None:
        return plan.action != "chat"
    if body.image_artifact_ids or body.audio_artifact_id:
        return True
    # Ordinary questions use the existing direct reply executor. Unknown requests
    # to perform concrete work retain bounded model-assisted routing.
    return bool(
        agent_draft_requested(params)
        or re.match(
            r"^(?:(?:please|prosz[eę])\s+|(?:can|could)\s+you\s+|czy\s+mo[zż]esz\s+)?"
            r"(?:build|create|make|write|run|execute|schedule|automate|implement|fix|"
            r"zbuduj|stw[oó]rz|utw[oó]rz|napisz|uruchom|wykonaj|zaplanuj|zautomatyzuj|napraw|dodaj)\b"
            r".{0,180}\b(?:agent|project|projekt|script|skrypt|code|kod|workflow|process|proces|"
            r"file|plik|spreadsheet|arkusz|report|raport|website|stron|aplikacj|task|zadani)",
            body.content.strip(),
            re.I | re.S,
        )
    )


def agent_draft_policy(params):
    return params.get("policy_mode") == "work" or (
        params.get("policy_mode") == "assistant" and params.get("agent_draft_authorized") is True
    )


def validate_chat_scope(body):
    if body.action not in CHAT_ACTIONS or any(
        getattr(body, key, None) is not None
        for key in (
            "coding",
            "commit",
            "publish",
            "load",
            "stop",
            "new_project",
            "continuation",
            "project_defaults",
        )
    ):
        raise HTTPException(
            422, "This explicit legacy request does not allow project, agent or runtime actions"
        )


def constrain_plan(plan, params):
    if (
        params.get("policy_mode") == "assistant"
        and plan.action == "agent.create"
        and not params.get("agent_draft_authorized")
    ):
        from app.assistant import Plan

        return Plan(
            action="clarify",
            reason="Describe the agent you want to create and its goal before preparing a draft.",
        )
    if params.get("policy_mode") == "chat" and plan.action not in CHAT_ACTIONS:
        from app.assistant import Plan

        return Plan(
            action="clarify",
            reason="This explicit legacy request is restricted to conversation and media actions. No project, agent or runtime action was executed.",
        )
    return plan

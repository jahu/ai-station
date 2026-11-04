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
    "audio.effects",
    "data.analyze",
    "audio.transcribe",
    "audio.analyze",
    "avatar.animate",
    "video.generate",
}
POLICY_VERSION = 1
AGENT_REQUEST = re.compile(
    r"^(?:(?:please|prosz[eę]|now|then|teraz)\s+){0,3}"
    r"(?:(?:can|could|would)\s+you(?:\s+please)?\s+|"
    r"(?:czy\s+)?(?:mo[zż]esz|m[oó]g[łl](?:by[śs]|aby[śs]))\s+)?"
    r"(?:create|make|build|prepare|save|write|set\s+up|stw[oó]rz|utw[oó]rz|zbuduj|przygotuj|zapisz|zr[oó]b|napisz|"
    r"stworzy[ćc]|utworzy[ćc]|przygotowa[ćc]|"
    r"(?:(?:i\s+)?(?:want|need)|i(?:\s+would|'d)\s+like|chc[eę]|chcia[łl](?:bym|abym)|potrzebuj[eę])"
    r"(?:\s+(?:(?:you\s+)?to\s+(?:have|create|make|prepare)|mie[ćc]|stworzy[ćc]|przygotowa[ćc]))?)\s+"
    r"(?:(?:for\s+me|dla\s+mnie|(?!(?:about|of|for|from|with|using|on|regarding|to|how|know|learn|understand|"
    r"jak|wiedzie[ćc]|dowiedzie[ćc]|zrozumie[ćc]|nauczy[ćc]|opis|instrukcj[ęe]|poradnik|o)\b)[\w-]+)\s+){0,8}"
    r"agent(?:a|s|[oó]w)?\b",
    re.I,
)


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
    match = AGENT_REQUEST.match(text)
    return bool(
        match
        and not re.match(
            r"\s+(?:instructions?|prompts?|tutorials?|diagrams?|documentation)\b", text[match.end() :], re.I
        )
    )


def requires_orchestration(body):
    from app.assistant import explicit_plan

    params = {**body.model_dump(mode="json", exclude={"attachments"}), "policy_mode": "assistant"}
    plan = explicit_plan(params)
    # Selected media still needs the existing Vision/transcription dispatch even
    # when the optional action is Conversation; direct text replies cannot read it.
    if body.image_artifact_ids or body.audio_artifact_id:
        return True
    if plan is not None:
        return plan.action != "chat"
    # Ordinary questions use the existing direct reply executor. Unknown requests
    # to perform concrete work retain bounded model-assisted routing.
    return bool(
        agent_draft_requested(params)
        or re.match(
            r"^(?:(?:please|prosz[eę])\s+|(?:can|could)\s+you\s+|czy\s+mo[zż]esz\s+)?"
            r"(?:build|create|make|write|run|execute|schedule|automate|implement|fix|"
            r"zbuduj|stw[oó]rz|utw[oó]rz|napisz|uruchom|wykonaj|zaplanuj|zautomatyzuj|napraw|dodaj)\b"
            r".{0,180}\b(?:project|projekt|script|skrypt|code|kod|workflow|process|proces|"
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

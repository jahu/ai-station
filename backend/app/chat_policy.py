"""Server-owned conversation capability policy, independent of model suggestions."""

from fastapi import HTTPException

CHAT_ACTIONS = {
    "auto",
    "chat",
    "clarify",
    "image.describe",
    "image.generate",
    "image.edit",
    "image.recompose",
    "image.upscale",
    "image.generate_video",
    "audio.speech",
    "avatar.animate",
    "video.generate",
}
POLICY_VERSION = 1


def policy_mode(mode):
    return "work" if mode in {"work", "orchestrator"} else "chat"


def validate_chat_scope(body):
    if body.action not in CHAT_ACTIONS or any(
        getattr(body, key, None) is not None for key in ("coding", "commit", "publish", "load", "stop")
    ):
        raise HTTPException(422, "Switch to Work to operate projects, agents or runtimes")


def constrain_plan(plan, params):
    if params.get("policy_mode") == "chat" and plan.action not in CHAT_ACTIONS:
        from app.assistant import Plan

        return Plan(
            action="clarify",
            reason="Switch to Work to operate projects, agents or runtimes. Your instruction has not been executed.",
        )
    return plan

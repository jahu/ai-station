"""Bounded owned conversation attachments and visible dialogue for follow-ups."""

from sqlalchemy import select

from app.creation_context import eligible, plain
from app.models import Artifact, Message, Run


def prior_context(session, conversation, user, *, excluded, limit=32):
    messages = list(
        session.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.id != user.id,
                Message.created_at <= user.created_at,
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(64)
        )
    )
    messages = [
        message
        for message in messages
        if eligible(message)
        and not message.metadata_json.get("controller_internal")
        and not message.metadata_json.get("controller_reply_delivered")
    ]
    inputs, seen, sources = [], set(excluded), {}
    for message in messages:
        if message.role != "user":
            continue
        ids = [
            str(item["id"])
            for key in ("images", "attachments")
            for item in message.metadata_json.get(key, [])
            if isinstance(item, dict) and item.get("id")
        ]
        source_run = session.get(Run, message.run_id) if message.run_id else None
        if source_run is not None and (
            source_run.owner_id != conversation.owner_id or source_run.conversation_id != conversation.id
        ):
            continue
        snapshots = {}
        if source_run is not None:
            snapshots.update(
                {
                    item["snapshot"]["id"]: item["snapshot"]
                    for item in source_run.parameters.get("controller_inputs", [])
                    if isinstance(item, dict)
                    and isinstance(item.get("snapshot"), dict)
                    and item["snapshot"].get("id")
                }
            )
            snapshots.update(
                {
                    item["artifact_id"]: {
                        "id": item["artifact_id"],
                        "relative_path": item["relative_path"],
                        "size_bytes": item["size_bytes"],
                        "sha256": item["sha256"],
                    }
                    for item in source_run.parameters.get("image_inputs") or []
                    if isinstance(item, dict)
                    and all(key in item for key in ("artifact_id", "relative_path", "size_bytes", "sha256"))
                }
            )
        for aid in ids:
            sources.setdefault(aid, message.id)
            if aid in seen or len(inputs) >= limit:
                continue
            artifact = session.get(Artifact, aid)
            if (
                artifact is None
                or artifact.owner_id != conversation.owner_id
                or artifact.trashed_at is not None
            ):
                continue
            snapshot = {
                "id": artifact.id,
                "relative_path": artifact.relative_path,
                "size_bytes": artifact.size_bytes,
                "sha256": artifact.sha256,
            }
            if aid in snapshots and snapshots[aid] != snapshot:
                continue
            # Historical attachments without a frozen source receipt cannot be
            # silently reintroduced as an unchanged inspected input.
            if artifact.artifact_type == "image" and aid not in snapshots:
                continue
            seen.add(aid)
            inputs.append(
                {"snapshot": snapshot, "origin": "previous_attachment", "source_message_id": message.id}
            )
    history, budget = [], 6000
    for message in messages:
        text = plain(message)[: min(1600, budget)]
        if text:
            history.append({"role": message.role, "content": text})
            budget -= len(text)
        if len(history) >= 8 or budget <= 0:
            break
    return {"inputs": inputs, "sources": sources, "history": list(reversed(history))}


def reference_context(entries):
    images = [item for item in entries if item["type"] == "image"]
    current = [item["alias"] for item in images if item.get("origin") == "current_attachment"]
    results = [
        item["alias"] for item in images if item.get("origin") in {"current_result", "previous_result"}
    ]
    return {
        "active_images": current or results[-1:] or [item["alias"] for item in images[:1]],
        "available_images": [
            {
                key: value
                for key, value in item.items()
                if key in {"alias", "name", "origin", "source_message_id", "source_tool", "source_step"}
            }
            for item in images
        ],
        "note": "These owned images are available to tools without another upload. Descriptors are not pixel observations. Use current aliases; older dialogue may mention aliases from a different turn. New attachments take priority unless the user explicitly selects an earlier original or result.",
    }

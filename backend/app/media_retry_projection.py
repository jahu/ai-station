"""Read-only current media attempts; earlier Runs remain ordinary inspectable history."""

from uuid import UUID

from app.models import Run
from app.state import TERMINAL

EXECUTORS = {"photo_pipe", "wan_video", "ace_step_music"}


def current_attempt(session, source):
    chain, seen = [], set()
    current = source
    for _ in range(16):
        if current.id in seen:
            raise ValueError("Media retry history contains a cycle; inspect its Runs")
        seen.add(current.id)
        chain.append(current)
        identifier = current.metadata_json.get("retry_run_id")
        if not identifier:
            return current, chain
        try:
            identifier = str(UUID(identifier))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Media retry history has an invalid reference") from exc
        child = session.get(Run, identifier)
        if (
            current.status not in {"failed", "canceled", "interrupted"}
            or not child
            or child.parent_run_id != current.id
            or child.task_id != source.task_id
            or child.conversation_id != source.conversation_id
            or child.executor_type != source.executor_type
            or child.capability != source.capability
            or child.execution_target != source.execution_target
        ):
            raise ValueError("Media retry history belongs to a different request; inspect its Runs")
        current = child
    raise ValueError("Media retry history exceeds its inspection bound")


def projection(session, steps):
    rows, retired, visited, errors = [], set(), set(), []
    for source in steps:
        if (
            source.executor_type not in EXECUTORS
            or source.parameters.get("internal_media")
            or source.id in visited
        ):
            continue
        try:
            current, chain = current_attempt(session, source)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        visited.update(item.id for item in chain)
        rows.append(current)
        for previous in chain[:-1]:
            retired.add(previous.id)
            receipt = previous.metadata_json.get("prompt_translation", {})
            prep = (
                session.get(Run, receipt["preparation_run_id"]) if receipt.get("preparation_run_id") else None
            )
            if (
                prep
                and prep.task_id == previous.task_id
                and prep.parent_run_id == previous.id
                and prep.executor_type == "media_translate"
            ):
                if prep.status in TERMINAL:
                    retired.add(prep.id)
                review = session.get(Run, receipt["review_run_id"]) if receipt.get("review_run_id") else None
                if (
                    review
                    and review.task_id == previous.task_id
                    and review.parent_run_id == prep.id
                    and review.executor_type == "media_translation_apply"
                    and review.status in TERMINAL
                ):
                    retired.add(review.id)
                for item in steps:
                    if (
                        item.task_id == previous.task_id
                        and item.executor_type == "llama_load"
                        and item.metadata_json.get("created_for_consumer") == prep.id
                        and item.status in TERMINAL
                    ):
                        retired.add(item.id)
    return rows, retired, errors

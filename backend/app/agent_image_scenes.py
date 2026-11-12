"""Concrete, bounded scene plans for opt-in recurring reference-image agents."""

import re
from typing import Annotated

from pydantic import Field, field_validator
from sqlalchemy import select

from app.media_text import Description
from app.models import Run


class ImageScene(Description):
    """Read-only compatibility for previously saved person-oriented plans."""

    description: str = Field(min_length=1, max_length=2400)
    setting: str = Field(min_length=3, max_length=320)
    pose: str = Field(min_length=3, max_length=320)
    expression: str = Field(min_length=3, max_length=320)

    @field_validator("setting", "pose", "expression")
    @classmethod
    def concrete_choice(cls, value):
        return require_concrete(value)


def require_concrete(value):
    if re.fullmatch(r"(?i)(a |an |the )?(new|different|changed|another)( \w+){0,2}", value):
        raise ValueError("Choose a concrete visual direction, not just 'different'")
    return value


Aspect = Annotated[str, Field(min_length=2, max_length=60)]
Direction = Annotated[str, Field(min_length=3, max_length=240)]


class ImageVariation(Description):
    """One final image instruction and only the changes appropriate to its brief."""

    description: str = Field(default="", max_length=1800)
    preserve: list[Direction] = Field(default_factory=list, max_length=6)
    changes: dict[Aspect, Direction] = Field(min_length=1, max_length=4)

    @field_validator("changes")
    @classmethod
    def distinct_concrete_changes(cls, values):
        if len({normalize(key) for key in values}) != len(values):
            raise ValueError("Choose one consistent direction for each aspect")
        for value in values.values():
            require_concrete(value)
        return values

    def image_prompt(self):
        # Compile every reviewed plan field, rather than trusting prose to repeat
        # the requested changes. No subject, medium or concrete variation is added.
        parts = [self.description] if self.description else []
        if self.preserve:
            parts.append("Keep these reference features: " + "; ".join(self.preserve) + ".")
        parts.append(
            "Apply these changes relative to the references: "
            + "; ".join(f"{aspect}: {direction}" for aspect, direction in self.changes.items())
            + "."
        )
        parts.append(
            "Use the references for the features to keep, not to copy the properties requested to change. "
            "Keeping a feature must not freeze its other attributes that are explicitly requested to change."
        )
        return "\n".join(parts)


def saved_variation(value):
    if isinstance(value, dict) and "changes" in value:
        return ImageVariation.model_validate(value)
    legacy = ImageScene.model_validate(value)
    return ImageVariation(
        description=legacy.description[:1800],
        changes={key: getattr(legacy, key)[:240] for key in ("setting", "pose", "expression")},
    )


def history_variations(rows):
    """Read old frozen histories without rewriting their stored snapshot."""
    result = []
    for row in rows:
        plan = {key: value for key, value in row.items() if key != "run_id"}
        result.append({"run_id": row["run_id"], **saved_variation(plan).model_dump()})
    return result


def signature(scene):
    return tuple(sorted((normalize(key), normalize(value)) for key, value in scene["changes"].items()))


def normalize(value):
    return " ".join(re.findall(r"\w+", value.casefold()))


def repeats(scene, history):
    return any(
        normalize(scene["description"]) == normalize(prior["description"])
        or signature(scene) == signature(prior)
        for prior in history
    )


def planning_history(history):
    """Supply exclusion directions, not complete prompts that invite copying."""
    return [{"run_id": row["run_id"], "changes": row["changes"]} for row in history]


def repetition_feedback(scene):
    return {
        "reason": "The proposed variation repeats a completed result and was rejected.",
        "rejected_changes": scene["changes"],
        "requirement": (
            "Choose at least one genuinely different concrete direction allowed by the original brief. "
            "Keep its requested invariants. Rewrite the complete description to agree with the new changes; "
            "do not reuse the rejected prompt or only change wording, aspect names or field order."
        ),
    }


def reference_identity(run):
    return [(item.get("id"), item.get("sha256")) for item in run.parameters.get("media_inputs", [])]


def recent_scenes(session, run):
    """Only this owner's same agent/reference set and actually successful generations."""
    if not run.agent_id or not reference_identity(run):
        return []
    rows = session.scalars(
        select(Run)
        .where(
            Run.agent_id == run.agent_id,
            Run.owner_id == run.owner_id,
            Run.executor_type == "agent_media",
            Run.status == "succeeded",
            Run.created_at < run.created_at,
        )
        .order_by(Run.created_at.desc(), Run.id.desc())
        .limit(20)
    )
    history = []
    for prior in rows:
        child = (
            session.get(Run, prior.metadata_json.get("media_run_id"))
            if prior.metadata_json.get("media_run_id")
            else None
        )
        if (
            child is None
            or child.parent_run_id != prior.id
            or child.agent_id != run.agent_id
            or child.owner_id != run.owner_id
            or child.capability not in {"image.recompose", "image.edit"}
            or child.status != "succeeded"
            or reference_identity(prior) != reference_identity(run)
        ):
            continue
        try:
            scene = saved_variation(prior.parameters.get("image_scene"))
        except ValueError:
            continue
        history.append({"run_id": child.id, **scene.model_dump()})
        if len(history) == 3:
            break
    return history

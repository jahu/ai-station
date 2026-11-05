"""Concrete, bounded scene plans for opt-in recurring reference-image agents."""

import re

from pydantic import Field, field_validator
from sqlalchemy import select

from app.media_text import Description
from app.models import Run


class ImageScene(Description):
    description: str = Field(min_length=1, max_length=2400)
    setting: str = Field(min_length=3, max_length=320)
    pose: str = Field(min_length=3, max_length=320)
    expression: str = Field(min_length=3, max_length=320)

    @field_validator("setting", "pose", "expression")
    @classmethod
    def concrete_choice(cls, value):
        if re.fullmatch(r"(?i)(a |an |the )?(new|different|changed|another)( \w+){0,2}", value):
            raise ValueError(
                "Choose an actual visible setting, body pose or facial expression, not 'different'"
            )
        return value

    def image_prompt(self):
        return (
            "Create a new photograph of the same person shown in the reference images. "
            "Keep recognizable facial identity and the requested appearance. "
            "Use the references for identity, not as a pose or composition to copy. "
            f"Setting: {self.setting}. Body pose: {self.pose}. Facial expression: {self.expression}. "
            f"Visual details: {self.description}"
        )


def signature(scene):
    return tuple(
        " ".join(re.findall(r"\w+", scene[key].casefold())) for key in ("setting", "pose", "expression")
    )


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
            or child.capability != "image.recompose"
            or child.status != "succeeded"
            or reference_identity(prior) != reference_identity(run)
        ):
            continue
        try:
            scene = ImageScene.model_validate(prior.parameters.get("image_scene"))
        except ValueError:
            continue
        history.append({"run_id": child.id, **scene.model_dump()})
        if len(history) == 3:
            break
    return history

"""Freeze a built-in native appearance recipe without changing user request identity."""

from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

PROFILE = "portrait_anchor_v1"


class AppearanceRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: Literal["portrait_anchor_v1"]
    observation: str = Field(pattern=r"^[0-9a-f]{64}$")


def frozen_recipe(plan):
    value = plan.get("appearance_recipe")
    return AppearanceRecipe.model_validate(value).model_dump() if value is not None else None


def select_recipe(profile, body):
    if body.size != 384 or body.steps < 8:
        return None
    recommendation = profile.get("recommended_appearance_profile")
    if recommendation is None:
        return None  # Existing/older native installations retain legacy dispatch.
    if recommendation != PROFILE or not profile.get("available"):
        raise HTTPException(409, "The recommended avatar appearance recipe is unavailable")
    for item in profile.get("appearance_profiles", []):
        if item.get("id") == recommendation and item.get("available"):
            try:
                return AppearanceRecipe.model_validate(
                    {"id": item["id"], "observation": item.get("observation")}
                ).model_dump()
            except ValueError as exc:
                raise HTTPException(409, "Refresh the avatar appearance capability observation") from exc
    raise HTTPException(409, "The recommended avatar appearance recipe is unavailable")


def verify_recipe(profile, recipe):
    if recipe is None:
        return
    expected = AppearanceRecipe.model_validate(recipe).model_dump()
    if not profile.get("available") or not any(
        item.get("available") and {"id": item.get("id"), "observation": item.get("observation")} == expected
        for item in profile.get("appearance_profiles", [])
    ):
        raise HTTPException(409, "Avatar appearance implementation or model changed; start a new job")

"""Reviewed media settings for persistent agents; not an execution entry point."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.image_schema import ImageRequest
from app.music_schema import MusicSettings


class AgentImageScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["image"]
    request: ImageRequest


class AgentMusicRequest(MusicSettings):
    # Receipts and child identity belong to the workflow publisher, not a draft
    # or model. Reuse the existing settings validator without accepting its UUID.
    caption: str = Field(min_length=1, max_length=512)


class AgentMusicScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["music"]
    request: AgentMusicRequest


AgentMediaScope = Annotated[AgentImageScope | AgentMusicScope, Field(discriminator="kind")]

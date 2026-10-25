"""Reviewed media settings for persistent agents; not an execution entry point."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from app.audio_schema import SpeechRequest
from app.avatar_schema import FullAvatarSettings
from app.image_schema import ImageRequest
from app.music_schema import MusicOptions, MusicSettings
from app.video_schema import LongVideoSettings


class AgentImageScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["image"]
    request: ImageRequest
    description_source: Literal["fixed", "goal"] = "fixed"

    @model_validator(mode="after")
    def supported_output(self):
        if self.request.video_prompt:
            raise ValueError("Image agents cannot select an unimplemented video output scope")
        if self.description_source == "goal" and self.request.mode == "upscale":
            raise ValueError("Upscale uses its reviewed source image without a generated description")
        return self


class AgentMusicRequest(MusicOptions):
    # Receipts and child identity belong to the workflow publisher, not a draft
    # or model. Reuse the existing settings validator without accepting its UUID.
    caption: str = Field(min_length=1, max_length=512)


class AgentMusicScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["music"]
    request: AgentMusicRequest
    description_source: Literal["fixed", "goal"] = "fixed"
    lyrics_source: Literal["fixed", "goal"] = "fixed"

    @model_validator(mode="after")
    def reviewed_lyrics_mode(self):
        if self.lyrics_source == "goal":
            if self.description_source != "goal" or self.request.instrumental:
                raise ValueError("Generated lyrics require vocal music and a goal-based description")
        else:
            MusicSettings.model_validate(self.request.model_dump(exclude={"caption"}))
        return self


class AgentSpeechRequest(SpeechRequest):
    # A disabled natural draft has no authority to invent a Library reference.
    # The operator chooses it before activation or execution.
    reference_artifact_id: UUID | None = None


class AgentSpeechScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["speech"]
    request: AgentSpeechRequest
    description_source: Literal["fixed", "goal"] = "fixed"


class AgentVideoRequest(LongVideoSettings):
    # Long settings reject explicitly supplied frames; omit the inherited default
    # from frozen snapshots so its round-trip preserves that public contract.
    # It is not a proposal input: advertising it makes models copy an invalid
    # short-clip default into a duration-based film, even during correction.
    # Keep the inherited explicit-input rejection and snapshot compatibility.
    frames: SkipJsonSchema[int] = Field(default=49, exclude=True)


class AgentVideoScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["video"]
    request: AgentVideoRequest
    description_source: Literal["fixed", "goal"] = "fixed"


class AgentAvatarRequest(FullAvatarSettings):
    image_artifact_id: UUID | None = None
    audio_artifact_id: UUID | None = None


class AgentAvatarScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["avatar"]
    request: AgentAvatarRequest
    description_source: Literal["fixed", "goal"] = "fixed"


AgentMediaScope = Annotated[
    AgentImageScope | AgentMusicScope | AgentSpeechScope | AgentVideoScope | AgentAvatarScope,
    Field(discriminator="kind"),
]


def fixed_media_only(definition):
    return (
        definition.tools == ["create_media"]
        and definition.media is not None
        and definition.media.description_source == "fixed"
    )


def writes_lyrics(scope):
    return scope.kind == "music" and scope.lyrics_source == "goal"

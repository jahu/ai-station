"""Bounded creative text contracts shared by agents and conversation orchestration."""

from pydantic import BaseModel, ConfigDict, Field


class Description(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    description: str = Field(min_length=1, max_length=10000)


class SongDescription(Description):
    lyrics: str = Field(min_length=1, max_length=4096)

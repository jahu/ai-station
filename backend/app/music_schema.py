"""Pure offline music settings; no API, registry or executor imports."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MusicSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    lyrics: str = Field(default="", max_length=4096)
    instrumental: bool = True
    duration_seconds: int = Field(default=30, ge=10, le=600, strict=True)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1, strict=True)
    gpu: str = Field(default="auto", pattern=r"^(auto|[0-9]{1,12})$")

    @model_validator(mode="after")
    def lyrics_match_mode(self):
        if self.instrumental and self.lyrics:
            raise ValueError("Choose instrumental or supplied lyrics")
        if not self.instrumental and not self.lyrics:
            raise ValueError("Provide lyrics for a song with vocals")
        return self

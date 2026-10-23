"""Current-turn music intent and typed settings; never a second executor."""

import re
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, ValidationError, model_serializer, model_validator

from app.music import MusicRequest
from app.music_schema import MusicOptions, MusicSettings

_REQUEST = re.compile(
    r"^(?:(?:please|prosz[eę])\s+)?"
    r"(?:generate|create|make|compose|wygeneruj|stw[oó]rz|utw[oó]rz|skomponuj)\b.{0,80}?\b"
    r"(?:(?:music|songs?|soundtracks?|tracks?|beats?|instrumentals?)\b|"
    r"(?:muzyk|utw[oó]r|piosenk|podk[łl]ad|melodi)\w*)",
    re.I,
)
_OTHER_INTENT = re.compile(
    r"\b(?:prompts?|prompty|promptu|brief\w*|plan\w*|agent\w*|project\w*|projekt\w*|"
    r"code|kod\w*|script\w*|skrypt\w*|website\w*|stron\w*|app|application|aplikacj\w*)\b",
    re.I,
)
_SCOPES = ("github", "coding", "new_project", "continuation", "commit", "publish", "load", "stop")


class MusicScope(MusicOptions):
    # None preserves a duration written in the message; otherwise use 30 s.
    duration_seconds: int | None = Field(default=None, ge=10, le=600, strict=True)
    lyrics_source: Literal["fixed", "goal"] = "fixed"

    @model_validator(mode="after")
    def reviewed_vocals(self):
        if self.lyrics_source == "goal":
            if self.instrumental:
                raise ValueError("Writing lyrics requires vocal music")
        else:
            MusicSettings.model_validate(
                {
                    **self.model_dump(exclude={"lyrics_source"}),
                    "duration_seconds": self.duration_seconds or 30,
                }
            )
        return self

    @model_serializer(mode="wrap")
    def legacy_scope_receipt(self, serializer):
        result = serializer(self)
        if self.lyrics_source == "fixed":
            result.pop("lyrics_source", None)
        return result


def requested(params):
    if params.get("music") is not None:
        return True
    if any(params.get(key) for key in _SCOPES):
        return False
    text = params.get("content", "").strip()
    match = _REQUEST.match(text)
    if not match or _OTHER_INTENT.search(text[: match.end()]):
        return False
    return not re.match(
        r"\s+(?:prompts?|brief\w*|plan\w*|players?|playlists?|generators?|apps?|videos?)\b",
        text[match.end() :],
        re.I,
    )


_INLINE_LYRICS = re.compile(
    r"(?:\n|\s)(?:(?:z|ze)\s+)?(?:lyrics|tekst(?:em)?(?:\s+piosenki)?|s[łl]ow(?:a|ami))\s*:\s*(.+)\Z",
    re.I | re.S,
)
_NO_VOCALS = re.compile(r"\b(?:without (?:vocals|lyrics|words)|bez (?:wokalu|tekstu|s[łl][oó]w))\b", re.I)
_VOCALS = re.compile(r"\b(?:with vocals|with lyrics|z wokalem|z tekstem|ze s[łl]owami)\b", re.I)


def inline_lyrics(params):
    if params.get("music") is not None:
        return None
    match = _INLINE_LYRICS.search(params["content"])
    return (params["content"][: match.start()].rstrip(" .;\n"), match.group(1).strip()) if match else None


def caption(params):
    supplied = inline_lyrics(params)
    return supplied[0] if supplied else params["content"]


def instrumental_intent(text):
    return bool(
        _NO_VOCALS.search(text) or re.search(r"\binstrumental\w*\b", text, re.I) and not _VOCALS.search(text)
    )


def settings(params):
    supplied = inline_lyrics(params)
    text = caption(params)
    if supplied and instrumental_intent(text):
        raise ValueError("Choose instrumental music or supplied vocal lyrics")
    scope = MusicScope.model_validate(
        {"instrumental": False, "lyrics": supplied[1]} if supplied else params.get("music") or {}
    )
    duration = scope.duration_seconds
    if duration is None:
        found = re.findall(
            r"(?<![\w.,])(\d{1,4}(?:[.,]\d+)?)\s*[- ]?\s*"
            r"(seconds?|secs?|sekund\w*|sek|minutes?|minut\w*|min|s)\b",
            text,
            re.I,
        )
        if len(found) > 1:
            raise ValueError("Choose one music duration, or set the length in Generate music")
        duration = 30
        if found:
            number, unit = found[0]
            value = float(number.replace(",", ".")) * (60 if unit.lower().startswith("min") else 1)
            if not value.is_integer() or not 10 <= value <= 600:
                raise ValueError("Choose a whole music duration between 10 and 600 seconds")
            duration = int(value)
        elif re.search(r"\d+\s*(?:hours?|godzin\w*)\b", text, re.I):
            raise ValueError("Music duration must be between 10 and 600 seconds")
    if (
        "instrumental" not in scope.model_fields_set
        and not scope.lyrics
        and re.search(
            r"\b(?:song|piosenk\w*|with vocals|with lyrics|z wokalem|z tekstem|ze słowami)\b",
            text,
            re.I,
        )
        and not instrumental_intent(text)
    ):
        scope = scope.model_copy(update={"lyrics_source": "goal", "instrumental": False})
    return MusicScope.model_validate({**scope.model_dump(), "duration_seconds": duration})


def prepare_turn(body):
    """Reject mixed scopes before provider/worker effects; thinking is model-only."""
    selected = body.action == "audio.music" or body.action == "auto" and requested(body.model_dump())
    if body.music is not None and not selected:
        raise HTTPException(422, "Music settings apply only to Generate music")
    if not selected:
        return body
    if any(
        getattr(body, key, None)
        for key in (
            *_SCOPES,
            "media",
            "attachments",
            "image_artifact_ids",
            "audio_artifact_id",
            "speech_text",
            "upscale_result",
        )
    ):
        raise HTTPException(
            422, "Music uses a description and optional lyrics, without references or other action settings"
        )
    if body.web_search.enabled and (body.web_search.query.strip() or body.web_search.render_pages):
        raise HTTPException(422, "Send exact Web research separately from local music generation")
    try:
        options = settings(body.model_dump(mode="json"))
        if options.lyrics_source == "goal":
            if len(body.content) > 16000:
                raise ValueError("Keep the song-writing instruction within 16000 characters")
        else:
            MusicRequest(
                client_request_id=UUID(int=0),
                caption=caption(body.model_dump(mode="json")),
                **options.model_dump(),
            )
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return body if options.lyrics_source == "goal" else body.model_copy(update={"reasoning": None})

"""Current-turn music intent and typed settings; never a second executor."""

import re
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, ValidationError

from app.music import MusicRequest, MusicSettings

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


class MusicScope(MusicSettings):
    # None preserves a duration written in the message; otherwise use 30 s.
    duration_seconds: int | None = Field(default=None, ge=10, le=600, strict=True)


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


def settings(params):
    scope = MusicScope.model_validate(params.get("music") or {})
    duration = scope.duration_seconds
    if duration is None:
        found = re.findall(
            r"(?<![\w.,])(\d{1,4}(?:[.,]\d+)?)\s*[- ]?\s*"
            r"(seconds?|secs?|sekund\w*|sek|minutes?|minut\w*|min|s)\b",
            params["content"],
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
        elif re.search(r"\d+\s*(?:hours?|godzin\w*)\b", params["content"], re.I):
            raise ValueError("Music duration must be between 10 and 600 seconds")
    if (
        "instrumental" not in scope.model_fields_set
        and not scope.lyrics
        and re.search(
            r"\b(?:song|piosenk\w*|with vocals|with lyrics|z wokalem|z tekstem|ze słowami)\b",
            params["content"],
            re.I,
        )
        and not re.search(
            r"\b(?:instrumental\w*|without vocals|bez wokalu|bez słów)\b", params["content"], re.I
        )
    ):
        raise ValueError(
            "For vocals, choose Generate music and supply your lyrics, or request an instrumental"
        )
    return MusicSettings(**{**scope.model_dump(), "duration_seconds": duration})


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
        MusicRequest(client_request_id=UUID(int=0), caption=body.content, **options.model_dump())
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return body.model_copy(update={"reasoning": None})

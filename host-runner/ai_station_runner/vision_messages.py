"""Inline-only image transport for owned multimodal runtimes; never URLs or paths."""

import base64
import binascii
import io
import warnings
from typing import Annotated, Literal

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_station_runner.local_model import Completion


class InlineImage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(max_length=2800000)

    @model_validator(mode="after")
    def inline_only(self):
        prefix, separator, content = self.url.partition(",")
        signatures = {
            "data:image/png;base64": b"\x89PNG\r\n\x1a\n",
            "data:image/jpeg;base64": b"\xff\xd8\xff",
            "data:image/webp;base64": b"RIFF",
        }
        if not separator or prefix not in signatures:
            raise ValueError("Only inline PNG, JPEG or WebP image data is accepted")
        try:
            decoded = base64.b64decode(content, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid inline image data") from exc
        if not 1 <= len(decoded) <= 2 * 1024 * 1024 or not decoded.startswith(signatures[prefix]):
            raise ValueError("Invalid or oversized inline image")
        if prefix == "data:image/webp;base64" and decoded[8:12] != b"WEBP":
            raise ValueError("Invalid inline image")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(decoded)) as image:
                    expected = {
                        "data:image/png;base64": "PNG",
                        "data:image/jpeg;base64": "JPEG",
                        "data:image/webp;base64": "WEBP",
                    }[prefix]
                    if image.format != expected or image.width * image.height > 4 * 1024 * 1024:
                        raise ValueError("Unsupported image dimensions or format")
                    image.verify()
        except (
            OSError,
            ValueError,
            UnidentifiedImageError,
            Image.DecompressionBombWarning,
            Image.DecompressionBombError,
        ) as exc:
            raise ValueError("Invalid inline image") from exc
        return self


class TextPart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["text"]
    text: str = Field(max_length=100000)


class ImagePart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["image_url"]
    image_url: InlineImage


class VisionMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: (
        Annotated[str, Field(max_length=100000)]
        | Annotated[list[TextPart | ImagePart], Field(min_length=1, max_length=8)]
    )

    @model_validator(mode="after")
    def images_are_user_input(self):
        if isinstance(self.content, list) and self.role != "user":
            raise ValueError("Image parts are only allowed in user input")
        return self


class VisionCompletion(Completion):
    @model_validator(mode="before")
    @classmethod
    def bound_raw_images(cls, data):
        if isinstance(data, dict):
            count, encoded = 0, 0
            messages = data.get("messages", [])
            if not isinstance(messages, list):
                return data
            if len(messages) > 100:
                raise ValueError("Vision message budget exceeded")
            for message in messages:
                content = message.get("content") if isinstance(message, dict) else None
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "image_url":
                            count += 1
                            image = part.get("image_url")
                            url = image.get("url") if isinstance(image, dict) else None
                            encoded += len(url) if isinstance(url, str) else 0
                            if count > 4 or encoded > 11200000:
                                raise ValueError("Vision image budget exceeded")
        return data

    messages: list[VisionMessage] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def bound_context(self):
        characters, images = 0, 0
        for message in self.messages:
            if isinstance(message.content, str):
                characters += len(message.content)
            else:
                for part in message.content:
                    if isinstance(part, TextPart):
                        characters += len(part.text)
                    else:
                        images += 1
        if characters > 128000 or images > 4:
            raise ValueError("Vision input exceeds its context/image limit")
        return self

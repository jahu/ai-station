"""Operator-reviewed SMTP configuration and message envelopes."""

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_MAILBOX = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\.[A-Za-z]{2,24}$"
)
_HOST = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}$")


def mailbox(value):
    if (
        not isinstance(value, str)
        or len(value) > 254
        or not _MAILBOX.fullmatch(value)
        or ".." in value
        or value.startswith(".")
        or ".@" in value
    ):
        raise ValueError("Use a plain ASCII email address without a display name")
    local, host = value.rsplit("@", 1)
    if not _HOST.fullmatch(host):
        raise ValueError("Use a valid email domain")
    return local + "@" + host.lower()


class SMTPSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    host: str = Field(min_length=3, max_length=253)
    transport: Literal["ssl", "starttls"] = "ssl"
    username: str = Field(default="", max_length=254, pattern=r"^[^\r\n\x00]*$")
    sender: str = Field(max_length=254)
    allowed_recipients: list[str] = Field(min_length=1, max_length=10)

    @field_validator("host")
    @classmethod
    def valid_host(cls, value):
        if not _HOST.fullmatch(value):
            raise ValueError("Enter an SMTP hostname, without a URL, path or port")
        return value.lower()

    @field_validator("sender")
    @classmethod
    def valid_sender(cls, value):
        return mailbox(value)

    @field_validator("allowed_recipients")
    @classmethod
    def valid_recipients(cls, values):
        values = [mailbox(v) for v in values]
        if len(set(values)) != len(values):
            raise ValueError("Allowed recipients must be unique")
        return sorted(values)


class EmailDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: UUID
    expected_updated_at: datetime
    recipients: list[str] = Field(min_length=1, max_length=5)
    subject: str = Field(min_length=1, max_length=200, pattern=r"^[^\r\n\x00]+$")
    body: str = Field(min_length=1, max_length=16000)

    @field_validator("recipients")
    @classmethod
    def valid_recipients(cls, values):
        return SMTPSettings.valid_recipients(values)

    @model_validator(mode="after")
    def safe_body(self):
        if "\x00" in self.body:
            raise ValueError("Message body cannot contain null bytes")
        return self

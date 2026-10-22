"""Reviewed deterministic market scope; no arbitrary provider URL or model arguments."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.email_schema import SMTPSettings

PAIR_NAMES = ("BTC-USD", "BTC-EUR", "ETH-USD", "ETH-EUR")


class MarketDataScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connector_id: UUID
    connector_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class MarketEmailScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connector_id: UUID
    connector_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    recipients: list[str] = Field(min_length=1, max_length=5)

    @field_validator("recipients")
    @classmethod
    def valid_recipients(cls, values):
        return SMTPSettings.valid_recipients(values)


class MarketScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["coinbase_exchange", "finnhub"] = "coinbase_exchange"
    instruments: list[str] = Field(default_factory=lambda: ["BTC-USD"], max_length=3)
    feed: MarketDataScope | None = None
    threshold_percent: str = Field(default="5", pattern=r"^\d{1,3}(?:\.\d{1,4})?$", max_length=8)
    direction: Literal["both", "up", "down"] = "both"
    comparison_window_seconds: int = Field(default=172800, ge=60, le=2592000, strict=True)
    cooldown_seconds: int = Field(default=3600, ge=60, le=2592000, strict=True)
    email: MarketEmailScope | None = None

    @model_validator(mode="before")
    @classmethod
    def stock_defaults(cls, value):
        if isinstance(value, dict) and value.get("provider") == "finnhub":
            return {"comparison_window_seconds": 604800, "instruments": [], **value}
        return value

    @model_validator(mode="after")
    def source_scope(self):
        if self.provider == "coinbase_exchange":
            if (
                self.feed is not None
                or not self.instruments
                or any(i not in PAIR_NAMES for i in self.instruments)
            ):
                raise ValueError("Choose Coinbase BTC/ETH instruments without a stock-data account")
        else:
            from app.stock_quotes import stock_symbol

            for instrument in self.instruments:
                stock_symbol(instrument)
        return self

    @field_validator("threshold_percent")
    @classmethod
    def positive_threshold(cls, value):
        if not Decimal("0") < Decimal(value) <= Decimal("100"):
            raise ValueError("Choose a threshold greater than zero and at most 100 percent")
        return format(Decimal(value).normalize(), "f")

    @field_validator("instruments")
    @classmethod
    def unique_instruments(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Choose unique instruments")
        return sorted(value)

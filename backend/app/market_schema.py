"""Reviewed deterministic market scope; no arbitrary provider URL or model arguments."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PAIR_NAMES = ("BTC-USD", "BTC-EUR", "ETH-USD", "ETH-EUR")


class MarketScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["coinbase_exchange"] = "coinbase_exchange"
    instruments: list[Literal["BTC-USD", "BTC-EUR", "ETH-USD", "ETH-EUR"]] = Field(
        default_factory=lambda: ["BTC-USD"], min_length=1, max_length=3
    )
    threshold_percent: str = Field(default="5", pattern=r"^\d{1,3}(?:\.\d{1,4})?$", max_length=8)
    direction: Literal["both", "up", "down"] = "both"
    comparison_window_seconds: int = Field(default=86400, ge=60, le=2592000, strict=True)
    cooldown_seconds: int = Field(default=3600, ge=60, le=2592000, strict=True)

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

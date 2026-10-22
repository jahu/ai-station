"""Pure contract fixtures only; no stock account, network requests or mail."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from app.stock_quotes import StockQuoteError, normalize_finnhub_quote, source_url, stock_symbol

NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)


def page(kind, data):
    return {
        "url": source_url(kind, None if kind == "status" else "AAPL"),
        "status": 200,
        "content_type": "application/json",
        "truncated": False,
        "text": json.dumps(data),
    }


def normalize(*, quote=None, profile=None, status=None):
    return normalize_finnhub_quote(
        page("quote", {"c": 123.456789, "t": int(NOW.timestamp()) - 30, **(quote or {})}),
        page(
            "profile",
            {
                "ticker": "AAPL",
                "currency": "USD",
                "name": "Example company",
                "exchange": "NASDAQ",
                **(profile or {}),
            },
        ),
        page(
            "status",
            {
                "exchange": "US",
                "isOpen": True,
                "session": "regular",
                "timezone": "America/New_York",
                "t": int(NOW.timestamp()),
                **(status or {}),
            },
        ),
        "AAPL",
        now=NOW,
    )


def test_recent_price_uses_exact_decimal_text_and_actual_provider_time():
    result = normalize()
    assert result["price"] == "123.456789"
    assert result["source_at"] == NOW - timedelta(seconds=30)
    assert result["metadata"]["source_time_kind"] == "provider_quote"
    assert result["metadata"]["freshness"] == "recent"
    assert result["metadata"]["market_status_at"] == NOW.isoformat()


def test_closed_weekend_keeps_last_known_time_without_inventing_a_live_trade():
    result = normalize(
        quote={"t": int((NOW - timedelta(days=3)).timestamp())}, status={"isOpen": False, "session": None}
    )
    assert result["metadata"]["freshness"] == "last_known"
    assert result["metadata"]["market_session"] == "closed"
    assert result["source_at"] == NOW - timedelta(days=3)


@pytest.mark.parametrize(
    "quote",
    [
        {"c": 0},
        {"c": -1},
        {"c": True},
        {"c": "123.45"},
        {"c": float("nan")},
        {"c": 1e50},
        {"t": True},
        {"t": 0},
        {"t": int(NOW.timestamp()) + 31},
        {"t": int(NOW.timestamp()) - 301},
    ],
)
def test_invalid_or_nonrecent_open_session_quote_cannot_become_an_observation(quote):
    with pytest.raises(StockQuoteError):
        normalize(quote=quote)


@pytest.mark.parametrize(
    "profile",
    [{"currency": "EUR"}, {"ticker": "OTHER"}, {"name": "x" * 201}, {"exchange": "LONDON STOCK EXCHANGE"}],
)
def test_profile_identity_and_currency_are_checked(profile):
    with pytest.raises(StockQuoteError):
        normalize(profile=profile)


@pytest.mark.parametrize(
    "status",
    [
        {"isOpen": "true"},
        {"exchange": "OTHER"},
        {"t": int(NOW.timestamp()) - 301},
        {"timezone": "not/a/timezone"},
        {"session": "made-up"},
        {"isOpen": False, "session": "regular"},
    ],
)
def test_market_status_is_validated_separately_from_quote_time(status):
    with pytest.raises(StockQuoteError):
        normalize(status=status)


@pytest.mark.parametrize(
    "value", ["../AAPL", "AAPL&token=secret", "BINANCE:BTCUSD", "aapl", "AAPL..US", "AAPL/US"]
)
def test_symbol_cannot_inject_a_path_query_or_other_capability(value):
    with pytest.raises(StockQuoteError):
        stock_symbol(value)


def test_huge_decimal_exponent_is_rejected_before_expanding_into_text():
    quote = page("quote", {})
    quote["text"] = '{"c":1e999999999,"t":' + str(int(NOW.timestamp())) + "}"
    with pytest.raises(StockQuoteError):
        normalize_finnhub_quote(
            quote,
            page("profile", {"ticker": "AAPL", "currency": "USD"}),
            page(
                "status",
                {
                    "exchange": "US",
                    "isOpen": True,
                    "session": "regular",
                    "timezone": "America/New_York",
                    "t": int(NOW.timestamp()),
                },
            ),
            "AAPL",
            now=NOW,
        )


@pytest.mark.parametrize("patch", [{"session": ["regular"]}, {"timezone": "x" * 1000}, {"session": None}])
def test_malformed_session_metadata_returns_a_safe_validation_error(patch):
    with pytest.raises(StockQuoteError):
        normalize(status=patch)

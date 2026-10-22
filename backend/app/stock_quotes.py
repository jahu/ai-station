"""Pure stock-source validation. Not an operational connector until its worker is qualified."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, DecimalException
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BASE_URL = "https://finnhub.io/api/v1"
MAX_KNOWN_AGE = 7 * 24 * 3600
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*$")


class StockQuoteError(ValueError):
    """Public static diagnostics; no raw response, credential or URL in errors."""


def stock_symbol(value):
    if not isinstance(value, str) or len(value) > 15 or not _SYMBOL.fullmatch(value):
        raise StockQuoteError("Choose a supported stock symbol")
    return value


def source_url(operation, symbol=None):
    if operation == "status" and symbol is None:
        return BASE_URL + "/stock/market-status?exchange=US"
    if operation not in {"quote", "profile"}:
        raise StockQuoteError("Unsupported stock data operation")
    endpoint = "/quote" if operation == "quote" else "/stock/profile2"
    return BASE_URL + endpoint + "?" + urlencode({"symbol": stock_symbol(symbol)})


def _invalid_number(_value):
    raise StockQuoteError("Stock data contains a non-finite number")


def _page(page, operation, symbol=None):
    if (
        not isinstance(page, dict)
        or page.get("url") != source_url(operation, symbol)
        or page.get("status") != 200
        or page.get("content_type") != "application/json"
        or page.get("truncated")
        or not isinstance(page.get("text"), str)
        or len(page["text"]) > 8000
    ):
        raise StockQuoteError("Stock provider response is unavailable or unsupported")
    try:
        value = json.loads(page["text"], parse_float=Decimal, parse_constant=_invalid_number)
    except (ValueError, TypeError, DecimalException) as exc:
        raise StockQuoteError("Stock provider returned invalid JSON data") from exc
    if not isinstance(value, dict):
        raise StockQuoteError("Stock provider returned an unsupported data object")
    return value


def _time(value, now, *, maximum_age):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise StockQuoteError("Stock data is missing a valid provider timestamp")
    try:
        result = datetime.fromtimestamp(value, timezone.utc)
    except (ValueError, OverflowError, OSError) as exc:
        raise StockQuoteError("Stock provider timestamp is out of range") from exc
    if not -30 <= (now - result).total_seconds() <= maximum_age:
        raise StockQuoteError("Stock provider timestamp is stale or in the future")
    return result


def normalize_finnhub_quote(quote_page, profile_page, status_page, symbol, *, now):
    """Keep vendor quote time distinct from fetch/current-market-status time."""
    symbol = stock_symbol(symbol)
    if now.tzinfo is None:
        raise StockQuoteError("Stock validation requires a timezone-aware clock")
    quote = _page(quote_page, "quote", symbol)
    profile = _page(profile_page, "profile", symbol)
    status = _page(status_page, "status")
    if profile.get("ticker") != symbol or profile.get("currency") != "USD":
        raise StockQuoteError("Stock profile does not match the reviewed USD instrument")
    if status.get("exchange") != "US" or not isinstance(status.get("isOpen"), bool):
        raise StockQuoteError("Stock market status does not match the reviewed exchange")
    session = status.get("session")
    zone = status.get("timezone")
    if (
        session is not None
        and not isinstance(session, str)
        or session not in {None, "regular", "pre-market", "post-market"}
        or not isinstance(zone, str)
        or len(zone) > 80
        or not re.fullmatch(r"[A-Za-z_]+(?:/[A-Za-z0-9_+.-]+){0,4}", zone)
        or status["isOpen"]
        and session is None
    ):
        raise StockQuoteError("Stock provider returned invalid session metadata")
    try:
        ZoneInfo(zone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise StockQuoteError("Stock provider returned an unsupported market timezone") from exc
    status_at = _time(status.get("t"), now, maximum_age=300)
    regular = status["isOpen"] and session == "regular"
    as_of = _time(quote.get("t"), now, maximum_age=300 if regular else MAX_KNOWN_AGE)
    price = quote.get("c")
    if isinstance(price, bool) or not isinstance(price, (int, Decimal)):
        raise StockQuoteError("Stock quote does not contain a numeric price")
    price = Decimal(price)
    # Bound exponents before formatting: a tiny JSON number such as 1e999999999
    # must not allocate an enormous string in the control-plane worker.
    if not price.is_finite() or price <= 0 or price.adjusted() > 23 or price.as_tuple().exponent < -18:
        raise StockQuoteError("Stock quote price is invalid")
    price = format(price, "f")
    name = profile.get("name")
    if name is None or name == "":
        name = symbol
    exchange = profile.get("exchange")
    if exchange is None:
        exchange = ""
    if not isinstance(name, str) or len(name) > 200 or not isinstance(exchange, str) or len(exchange) > 160:
        raise StockQuoteError("Stock profile labels exceed the supported bounds")
    return {
        "instrument": symbol,
        "price": price,
        "source_at": as_of,
        "source_sequence": str(quote["t"]),
        "source_url": source_url("quote", symbol),
        "metadata": {
            "provider": "finnhub",
            "currency": "USD",
            "source_time_kind": "provider_quote",
            "market_status_at": status_at.isoformat(),
            "market_session": session or "closed",
            "market_open": status["isOpen"],
            "timezone": zone,
            "freshness": "recent" if (now - as_of).total_seconds() <= 300 else "last_known",
            "company_name": name,
            "exchange": exchange,
        },
    }

"""Calendar schedules resolve wall-clock occurrences to durable UTC instants."""

import re
from datetime import UTC, datetime
from functools import lru_cache
from importlib.resources import files
from typing import Annotated
from zoneinfo import ZoneInfo

from croniter import croniter
from pydantic import AfterValidator, Field


@lru_cache(maxsize=1)
def timezones():
    return frozenset(files("tzdata").joinpath("zones").read_text().splitlines()) | {"UTC"}


def validate_timezone(value):
    if value not in timezones():
        raise ValueError("Choose an available IANA timezone, such as Europe/Warsaw or UTC")
    ZoneInfo(value)
    return value


def instruction_timezone(instruction, selected):
    validate_timezone(selected)
    explicit_utc = re.search(
        r"\b(?:at|o)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*utc\b(?!\s*[+-]\s*\d)",
        instruction,
        re.I,
    )
    return "UTC" if explicit_utc else selected


ScheduleTimezone = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(validate_timezone)]


def next_cron(expression, zone_name, after):
    validate_timezone(zone_name)
    zone = ZoneInfo(zone_name)
    if after.tzinfo is None:
        raise ValueError("Schedule instants require an explicit timezone")
    after = after.astimezone(UTC)
    try:
        horizon = after.replace(year=after.year + 5)
    except ValueError:
        horizon = after.replace(year=after.year + 5, day=28)
    wall = after.astimezone(zone).replace(tzinfo=None)
    iterator = croniter(expression, wall, max_years_between_matches=5)
    # A full skipped/repeated date is at most 1440 wall-clock minutes.
    for _ in range(2048):
        candidate = iterator.get_next(datetime)
        instant = candidate.replace(tzinfo=zone, fold=0).astimezone(UTC)
        if instant > horizon:
            break
        if instant <= after:
            continue
        if instant.astimezone(zone).replace(tzinfo=None) != candidate:
            continue  # This wall-clock minute did not exist.
        return instant
    raise ValueError("Cron must have a valid occurrence within five years")

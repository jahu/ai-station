"""User cadence wins over model defaults without changing unrelated settings."""

import pytest
from app.draft_schedule import schedule_values


@pytest.mark.parametrize(
    "instruction,trigger,cron,seconds",
    [
        ("Co 15 minut generuj mi zdjęcie gór.", "cron", "*/15 * * * *", None),
        ("co 5 minut twórz ilustrację", "cron", "*/5 * * * *", None),
        ("Every 30 minutes create an image", "cron", "*/30 * * * *", None),
        ("Co 2 godziny przygotuj raport", "cron", "0 */2 * * *", None),
        ("Co 90 minut przygotuj raport", "interval", "", 5400),
        ("Every 45 minutes prepare a report", "interval", "", 2700),
        ("Co rano o 08:30 przygotuj raport", "cron", "30 8 * * *", None),
        ("Codziennie o08:00 przygotuj raport", "cron", "0 8 * * *", None),
    ],
)
def test_explicit_cadence_overrides_manual_or_conflicting_model(instruction, trigger, cron, seconds):
    for proposal in (
        {"trigger": "manual"},
        {"trigger": "cron", "cron_expr": "0 9 * * *", "interval_seconds": 17},
    ):
        result = schedule_values({**proposal, "name": "Preserved"}, instruction=instruction)
        assert result == {
            "trigger": trigger,
            "cron_expr": cron,
            "interval_seconds": seconds,
            "run_at": None,
            "name": "Preserved",
        }


def test_unspecified_schedule_keeps_model_interpretation_and_clears_inactive_fields():
    result = schedule_values(
        {"trigger": "cron", "cron_expr": "0 9 * * *", "interval_seconds": 30},
        instruction="Prepare a helpful report",
    )
    assert result["cron_expr"] == "0 9 * * *" and result["interval_seconds"] is None

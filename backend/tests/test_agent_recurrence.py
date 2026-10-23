"""Quick drafts must preserve explicit elapsed-time cadence without inference."""

import pytest
from app.api import app
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    ("instruction", "seconds"),
    [
        ("Every 5 minutes check workstation status", 300),
        ("Co 5 minut sprawdzaj stan stacji", 300),
        ("Every 1 minute check workstation status", 60),
        ("Co 1 minutę sprawdzaj stan stacji", 60),
        ("Every minute check workstation status", 60),
        ("Co minutę sprawdzaj stan stacji", 60),
        ("Every 90 seconds check workstation status", 90),
        ("Co 90 sekund sprawdzaj stan stacji", 90),
        ("Every 1 hour check workstation status", 3600),
        ("Co godzinę sprawdzaj stan stacji", 3600),
        ("Every 12 hours check workstation status", 43200),
        ("Co 2 godziny sprawdzaj stan stacji", 7200),
        ("Every 120 minutes check workstation status", 7200),
        ("Every 200 hours check workstation status", 720000),
        ("Every 31536000 seconds check workstation status", 31536000),
    ],
)
def test_quick_draft_preserves_explicit_interval_and_stays_disabled(instruction, seconds):
    with TestClient(app) as client:
        result = client.post(
            "/api/agents/draft",
            json={"instruction": instruction, "schedule_timezone": "Europe/Warsaw"},
        )
        assert result.status_code == 201, result.text
        agent = result.json()
        assert agent["trigger"] == "interval" and agent["interval_seconds"] == seconds
        assert agent["cron_expr"] == "" and agent["run_at"] is None
        assert not agent["enabled"] and agent["next_run_at"] is None
        assert agent["schedule_timezone"] == "Europe/Warsaw" and agent["goal"] == instruction
        assert client.get("/api/runs").json() == []


@pytest.mark.parametrize(
    "amount",
    ["0", "30", "59", "31536001", "99999999999999999999999999999999999999999999", "-60", "1.5"],
)
def test_unsupported_interval_is_not_clamped_or_activated(amount):
    with TestClient(app) as client:
        response = client.post(
            "/api/agents/draft", json={"instruction": f"Every {amount} seconds check workstation"}
        )
        assert response.status_code == 201, response.text
        agent = response.json()
        assert agent["trigger"] == "manual" and agent["interval_seconds"] is None
        assert not agent["enabled"] and agent["next_run_at"] is None
        assert client.get("/api/runs").json() == []


def test_oversized_numeric_interval_does_not_raise_or_become_a_clock_schedule():
    with TestClient(app) as client:
        for count in ("0", "9" * 5000):
            response = client.post(
                "/api/agents/draft",
                json={"instruction": f"Every {count} minutes at 09:00 check workstation"},
            )
            assert response.status_code == 201, response.text
            agent = response.json()
            assert agent["trigger"] == "manual" and agent["interval_seconds"] is None
            assert not agent["enabled"] and agent["next_run_at"] is None

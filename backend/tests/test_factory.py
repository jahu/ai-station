from app.api import app
from app.factory import draft_agent
from fastapi.testclient import TestClient


def test_factory_copies_policies_schedules_and_quoted_query_without_enabling():
    api = TestClient(app)
    draft = api.post(
        "/api/agents/draft",
        json={
            "instruction": (
                "Weekdays at 07:15 UTC require approval, gated inspect tools first, "
                'allow retry, notify on failure, remember reports, and search for "public gpu news". '
                "Call tools to summarize workstation memory."
            ),
            "model": "fake-local",
        },
    ).json()
    assert draft["enabled"] is False and draft["next_run_at"] is None
    assert draft["trigger"] == "cron" and draft["cron_expr"] == "15 7 * * 1-5"
    assert draft["require_approval"] is True
    assert draft["workflow_mode"] == "gated"
    assert draft["retry_policy"] == {"mode": "manual"}
    assert draft["notification_policy"] == {
        "on_success": False,
        "on_failure": True,
        "on_approval": False,
    }
    assert draft["tool_calling"] == "bounded"
    assert draft["search_query"] == "public gpu news"
    assert "remember_report" in draft["tools"]
    assert "memory_search" in draft["tools"]
    assert "web_search" in draft["tools"]
    assert "system_snapshot" in draft["tools"]
    assert (
        api.post(
            f"/api/agents/{draft['id']}/enabled",
            json={"enabled": True, "expected_updated_at": draft["updated_at"]},
        ).status_code
        == 422
    )
    assert api.get(f"/api/agents/{draft['id']}").json()["enabled"] is False


def test_factory_interval_one_shot_and_weekly_phrases_stay_disabled():
    hours = draft_agent("Every 6 hours summarize workstation GPU")
    assert hours.enabled is False
    assert hours.trigger == "interval" and hours.interval_seconds == 21600
    assert hours.tools == ["system_snapshot"]
    weekly = draft_agent("Every monday at 14:30 UTC summarize memory")
    assert weekly.trigger == "cron" and weekly.cron_expr == "30 14 * * 1"
    assert weekly.enabled is False
    once = draft_agent("Once at 2030-01-15T09:00:00Z check GPU workstation status")
    assert once.trigger == "datetime"
    assert once.run_at is not None and once.run_at.tzinfo is not None
    assert once.enabled is False
    evening = draft_agent("Co wieczór sprawdź stacji GPU")
    assert evening.trigger == "cron" and evening.cron_expr == "0 20 * * *"
    minutes = draft_agent("Every 90 minutes check hardware")
    assert minutes.trigger == "interval" and minutes.interval_seconds == 5400
    too_short = draft_agent("Every 30 minutes check hardware")
    assert too_short.trigger == "manual" and too_short.interval_seconds is None


def test_unrecognized_instruction_stays_manual_and_silent():
    agent = draft_agent("Write a short local summary")
    assert agent.enabled is False
    assert agent.trigger == "manual"
    assert agent.tools == []
    assert agent.require_approval is False
    assert agent.workflow_mode == "sequential"
    assert agent.tool_calling == "none"
    assert agent.retry_policy == {"mode": "none"}
    assert agent.notification_policy == {
        "on_success": False,
        "on_failure": False,
        "on_approval": False,
    }

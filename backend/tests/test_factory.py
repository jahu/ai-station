import pytest
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
                "allow retry, notify on failure, remember reports, remember workflow observations, "
                'and search for "public gpu news". '
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
    assert "remember_workflow" in draft["tools"]
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


@pytest.mark.parametrize(
    "instruction",
    [
        "Codziennie sprawdzaj ceny akcji Apple i wyślij email do private@example.com",
        "Every day check stock prices AAPL and Bitcoin and email private@example.com",
    ],
)
def test_stock_examples_draft_public_research_without_choosing_an_account(instruction):
    agent = draft_agent(instruction, model="fake-local")
    assert agent.tools == ["web_search"]
    assert agent.market is None and agent.model == "fake-local"
    assert not agent.enabled and agent.search_query == "" and agent.fetch_urls == []
    assert "do not claim email delivery" in agent.output_expectation


def test_stock_research_preserves_reviewed_query_or_public_page():
    query = draft_agent('Daily check stock prices; search for "Apple stock price"', model="fake-local")
    assert query.tools == ["web_search"] and query.search_query == "Apple stock price"
    page = draft_agent("Daily check stock prices on https://example.com/prices", model="fake-local")
    assert page.tools == ["http_fetch"] and page.fetch_urls == ["https://example.com/prices"]
    assert page.market is None and not page.enabled


def test_crypto_price_watch_keeps_its_existing_keyless_source():
    agent = draft_agent("Every day check Bitcoin prices")
    assert agent.tools == ["market_watch"] and agent.market["provider"] == "coinbase_exchange"
    assert agent.market["instruments"] == ["BTC-USD"] and agent.model == ""


@pytest.mark.parametrize("subject", ["stock", "Bitcoin"])
def test_price_data_in_a_spreadsheet_stays_an_offline_python_task(subject):
    agent = draft_agent(f"Analyze {subject} prices in this CSV spreadsheet")
    assert agent.tools == ["python_data"] and agent.model == "auto"
    assert agent.market is None and not agent.search_query and not agent.fetch_urls

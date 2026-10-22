"""Explicit public-read acceptance. No GPU, model, credentials, trading or email."""

import json
import os
from pathlib import Path

import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.models import MarketObservation, Run
from fastapi.testclient import TestClient
from sqlalchemy import select


@pytest.mark.skipif(
    os.getenv("AI_STATION_REAL_MARKET_TESTS") != "1", reason="Explicit public quote opt-in required"
)
def test_real_public_quote_through_agent_api_and_worker():
    with TestClient(app) as client:
        response = client.post(
            "/api/agents",
            json={
                "name": "Public quote acceptance",
                "goal": "Observe BTC-USD",
                "tools": ["market_watch"],
                "market": {},
                "enabled": True,
            },
        )
        assert response.status_code == 201, response.text
        agent = response.json()
        queued = client.post(
            f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]}
        )
        assert queued.status_code == 202, queued.text
        with session_factory()() as session:
            for _ in range(8):
                if not tick(session, "real-market-acceptance"):
                    break
            runs = list(
                session.scalars(
                    select(Run).where(Run.parent_run_id == queued.json()["id"]).order_by(Run.created_at)
                )
            )
            assert len(runs) == 4
            assert all(r.status == "succeeded" for r in runs), [(r.status, r.error_message) for r in runs]
            result = runs[-1].metadata_json["market_result"]
            assert result["rows"][0]["status"] == "baseline"
            assert result["email_sent"] is False and result["notice_ids"] == []
            quote = session.scalar(select(MarketObservation).where(MarketObservation.agent_id == agent["id"]))
            assert quote and quote.source_url == "https://api.exchange.coinbase.com/products/BTC-USD/ticker"
            evidence = {
                "passed": True,
                "public_provider": True,
                "normal_api_worker": True,
                "isolated_database": True,
                "model_used": False,
                "gpu_used": False,
                "external_messages_sent": False,
                "result": result,
                "run_ids": [r.id for r in runs],
            }
            if os.getenv("AI_STATION_MARKET_EVIDENCE"):
                Path(os.environ["AI_STATION_MARKET_EVIDENCE"]).write_text(json.dumps(evidence, indent=2))

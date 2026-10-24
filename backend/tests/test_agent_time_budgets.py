"""A reviewed multi-hour budget does not renew at child dispatch or create work."""

import pytest
from app.agent_drafts import Proposal
from app.agent_schema import AgentSettings
from app.api import app
from fastapi.testclient import TestClient


@pytest.mark.parametrize("runtime", [5, 600, 7200, 14400])
def test_reviewed_runtime_round_trips_through_definition_update_and_duplicate(runtime):
    with TestClient(app) as client:
        response = client.post(
            "/api/agents", json={"name": "Reviewed budget", "goal": "Report only", "maximum_runtime": runtime}
        )
        assert response.status_code == 201, response.text
        row = response.json()
        assert row["maximum_runtime"] == runtime and not row["enabled"]
        changed = client.put(
            f"/api/agents/{row['id']}",
            json={
                **{key: row[key] for key in AgentSettings.model_fields if key in row},
                "expected_updated_at": row["updated_at"],
                "description": "Preserve exact saved budget",
            },
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["maximum_runtime"] == runtime
        copied = client.post(
            f"/api/agents/{row['id']}/duplicate", json={"expected_updated_at": changed.json()["updated_at"]}
        )
        assert copied.status_code == 201 and copied.json()["maximum_runtime"] == runtime
        assert not copied.json()["enabled"]
        assert client.get("/api/runs").json() == []


@pytest.mark.parametrize("schema", [AgentSettings, Proposal])
@pytest.mark.parametrize("runtime", [4, 14401, 2.5, float("nan"), float("inf")])
def test_definitions_and_assisted_proposals_reject_unbounded_or_invalid_budgets(schema, runtime):
    with pytest.raises(ValueError):
        schema(name="Review first", goal="A bounded goal", maximum_runtime=runtime)


def test_existing_default_and_assisted_proposal_budget_do_not_increase_implicitly():
    assert AgentSettings(name="Existing", goal="Preserve").maximum_runtime == 600
    assert Proposal(name="Draft", goal="Review").maximum_runtime == 600
    proposal = Proposal(name="Long draft", goal="Review before enabling", maximum_runtime=7200)
    assert proposal.maximum_runtime == 7200

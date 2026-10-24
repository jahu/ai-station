"""Creation from instructions needs explicit intent, never dummy file inputs."""

import pytest
from app.agent_schema import AgentSettings
from app.conversation_data_schema import DataScope
from app.data_schema import AgentDataScope
from pydantic import ValidationError


def test_conversation_can_explicitly_create_files_without_uploaded_or_public_inputs():
    scope = DataScope(operation="create")
    assert scope.input_artifact_ids == [] and scope.research is None
    assert scope.files().model_dump(mode="json") == {
        "input_artifact_ids": [],
        "max_repairs": 1,
        "operation": "create",
    }


def test_persistent_agent_can_draft_explicit_file_creation_without_inputs():
    agent = AgentSettings(
        name="Create a workbook",
        goal="Create an XLSX with the integers 1 to 10 and their squares",
        model="auto",
        tools=["python_data"],
        data={"operation": "create", "input_artifact_ids": []},
    )
    assert agent.data.operation == "create" and not agent.enabled


@pytest.mark.parametrize("scope", [AgentDataScope, DataScope])
def test_missing_analysis_inputs_remain_invalid_without_an_explicit_creation_operation(scope):
    with pytest.raises(ValidationError):
        scope.model_validate({"input_artifact_ids": []})

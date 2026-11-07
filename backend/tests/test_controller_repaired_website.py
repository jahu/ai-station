"""A verified bounded repair remains successful without hiding failed history."""

# Reused disposable repository/sandbox fixtures keep their public parameter names.
# ruff: noqa: F811
from types import SimpleNamespace

import pytest
from app.api import app
from app.assistant_controller_tools import observation
from app.coding_tasks import queue_validation
from app.db import session_factory
from app.engine import tick
from app.models import Message, Run
from app.runs import create_run
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_projects import owned_runner, repository, validation_sandbox  # noqa: F401
from test_website_output_validation import website_source


@pytest.mark.parametrize("repaired", [False, True])
def test_controller_observes_current_validation_and_preserves_superseded_failure(
    repository, owned_runner, validation_sandbox, repaired
):
    script = (
        "from pathlib import Path; Path('dist').mkdir(exist_ok=True); "
        "Path('dist/index.html').write_text('<h1>Checked repaired site</h1>') "
        "if Path('build.py').exists() else None"
    )
    with TestClient(app) as api:
        cid = api.post("/api/chat/conversations", json={"model": "fixture-local"}).json()["id"]
        source_id, first_id, workspace = website_source(api, repository, owned_runner, script, repair=True)
        with session_factory()() as s:
            source = s.get(Run, source_id)
            source.task.conversation_id = cid
            for row in s.scalars(select(Run).where(Run.task_id == source.task_id)):
                row.conversation_id = cid
            wrapper = create_run(
                s,
                source.task,
                run_type="orchestration",
                capability="assistant.orchestrate",
                executor_type="orchestrator",
                parameters={},
            )
            wrapper.status = "succeeded"
            s.get(Run, source.parent_run_id).parent_run_id = wrapper.id
            s.add(
                Message(
                    conversation_id=cid,
                    run_id=wrapper.id,
                    role="assistant",
                    content="Building",
                    metadata_json={"orchestration": True},
                )
            )
            s.commit()
            assert tick(s, "first-site-check") == first_id
            first = s.get(Run, first_id)
            assert first.status == "failed"
            repair = s.get(Run, first.metadata_json["repair_run_id"])
            # Fake model work stays inside the selected disposable source scope.
            if repaired:
                (workspace / "build.py").write_text("# Corrected selected build source\n")
            repair.status = "succeeded"
            repair.metadata_json = {
                **repair.metadata_json,
                "coding_review": {"files": [{"path": "build.py"}]},
            }
            queue_validation(s, repair, prepared=True)
            second_id = repair.metadata_json["validation_run_id"]
            s.commit()
            assert tick(s, "repaired-site-check") == second_id
            second = s.get(Run, second_id)
            assert second.status == ("succeeded" if repaired else "failed")
            root = SimpleNamespace(owner_id=wrapper.owner_id, conversation_id=cid)
            active, result = observation(
                s, root, {"index": 1, "tool": "project.create_code", "run_id": wrapper.id}
            )
            assert not active and result["status"] == second.status
            assert result["recovered_errors"][0]["error"] == first.error_message[:500]
            assert bool(result["errors"]) is not repaired
            assert ("archive" in result["produced_types"]) is repaired
            assert first.status == "failed" and first.error_message
    assert not (repository / "build.py").exists()

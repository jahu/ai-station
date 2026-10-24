"""Graph publication, generation and delivery have distinct inspectable outcomes."""

import pytest
from app.agent_outcome import workflow_outcome
from app.models import Agent
from app.runs import create_run, create_task
from test_conversation_agent_control import saved as saved


def graph(session, *, tools=None):
    agent = Agent(name="Outcome agent", goal="Produce a result", model="fake-local")
    session.add(agent)
    session.flush()
    task = create_task(
        session, title="Outcome", prompt="Produce a result", capability="agent", agent_id=agent.id
    )
    root = create_run(
        session,
        task,
        run_type="agent",
        capability="agent.workflow",
        executor_type="agent_workflow",
        agent_id=agent.id,
        parameters={"definition": {"tools": tools or []}},
    )
    root.status = "succeeded"
    session.flush()
    return root


def child(session, root, executor="agent", status="succeeded", **parameters):
    run = create_run(
        session,
        root.task,
        run_type="agent",
        capability="agent.result",
        executor_type=executor,
        agent_id=root.agent_id,
        parent_run_id=root.id,
        parameters=parameters,
    )
    run.status = status
    session.flush()
    return run


@pytest.mark.parametrize(
    "status", ["failed", "interrupted", "canceled", "running", "waiting_for_approval", "queued"]
)
def test_publisher_success_does_not_hide_actual_stage_state(session, status):
    root = graph(session)
    report = child(session, root, status=status)
    value = workflow_outcome(session, root)
    assert value["status"] == status and value["result_run_id"] == report.id
    assert root.status == "succeeded"  # Projection never rewrites the execution journal.


def test_publication_without_a_result_is_not_completion(session):
    root = graph(session)
    child(session, root, executor="agent_tool")
    assert workflow_outcome(session, root)["status"] == "interrupted"


def test_cancel_request_has_deterministic_priority_over_other_active_work(session):
    root = graph(session)
    child(session, root, status="queued")
    child(session, root, executor="agent_tool", status="running")
    child(session, root, executor="browser", status="cancel_requested")
    assert workflow_outcome(session, root)["status"] == "cancel_requested"


@pytest.mark.parametrize("status", ["waiting_for_approval", "failed", "canceled", "succeeded"])
def test_email_outcome_is_separate_from_completed_generation(session, status):
    root = graph(session)
    report = child(session, root)
    delivery = child(session, root, executor="email_send", status=status)
    delivery.parent_run_id = report.id
    if status == "canceled":
        root.task.metadata_json = {"stop_requested_at": "2026-10-25T12:00:00+00:00"}
    value = workflow_outcome(session, root)
    assert value == {
        "status": "succeeded",
        "result_run_id": report.id,
        "delivery_status": status,
        "delivery_run_id": delivery.id,
    }


def test_delivery_preparation_failure_does_not_erase_report(session):
    root = graph(session)
    report = child(session, root)
    report.metadata_json = {"result_email": {"state": "preparation_failed"}}
    assert workflow_outcome(session, root)["delivery_status"] == "failed"
    assert workflow_outcome(session, root)["status"] == "succeeded"


@pytest.mark.parametrize("valid", [True, False])
def test_only_linked_coding_repair_supersedes_failed_validation(session, valid):
    root = graph(session, tools=["coding_local"])
    proposal = child(session, root, executor="local_proposal", commands=[["pytest"]])
    validation = child(session, root, executor="project_validation", status="failed")
    validation.parent_run_id = proposal.id
    repair = child(
        session,
        root,
        executor="local_proposal",
        commands=[["pytest"]],
        repair_source_run_id=proposal.id,
        repair_validation_run_id=validation.id if valid else "wrong",
    )
    repair.parent_run_id = validation.id
    proposal.metadata_json = {"repair_run_id": repair.id}
    validation.metadata_json = {"repair_run_id": repair.id}
    final = child(session, root, executor="project_validation")
    final.parent_run_id = repair.id
    assert workflow_outcome(session, root)["status"] == ("succeeded" if valid else "failed")


@pytest.mark.parametrize("valid", [True, False])
def test_data_repair_replaces_only_its_own_failed_python_attempt(session, valid):
    root = graph(session, tools=["python_data"])
    python = child(session, root, executor="python", status="failed")
    old = child(
        session,
        root,
        executor="agent_data_result",
        python_run_id=python.id,
        agent_data={"attempt": 0, "inputs": ["one"]},
    )
    old.parent_run_id = python.id
    repair = child(
        session,
        root,
        executor="agent_data_generate",
        agent_data={"attempt": 1, "inputs": ["one" if valid else "other"]},
    )
    repair.parent_run_id = old.id
    old.metadata_json = {"repair_run_id": repair.id}
    child(session, root, executor="agent_data_result")
    assert workflow_outcome(session, root)["status"] == ("succeeded" if valid else "failed")


@pytest.mark.parametrize("status", ["waiting_for_approval", "failed", "canceled"])
def test_conversation_uses_completed_report_while_delivery_is_separate(saved, monkeypatch, status):
    from app.agent_result_context import reference
    from app.db import session_factory
    from app.models import Message, Run
    from test_agent_result_context import REPORT, completed

    mid, rid, _ = completed(saved, monkeypatch)
    with session_factory()() as db:
        report = db.get(Run, rid)
        root = db.get(Run, report.parent_run_id)
        delivery = child(db, root, executor="email_send", status=status)
        delivery.parent_run_id = report.id
        if status == "canceled":
            root.task.metadata_json = {"stop_requested_at": "2026-10-25T12:00:00+00:00"}
        text, provenance = reference(db, db.get(Message, mid))
        assert provenance["available"] and provenance["status"] == "succeeded"
        assert provenance["run_id"] == report.id and REPORT in text


@pytest.mark.parametrize(
    "kind,executor",
    [
        ("image", "photo_pipe"),
        ("music", "ace_step_music"),
        ("speech", "chatterbox"),
        ("video", "media_compose"),
        ("avatar", "media_compose"),
    ],
)
def test_media_requires_its_final_output_stage_not_just_preparation(session, kind, executor):
    root = graph(session)
    root.parameters = {"definition": {"tools": ["create_media"], "media": {"kind": kind}}}
    child(session, root, executor="agent_media")
    assert workflow_outcome(session, root)["status"] == "interrupted"
    final = child(session, root, executor=executor)
    assert workflow_outcome(session, root) == {"status": "succeeded", "result_run_id": final.id}

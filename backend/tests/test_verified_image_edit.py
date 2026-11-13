import io
import json
import tempfile
from pathlib import Path

import pytest
from app.api import app
from app.artifacts import register_file
from app.db import session_factory
from app.engine import tick
from app.executors import EXECUTORS
from app.local_provider import LocalChatProvider
from app.models import Artifact, Run
from app.photo_executor import PhotoPipeExecutor
from app.runs import request_cancel, transition
from app.state import RunStatus
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin
from sqlalchemy import select
from test_agent_media import implemented_media as implemented_media
from test_vision import vision_runtime as vision_runtime


@pytest.fixture
def edit_runtime(vision_runtime, monkeypatch):
    state = {"photos": 0, "reviews": 0, "identical_first": False, "verdict": "passed"}

    async def stream(self, **parameters):
        content = parameters["messages"][0]["content"]
        text = content[0]["text"] if isinstance(content, list) else content
        payload = json.loads(text.rsplit("\n", 1)[1])
        title = payload["schema"]["title"]
        if state.get("invalid_json") and len(parameters["messages"]) == 1:
            state["invalid_json"] = False
            yield '{"invalid":'
            return
        state.setdefault("stages", []).append(title)
        if title == "SourceInspection":
            yield json.dumps(
                {
                    "references": [
                        {"index": i, "description": "A red rectangle, original color and shape visible."}
                        for i in payload["indices"]
                    ]
                }
            )
        elif title == "CandidateObservation":
            assert "user_request" not in payload and "instruction" not in payload
            assert "previous_observation" not in payload
            assert len([part for part in content if part["type"] == "image_url"]) == 1
            yield json.dumps(
                {
                    "description": "A blue rectangle.",
                    "framing": "The complete rectangle is visible inside the frame.",
                    "clipped_elements": [],
                    "uncertainty": "",
                }
            )
        elif title == "ReviewConsistency":
            assert isinstance(content, str)
            assert payload["candidate_observation"] and payload["proposed_review"]
            yield json.dumps(
                {
                    "verdict": state["audit_verdicts"].pop(0)
                    if state.get("audit_verdicts")
                    else state.get("audit_verdict", "consistent"),
                    "evidence": "Compared the proposed verdict with the independently observed visible extent.",
                }
            )
        elif title == "EditPlan":
            yield json.dumps(
                {
                    "visual": {
                        "description": "A blue rectangle.",
                        "preserve": ["rectangular shape"],
                        "changes": {"color": "blue instead of the original red"},
                    },
                    "reference_layout": state.get("plan_layout"),
                    "base_reference_index": 0,
                    "criteria": [
                        {
                            "kind": "change",
                            "expected": "The rectangle is blue rather than red",
                            "reference_indices": [0],
                        },
                        {
                            "kind": "preserve",
                            "expected": state.get("preserve_expected", "The rectangular shape is retained"),
                            "reference_indices": [0],
                        },
                    ],
                }
            )
        elif title == "EditReview":
            state["reviews"] += 1
            assert payload["candidate_observation"]["description"] == "A blue rectangle."
            labels = [part["text"] for part in content[1:] if part["type"] == "text"]
            assert labels[-1].startswith("CANDIDATE")
            assert all(label.startswith("ORIGINAL REFERENCE index ") for label in labels[:-1])
            yield json.dumps(
                {
                    "request_verdict": state.get("request_verdict", state["verdict"]),
                    "request_evidence": "Compared actual original and candidate against the original requested change.",
                    "checks": [
                        {
                            "criterion_index": int(i),
                            "verdict": state["verdict"]
                            if c["kind"] == "change"
                            else state.get("preserve_verdict", "passed"),
                            "evidence": "Observed candidate compared with the original reference.",
                        }
                        for i, c in payload["criteria"].items()
                    ],
                    "correction": "Make the requested color change clearly visible.",
                }
            )
        else:
            raise AssertionError(title)

    monkeypatch.setattr(LocalChatProvider, "stream", stream)

    class Photo:
        name = "photo_pipe"

        def execute(self, session, run):
            state["photos"] += 1
            transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
            transition(session, run, RunStatus.RUNNING, event_type="executor.started")
            image = Image.new(
                "RGB", (512, 768), "red" if state["identical_first"] and state["photos"] == 1 else "blue"
            )
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text("attempt", str(state["photos"]))
            with tempfile.NamedTemporaryFile(suffix=".png") as output:
                image.save(output.name, pnginfo=metadata)
                artifact = register_file(
                    session,
                    source=Path(output.name),
                    artifact_type="image",
                    mime_type="image/png",
                    original_filename="attempt.png",
                    run_id=run.id,
                    parent_artifact_ids=run.parameters["parent_artifact_ids"],
                    metadata={"width": 512, "height": 768, "seed": run.parameters["seed"]},
                )
            PhotoPipeExecutor().on_success(session, run, artifact)
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
            return "done"

    state["executors"] = {**EXECUTORS, "photo_pipe": Photo()}
    return state


def submit(client, **changes):
    output = io.BytesIO()
    Image.new("RGB", (512, 768), "red").save(output, "PNG")
    source = client.post(
        "/api/images/uploads", files={"file": ("rectangle.png", output.getvalue(), "image/png")}
    ).json()
    response = client.post(
        "/api/images/runs",
        json={
            "mode": "img2img",
            "backend": "qwen",
            "edit_prompt": "Change red to blue; keep the shape",
            "verify_changes": True,
            "input_artifact_ids": [source["id"]],
            **changes,
        },
    )
    assert response.status_code == 202, response.text
    return response.json(), source


def drain(state):
    for _ in range(70):
        with session_factory()() as session:
            if tick(session, "verified-edit-test", executors=state["executors"]) is None:
                return
    raise AssertionError("Edit queue did not drain")


def test_verified_edit_uses_real_workflow_and_only_publishes_accepted_candidate(edit_runtime):
    with TestClient(app) as client:
        root, source = submit(client)
        assert root["executor_type"] == "image_edit"
        assert edit_runtime["photos"] == 0
        drain(edit_runtime)
        result = client.get(f"/api/runs/{root['id']}").json()
        assert result["status"] == "succeeded", result.get("error_message")
        assert edit_runtime["photos"] == edit_runtime["reviews"] == 1
        accepted_api = client.get(f"/api/artifacts?run_id={root['id']}")
        assert accepted_api.status_code == 200
        assert [a["id"] for a in accepted_api.json()] == result["metadata"]["accepted_artifact_ids"]
        workflow = client.get(f"/api/images/runs/{root['id']}/workflow").json()
        assert workflow["steps"][-1]["executor_type"] == "photo_pipe"
        with session_factory()() as session:
            accepted = session.get(Artifact, result["metadata"]["accepted_artifact_ids"][0])
            assert accepted.parent_artifact_ids == [source["id"]]
            assert accepted.metadata_json["image_edit_review"]["status"] == "accepted"
            assert (
                len(
                    list(
                        session.scalars(
                            select(Artifact).where(Artifact.relative_path == accepted.relative_path)
                        )
                    )
                )
                == 1
            )


@pytest.mark.parametrize("backend", ["qwen", "krea2"])
@pytest.mark.parametrize("seed", [None, 42])
def test_identical_pixels_are_rejected_even_when_png_metadata_differs_then_corrected(
    edit_runtime, backend, seed, monkeypatch
):
    changes = {"backend": backend}
    if backend == "krea2":
        from test_image_models import registered

        with session_factory()() as session:
            model, _ = registered(session)
            changes["model_id"] = model.id
            session.commit()
    if seed is not None:
        changes["seed"] = seed
    else:
        monkeypatch.setattr("app.images.secrets.randbits", lambda _: 41)
    edit_runtime["identical_first"] = True
    with TestClient(app) as client:
        root, source = submit(client, **changes)
        drain(edit_runtime)
        result = client.get(f"/api/runs/{root['id']}").json()
        assert result["status"] == "succeeded", result.get("error_message")
        assert edit_runtime["photos"] == 2
        assert edit_runtime["reviews"] == 1  # No model opinion can approve unchanged pixels.
        with session_factory()() as session:
            attempts = result["metadata"]["edit_attempts"]
            first = session.scalar(select(Artifact).where(Artifact.run_id == attempts[0]["photo_run"]))
            assert first.sha256 != source["sha256"]
            assert first.metadata_json["image_edit_review"]["status"] == "rejected"
            photos = [session.get(Run, a["photo_run"]) for a in attempts]
            assert all(r.parameters["parent_artifact_ids"] == [source["id"]] for r in photos)
            if seed is None:
                assert photos[0].parameters["seed"] != photos[1].parameters["seed"]
                assert all(r.parameters["seed"] != 42 for r in photos)
            else:
                assert all(r.parameters["seed"] == seed for r in photos)


@pytest.mark.parametrize("verdict,expected_photos", [("failed", 2), ("uncertain", 1)])
def test_unverified_changes_never_become_success_or_final_preview(edit_runtime, verdict, expected_photos):
    edit_runtime["verdict"] = verdict
    with TestClient(app) as client:
        root, _ = submit(client)
        drain(edit_runtime)
        result = client.get(f"/api/runs/{root['id']}").json()
        assert result["status"] == "failed", result
        assert result["error_type"] == "ImageEditNotVerified", result.get("error_message")
        assert not result["metadata"].get("accepted_artifact_ids")
        assert edit_runtime["photos"] == expected_photos
        assert len(client.get(f"/api/images/runs/{root['id']}/workflow").json()["steps"]) == 1


@pytest.mark.parametrize(
    "explicit,preserve_failed,preset_strength",
    [
        ({}, False, None),
        ({"reference_strength": 3}, False, None),
        ({"grounding_px": 768}, False, None),
        ({}, True, None),
        ({}, False, 0),
    ],
)
def test_krea_correction_only_relaxes_automatic_controls_after_preservation_passes(
    edit_runtime, explicit, preserve_failed, preset_strength
):
    from test_image_models import registered

    with session_factory()() as session:
        model, _ = registered(session)
        if preset_strength is not None:
            model.metadata_json = {
                "image": {
                    **model.metadata_json["image"],
                    "presets": {"recompose": {"reference_strength": preset_strength}},
                }
            }
        model_id = model.id
        session.commit()
    edit_runtime["verdict"] = "failed"
    if preserve_failed:
        edit_runtime["preserve_verdict"] = "failed"
    with TestClient(app) as client:
        root, _ = submit(client, backend="krea2", model_id=model_id, **explicit)
        drain(edit_runtime)
        result = client.get(f"/api/runs/{root['id']}").json()
        assert result["status"] == "failed" and result["error_type"] == "ImageEditNotVerified"
        with session_factory()() as session:
            first, second = [session.get(Run, a["photo_run"]) for a in result["metadata"]["edit_attempts"]]
            for field, adjusted in (("reference_strength", 1), ("grounding_px", 512)):
                assert second.parameters[field] == (
                    first.parameters[field]
                    if preserve_failed
                    or field in explicit
                    or (field == "reference_strength" and preset_strength == 0)
                    else adjusted
                )
            assert first.parameters["model_id"] == second.parameters["model_id"] == model_id
            assert first.parameters["parent_artifact_ids"] == second.parameters["parent_artifact_ids"]


@pytest.mark.parametrize("verdict,attempts", [("contradicted", 2), ("uncertain", 1)])
def test_inconsistent_passed_visual_review_cannot_publish_a_success(edit_runtime, verdict, attempts):
    edit_runtime["audit_verdict"] = verdict
    with TestClient(app) as client:
        root, _ = submit(client)
        drain(edit_runtime)
        result = client.get(f"/api/runs/{root['id']}").json()
        assert result["status"] == "failed" and result["error_type"] == "ImageEditNotVerified"
        assert not result["metadata"].get("accepted_artifact_ids")
        assert edit_runtime["photos"] == attempts
        assert all(attempt["audit_runs"] for attempt in result["metadata"]["edit_attempts"])


def test_conflicting_observation_is_rechecked_once_before_regenerating(edit_runtime):
    edit_runtime["audit_verdicts"] = ["contradicted", "consistent"]
    with TestClient(app) as client:
        root, _ = submit(client)
        drain(edit_runtime)
        result = client.get(f"/api/runs/{root['id']}").json()
        assert result["status"] == "succeeded", result
        assert edit_runtime["photos"] == 1
        attempt = result["metadata"]["edit_attempts"][0]
        assert attempt["observation_recheck_run"] and len(attempt["recheck_audit_runs"]) == 1


def test_stop_waiting_edit_cancels_owned_stages_without_publishing_photo(edit_runtime):
    with TestClient(app) as client:
        root, _ = submit(client)
        with session_factory()() as session:
            tick(session, "verified-edit-test", executors=edit_runtime["executors"])
            request_cancel(session, session.get(Run, root["id"]))
            session.commit()
        drain(edit_runtime)
        assert client.get(f"/api/runs/{root['id']}").json()["status"] == "canceled"
        assert edit_runtime["photos"] == 0


def test_format_repair_does_not_repeat_generation(edit_runtime):
    edit_runtime["invalid_json"] = True
    with TestClient(app) as client:
        root, _ = submit(client)
        drain(edit_runtime)
        result = client.get(f"/api/runs/{root['id']}").json()
        assert result["status"] == "succeeded", result.get("error_message")
        assert edit_runtime["photos"] == 1


def test_eight_references_are_inspected_in_bounded_groups(edit_runtime):
    with TestClient(app) as client:
        _, source = submit(client)
        root, _ = submit(client, input_artifact_ids=[source["id"]] * 8)
        # Duplicate references are still numbered deliberately; no reference
        # is silently dropped to satisfy the vision model's four-image bound.
        drain(edit_runtime)
        result = client.get(f"/api/runs/{root['id']}").json()
        assert result["status"] == "succeeded", result.get("error_message")
        assert len(result["metadata"]["inspect_runs"]) == 2


def test_source_changed_after_enqueue_cannot_render(edit_runtime):
    with TestClient(app) as client:
        root, source = submit(client)
        with session_factory()() as session:
            artifact = session.get(Artifact, source["id"])
            artifact.sha256 = "0" * 64
            session.commit()
        drain(edit_runtime)
        result = client.get(f"/api/runs/{root['id']}").json()
        assert result["status"] == "failed"
        assert edit_runtime["photos"] == 0


def test_failed_edit_retry_is_a_new_bounded_workflow_and_idempotent(edit_runtime):
    from uuid import uuid4

    edit_runtime["verdict"] = "failed"
    with TestClient(app) as client:
        root, source = submit(client)
        drain(edit_runtime)
        identity = {"client_request_id": str(uuid4())}
        response = client.post(f"/api/images/runs/{root['id']}/retry", json=identity)
        assert response.status_code == 202, response.text
        retry = response.json()
        assert retry["executor_type"] == "image_edit"
        assert retry["parameters"]["input_artifact_ids"] == [source["id"]]
        assert client.post(f"/api/images/runs/{root['id']}/retry", json=identity).json()["id"] == retry["id"]
        edit_runtime["verdict"] = "passed"
        drain(edit_runtime)
        assert client.get(f"/api/runs/{retry['id']}").json()["status"] == "succeeded"
        assert client.get(f"/api/runs/{root['id']}").json()["status"] == "failed"


def test_claim_recovery_reuses_stage_identity_without_replaying_native_execution(edit_runtime):
    from app.image_edits import recover_control

    with TestClient(app) as client:
        root, _ = submit(client)
        with session_factory()() as session:
            tick(session, "verified-edit-test", executors=edit_runtime["executors"])
            row = session.get(Run, root["id"])
            # Simulate loss after a later claim, retaining durable child pointers.
            transition(session, row, RunStatus.CLAIMED, event_type="run.claimed")
            previous = row.metadata_json["inspect_runs"]
            recover_control(session, row)
            assert row.status == "queued"
            assert row.metadata_json["inspect_runs"] == previous
            session.commit()
        drain(edit_runtime)
        result = client.get(f"/api/runs/{root['id']}").json()
        assert result["status"] == "succeeded", result.get("error_message")
        assert edit_runtime["photos"] == 1
        assert result["metadata"]["inspect_runs"] == previous


@pytest.mark.parametrize("count", [1, 2])
@pytest.mark.parametrize("verdict", ["passed", "failed"])
def test_current_react_chat_uses_verified_edit_and_cannot_bypass_its_attempt_bound(
    edit_runtime, monkeypatch, verdict, count
):
    from uuid import uuid4

    from app import assistant_decisions

    original_infer = assistant_decisions.infer
    decisions = []
    aliases = [f"input:image:{i + 1}" for i in range(count)]
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["test-model"])
    edit_runtime["verdict"] = verdict

    async def controller_infer(session, run, messages, *, json_output=True):
        if run.executor_type != "assistant_decision":
            return await original_infer(session, run, messages, json_output=json_output)
        if isinstance(messages[0]["content"], str) and messages[0]["content"].startswith(
            "Infer the user's requested outcomes"
        ):
            return json.dumps(
                {
                    "reason": "Change the supplied rectangle's color",
                    "immediate": [
                        {
                            "kind": "image",
                            "count": 1,
                            "description": "Make the supplied red rectangle blue",
                            "reference_mode": "provided",
                            "source_inputs": aliases,
                        }
                    ],
                }
            )
        decisions.append(run.id)
        if len(decisions) == 1:
            return "Thought: Edit the supplied references.\nAction: image_edit\nAction Input: " + json.dumps(
                {"instruction": "Change red to blue; keep the shape", "images": aliases}
            )
        return "Thought: The edit was verified.\nAnswer: The edited image is ready."

    monkeypatch.setattr(assistant_decisions, "infer", controller_infer)
    with TestClient(app) as client:
        data = io.BytesIO()
        Image.new("RGB", (512, 768), "red").save(data, "PNG")
        source = client.post(
            "/api/images/uploads", files={"file": ("red.png", data.getvalue(), "image/png")}
        ).json()
        references = [source["id"]]
        if count == 2:
            other = io.BytesIO()
            Image.new("RGB", (512, 768), "green").save(other, "PNG")
            references.append(
                client.post(
                    "/api/images/uploads", files={"file": ("green.png", other.getvalue(), "image/png")}
                ).json()["id"]
            )
        response = client.post(
            "/api/chat/turns",
            json={
                "client_request_id": str(uuid4()),
                "selection": {"execution_mode": "assistant", "model": "test-model"},
                "execution_mode": "assistant",
                "content": "Make this rectangle blue",
                "image_artifact_ids": references,
                "web_search": {"enabled": False},
            },
        )
        assert response.status_code == 202, response.text
        root = response.json()["run"]
        drain(edit_runtime)
        result = client.get(f"/api/runs/{root['id']}").json()
        assert result["status"] == ("succeeded" if verdict == "passed" else "failed"), result.get(
            "error_message"
        )
        with session_factory()() as session:
            edits = list(
                session.scalars(
                    select(Run).where(
                        Run.conversation_id == root["conversation_id"], Run.executor_type == "image_edit"
                    )
                )
            )
            assert len(edits) == 1, [
                (
                    r.executor_type,
                    r.status,
                    r.error_message,
                    r.parameters.get("verify_image_changes"),
                    r.parameters.get("controller_verified_edits"),
                )
                for r in session.scalars(select(Run).where(Run.task_id == root["task_id"]))
            ]
            assert edits[0].parameters["user_request"] == "Make this rectangle blue"
        assert edit_runtime["photos"] == (1 if verdict == "passed" else 2)
        if verdict == "failed":
            assert len(decisions) == 1
            assert result["error_type"] == "ImageEditNotVerified"


def test_original_goal_check_can_reject_even_if_generated_criteria_pass(edit_runtime):
    edit_runtime["request_verdict"] = "failed"
    edit_runtime["preserve_verdict"] = "not_required"
    with TestClient(app) as client:
        root, _ = submit(client)
        drain(edit_runtime)
        result = client.get(f"/api/runs/{root['id']}").json()
        assert result["status"] == "failed"
        assert result["error_type"] == "ImageEditNotVerified"
        assert edit_runtime["photos"] == 2
        assert client.get(f"/api/artifacts?run_id={root['id']}").json() == []


def test_accepted_edit_history_survives_trash_without_delivering_deleted_bytes(edit_runtime):
    from app.image_edits import accepted_artifacts

    with TestClient(app) as client:
        root, _ = submit(client)
        drain(edit_runtime)
        accepted = client.get(f"/api/artifacts?run_id={root['id']}").json()[0]
        response = client.request(
            "DELETE",
            f"/api/artifacts/{accepted['id']}",
            json={"expected_updated_at": accepted["library_updated_at"]},
        )
        assert response.status_code == 200, response.text
        history = client.get(f"/api/artifacts?run_id={root['id']}")
        assert history.status_code == 200
        assert history.json()[0]["trashed_at"]
        with session_factory()() as session:
            with pytest.raises(ValueError, match="unavailable"):
                accepted_artifacts(session, session.get(Run, root["id"]))


def test_image_agent_publishes_only_verified_result_and_uses_accepted_file_for_delivery(
    edit_runtime, implemented_media, monkeypatch
):
    from app.agent_email_results import verified_result
    from app.agent_schema import AgentSettings
    from app.runner_client import RunnerClient
    from test_agent_media import create, start

    original_request = RunnerClient.request

    def capabilities(self, method, path, body=None):
        if method == "GET" and path == "/v1/photo/capabilities":
            return {
                "available": True,
                "backends": ["qwen"],
                "modes": ["t2i", "img2img", "recompose", "upscale"],
            }
        return original_request(self, method, path, body)

    monkeypatch.setattr(RunnerClient, "request", capabilities)

    with TestClient(app) as client:
        data = io.BytesIO()
        Image.new("RGB", (512, 768), "red").save(data, "PNG")
        source = client.post(
            "/api/images/uploads", files={"file": ("red.png", data.getvalue(), "image/png")}
        ).json()
        agent = create(
            client,
            kind="image",
            request={
                "mode": "img2img",
                "verify_changes": True,
                "backend": "qwen",
                "edit_prompt": "Change red to blue; keep the shape",
                "input_artifact_ids": [source["id"]],
            },
        )
        root = start(client, agent)
        drain(edit_runtime)
        from app.agent_outcome import workflow_outcome

        with session_factory()() as session:
            workflow = workflow_outcome(session, session.get(Run, root["id"]))
        assert workflow["status"] == "succeeded", workflow
        result = client.get(f"/api/runs/{workflow['result_run_id']}").json()
        assert result["executor_type"] == "image_edit"
        accepted = result["metadata"]["accepted_artifact_ids"]
        assert [row["id"] for row in client.get(f"/api/artifacts?run_id={result['id']}").json()] == accepted
        notices = client.get("/api/notices").json()
        assert not any(
            row["kind"] == "succeeded"
            and row["run_id"] in [attempt["photo_run"] for attempt in result["metadata"]["edit_attempts"]]
            for row in notices
        )
        with session_factory()() as session:
            parent = session.get(Run, root["id"])
            report = verified_result(
                session,
                session.get(Run, result["id"]),
                parent,
                AgentSettings.model_validate(parent.parameters["definition"]),
                media_metadata_only=True,
            )
            assert accepted[0] in json.dumps(report)


def test_generated_qwen_layout_hint_is_omitted_without_changing_brief_or_repeating_render(edit_runtime):
    edit_runtime["plan_layout"] = "aligned"
    with TestClient(app) as client:
        root, _ = submit(client)
        drain(edit_runtime)
        result = client.get(f"/api/runs/{root['id']}").json()
        assert result["status"] == "succeeded", result.get("error_message")
        assert edit_runtime["photos"] == 1
        with session_factory()() as session:
            plan = session.get(Run, result["metadata"]["edit_plan_run"])
            assert plan.metadata_json["edit_result"]["reference_layout"] is None
            assert plan.metadata_json["edit_result"]["visual"]["changes"] == {
                "color": "blue instead of the original red"
            }
            from app.models import RunEvent

            assert session.scalar(
                select(RunEvent).where(
                    RunEvent.run_id == plan.id, RunEvent.event_type == "image.edit.plan.control_omitted"
                )
            )


def test_incidental_preservation_cannot_block_a_verified_user_goal(edit_runtime):
    edit_runtime["preserve_verdict"] = "not_required"
    edit_runtime["preserve_expected"] = "Retain an incidental texture that the user never asked to keep"
    with TestClient(app) as client:
        root, _ = submit(client)
        drain(edit_runtime)
        result = client.get(f"/api/runs/{root['id']}").json()
        assert result["status"] == "succeeded", result.get("error_message")
        assert edit_runtime["photos"] == 1


def test_not_required_cannot_bypass_a_requested_change(edit_runtime):
    edit_runtime["verdict"] = "not_required"
    edit_runtime["request_verdict"] = "passed"
    with TestClient(app) as client:
        root, _ = submit(client)
        drain(edit_runtime)
        result = client.get(f"/api/runs/{root['id']}").json()
        assert result["status"] == "failed"
        assert not result["metadata"].get("accepted_artifact_ids")
        assert edit_runtime["photos"] == 1

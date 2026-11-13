"""Durable, bounded inspect → plan → render → review image editing."""

import asyncio
import hashlib
import io
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from PIL import Image, ImageOps
from sqlalchemy import select

from app.artifacts import register_file
from app.db import utcnow
from app.dependencies import depend_on
from app.events import append_event
from app.image_edit_contract import (
    AUDIT_REVIEW,
    INSPECT,
    OBSERVE_CANDIDATE,
    PLAN,
    REVIEW,
    CandidateObservation,
    EditPlan,
    EditReview,
    ReviewConsistency,
    SourceInspection,
)
from app.image_models import choice, defaults, frozen_model, resolve_request
from app.image_schema import ImageRequest
from app.models import Artifact, Run
from app.permissions import permissions_for, require
from app.providers import ProviderError
from app.python_execution import read_owned_file
from app.run_transactions import RunStopped, database_step, database_step_sync
from app.runs import create_run, create_task, mark_failed, transition
from app.state import RunStatus
from app.task_control import lock_task
from app.vision_inputs import freeze, verify

NAME = "image_edit"
REASON = "image_edit_reason"


def checked_sources(session, snapshots):
    if not isinstance(snapshots, list) or not 1 <= len(snapshots) <= 8:
        raise ValueError("Edit requires one to eight frozen original references")
    for offset in range(0, len(snapshots), 4):
        verify(session, snapshots[offset : offset + 4], read_bytes=True)


def enqueue_edit(session, body, *, task=None, parent_run_id=None):
    """No provider or native execution in the request transaction."""
    if body.translation and body.translation.review:
        raise HTTPException(
            422, "Verified Edit plans changes automatically; prompt-only review uses legacy editing"
        )
    ids = [str(i) for i in body.input_artifact_ids]
    for identity in ids:
        source = session.get(Artifact, identity)
        if source is None:
            raise HTTPException(404, "Source image not found")
        if source.artifact_type != "image" or source.mime_type not in {
            "image/png",
            "image/jpeg",
            "image/webp",
        }:
            raise HTTPException(422, "Edit references must be PNG, JPEG or WebP images")
        if source.trashed_at is not None or source.purged_at is not None or source.purge_run_id:
            raise HTTPException(422, "An edit reference is unavailable")
    sources = freeze(session, ids)
    identifier = (
        str(body.model_id)
        if body.model_id
        else body.backend
        if "backend" in body._explicit_fields
        else defaults(session)["choices"]["img2img"]
    )
    if body.model_selection == "auto":
        from app.image_models import recommendation

        suggested = recommendation(session, "recompose", body.edit_prompt or body.prompt, len(ids))
        if (
            body.model_selection_revision is not None
            and body.model_selection_revision != suggested["revision"]
        ):
            raise HTTPException(409, "Image defaults changed; refresh before editing")
        identifier = suggested["choice"]["id"]
    model = choice(session, identifier)
    mode = "recompose" if "recompose" in model["modes"] else "img2img"
    if len(ids) > model["maximum_references"] or mode == "img2img" and len(ids) != 1:
        raise HTTPException(422, "The selected model cannot use this many edit references")
    instruction = body.edit_prompt or body.prompt
    user_request = instruction
    prior_edits = []
    explicit_controls = body._explicit_fields & {"reference_layout", "reference_strength", "grounding_px"}
    parent = session.get(Run, parent_run_id) if parent_run_id else None
    if parent and parent.executor_type == "orchestrator" and parent.parameters.get("controller_parent_id"):
        from app.assistant_controller import verify_wrapper

        wrapper = session.get(Run, parent.parent_run_id)
        verify_wrapper(session, wrapper)
        controller = session.get(Run, parent.parameters["controller_parent_id"])
        if wrapper.metadata_json.get("child_run_id") != parent.id or controller.owner_id != parent.owner_id:
            raise ValueError("The edit instruction lost its originating conversation")
        user_request = controller.parameters["controller_request"]["content"]
        # Conversation tools expose layout only; other values came from the
        # selected model preset, not an explicit operator tuning decision.
        explicit_controls -= {"reference_strength", "grounding_px"}
        from app.assistant_controller_tools import subtree

        for step in controller.metadata_json.get("controller_steps", [])[-8:]:
            if step.get("tool") not in {"image.edit", "image.recompose"} or not step.get("observation"):
                continue
            for prior in subtree(session, controller, step["run_id"]):
                if prior.executor_type == NAME and prior.status == "succeeded":
                    plan_run = child(session, prior, prior.metadata_json["edit_plan_run"])
                    prior_edits.append(
                        {
                            "changes": plan_run.metadata_json["edit_result"]["visual"]["changes"],
                            "accepted_artifact_ids": prior.metadata_json.get("accepted_artifact_ids", []),
                        }
                    )
    elif parent and parent.executor_type == "agent_media":
        user_request = (parent.parameters.get("definition") or {}).get("goal") or instruction
    values = {key: getattr(body, key) for key in body._explicit_fields}
    for key in ("model_selection", "model_selection_revision", "verify_changes"):
        values.pop(key, None)
    values.update(
        mode=mode,
        backend=model["backend"],
        prompt=instruction,
        edit_prompt=instruction,
        input_artifact_ids=ids,
        prompt_style="instruction",
    )
    if model.get("definition_id"):
        values["model_id"] = model["definition_id"]
    first = session.get(Artifact, ids[0])
    if mode == "recompose" and not (body._explicit_fields & {"width", "height"}):
        width, height = first.metadata_json.get("width"), first.metadata_json.get("height")
        if type(width) is not int or type(height) is not int or min(width, height) <= 0:
            raise HTTPException(422, "The source image needs verified dimensions")
        maximum = body.max_side or (1024 if model["backend"] == "krea2" else 1216)
        scale = max(min(1.0, maximum / max(width, height)), 256 / min(width, height))
        values.update(width=round(width * scale / 32) * 32, height=round(height * scale / 32) * 32)
    deadline = utcnow() + timedelta(hours=2)
    if parent and parent.parameters.get("execution_deadline_at"):
        deadline = min(deadline, datetime.fromisoformat(parent.parameters["execution_deadline_at"]))
    request, binding = resolve_request(session, ImageRequest(**values))
    task = task or create_task(
        session, title=instruction[:80], prompt=instruction, capability="image.edit", intent="image"
    )
    run = create_run(
        session,
        task,
        run_type="image",
        capability="image.edit",
        executor_type=NAME,
        execution_target="container",
        requested_gpu=body.gpu,
        requested_resources={},
        permissions=permissions_for("image_generation"),
        retry_class="safe",
        parent_run_id=parent_run_id,
        parameters={
            **request.model_dump(mode="json"),
            "verify_changes": True,
            "original_instruction": instruction,
            "user_request": user_request,
            "prior_edits": prior_edits[-8:],
            "source_inputs": sources,
            "selected_model": identifier,
            "frozen_model": binding,
            "explicit_controls": sorted(explicit_controls),
            "execution_deadline_at": deadline.isoformat(),
        },
        metadata={"edit_phase": "Inspecting references", "edit_attempts": []},
    )
    return run


def child(session, root, identity):
    row = session.get(Run, identity)
    if (
        row is None
        or row.parent_run_id != root.id
        or row.task_id != root.task_id
        or row.owner_id != root.owner_id
    ):
        raise ValueError("Edit child provenance changed")
    return row


def result(session, root, identity):
    row = child(session, root, identity)
    if row.status != "succeeded" or row.executor_type != REASON:
        from app.redact import redact

        raise ValueError(
            "Local edit inspection or review did not complete: " + redact(row.error_message)[:1000]
        )
    return row.metadata_json["edit_result"]


def enqueue_reason(session, root, key, stage, payload, ids=()):
    row = session.scalar(
        select(Run).where(Run.task_id == root.task_id, Run.operation_key == f"edit:{root.id}:{key}")
    )
    request_hash = hashlib.sha256(
        json.dumps({"stage": stage, "payload": payload, "ids": list(ids)}, sort_keys=True).encode()
    ).hexdigest()
    if row is not None:
        row = child(session, root, row.id)
        if row.parameters.get("request_hash") != request_hash:
            raise ValueError("An edit stage identity changed")
        return row
    row = create_run(
        session,
        root.task,
        run_type="planning",
        capability="image.edit." + stage,
        executor_type=REASON,
        execution_target="container",
        operation_key=f"edit:{root.id}:{key}",
        parent_run_id=root.id,
        permissions=["filesystem_read", "workspace_write"],
        retry_class="safe",
        parameters={
            "stage": stage,
            "payload": payload,
            "request_hash": request_hash,
            "vision_artifact_ids": list(ids),
            "vision_inputs": freeze(session, ids) if ids else [],
            "source_inputs": root.parameters["source_inputs"],
            "execution_deadline_at": root.parameters["execution_deadline_at"],
        },
    )
    from app.chat_providers import BUILTIN_KEY, snapshot_provider
    from app.vision import prepare_runtime

    runtime, model, projector, load = prepare_runtime(session, row)
    append_event(
        session,
        row.id,
        "vision.model_selected",
        {
            "model_file_id": model.id,
            "projector_file_id": projector.id,
            "location": "local",
            "image_ids": list(ids),
        },
    )
    row.parameters = {
        **row.parameters,
        **snapshot_provider(session, SimpleNamespace(provider=BUILTIN_KEY, model="llamacpp:" + model.id)),
        "endpoint": runtime.endpoint,
        "model": "llamacpp:" + model.id,
        "max_tokens": 4096,
        "temperature": 0.1,
    }
    if load:
        depend_on(session, row, load)
    elif runtime.status != "ready":
        depend_on(session, row, session.get(Run, runtime.metadata_json["load_run_id"]))
    return row


def waiting(session, root, rows, phase):
    root.metadata_json = {**root.metadata_json, "edit_phase": phase}
    root.summary = phase
    transition(
        session,
        root,
        RunStatus.WAITING_FOR_TOOL,
        event_type="image.edit.waiting",
        payload={"phase": phase, "run_ids": [r.id for r in rows]},
    )
    root.worker_id = None
    root.lease_expires_at = None
    for row in rows:
        depend_on(session, root, row, require_success=False)


def review_tag(artifact, root, status):
    artifact.metadata_json = {
        **artifact.metadata_json,
        "image_edit_review": {"root_id": root.id, "status": status},
    }


class ImageEditExecutor:
    name = NAME

    def execute(self, session, run):
        require(run.effective_permissions, "filesystem_read")
        require(run.effective_permissions, "workspace_write")
        lock_task(session, run.task)
        session.refresh(run)
        if run.status == "cancel_requested" or run.task.metadata_json.get("stop_requested_at"):
            if run.status != "cancel_requested":
                from app.runs import request_cancel

                request_cancel(session, run)
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        # The coordinator publishes children and phase pointers atomically.
        self.advance(session, run)
        return "done"

    def advance(self, session, root):
        sources = root.parameters["source_inputs"]
        checked_sources(session, sources)
        _, binding = frozen_model(session, root.parameters["selected_model"], root.parameters["mode"])
        if binding != root.parameters["frozen_model"]:
            raise ValueError("The selected edit model changed; review its selection")
        state = dict(root.metadata_json)
        if "inspect_runs" not in state:
            rows = []
            for offset in range(0, len(sources), 4):
                subset = sources[offset : offset + 4]
                rows.append(
                    enqueue_reason(
                        session,
                        root,
                        f"inspect:{offset}",
                        "inspect",
                        {
                            "instruction": root.parameters["original_instruction"],
                            "indices": list(range(offset, offset + len(subset))),
                        },
                        [i["artifact_id"] for i in subset],
                    )
                )
            root.metadata_json = {**state, "inspect_runs": [r.id for r in rows]}
            waiting(session, root, rows, "Inspecting references")
            return
        observations = [
            item for rid in state["inspect_runs"] for item in result(session, root, rid)["references"]
        ]
        attempts = list(state.get("edit_attempts", []))
        attempt = len(attempts) or 1
        plan_id = state.get("edit_plan_run")
        if not plan_id:
            row = enqueue_reason(
                session,
                root,
                f"plan:{attempt}",
                "plan",
                {
                    "instruction": root.parameters["original_instruction"],
                    "user_request": root.parameters["user_request"],
                    "prior_edits": root.parameters["prior_edits"],
                    "references": observations,
                    "backend": root.parameters["backend"],
                    "feedback": state.get("edit_feedback", []),
                    "reference_count": len(sources),
                },
            )
            root.metadata_json = {**state, "edit_plan_run": row.id}
            waiting(session, root, [row], "Planning the changes")
            return
        plan = EditPlan.model_validate(result(session, root, plan_id))
        if plan.base_reference_index >= len(sources) or any(
            any(type(i) is not int or not 0 <= i < len(sources) for i in c.reference_indices)
            or len(set(c.reference_indices)) != len(c.reference_indices)
            for c in plan.criteria
        ):
            raise ValueError("Edit plan uses an unavailable reference")
        if not attempts or "photo_run" not in attempts[-1]:
            from app.images import create_image_run, fresh_seed

            values = {k: v for k, v in root.parameters.items() if k in ImageRequest.model_fields}
            values.update(
                verify_changes=False, upscale_result=False, video_prompt=None, translation={"mode": "off"}
            )
            prompt = plan.visual.image_prompt()
            values.update(prompt=prompt, edit_prompt=prompt)
            if attempts and values["backend"] == "krea2" and state.get("edit_relax_references"):
                adjusted = {}
                for field, maximum in (("reference_strength", 1.0), ("grounding_px", 512)):
                    if field not in root.parameters["explicit_controls"]:
                        values[field] = min(values.get(field) or maximum, maximum)
                        adjusted[field] = values[field]
                if adjusted:
                    append_event(
                        session,
                        root.id,
                        "image.edit.reference_adjusted",
                        {
                            "reason": "Requested changes failed while preservation checks passed",
                            "controls": adjusted,
                        },
                    )
            if attempts and values.get("seed") is None:
                # A correction is a new visual attempt, not a transport retry.
                # Freeze a distinct seed before dispatch; explicit seeds keep authority.
                previous_attempt = next(a for a in reversed(attempts) if a.get("photo_run"))
                previous = child(session, root, previous_attempt["photo_run"])
                values["seed"] = fresh_seed(
                    session,
                    [session.get(Artifact, source["artifact_id"]) for source in sources],
                    previous=previous.parameters["seed"],
                )
            if plan.reference_layout is not None:
                if values["backend"] != "krea2":
                    raise ValueError("The edit plan proposed unsupported reference controls")
                if "reference_layout" not in root.parameters["explicit_controls"]:
                    values["reference_layout"] = plan.reference_layout
            photo = create_image_run(session, ImageRequest(**values), task=root.task, parent_run_id=root.id)
            photo.metadata_json = {**photo.metadata_json, "image_edit_root_id": root.id}
            record = {"photo_run": photo.id, "plan_run": plan_id}
            if attempts and not attempts[-1]:
                attempts[-1] = record
            else:
                attempts.append(record)
            root.metadata_json = {**state, "edit_attempts": attempts}
            waiting(
                session,
                root,
                [photo],
                "Creating the edited image" if len(attempts) == 1 else "Correcting the image",
            )
            return
        current = dict(attempts[-1])
        photo = child(session, root, current["photo_run"])
        if photo.status != "succeeded":
            raise ValueError("Image generation did not complete; inspect its Run")
        artifact = session.scalar(
            select(Artifact).where(Artifact.run_id == photo.id, Artifact.artifact_type == "image")
        )
        if artifact is None or artifact.trashed_at is not None or artifact.purged_at is not None:
            raise ValueError("The candidate image is unavailable")
        if "observation_run" not in current:
            observation = enqueue_reason(
                session, root, f"observe:{len(attempts)}", "observe_candidate", {}, [artifact.id]
            )
            current["observation_run"] = observation.id
            attempts[-1] = current
            root.metadata_json = {**state, "edit_attempts": attempts}
            waiting(session, root, [observation], "Inspecting the generated image")
            return
        observation = CandidateObservation.model_validate(result(session, root, current["observation_run"]))
        if "review_runs" not in current:
            groups = {}
            for index, criterion in enumerate(plan.criteria):
                groups.setdefault(tuple(criterion.reference_indices), []).append(index)
            rows = []
            for group, indices in groups.items():
                ids = [sources[i]["artifact_id"] for i in group]
                rows.append(
                    enqueue_reason(
                        session,
                        root,
                        f"review:{len(attempts)}:{len(rows)}",
                        "review",
                        {
                            "instruction": root.parameters["original_instruction"],
                            "user_request": root.parameters["user_request"],
                            "prior_edits": root.parameters["prior_edits"],
                            "reference_indices": list(group),
                            "criteria": {str(i): plan.criteria[i].model_dump() for i in indices},
                            "base_reference_id": sources[plan.base_reference_index]["artifact_id"],
                            "candidate_id": artifact.id,
                            "candidate_observation": observation.model_dump(),
                        },
                        ids + [artifact.id],
                    )
                )
            current["review_runs"] = [r.id for r in rows]
            attempts[-1] = current
            root.metadata_json = {**state, "edit_attempts": attempts}
            review_tag(artifact, root, "pending")
            waiting(session, root, rows, "Checking the requested changes")
            return
        reviews = [EditReview.model_validate(result(session, root, rid)) for rid in current["review_runs"]]
        if all(review.request_verdict == "passed" for review in reviews):
            if "audit_runs" not in current:
                rows = [
                    enqueue_reason(
                        session,
                        root,
                        f"audit:{len(attempts)}:{index}",
                        "audit_review",
                        {
                            "user_request": root.parameters["user_request"],
                            "instruction": root.parameters["original_instruction"],
                            "candidate_observation": observation.model_dump(),
                            "criteria": {
                                str(check.criterion_index): plan.criteria[check.criterion_index].model_dump()
                                for check in review.checks
                            },
                            "proposed_review": review.model_dump(),
                        },
                    )
                    for index, review in enumerate(reviews)
                ]
                current["audit_runs"] = [row.id for row in rows]
                attempts[-1] = current
                root.metadata_json = {**state, "edit_attempts": attempts}
                waiting(session, root, rows, "Checking review consistency")
                return
            for review, identity in zip(reviews, current["audit_runs"], strict=True):
                audit = ReviewConsistency.model_validate(result(session, root, identity))
                if audit.verdict != "consistent":
                    verdict = "failed" if audit.verdict == "contradicted" else "uncertain"
                    review.request_verdict = verdict
                    review.request_evidence = audit.evidence
                    review.correction = audit.evidence
                    for check in review.checks:
                        if plan.criteria[check.criterion_index].kind == "change":
                            check.verdict = verdict
                            check.evidence = audit.evidence
        checks = [check for review in reviews for check in review.checks]
        if {check.criterion_index for check in checks} != set(range(len(plan.criteria))) or len(
            checks
        ) != len(plan.criteria):
            raise ValueError("The edit review omitted or duplicated criteria")
        if any(
            check.verdict == "not_required" and plan.criteria[check.criterion_index].kind != "preserve"
            for check in checks
        ):
            raise ValueError("A requested change cannot be waived by the review")
        passed = all(check.verdict in {"passed", "not_required"} for check in checks) and all(
            review.request_verdict == "passed" for review in reviews
        )
        review_tag(artifact, root, "accepted" if passed else "rejected")
        append_event(
            session,
            root.id,
            "image.edit.reviewed",
            {"attempt": len(attempts), "passed": passed, "artifact_id": artifact.id},
        )
        if passed:
            root.metadata_json = {
                **state,
                "accepted_artifact_ids": [artifact.id],
                "accepted_run_id": photo.id,
                "edit_phase": "Changes verified",
            }
            root.summary = "Changes verified: " + "; ".join(plan.visual.changes.values())[:700]
            from app.photo_executor import PhotoPipeExecutor

            PhotoPipeExecutor().on_success(session, root, artifact)
            transition(session, root, RunStatus.SUCCEEDED, event_type="run.completed")
            return
        if len(attempts) >= 2 or not (
            any(check.verdict == "failed" for check in checks)
            or any(review.request_verdict == "failed" for review in reviews)
        ):
            mark_failed(
                session,
                root,
                "ImageEditNotVerified",
                "The requested image changes could not be verified. Attempts and review evidence remain available.",
            )
            return
        root.metadata_json = {
            **state,
            "edit_plan_run": None,
            "edit_feedback": [review.model_dump() for review in reviews],
            "edit_relax_references": any(
                check.verdict == "failed" and plan.criteria[check.criterion_index].kind == "change"
                for check in checks
            )
            and all(
                check.verdict in {"passed", "not_required"}
                for check in checks
                if plan.criteria[check.criterion_index].kind == "preserve"
            ),
            "edit_attempts": [*attempts, {}],
        }
        self.advance(session, root)


def pixel_identity(session, run):
    payload = run.parameters["payload"]
    ids = [payload["base_reference_id"], payload["candidate_id"]]
    decoded = []
    for identity in ids:
        row = session.get(Artifact, identity)
        if row is None:
            raise ValueError("Review input is unavailable")
        data = read_owned_file(row.relative_path, row.size_bytes, row.sha256, limit=20 * 1024**2, binary=True)
        with Image.open(io.BytesIO(data)) as source:
            if source.width * source.height > 16 * 1024**2:
                raise ValueError("Review image exceeds its pixel limit")
            image = ImageOps.exif_transpose(source).convert("RGBA")
            decoded.append((image.size, hashlib.sha256(image.tobytes()).digest()))
    return decoded[0] == decoded[1]


class ImageEditReasonExecutor:
    name = REASON

    def execute(self, session, run):
        return asyncio.run(self.perform(session, run))

    async def perform(self, session, run):
        require(run.effective_permissions, "filesystem_read")
        require(run.effective_permissions, "workspace_write")
        if run.parameters.get("location") != "local" or not run.parameters.get("model", "").startswith(
            "llamacpp:"
        ):
            raise ProviderError("Edit inspection and review require an owned local vision runtime")
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        claim = run.worker_id, run.claimed_at
        deadline = datetime.fromisoformat(run.parameters["execution_deadline_at"])
        stage, payload = run.parameters["stage"], run.parameters["payload"]
        schema = {
            "inspect": SourceInspection,
            "plan": EditPlan,
            "review": EditReview,
            "observe_candidate": CandidateObservation,
            "audit_review": ReviewConsistency,
        }[stage]
        system = {
            "inspect": INSPECT,
            "plan": PLAN,
            "review": REVIEW,
            "observe_candidate": OBSERVE_CANDIDATE,
            "audit_review": AUDIT_REVIEW,
        }[stage]
        output_schema = schema.model_json_schema()
        if stage == "plan" and payload["backend"] != "krea2":
            output_schema["properties"]["reference_layout"] = {
                "type": "null",
                "default": None,
                "description": "This model has no reference-layout control; omit or use null.",
            }
        omitted_control = False
        session.commit()
        try:
            checked_sources(session, run.parameters["source_inputs"])
            if run.parameters["vision_inputs"]:
                verify(session, run.parameters["vision_inputs"], read_bytes=True)
            if stage == "review" and pixel_identity(session, run):
                parsed = EditReview(
                    request_verdict="failed",
                    request_evidence="Candidate pixels are identical to the original base image; the requested edit did not happen.",
                    checks=[
                        {
                            "criterion_index": int(i),
                            "verdict": "failed" if c["kind"] == "change" else "uncertain",
                            "evidence": "Candidate pixels are identical to the original base image.",
                        }
                        for i, c in payload["criteria"].items()
                    ],
                    correction="Apply the requested changes; do not return the unchanged original.",
                )
            else:
                from app.assistant_decisions import infer
                from app.vision import image_context

                messages = [
                    {
                        "role": "user",
                        "content": system
                        + "\n"
                        + json.dumps({"schema": output_schema, **payload}, ensure_ascii=False),
                    }
                ]
                if run.parameters["vision_artifact_ids"]:
                    messages = image_context(session, run, messages)
                    if stage == "review":
                        content = messages[0]["content"]
                        parts = [content[0]]
                        for offset, (identity, image) in enumerate(
                            zip(run.parameters["vision_artifact_ids"], content[1:], strict=True)
                        ):
                            role = (
                                "CANDIDATE — generated output to judge"
                                if identity == payload["candidate_id"]
                                else "ORIGINAL REFERENCE index " + str(payload["reference_indices"][offset])
                            )
                            parts.extend([{"type": "text", "text": role}, image])
                        messages[0]["content"] = parts
                session.commit()
                for format_attempt in range(2):
                    raw = await infer(session, run, messages, json_output=False)
                    try:
                        if raw.lstrip().startswith("```"):
                            raw = raw.strip().split("\n", 1)[1].rsplit("```", 1)[0]
                        parsed = schema.model_validate_json(raw)
                        if stage == "inspect" and sorted(o.index for o in parsed.references) != sorted(
                            payload["indices"]
                        ):
                            raise ValueError("Source inspection changed its reference indices")
                        if stage == "review" and sorted(c.criterion_index for c in parsed.checks) != sorted(
                            int(i) for i in payload["criteria"]
                        ):
                            raise ValueError("Review changed its expected criterion indices")
                        if stage == "plan" and (
                            parsed.base_reference_index >= payload["reference_count"]
                            or any(
                                len(set(c.reference_indices)) != len(c.reference_indices)
                                or any(
                                    type(i) is not int or not 0 <= i < payload["reference_count"]
                                    for i in c.reference_indices
                                )
                                for c in parsed.criteria
                            )
                        ):
                            raise ValueError("Edit plan uses an unavailable reference")
                        if stage == "review" and any(
                            c.verdict == "not_required"
                            and payload["criteria"][str(c.criterion_index)]["kind"] != "preserve"
                            for c in parsed.checks
                        ):
                            raise ValueError("A requested change cannot be marked not_required")
                        if (
                            stage == "plan"
                            and payload["backend"] != "krea2"
                            and parsed.reference_layout is not None
                        ):
                            # A generated optional control is not user authority.
                            # Omit this non-applicable engine hint; never change
                            # the visual brief or dispatch an unsupported field.
                            parsed.reference_layout = None
                            omitted_control = True
                        break
                    except (ValueError, IndexError) as error:
                        if format_attempt:
                            raise
                        # Repair only the closed format/indices, never silently
                        # manufacture a visual verdict or repeat generation.
                        messages.extend(
                            [
                                {"role": "assistant", "content": raw[:24000]},
                                {
                                    "role": "user",
                                    "content": "Correct your JSON to the supplied schema and exact reference/criterion indices. "
                                    + str(error)[:2000]
                                    + " Return the complete corrected JSON only.",
                                },
                            ]
                        )

            def publish():
                if omitted_control:
                    append_event(
                        session,
                        run.id,
                        "image.edit.plan.control_omitted",
                        {
                            "field": "reference_layout",
                            "backend": payload["backend"],
                            "reason": "not supported by the selected model",
                        },
                    )
                checked_sources(session, run.parameters["source_inputs"])
                if run.parameters["vision_inputs"]:
                    verify(session, run.parameters["vision_inputs"], read_bytes=True)
                with tempfile.NamedTemporaryFile(suffix=".json") as file:
                    file.write(parsed.model_dump_json().encode())
                    file.flush()
                    register_file(
                        session,
                        source=Path(file.name),
                        artifact_type="json",
                        mime_type="application/json",
                        original_filename=f"image-edit-{stage}.json",
                        run_id=run.id,
                        parent_artifact_ids=run.parameters["vision_artifact_ids"],
                        metadata={"image_edit_stage": stage, "internal_media": True},
                    )
                run.metadata_json = {**run.metadata_json, "edit_result": parsed.model_dump()}
                transition(session, run, RunStatus.SUCCEEDED, event_type="image.edit." + stage)

            await database_step(session, run, claim, deadline, publish)
        except RunStopped:
            session.rollback()
        except Exception as error:
            message = str(error)
            session.rollback()
            try:
                database_step_sync(
                    session,
                    run,
                    claim,
                    deadline,
                    lambda: mark_failed(session, run, "ImageEditReasoningError", message),
                )
            except RunStopped:
                session.rollback()
        return "done"


def published_artifacts(artifacts):
    return [
        row
        for row in artifacts
        if (row.metadata_json.get("image_edit_review") or {}).get("status") not in {"pending", "rejected"}
    ]


def recover_control(session, run):
    """Only CPU coordination and pure local inference may be replayed here."""
    if run.status == "cancel_requested":
        transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
        return
    count = run.metadata_json.get("edit_lease_recoveries", 0)
    transition(session, run, RunStatus.INTERRUPTED, event_type="image.edit.lease_expired")
    if type(count) is not int or count >= (2 if run.executor_type == NAME else 1):
        return
    if run.executor_type == REASON and run.parameters.get("location") != "local":
        return
    run.metadata_json = {**run.metadata_json, "edit_lease_recoveries": count + 1}
    run.worker_id = None
    run.lease_expires_at = None
    run.finished_at = None
    transition(
        session,
        run,
        RunStatus.QUEUED,
        event_type="image.edit.recovered",
        payload={"native_execution_replayed": False},
    )


def retry_edit(session, original, body):
    from app.media_retry_intent import existing_fresh, finish_retry, locked_source, task_for_retry

    if body.translation != "reuse":
        raise HTTPException(409, "Edit retries re-plan the original instruction automatically")
    locked_source(session, original)
    identity = {"id": str(body.client_request_id), "translation": "reuse"}
    if previous := existing_fresh(session, original, identity, replayable=bool(body.client_request_id)):
        return previous
    previous_id = original.metadata_json.get("retry_run_id")
    if previous_id:
        previous = child(session, original, previous_id)
        if (
            previous.executor_type == NAME
            and body.client_request_id
            and previous.metadata_json.get("media_retry_request") == identity
        ):
            return previous
        raise HTTPException(409, "An edit retry already exists; inspect that Run")
    # No new attempt while any owned child is still in flight. Native replay
    # remains the responsibility of the normal photo process protocol.
    from app.state import TERMINAL

    descendants = list(session.scalars(select(Run).where(Run.task_id == original.task_id)))
    if any(row.parent_run_id == original.id and row.status not in TERMINAL for row in descendants):
        raise HTTPException(409, "The earlier edit stages must finish before retrying")
    if any(
        row.parent_run_id == original.id
        and row.executor_type == "photo_pipe"
        and row.metadata_json.get("dispatch_attempted")
        and not row.metadata_json.get("process_confirmed_gone")
        for row in descendants
    ):
        raise HTTPException(409, "The earlier image process needs ownership inspection before retrying")
    checked_sources(session, original.parameters["source_inputs"])
    _, binding = frozen_model(session, original.parameters["selected_model"], original.parameters["mode"])
    if binding != original.parameters["frozen_model"]:
        raise HTTPException(409, "The selected edit model changed; start a new Edit")
    task = task_for_retry(session, original, "reuse")
    values = {k: v for k, v in original.parameters.items() if k in ImageRequest.model_fields}
    values["verify_changes"] = True
    retry = enqueue_edit(
        session,
        ImageRequest(**values),
        task=task,
        parent_run_id=original.id if task.id == original.task_id else None,
    )
    retry.parameters = {
        **retry.parameters,
        **{
            k: original.parameters[k]
            for k in (
                "user_request",
                "original_instruction",
                "prior_edits",
                "explicit_controls",
                "source_inputs",
                "selected_model",
                "frozen_model",
            )
        },
    }
    retry.metadata_json = {**retry.metadata_json, "media_retry_request": identity}
    finish_retry(session, original, retry, identity)
    return retry


def accepted_artifacts(session, root, *, available=True):
    if root.status != "succeeded":
        return []
    photo = child(session, root, root.metadata_json["accepted_run_id"])
    if photo.executor_type != "photo_pipe" or photo.status != "succeeded":
        raise ValueError("Accepted image provenance changed")
    rows = [session.get(Artifact, identity) for identity in root.metadata_json["accepted_artifact_ids"]]
    if not rows or any(
        row is None
        or row.run_id != photo.id
        or row.owner_id != root.owner_id
        or available
        and (row.trashed_at is not None or row.purged_at is not None or row.purge_run_id)
        or row.metadata_json.get("image_edit_review") != {"root_id": root.id, "status": "accepted"}
        for row in rows
    ):
        raise ValueError("Accepted image is unavailable or its provenance changed")
    return rows

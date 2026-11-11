"""Durable infer → act → observe conversation orchestration, with no occupied waiting slot."""

import asyncio
import hashlib
import json
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app.assistant_controller_tools import (
    TOOLS,
    available_tools,
    catalog,
    observation,
    public_catalog,
    subtree,
    wrapper_parameters,
)
from app.assistant_decisions import Decision
from app.chat_providers import chat_permissions, snapshot_provider
from app.db import utcnow
from app.dependencies import depend_on
from app.events import append_event
from app.models import Artifact, Conversation, Message, Run
from app.runs import create_run, create_task, transition
from app.state import TERMINAL, RunStatus
from app.task_control import lock_task

VERSION = "react-v1"
PROTOCOL = "llamaindex-react-v1"
MAX_STEPS = 16


def missing_outcomes(observations, outcomes):
    counts = {}
    studio_counts = {}
    media = {
        "image.generate": "image",
        "image.edit": "image",
        "image.recompose": "image",
        "image.upscale": "image",
        "video.generate": "video",
        "avatar.animate": "avatar",
        "audio.speech": "audio",
        "audio.music": "audio",
        "audio.effects": "audio",
    }
    for item in observations:
        if item.get("status") != "succeeded":
            continue
        name = item["tool"]
        if name == "studio.produce" and "video" in item.get("produced_types", []):
            index = item.get("studio_outcome_index")
            if isinstance(index, int) and not isinstance(index, bool):
                studio_counts[index] = studio_counts.get(index, 0) + 1
        kind = media.get(name)
        types = item.get("produced_types", [])
        if kind and ("video" if kind == "avatar" else kind) in types:
            counts[kind] = counts.get(kind, 0) + 1
        if name == "agent.create" and item.get("agent_ids"):
            counts["agent_draft"] = counts.get("agent_draft", 0) + len(item["agent_ids"])
        if name == "chat.reply":
            counts["text"] = counts.get("text", 0) + 1
        if name in {"data.create", "data.analyze"} and any(
            kind not in {"log", "git_diff", "code_patch"} for kind in types
        ):
            counts["files"] = counts.get("files", 0) + 1
        if name in {"project.create", "project.create_code"}:
            counts["project"] = counts.get("project", 0) + 1
        if name in {"project.create_code", "coding.local"} and any(
            kind in {"code_patch", "git_diff"} for kind in types
        ):
            counts["local_changes"] = counts.get("local_changes", 0) + 1
        if name == "system.inspect" and "json" in types:
            counts["system_state"] = counts.get("system_state", 0) + 1
    # Talking avatars are videos, but one output cannot fulfill two separate
    # deliverables. Reserve explicitly requested avatars before allocating the
    # remaining avatar videos to ordinary video outcomes, regardless of order.
    avatars = counts.get("avatar", 0)
    reserved = min(avatars, sum(item["count"] for item in outcomes if item["kind"] == "avatar"))
    counts["avatar"] = reserved
    counts["video"] = counts.get("video", 0) + avatars - reserved
    pending = []
    for index, item in enumerate(outcomes):
        if item["kind"] == "studio_material":
            completed = min(item["count"], studio_counts.get(index, 0))
            if completed < item["count"]:
                pending.append({**item, "remaining": item["count"] - completed, "outcome_index": index})
            continue
        completed = min(item["count"], counts.get(item["kind"], 0))
        counts[item["kind"]] = counts.get(item["kind"], 0) - completed
        if completed < item["count"]:
            pending.append({**item, "remaining": item["count"] - completed})
    return pending


def automatic(body):
    return body.action == "auto" and not any(
        getattr(body, name, None)
        for name in (
            "commit",
            "publish",
            "load",
            "stop",
            "continuation",
            "new_project",
            "analysis_agent_source_run_id",
        )
    )


def enqueue(session, conversation, body, *, commit=True):
    from app.chat_attachments import link_attachments, message_content, save_attachments

    snapshot = snapshot_provider(session, conversation)
    from app.assistant_image_profiles import inventory

    image_catalog = inventory(session)
    user = Message(
        conversation_id=conversation.id,
        role="user",
        content=message_content(body.content, body.attachments),
        metadata_json={
            "user_text": body.content,
            "execution_mode": "assistant",
            "execution_mode_override": body.execution_mode,
        },
    )
    session.add(user)
    session.flush()
    if body.attachments:
        user.metadata_json = {
            **user.metadata_json,
            "attachments": save_attachments(session, user, body.attachments),
        }
    if body.reasoning is not None:
        from app.chat_reasoning import certificate, validated_options

        options = validated_options(session, conversation.model, body.reasoning, conversation.max_tokens)
        user.metadata_json = {
            **user.metadata_json,
            "reasoning": options,
            "reasoning_certificate": certificate(session, conversation.model),
        }
    ids = [str(aid) for aid in body.image_artifact_ids] + (
        [str(body.audio_artifact_id)] if body.audio_artifact_id else []
    )
    ids += [item["id"] for item in user.metadata_json.get("attachments", [])]
    if body.data:
        ids += [str(aid) for aid in body.data.input_artifact_ids]
    if body.effects and body.effects.video_artifact_id:
        ids.append(str(body.effects.video_artifact_id))
    counts, inputs = {}, []
    for aid in dict.fromkeys(ids):
        artifact = session.get(Artifact, aid)
        if artifact is None or artifact.owner_id != conversation.owner_id or artifact.trashed_at is not None:
            raise HTTPException(422, "Choose your existing untrashed input artifacts")
        if aid in {str(value) for value in body.image_artifact_ids} and artifact.artifact_type != "image":
            raise HTTPException(422, "Choose image artifacts as image references")
        if aid == str(body.audio_artifact_id) and artifact.artifact_type != "audio":
            raise HTTPException(422, "Choose an audio artifact as the recording")
        counts[artifact.artifact_type] = counts.get(artifact.artifact_type, 0) + 1
        inputs.append(
            {
                "alias": f"input:{artifact.artifact_type}:{counts[artifact.artifact_type]}",
                "origin": "current_attachment",
                "source_message_id": user.id,
                "snapshot": {
                    "id": artifact.id,
                    "sha256": artifact.sha256,
                    "relative_path": artifact.relative_path,
                    "size_bytes": artifact.size_bytes,
                },
            }
        )
    recent = session.scalar(
        select(Run)
        .where(
            Run.conversation_id == conversation.id,
            Run.executor_type == "assistant_controller",
            Run.status.in_(TERMINAL),
        )
        .order_by(Run.created_at.desc(), Run.id.desc())
        .limit(1)
    )
    recent_work = None
    if recent is not None:
        recent_work = {"instruction": recent.parameters["content"][:4000], "steps": []}
        prior_counts, previous_sources = {}, []
        for step in recent.metadata_json.get("controller_steps", []):
            observed = step.get("observation")
            if observed is None:
                continue
            recent_work["steps"].append(
                {
                    "tool": step["tool"],
                    "status": observed["status"],
                    "summaries": observed["summaries"][:2],
                    "agent_ids": observed["agent_ids"],
                }
            )
            previous_sources.extend(
                {
                    **item,
                    "origin": "previous_result",
                    "source_tool": step["tool"],
                    "source_step": step["index"],
                }
                for item in step.get("artifacts", [])
            )
        previous_sources.extend(
            {
                **item,
                "origin": "previous_attachment"
                if item.get("origin") in {None, "current_attachment"}
                else item["origin"],
            }
            for item in recent.parameters.get("controller_inputs", [])
        )
        seen = {item["snapshot"]["id"] for item in inputs}
        for item in previous_sources:
            if len(inputs) >= 32:
                break
            row = session.get(Artifact, item["snapshot"]["id"])
            if (
                row is None
                or row.id in seen
                or row.owner_id != conversation.owner_id
                or row.trashed_at is not None
                or any(
                    getattr(row, key) != item["snapshot"].get(key)
                    for key in ("relative_path", "size_bytes", "sha256")
                )
                or (snapshot["location"] != "local" and row.artifact_type not in {"image", "audio", "video"})
            ):
                continue
            seen.add(row.id)
            prior_counts[row.artifact_type] = prior_counts.get(row.artifact_type, 0) + 1
            inputs.append(
                {
                    "alias": f"previous:{row.artifact_type}:{prior_counts[row.artifact_type]}",
                    "snapshot": item["snapshot"],
                    **{
                        key: item[key]
                        for key in ("origin", "source_tool", "source_step", "source_message_id")
                        if key in item
                    },
                }
            )
    from app.conversation_assets import prior_context

    prior = prior_context(
        session,
        conversation,
        user,
        excluded={item["snapshot"]["id"] for item in inputs},
        limit=max(0, 32 - len(inputs)),
    )
    prior_counts = {}
    for item in inputs:
        if item["alias"].startswith("previous:"):
            kind = session.get(Artifact, item["snapshot"]["id"]).artifact_type
            prior_counts[kind] = max(prior_counts.get(kind, 0), int(item["alias"].rsplit(":", 1)[1]))
        if "source_message_id" not in item and item["snapshot"]["id"] in prior["sources"]:
            item["source_message_id"] = prior["sources"][item["snapshot"]["id"]]
    for item in prior["inputs"]:
        artifact = session.get(Artifact, item["snapshot"]["id"])
        if snapshot["location"] != "local" and artifact.artifact_type not in {"image", "audio", "video"}:
            continue
        prior_counts[artifact.artifact_type] = prior_counts.get(artifact.artifact_type, 0) + 1
        inputs.append(
            {**item, "alias": f"previous:{artifact.artifact_type}:{prior_counts[artifact.artifact_type]}"}
        )
    user.metadata_json = {
        **user.metadata_json,
        "images": [
            {"id": str(aid), "name": session.get(Artifact, str(aid)).original_filename}
            for aid in body.image_artifact_ids
        ],
    }
    from app.studio_assistant_contract import project_catalog

    creative_catalog = project_catalog(session, owner_id=conversation.owner_id, location=snapshot["location"])
    task = create_task(
        session,
        title=body.content[:80],
        prompt=body.content,
        capability="assistant.orchestrate",
        intent="assistant",
        conversation_id=conversation.id,
    )
    request = body.model_dump(mode="json", exclude={"attachments"})
    run = create_run(
        session,
        task,
        run_type="orchestration",
        capability="assistant.orchestrate",
        executor_type="assistant_controller",
        execution_target="container",
        retry_class="safe",
        parameters={
            "controller_version": VERSION,
            "controller_protocol": PROTOCOL,
            "controller_image_policy": "configured-default-v2",
            "controller_studio_policy": "studio-v1",
            "controller_creative_projects": creative_catalog,
            "content": body.content,
            "controller_request": {**request, "user_message_id": user.id, "model": conversation.model},
            "controller_provider": snapshot,
            "controller_inputs": inputs,
            "planner_context": prior["history"],
            "recent_work": recent_work,
            "controller_image_catalog": image_catalog,
            "reference_text": user.content[len(body.content) :][:24000],
            "web_search": body.web_search.model_dump(),
            **{name: request.get(name) for name in ("coding", "data", "effects")},
            "execution_deadline_at": (utcnow() + timedelta(hours=24)).isoformat(),
        },
        metadata={"controller_steps": [], "controller_phase": "decide"},
    )
    user.run_id = run.id
    link_attachments(session, user, run)
    session.add(
        Message(
            conversation_id=conversation.id,
            role="assistant",
            content="",
            run_id=run.id,
            metadata_json={
                "partial": True,
                "orchestration": True,
                "routing_only": False,
                "controller_version": VERSION,
            },
        )
    )
    conversation.updated_at = utcnow()
    if conversation.title == "New conversation":
        conversation.title = body.content[:80]
    if commit:
        session.commit()
    return run


def message_for(session, run):
    row = session.scalar(select(Message).where(Message.run_id == run.id, Message.role == "assistant"))
    if row is None:
        raise ValueError("Controller has no originating response")
    return row


def wait_for(session, root, runs):
    transition(
        session,
        root,
        RunStatus.WAITING_FOR_TOOL,
        event_type="assistant.awaiting_tool",
        payload={"run_ids": [row.id for row in runs]},
    )
    root.worker_id = None
    root.lease_expires_at = None
    for row in runs:
        depend_on(session, root, row, require_success=False)


def sources(root):
    import re

    from app.http_fetch import prompt_public_urls, public_url

    # Parse resource syntax only. Whether to read a supplied domain is a model
    # decision, never inferred here from imperative verbs or subject keywords.
    urls = prompt_public_urls(root.parameters["content"])
    for match in re.finditer(
        r"(?<![\w@./-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}(?::[0-9]{1,5})?(?:/[^\s<>\"']*)?",
        root.parameters["content"],
        re.I,
    ):
        url = public_url("https://" + match.group().rstrip(".,;!?)]}"))
        if url and url not in urls and len(urls) < 3:
            urls.append(url)

    links = {f"input:source:{index}": url for index, url in enumerate(urls, 1)}
    for step in root.metadata_json.get("controller_steps", []):
        offset = 0
        for data in step.get("observation", {}).get("tool_data", []):
            for source in data.get("sources", []) if isinstance(data, dict) else []:
                offset += 1
                links[f"step:{step['index']}:source:{offset}"] = source["url"]
    return links


def analysis_catalog(session, root):
    """Read existing typed analysis provenance; never infer intent from wording."""
    if root.parameters["controller_provider"]["location"] != "local":
        return {}
    from app.data_agent_draft import capture

    rows = session.execute(
        select(Message, Run)
        .join(Run, Message.run_id == Run.id)
        .where(
            Message.conversation_id == root.conversation_id,
            Message.role == "user",
            Run.executor_type == "orchestrator",
            Run.status == "succeeded",
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(16)
    )
    entries = {}
    for user, source in rows:
        if not source.parameters.get("data") or source.owner_id != root.owner_id:
            continue
        try:
            snapshot = capture(session, root.conversation_id, user, source)
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        entries[f"analysis:{source.id}"] = snapshot
        if len(entries) >= 8:
            break
    return entries


def decision_context(session, root):
    from app.conversation_assets import reference_context

    observations = []
    for step in root.metadata_json.get("controller_steps", []):
        observed = step.get("observation")
        if observed:
            # The full tool record/artifacts stay in their own Runs. Model context
            # contains bounded untrusted observations, never filesystem locations.
            observations.append(
                {
                    "index": step["index"],
                    "tool": step["tool"],
                    "arguments": step["arguments"],
                    "status": observed["status"],
                    "summaries": observed["summaries"],
                    "responses": observed["responses"],
                    "errors": observed["errors"],
                    "agent_ids": observed["agent_ids"],
                    "produced_types": observed["produced_types"],
                    **(
                        {"studio_outcome_index": observed["studio_outcome_index"]}
                        if "studio_outcome_index" in observed
                        else {}
                    ),
                    "tool_data_excerpt": json.dumps(observed["tool_data"], ensure_ascii=False)[:6000],
                }
            )
    available = available_tools(root.parameters)
    schemas = {
        TOOLS[name].arguments.__name__: TOOLS[name].arguments.model_json_schema() for name in available
    }
    entries = public_catalog(catalog(session, root))
    from app.studio_assistant_contract import public_projects

    return {
        "creative_projects": public_projects(root.parameters.get("controller_creative_projects", {})),
        "instruction": root.parameters["content"],
        "current_time": utcnow().isoformat(),
        "recent_context": root.parameters.get("planner_context", []),
        "recent_work": root.parameters.get("recent_work"),
        "selected_data": root.parameters.get("data"),
        "analysis_results": [
            {"alias": alias, "goal": source["definition"]["goal"], "input_names": source["input_names"]}
            for alias, source in analysis_catalog(session, root).items()
        ],
        "reference_text": root.parameters.get("reference_text", ""),
        "tools": available,
        "argument_types": schemas,
        "inputs_and_results": entries,
        "reference_context": reference_context(entries),
        "image_models": root.parameters.get("controller_image_catalog", {}),
        "image_model_policy": (
            "Honor an explicit image_model; otherwise use the configured per-operation default. Reference images select content, not the generator. A recurring draft bound to a newly produced result retains its compatible result model."
            if root.parameters.get("controller_image_policy") == "configured-default-v2"
            else "Legacy scope: retain a compatible source profile or the frozen configured default unless explicitly overridden."
        ),
        "sources": sources(root),
        "selected_web_query": (root.parameters.get("web_search") or {}).get("query", ""),
        "observations": observations,
        "remaining_tool_budget": MAX_STEPS - len(observations),
        "outcomes": root.metadata_json.get("controller_outcomes", []),
        "missing_outcomes": missing_outcomes(observations, root.metadata_json.get("controller_outcomes", [])),
    }


def decision_run(session, root):
    from app.llama import prepare_consumer

    index = len(root.metadata_json.get("controller_steps", []))
    snapshot = root.parameters["controller_provider"]
    child = create_run(
        session,
        root.task,
        run_type="planning",
        capability="assistant.decide",
        executor_type="assistant_decision",
        execution_target="container",
        operation_key=f"decision:{root.id}:{index}",
        parameters={
            **snapshot,
            "model": root.parameters["controller_request"]["model"],
            "execution_deadline_at": root.parameters["execution_deadline_at"],
            "decision_context": decision_context(session, root),
            "controller_protocol": root.parameters.get("controller_protocol"),
        },
        permissions=chat_permissions(snapshot),
        retry_class="safe" if snapshot.get("location") == "local" else "inspect",
        parent_run_id=root.id,
    )
    prepare_consumer(session, child)
    root.metadata_json = {**root.metadata_json, "controller_phase": "decision", "decision_run_id": child.id}
    wait_for(session, root, [child])


def dispatch(session, root, decision):

    steps = list(root.metadata_json.get("controller_steps", []))
    index = len(steps) + 1
    name = decision.tool
    if name not in available_tools(root.parameters):
        raise ValueError("The proposed tool is unavailable in this request scope")
    args = TOOLS[name].arguments.model_validate(decision.arguments)
    if name == "web.search":
        selected_query = (root.parameters.get("web_search") or {}).get("query", "").strip()
        if selected_query and args.query != selected_query:
            raise ValueError(
                "Use the selected public search query exactly; do not send private instructions instead"
            )
    snapshot = root.parameters["controller_provider"]
    if name == "studio.produce":
        from app.studio_assistant import request_parameters

        params = request_parameters(session, root, decision.arguments)
        executor, permissions = "assistant_studio", list(TOOLS[name].permissions)
    elif name in {"web.search", "web.read", "artifact.read"}:
        params = {
            "tool": name,
            "arguments": args.model_dump(),
            "execution_deadline_at": root.parameters["execution_deadline_at"],
            "controller_parent_id": root.id,
        }
        if name == "web.read":
            links = sources(root)
            if any(alias not in links for alias in args.sources):
                raise ValueError("Read only supplied source aliases")
            params["urls"] = [links[alias] for alias in args.sources]
        if name == "artifact.read":
            entries = catalog(session, root)
            if any(alias not in entries for alias in args.artifacts):
                raise ValueError("Read only supplied artifact aliases")
            params["inputs"] = [entries[alias] for alias in args.artifacts]
            executor, permissions = "assistant_artifact", ["filesystem_read"]
        else:
            executor, permissions = "assistant_web", ["network_read"]
    else:
        params = wrapper_parameters(session, root, name, decision.arguments)
        params["execution_deadline_at"] = root.parameters["execution_deadline_at"]
        executor = "assistant_tool_setup"
        permissions = chat_permissions(snapshot, list(TOOLS[name].permissions))
    child = create_run(
        session,
        root.task,
        run_type="tool",
        capability="assistant.tool",
        executor_type=executor,
        execution_target="container",
        operation_key=f"tool:{root.id}:{index}",
        parameters=params,
        permissions=permissions,
        retry_class="inspect",
        parent_run_id=root.id,
        metadata={"studio_enqueue_only": True} if name == "studio.produce" else None,
    )
    fingerprint = hashlib.sha256(json.dumps(params, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    step = {
        "index": index,
        "tool": name,
        "arguments": args.model_dump(),
        "reason": decision.reason,
        "run_id": child.id,
        "request_sha256": fingerprint,
    }
    steps.append(step)
    child.parameters = {**child.parameters, "controller_tool_context": {"root_id": root.id, "tool": name}}
    root.metadata_json = {**root.metadata_json, "controller_steps": steps, "controller_phase": "tool"}
    append_event(
        session,
        root.id,
        "assistant.tool.requested",
        {"index": index, "tool": name, "reason": decision.reason, "run_id": child.id},
    )
    message_for(session, root).content = decision.reason
    wait_for(session, root, [child])


def verify_wrapper(session, run):
    root_id = run.parameters.get("controller_parent_id")
    if root_id is None:
        return
    root = session.get(Run, root_id)
    if (
        root is None
        or root.executor_type != "assistant_controller"
        or root.parameters.get("controller_version") != VERSION
        or root.owner_id != run.owner_id
        or root.conversation_id != run.conversation_id
    ):
        raise ValueError("Invalid controller tool binding")
    anchor = session.get(Run, run.parent_run_id) if run.parent_run_id != root.id else run
    if (
        anchor is None
        or anchor.parent_run_id != root.id
        or anchor.task_id != root.task_id
        or anchor.owner_id != root.owner_id
        or (anchor.id != run.id and anchor.metadata_json.get("child_run_id") != run.id)
    ):
        raise ValueError("Controller tool provenance changed")
    step = next(
        (step for step in root.metadata_json.get("controller_steps", []) if step["run_id"] == anchor.id), None
    )
    if step is None:
        raise ValueError("Tool was not published by this controller")
    frozen_request = {
        key: value for key, value in anchor.parameters.items() if key != "controller_tool_context"
    }
    digest = hashlib.sha256(
        json.dumps(frozen_request, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    if digest != step.get("request_sha256"):
        raise ValueError("Controller tool request changed after publication")
    if run.executor_type in {"assistant_web", "assistant_artifact"}:
        if run.parameters.get("tool") != step["tool"] or run.parameters.get("arguments") != step["arguments"]:
            raise ValueError("Controller read arguments changed before execution")
        if step["tool"] == "web.read":
            if run.parameters.get("urls") != [sources(root)[alias] for alias in step["arguments"]["sources"]]:
                raise ValueError("Controller public sources changed")
        if step["tool"] == "artifact.read":
            entries = catalog(session, root)
            if run.parameters.get("inputs") != [entries[alias] for alias in step["arguments"]["artifacts"]]:
                raise ValueError("Controller artifacts changed")
    if run.executor_type == "assistant_tool_setup":
        conversation = session.get(Conversation, root.conversation_id)
        selected = snapshot_provider(session, conversation)
        frozen = root.parameters["controller_provider"]
        for field in ("provider", "provider_id", "location", "secret_ref", "provider_config_version"):
            if selected.get(field) != frozen.get(field):
                raise ValueError("The selected provider changed during the controller task")
        if not str(frozen["endpoint"]).startswith("llamacpp:") and selected["endpoint"] != frozen["endpoint"]:
            raise ValueError("The selected provider endpoint changed during the controller task")
        expected = wrapper_parameters(session, root, step["tool"], step["arguments"])
        for field in (
            "action",
            "content",
            "image_artifact_ids",
            "audio_artifact_id",
            "coding",
            "data",
            "media",
            "effects",
            "new_project",
            "load",
            "stop",
            "publish",
            "commit",
            "agent_draft_authorized",
            "web_search",
            "user_message_id",
            "speech_model_id",
            "avatar_model_id",
            "controller_reply_context",
            "controller_data_agent_source",
            "controller_agent_media_kind",
            "controller_agent_scope",
            "controller_image_request",
        ):
            if run.parameters.get(field) != expected.get(field):
                raise ValueError("Controller tool scope changed before execution")


def controller_results(session, root):
    from app.assistant import task_results

    entries, artifacts, seen = [], [], set()
    for step in root.metadata_json.get("controller_steps", []):
        rows = subtree(session, root, step["run_id"])
        anchor = rows[0]
        wrapper = next((row for row in rows if row.executor_type == "orchestrator"), None)
        source = (
            session.scalar(select(Message).where(Message.run_id == wrapper.id, Message.role == "assistant"))
            if wrapper
            else None
        )
        result = task_results(session, source, wrapper) if source else {}
        if step["tool"] == "studio.produce":
            from app.serialize import artifact_dict
            from app.studio_assistant import final_output

            output = final_output(session, anchor) if anchor.status == "succeeded" else None
            result = {
                "steps": [],
                "artifacts": [artifact_dict(output)] if output is not None else [],
                "studio_material_id": anchor.metadata_json.get("studio_material_id"),
            }
        for artifact in result.get("artifacts", []):
            if artifact["id"] not in seen:
                artifacts.append(artifact)
                seen.add(artifact["id"])
        status = step.get("observation", {}).get("status") or (
            "running"
            if any(row.status not in TERMINAL for row in rows)
            else "failed"
            if any(row.status != "succeeded" for row in rows)
            else "succeeded"
        )
        data = anchor.metadata_json.get("controller_tool_result") or {}
        links = (
            data.get("sources", [])
            if step["tool"] == "web.search"
            else [
                {"url": page["url"], "title": page.get("title") or page["url"]}
                for page in data.get("pages", [])
            ]
        )
        entries.append(
            {
                "index": step["index"],
                "tool": step["tool"],
                "reason": step["reason"],
                "status": status,
                "run_id": anchor.id,
                "result": result,
                "sources": [
                    {"url": item["url"], "title": item.get("title") or item["url"]} for item in links[:6]
                ],
                **(
                    {
                        "agent_draft": {
                            "agent_id": source.metadata_json["agent_id"],
                            "source_message_id": source.id,
                        }
                    }
                    if source and source.metadata_json.get("agent_id")
                    else {}
                ),
            }
        )
    return {
        "controller_steps": entries,
        "steps": [],
        "artifacts": artifacts,
        "task_status": root.status,
        "controller_outcomes": root.metadata_json.get("controller_outcomes", []),
        "controller_root_id": root.id,
    }


class AssistantToolSetupExecutor:
    """Prepare each capability through its existing reviewed enqueue contract."""

    name = "assistant_tool_setup"

    def execute(self, session, run):
        from app.assistant import enqueue_assistant
        from app.chat import MessageBody
        from app.task_control import cancel_task

        verify_wrapper(session, run)
        root = session.get(Run, run.parameters["controller_parent_id"])
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        session.commit()
        params = dict(run.parameters)
        values = {key: value for key, value in params.items() if key in MessageBody.model_fields}
        body = MessageBody.model_validate(values)
        user = Message(
            conversation_id=run.conversation_id,
            role="user",
            content=body.content,
            metadata_json={
                "user_text": body.content,
                "execution_mode": "assistant",
                "controller_internal": True,
                "routing_only": True,
            },
        )
        session.add(user)
        session.flush()
        if params.get("controller_data_agent_source"):
            user.metadata_json = {
                **user.metadata_json,
                "data_agent_source": params["controller_data_agent_source"],
            }
        result = enqueue_assistant(
            session,
            session.get(Conversation, run.conversation_id),
            user,
            body,
            commit=False,
            parent_run_id=run.id,
        )
        child = session.get(Run, result["id"])
        child.parameters = {
            **child.parameters,
            "controller_parent_id": root.id,
            "execution_deadline_at": root.parameters["execution_deadline_at"],
            **{
                key: params[key]
                for key in ("controller_agent_scope", "controller_image_request")
                if key in params
            },
            **(
                {"controller_agent_media_kind": params["controller_agent_media_kind"]}
                if params.get("controller_agent_media_kind")
                else {}
            ),
            **(
                {"controller_project_name": params["controller_project_name"]}
                if params.get("controller_project_name")
                else {}
            ),
            **(
                {
                    "controller_reply_context": params["controller_reply_context"],
                    "user_message_id": root.parameters["controller_request"]["user_message_id"],
                }
                if "controller_reply_context" in params
                else {}
            ),
        }
        child.task.metadata_json = {
            **child.task.metadata_json,
            "controller_parent_id": root.id,
            "controller_anchor_id": run.id,
        }
        response = message_for(session, child)
        response.metadata_json = {**response.metadata_json, "controller_internal": True, "routing_only": True}
        run.metadata_json = {**run.metadata_json, "child_run_id": child.id}
        lock_task(session, root.task)
        session.refresh(run)
        if root.task.metadata_json.get("stop_requested_at") or run.status == "cancel_requested":
            cancel_task(session, child.task)
            if run.status != "cancel_requested":
                transition(session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested")
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
        else:
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"


class AssistantControllerExecutor:
    name = "assistant_controller"

    def execute(self, session, run):
        lock_task(session, run.task)
        if run.task.metadata_json.get("stop_requested_at") or run.status == "cancel_requested":
            if run.status != "cancel_requested":
                transition(session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested")
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
            return "done"
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        from datetime import datetime

        if utcnow() >= datetime.fromisoformat(run.parameters["execution_deadline_at"]):
            raise ValueError("Controller runtime budget exhausted; completed results are preserved")
        state = run.metadata_json
        if state["controller_phase"] == "decision":
            decision = session.get(Run, state["decision_run_id"])
            if decision is None or decision.parent_run_id != run.id or decision.status != "succeeded":
                detail = (
                    decision.error_message[:400]
                    if decision and decision.parent_run_id == run.id and decision.owner_id == run.owner_id
                    else "The decision has no valid completed result"
                )
                raise ValueError(
                    "Controller decision failed: " + detail + ". Completed results remain available"
                )
            value = Decision.model_validate(decision.metadata_json["decision"])
            if not state.get("controller_outcomes") and value.outcomes:
                state = {**state, "controller_outcomes": [outcome.model_dump() for outcome in value.outcomes]}
                run.metadata_json = state
            if value.kind == "tool":
                dispatch(session, run, value)
            else:
                response = message_for(session, run)
                response.content = value.response
                response.metadata_json = {**response.metadata_json, "partial": False, "routing_only": False}
                run.metadata_json = {
                    **state,
                    "controller_phase": "finished",
                    "controller_outcome": value.kind,
                }
                transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
            return "done"
        if state["controller_phase"] == "tool":
            steps = list(state["controller_steps"])
            step = dict(steps[-1])
            active, result = observation(session, run, step)
            if active:
                wait_for(session, run, active)
                return "waiting"
            step.update(observation=result, artifacts=result["artifacts"])
            steps[-1] = step
            run.metadata_json = {**state, "controller_steps": steps, "controller_phase": "decide"}
            append_event(
                session,
                run.id,
                "assistant.tool.observed",
                {"index": step["index"], "tool": step["tool"], "status": result["status"]},
            )
            if step["tool"] == "chat.reply" and result["status"] == "succeeded":
                message = message_for(session, run)
                message.content = "Completed." if len(steps) > 1 else ""
                message.metadata_json = {
                    **message.metadata_json,
                    "partial": False,
                    "controller_reply_delivered": True,
                }
                rows = subtree(session, run, step["run_id"])
                child_ids = [row.id for row in rows if row.executor_type == "chat"]
                for reply in session.scalars(
                    select(Message).where(Message.run_id.in_(child_ids), Message.role == "assistant")
                ):
                    reply.metadata_json = {
                        **reply.metadata_json,
                        "orchestration": True,
                        "controller_root_id": run.id,
                    }
                run.metadata_json = {
                    **run.metadata_json,
                    "controller_phase": "finished",
                    "controller_outcome": "replied",
                }
                transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
                return "done"
        if len(run.metadata_json["controller_steps"]) >= MAX_STEPS:
            message = message_for(session, run)
            message.content = "The tool-step budget was reached. Completed results are preserved; describe what to continue next."
            message.metadata_json = {**message.metadata_json, "partial": False, "routing_only": False}
            run.metadata_json = {**run.metadata_json, "controller_outcome": "budget_exhausted"}
            run.error_type = "ControllerBudgetExceeded"
            run.error_message = message.content
            transition(session, run, RunStatus.FAILED, event_type="run.failed")
            return "done"
        decision_run(session, run)
        return "waiting"


class AssistantWebExecutor:
    name = "assistant_web"

    def execute(self, session, run):
        from app.http_fetch import execute_fetch
        from app.web_search import execute_search

        verify_wrapper(session, run)
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        session.commit()
        result = (
            asyncio.run(execute_search(session, run, run.parameters["arguments"]["query"]))
            if run.parameters["tool"] == "web.search"
            else asyncio.run(execute_fetch(session, run, run.parameters["urls"]))
        )
        session.refresh(run)
        if result is None or run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
        else:
            run.metadata_json = {**run.metadata_json, "controller_tool_result": result}
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"


def verified_search_sources(session, run, item, value):
    """Carry source coordinates only from an owned, byte-verified search result.

    The artifact reader calls this after its frozen size/hash/file check. A JSON
    attachment or source_tool label alone cannot introduce network destinations.
    """
    from app.http_fetch import public_url

    artifact = session.get(Artifact, item["snapshot"]["id"])
    origin = session.get(Run, artifact.run_id) if artifact and artifact.run_id else None
    if (
        artifact is None
        or artifact.owner_id != run.owner_id
        or origin is None
        or origin.owner_id != run.owner_id
        or origin.conversation_id != run.conversation_id
        or origin.status != "succeeded"
        or not isinstance(value, dict)
    ):
        return []
    observed = origin.metadata_json.get("web_search")
    if (
        not isinstance(observed, dict)
        or observed.get("artifact_id") != artifact.id
        or not isinstance(value.get("sources"), list)
        or len(value["sources"]) > 5
        or value["sources"] != observed.get("sources")
    ):
        return []
    return [
        {"url": source["url"]}
        for source in value["sources"]
        if isinstance(source, dict) and public_url(source.get("url"))
    ]


class AssistantArtifactExecutor:
    name = "assistant_artifact"

    def execute(self, session, run):
        from app.chat_attachments import extract_pdf
        from app.paths import validate_relative
        from app.python_execution import read_owned_file

        verify_wrapper(session, run)
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        session.commit()
        results, public_sources = [], []
        for item in run.parameters["inputs"]:
            mime = item["mime_type"]
            if not (mime.startswith("text/") or mime in {"application/json", "application/pdf"}):
                raise ValueError("Use image inspection or reviewed data tools for this artifact format")
            snapshot = item["snapshot"]
            validate_relative(snapshot["relative_path"])
            data = read_owned_file(
                snapshot["relative_path"],
                snapshot["size_bytes"],
                snapshot["sha256"],
                limit=131072,
                binary=True,
            )
            text = extract_pdf(data) if mime == "application/pdf" else data.decode("utf-8")
            keys = []
            section = run.parameters["arguments"].get("section")
            if mime == "application/json":
                value = json.loads(text)
                keys = list(value)[:100] if isinstance(value, dict) else []
                if section in {None, "sources"}:
                    public_sources.extend(verified_search_sources(session, run, item, value))
                if section is not None:
                    if not isinstance(value, dict) or section not in value:
                        raise ValueError("Choose an existing top-level JSON section")
                    text = json.dumps(value[section], ensure_ascii=False)
            elif section is not None:
                raise ValueError("A section is available only for JSON artifacts")
            results.append(
                {
                    "alias": item["alias"],
                    "sha256": snapshot["sha256"],
                    "text": text[:6000],
                    "truncated": len(text) > 6000,
                    "top_level_keys": keys,
                }
            )
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
        else:
            run.metadata_json = {
                **run.metadata_json,
                "controller_tool_result": {"artifacts": results, "sources": public_sources},
            }
            append_event(session, run.id, "artifact.read", {"aliases": [item["alias"] for item in results]})
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        return "done"

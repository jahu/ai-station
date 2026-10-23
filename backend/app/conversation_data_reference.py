"""Resolve current-user data references to verified original conversation inputs."""

import json
import re

from fastapi import HTTPException
from sqlalchemy import select

from app.conversation_data_schema import DataScope
from app.models import Artifact, ChatWorkContext, Message, Run

GROUP = r"(?:these (?:input |csv |excel |xlsx )?(?:files|spreadsheets|data)|this (?:data|dataset)|te dane|tych danych|te pliki|tych plik[óo]w|tych plikach|te arkusze|tych arkusz[ay]ch|tych arkuszy)"
SINGLE = r"(?:this (?:input )?(?:file|spreadsheet)|that (?:file|spreadsheet)|ten plik|tego pliku|tym pliku|ten arkusz|tego arkusza|tym arkuszu)"
ERROR = "The latest data input is unavailable or has no verified completed analysis. Select CSV/Excel files explicitly."


def instruction(content):
    from app.chat_pages import _instruction_text

    return re.sub(r"\s+", " ", _instruction_text(content)).strip()


def requested(content):
    text = instruction(content)
    if not re.search(rf"\b(?:{GROUP}|{SINGLE})\b", text, re.I):
        return False
    if re.search(
        r"\b(?:(?:this|that|previous|last|the)\s+(?:result|output|table)|(?:ten|tego|tym|poprzedni\w*)\s+(?:wynik\w*|tabel\w*))\b",
        text,
        re.I,
    ):
        return False
    prefix = r"^(?:(?:a|teraz|jeszcze|następnie|nastepnie|proszę|prosze|please|now|then|also|and)\s+){0,4}"
    prefix += r"(?:(?:(?:can|could|would) you|(?:czy )?(?:możesz|mozesz))\s+)?"
    operation = r"(?:calculate|compute|sum|average|group|aggregate|analy[sz]e|compare|filter|sort|count|transform|extract|policz(?:y[ćc])?|oblicz(?:y[ćc])?|przelicz(?:y[ćc])?|zsumuj|por[óo]wnaj|pogrupuj|podziel|wylicz|przeanalizuj|posortuj|wyodr[ęe]bnij)\b"
    if re.search(prefix + operation, text, re.I):
        return True
    return bool(
        re.search(prefix + r"(?:jaka|jaki|jakie|ile|what|how)\b", text, re.I)
        and re.search(
            r"\b(?:sum\w*|[śs]redn\w*|average|mean|median\w*|total|count|liczb\w*|minimum|maximum|wiersz\w*|rows?|records?|rekord\w*)\b",
            text,
            re.I,
        )
    )


def quoted_context(question, answer):
    values = {"previous_question": question[:2000], "previous_answer": answer[:2000]}
    while True:
        text = json.dumps(
            {
                **values,
                "truncated": len(values["previous_question"]) < len(question)
                or len(values["previous_answer"]) < len(answer),
            },
            ensure_ascii=False,
        )
        if len(text) <= 6000:
            return text
        key = max(values, key=lambda name: len(values[name]))
        values[key] = values[key][: -max(1, len(text) - 6000)]


def source_reference(session, user, root):
    from app.assistant import task_results
    from app.conversation_data import root_binding, validate_workflow
    from app.data_agents import DataAnswer, freeze_inputs

    scope, _ = root_binding(session, root, for_execution=False)
    if user.id != root.parameters.get("user_message_id") or user.run_id != root.id:
        raise ValueError("The selected data message does not own this analysis")
    messages = list(
        session.scalars(
            select(Message)
            .where(
                Message.run_id == root.id,
                Message.conversation_id == root.conversation_id,
                Message.role == "assistant",
            )
            .limit(2)
        )
    )
    if (
        len(messages) != 1
        or not messages[0].metadata_json.get("orchestration")
        or any(messages[0].metadata_json.get(key) for key in ("partial", "superseded", "routing_only"))
    ):
        raise ValueError("The source analysis is not a visible completed conversation result")
    workflow = session.get(Run, root.metadata_json.get("data_workflow_run_id", ""))
    if (
        workflow is None
        or workflow.status != "succeeded"
        or validate_workflow(session, workflow, for_execution=False) is not root
    ):
        raise ValueError("The original data workflow is unverified")
    if task_results(session, messages[0], root).get("task_status") != "succeeded":
        raise ValueError("The source data task did not complete successfully")
    results = [
        row
        for row in session.scalars(
            select(Run)
            .where(
                Run.task_id == root.task_id,
                Run.conversation_id == root.conversation_id,
                Run.executor_type == "agent_data_result",
                Run.status == "succeeded",
            )
            .limit(4)
        )
        if row.metadata_json.get("data_result")
    ]
    if len(results) != 1:
        raise ValueError("Choose inputs from one completed data result")
    result = results[0]
    state = result.parameters.get("agent_data") or {}
    python = session.get(Run, result.parameters.get("python_run_id", ""))
    ids = [str(aid) for aid in scope.input_artifact_ids]
    if (
        result.agent_id is not None
        or result.project_id != workflow.project_id
        or state.get("workflow_run_id") != workflow.id
        or state.get("definition") != workflow.parameters.get("definition")
        or state.get("data_inputs") != root.parameters.get("data_inputs")
        or result.metadata_json["data_result"].get("input_artifact_ids") != ids
        or python is None
        or python.executor_type != "python"
        or python.status != "succeeded"
        or python.task_id != root.task_id
        or python.project_id != workflow.project_id
        or python.conversation_id != root.conversation_id
        or python.agent_id is not None
        or result.parent_run_id != python.id
        or python.parameters.get("agent_data") != state
        or python.metadata_json.get("data_result_run_id") != result.id
        or not python.metadata_json.get("process_confirmed_gone")
    ):
        raise ValueError("The completed result does not belong to its original inputs")
    frozen = freeze_inputs(session, scope.files())
    if frozen != root.parameters.get("data_inputs"):
        raise ValueError("The original data input or inspection changed")
    answer = DataAnswer.model_validate(
        {key: result.metadata_json["data_result"][key] for key in DataAnswer.model_fields}
    )
    return {
        "source_kind": "analyzed_data",
        "artifact_id": ids[0],
        "artifact_ids": ids,
        "filenames": [session.get(Artifact, aid).original_filename for aid in ids],
        "message_id": messages[0].id,
        "user_message_id": user.id,
        "run_id": root.id,
        "data_scope": scope.model_dump(mode="json"),
        "data_inputs": frozen,
        "context": quoted_context(root.parameters["content"], answer.answer),
    }


def resolve(session, conversation, body, mode):
    if mode not in {"chat", "work", "orchestrator"} or body.action != "auto" or body.data is not None:
        return body, None
    if (
        any(
            getattr(body, key, None)
            for key in (
                "attachments",
                "image_artifact_ids",
                "audio_artifact_id",
                "speech_text",
                "music",
                "media",
                "github",
                "coding",
                "new_project",
                "project_defaults",
                "continuation",
                "commit",
                "publish",
                "load",
                "stop",
                "upscale_result",
            )
        )
        or body.web_search.enabled
        and (body.web_search.query.strip() or body.web_search.render_pages)
    ):
        return body, None
    context = session.get(ChatWorkContext, conversation.id)
    if context and context.task_id:
        return body, None
    if not requested(body.content):
        return body, None
    from app.assistant import explicit_plan

    if explicit_plan(body.model_dump(mode="json", exclude={"attachments"})) is not None:
        return body, None
    previous = session.execute(
        select(Message, Run)
        .outerjoin(Run, Message.run_id == Run.id)
        .where(Message.conversation_id == conversation.id, Message.role == "user")
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(64)
    )
    for user, root in previous:
        params = root.parameters if root is not None else {}
        if user.metadata_json.get("data_scope") or params.get("data"):
            try:
                reference = source_reference(session, user, root)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise HTTPException(422, ERROR) from exc
            if len(reference["artifact_ids"]) > 1 and not re.search(GROUP, instruction(body.content), re.I):
                raise HTTPException(
                    422, "Several analysed files match. Refer to the group or select one file."
                )
            from app.conversation_data import prepare_turn

            return prepare_turn(
                body.model_copy(update={"data": DataScope.model_validate(reference["data_scope"])})
            ), reference
        if (
            user.metadata_json.get("attachments")
            or user.metadata_json.get("images")
            or params.get("audio_artifact_id")
            or params.get("image_artifact_ids")
        ):
            return body, None
    return body, None


def verify_reference(session, run):
    reference = run.parameters.get("data_reference")
    user = session.get(Message, run.parameters.get("user_message_id", ""))
    recorded = user.metadata_json.get("conversation_reference") if user else None
    if not reference and not (recorded and recorded.get("source_kind") == "analyzed_data"):
        return
    if not reference or reference != recorded or reference.get("source_kind") != "analyzed_data":
        raise ValueError("The data continuation differs from its submitted source")
    source = session.get(Run, reference["run_id"])
    prior = session.get(Message, reference["user_message_id"])
    if (
        source is None
        or prior is None
        or source.conversation_id != run.conversation_id
        or prior.conversation_id != run.conversation_id
    ):
        raise ValueError("The data continuation source belongs to another conversation")
    if (
        source_reference(session, prior, source) != reference
        or run.parameters.get("data_inputs") != reference["data_inputs"]
        or run.parameters.get("data") != reference["data_scope"]
    ):
        raise ValueError("The data continuation source changed after Send")

"""Immutable public-source JSON input for the existing offline Python workflow."""

import json
import tempfile
from pathlib import Path

from app.agent_coding_policy import coding_research_steps
from app.artifacts import register_file
from app.models import Artifact, Run
from app.python_execution import input_snapshots, read_owned_file

MAX_SNAPSHOT_BYTES = 128 * 1024


def snapshot_research(session, handoff, definition):
    from app.agent_page_coding import verified_sources

    parent, observations, provenance = verified_sources(session, handoff, definition, complete=True)
    if not parent.agent_id or "python_data" not in definition.tools:
        raise ValueError("Research data requires its reviewed persistent Python agent")
    payload = json.dumps({"observations": observations}, ensure_ascii=False).encode()
    if len(payload) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Public research exceeds the bounded offline input; review fewer sources")
    with tempfile.NamedTemporaryFile(suffix=".json") as handle:
        handle.write(payload)
        handle.flush()
        artifact = register_file(
            session,
            source=Path(handle.name),
            artifact_type="json",
            mime_type="application/json",
            original_filename="research.json",
            run_id=handoff.id,
            parent_artifact_ids=[aid for item in provenance for aid in item["artifact_ids"]],
            metadata={"agent_data_research": True},
        )
    return {"context_run_id": handoff.id, "input": input_snapshots(session, [artifact.id])[0]}


def verify_research(session, workflow, receipt, definition):
    """Recheck exact source provenance and snapshot bytes on every data attempt."""
    from app.agent_page_coding import verified_sources

    reviewed = bool(coding_research_steps(definition.tools))
    if not reviewed:
        if receipt is not None or workflow.parameters.get("data_research") is not None:
            raise ValueError("Data analysis cannot inherit unreviewed public sources")
        return None
    if (
        not isinstance(receipt, dict)
        or workflow.agent_id is None
        or workflow.parameters.get("data_research") != receipt
        or not isinstance(receipt.get("input"), dict)
    ):
        raise ValueError("Data analysis lost its reviewed research binding")
    handoff = session.get(Run, receipt.get("context_run_id"))
    artifact = session.get(Artifact, receipt["input"].get("artifact_id"))
    if (
        handoff is None
        or handoff.executor_type != "agent_page_coding"
        or handoff.status != "succeeded"
        or handoff.parent_run_id != workflow.id
        or artifact is None
        or artifact.run_id != handoff.id
        or artifact.artifact_type != "json"
        or artifact.mime_type != "application/json"
        or artifact.metadata_json.get("agent_data_research") is not True
        or input_snapshots(session, [artifact.id]) != [receipt["input"]]
    ):
        raise ValueError("Research snapshot does not belong to the successful source handoff")
    parent, observations, provenance = verified_sources(session, handoff, definition, complete=True)
    if parent.id != workflow.id or artifact.parent_artifact_ids != [
        aid for item in provenance for aid in item["artifact_ids"]
    ]:
        raise ValueError("Research snapshot changed its source lineage")
    path = read_owned_file(
        artifact.relative_path, artifact.size_bytes, artifact.sha256, limit=MAX_SNAPSHOT_BYTES
    )
    if json.loads(path.read_bytes()) != {"observations": observations}:
        raise ValueError("Research snapshot differs from the original public observations")
    _, excerpts, _ = verified_sources(session, handoff, definition)
    return {
        "input_name": artifact.id + ".json",
        "observations": excerpts,
        "full_source_in_input_file": True,
    }


def execution_inputs(scope):
    inputs = [
        {key: value for key, value in item.items() if key not in {"preview_run_id", "preview_artifact_id"}}
        for item in scope["data_inputs"]
    ]
    if scope.get("data_research"):
        inputs.append(scope["data_research"]["input"])
    return inputs

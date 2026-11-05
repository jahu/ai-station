"""Existing model-install Runs can recheck an encoder without transferring weights."""

import asyncio

from app.config import get_settings
from app.embedding_process import CpuEmbeddingProcess, reserve_cpu
from app.models import User
from app.registered_embeddings import frozen
from app.runs import transition
from app.state import RunStatus
from app.task_control import lock_task


def execute(session, run, definition):
    claim = run.worker_id, run.claimed_at
    if not reserve_cpu(session, run):
        return "requeued"
    if frozen(session, definition.id) != run.parameters["embedding_model"]:
        raise ValueError("The encoder binding changed after re-check was queued")
    transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
    transition(session, run, RunStatus.RUNNING, event_type="executor.started")
    session.commit()

    async def verify():
        async with asyncio.timeout(90):
            cpu = CpuEmbeddingProcess(session, run, get_settings().data_dir)
            try:
                await cpu.open(admit=True)
                await cpu.encode("ai-station embedding probe", "query")
                return cpu.proof
            finally:
                await cpu.close()

    try:
        proof = asyncio.run(verify())
    finally:
        if (run.worker_id, run.claimed_at) == claim and (
            run.pid is None or run.metadata_json.get("cpu_process_confirmed_gone")
        ):
            from app.resources import release_run_locks

            release_run_locks(session, run.id)
    lock_task(session, run.task)
    session.refresh(run)
    if (run.worker_id, run.claimed_at) != claim:
        session.rollback()
        return "done"
    if run.status != "running" or run.task.metadata_json.get("stop_requested_at"):
        return "done"
    if run.owner_id:
        owner = session.get(User, run.owner_id, populate_existing=True, with_for_update=True)
        if owner is None or not owner.enabled or not owner.is_admin:
            raise ValueError("Encoder re-check administrator authority changed")
    if frozen(session, definition.id) != run.parameters["embedding_model"]:
        raise ValueError("The encoder changed before re-check publication")
    definition.last_verify_run_id = run.id
    definition.metadata_json = {
        **definition.metadata_json,
        "embedding": {**definition.metadata_json["embedding"], "graph": proof},
    }
    run.summary = "Encoder graph, immutable bundle and nonzero CPU probe verified without another download."
    transition(
        session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={"encoder_graph": proof}
    )
    return "done"

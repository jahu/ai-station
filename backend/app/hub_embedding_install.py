"""Complete encoder/tokenizer preparation, owned CPU admission and shared publication."""

import asyncio
import json
import tempfile
from pathlib import Path

from sqlalchemy import select

from app.artifacts import register_file
from app.config import get_settings
from app.db import utcnow
from app.embedding_binding import Binding, objects
from app.embedding_graph import recipe
from app.embedding_process import CpuEmbeddingProcess
from app.events import append_event
from app.models import ModelDefinition, ModelFile, User
from app.runs import transition
from app.state import RunStatus
from app.task_control import lock_task


def adopt(session, run, entry, model_path, check, progress, recovered, obtain):
    from app.model_download_job import Stopped

    root = get_settings().data_dir

    async def prepare():
        tokenizer = await obtain(
            root,
            entry.tokenizer,
            check=check,
            progress=lambda received, total: progress(
                entry.file.size_bytes + received, entry.file.size_bytes + total
            ),
            source_recovered=recovered,
        )
        async with asyncio.timeout(90):
            check()
            binding = Binding(
                model={
                    "sha256": entry.file.sha256,
                    "size_bytes": entry.file.size_bytes,
                    "mtime": model_path.stat().st_mtime,
                },
                tokenizer={
                    "sha256": entry.tokenizer.sha256,
                    "size_bytes": entry.tokenizer.size_bytes,
                    "mtime": tokenizer.stat().st_mtime,
                },
                schema_sha256=recipe()["schema_sha256"],
            ).model_dump(mode="json")
            run.parameters = {**run.parameters, "embedding_model": binding}
            session.commit()
            cpu = CpuEmbeddingProcess(session, run, root)
            try:
                await cpu.open(admit=True)
                vector = await cpu.encode("ai-station embedding probe", "query")
                if len(vector) != 384:
                    raise ValueError("The encoder returned the wrong dimension")
                return binding, cpu.proof
            finally:
                await cpu.close()

    binding, proof = asyncio.run(prepare())
    check()
    lock_task(session, run.task)
    check(commit=False)
    if run.task.metadata_json.get("stop_requested_at") or run.status != "running":
        raise Stopped("Encoder installation stopped before publication")
    if (run.task.metadata_json.get("model_download") or {}).get("license_accepted") is not True:
        raise ValueError("Review and accept the encoder/tokenizer licenses")
    if run.owner_id:
        owner = session.get(User, run.owner_id, populate_existing=True, with_for_update=True)
        if owner is None or not owner.enabled or not owner.is_admin:
            raise Stopped("Encoder installation administrator authority changed")
    objects(root, binding)
    files = []
    for role, spec, name in (
        ("model", entry.file, entry.filename),
        ("tokenizer", entry.tokenizer, "tokenizer.json"),
    ):
        source = binding[role]
        relative = "models/store/" + spec.sha256
        file = session.scalar(select(ModelFile).where(ModelFile.relative_path == relative))
        if file is None:
            file = ModelFile(
                host_path=None,
                relative_path=relative,
                sha256=spec.sha256,
                filename=name,
                size_bytes=spec.size_bytes,
                mtime=source["mtime"],
                format="onnx" if role == "model" else "json",
                category="other",
                family="bert_e5_small",
                quantization="F32" if role == "model" else None,
                capabilities=["embedding" if role == "model" else "embedding_tokenizer"],
                root_label="AI Station storage",
                availability="present",
                last_seen_at=utcnow(),
            )
            session.add(file)
            session.flush()
        elif (
            file.sha256 != spec.sha256
            or file.size_bytes != spec.size_bytes
            or abs(file.mtime - source["mtime"]) > 0.001
        ):
            raise ValueError("A registered encoder bundle object changed")
        files.append(file)
    definition = session.scalar(select(ModelDefinition).where(ModelDefinition.file_id == files[0].id))
    if definition is not None and (definition.metadata_json.get("embedding") or {}).get("binding") != binding:
        raise ValueError("This encoder already has another binding; inspect its definition")
    if definition is None:
        definition = ModelDefinition(
            name=entry.name,
            file_id=files[0].id,
            category="other",
            family="bert_e5_small",
            capabilities=["embedding"],
            status="registered",
            last_verify_run_id=run.id,
            metadata_json={
                "embedding": {"binding": binding, "graph": proof, "probe_checked": True},
                "source": entry.model_dump(mode="json"),
                "locally_qualified": False,
            },
        )
        session.add(definition)
        session.flush()
    total = entry.file.size_bytes + entry.tokenizer.size_bytes
    result = {
        "model_file_id": files[0].id,
        "definition_id": definition.id,
        "binding": binding,
        "graph": proof,
        "probe_checked": True,
        "locally_qualified": False,
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json") as receipt:
        json.dump(result, receipt)
        receipt.flush()
        register_file(
            session,
            source=Path(receipt.name),
            artifact_type="json",
            mime_type="application/json",
            original_filename="memory-encoder-preparation.json",
            run_id=run.id,
            metadata={"embedding_model_preparation": True},
        )
    run.metadata_json = {
        **run.metadata_json,
        **result,
        "model_download": {
            "phase": "files_verified",
            "received_bytes": total,
            "expected_bytes": total,
            "ready_to_try": True,
        },
    }
    run.summary = "Encoder and tokenizer verified on CPU. Choose Use for memory to change semantic retrieval."
    append_event(session, run.id, "model.download.verified", result)
    transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
    return "done"

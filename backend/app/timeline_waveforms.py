"""Bounded source waveforms are ordinary private worker Runs, never invented UI."""

import array
import sys
import wave
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.db import utcnow
from app.events import append_event
from app.heartbeat import cancel_expired_run
from app.models import Artifact, Run
from app.permissions import require
from app.runs import create_run, create_task, run_dict, transition
from app.state import RunStatus
from app.timelines import DB, source_snapshot

router = APIRouter(prefix="/api/timelines", tags=["media waveforms"])


def peaks(reader):
    samples, channels, width = reader.getnframes(), reader.getnchannels(), reader.getsampwidth()
    for index in range(512):
        first, end = index * samples // 512, (index + 1) * samples // 512
        raw = reader.readframes(end - first)
        if len(raw) != (end - first) * channels * width:
            raise ValueError("Waveform source is truncated")
        if width == 1:
            peak = max((abs(v - 128) for v in raw), default=0) / 128
        elif width == 3:
            peak = max(
                (abs(int.from_bytes(raw[i : i + 3], "little", signed=True)) for i in range(0, len(raw), 3)),
                default=0,
            ) / (2**23)
        else:
            values = array.array("h" if width == 2 else "i")
            values.frombytes(raw)
            if sys.byteorder != "little":
                values.byteswap()
            peak = max((abs(v) for v in values), default=0) / (2 ** (8 * width - 1))
        yield round(min(1.0, peak), 5)


@router.post("/waveforms/{artifact_id}", status_code=202)
def waveform(artifact_id: UUID, session: DB):
    from app.data_access import private_for_update

    artifact = private_for_update(session, Artifact, str(artifact_id))
    if artifact is None:
        raise HTTPException(404, "Audio not found")
    try:
        source = source_snapshot(session, artifact_id)
        if source["kind"] != "audio":
            raise ValueError("Choose a PCM WAV waveform")
    except (ValueError, OSError, wave.Error, EOFError) as exc:
        raise HTTPException(422, str(exc)) from exc
    rows = session.scalars(
        select(Run)
        .where(
            Run.executor_type == "timeline_waveform",
            Run.parameters["source"]["artifact_id"].as_string() == source["artifact_id"],
            Run.parameters["source"]["sha256"].as_string() == source["sha256"],
            Run.status.not_in(["failed", "canceled", "interrupted"]),
        )
        .order_by(Run.created_at.desc())
        .limit(10)
    )
    for row in rows:
        if row.parameters.get("source") == source:
            return run_dict(row)
    task = create_task(
        session,
        title="Inspect audio waveform",
        prompt="Build an owned source waveform",
        capability="media.waveform",
    )
    run = create_run(
        session,
        task,
        run_type="inspection",
        capability="media.waveform",
        executor_type="timeline_waveform",
        execution_target="container",
        requested_gpu="none",
        permissions=["filesystem_read", "workspace_write"],
        retry_class="safe",
        parameters={"source": source},
    )
    session.commit()
    return run_dict(run)


class WaveformExecutor:
    name = "timeline_waveform"

    def execute(self, session, run):
        from app.config import get_settings
        from app.paths import safe_join

        require(run.effective_permissions, "filesystem_read")
        require(run.effective_permissions, "workspace_write")
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        source = source_snapshot(session, run.parameters["source"]["artifact_id"], verify=True)
        if source != run.parameters["source"]:
            raise ValueError("Waveform source identity changed")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        session.commit()
        values = []
        with wave.open(str(safe_join(get_settings().data_dir, source["relative_path"]))) as reader:
            for value in peaks(reader):
                values.append(value)
                if len(values) % 16 == 0:
                    session.refresh(run)
                    cancel_expired_run(session, run.id)
                    if run.status == "cancel_requested":
                        transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                        session.commit()
                        return "done"
                    session.commit()
        current = source_snapshot(session, source["artifact_id"], verify=True)
        if current != source:
            raise ValueError("Waveform source changed during inspection")
        run.metadata_json = {
            **run.metadata_json,
            "waveform": {
                "peaks": values,
                "source_sha256": source["sha256"],
                "samples": source["samples"],
                "sample_rate": source["sample_rate"],
                "channels": source["channels"],
            },
        }
        append_event(
            session, run.id, "media.waveform.inspected", {"samples": source["samples"], "bins": len(values)}
        )
        transition(
            session,
            run,
            RunStatus.SUCCEEDED,
            event_type="run.completed",
            payload={"inspected_at": utcnow().isoformat()},
        )
        return "done"

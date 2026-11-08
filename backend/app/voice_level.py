"""Worker-only speech finishing and explicit non-destructive Library repair Runs."""

import tempfile
import time
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4, uuid5

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError

from app.artifacts import adopt_existing
from app.config import get_settings
from app.db import session_scope
from app.events import append_event
from app.heartbeat import cancel_expired_run
from app.host_media_executor import HostMediaExecutor
from app.models import Artifact, Task
from app.paths import artifact_relative, safe_join
from app.permissions import require
from app.runs import create_run, run_dict, transition
from app.state import RunStatus
from app.voice_level_dsp import PROFILE, digest, level_wave, mux_voice

router = APIRouter(prefix="/api/artifacts")
DB = Annotated[object, Depends(session_scope, scope="function")]


class FinishingCanceled(Exception):
    pass


class FinishingClaimLost(Exception):
    pass


def checked_source(session, identity, expected=None):
    source = session.get(Artifact, str(identity), populate_existing=True)
    if source is None or source.trashed_at or source.purge_run_id or source.purged_at:
        raise ValueError("Choose available media from your Library")
    if (source.artifact_type, source.mime_type) not in {("audio", "audio/wav"), ("video", "video/mp4")}:
        raise ValueError("Choose PCM WAV speech or an MP4 with a voice track")
    snapshot = {
        "id": source.id,
        "relative_path": source.relative_path,
        "size_bytes": source.size_bytes,
        "sha256": source.sha256,
        "artifact_type": source.artifact_type,
        "mime_type": source.mime_type,
    }
    if expected is not None and snapshot != expected:
        raise ValueError("The source changed after voice leveling was queued")
    return source, snapshot


def process_output(relative, run_id, check, expected_sha=None):
    root = get_settings().data_dir.resolve()
    source = safe_join(root, relative)
    if (
        source != root / relative
        or not relative.startswith("artifacts/")
        or source.suffix not in {".wav", ".mp4"}
    ):
        raise ValueError("Voice input must stay inside its canonical artifact boundary")
    if source.stat().st_size > 2 * 1024**3:
        raise ValueError("Voice input exceeds its decode budget")
    original_sha = digest(source, check)
    if expected_sha and original_sha != expected_sha:
        raise ValueError("Voice input bytes changed")
    work = safe_join(root, f"runs/{run_id}")
    if work != root / f"runs/{run_id}":
        raise ValueError("Voice work cannot cross symlinks")
    work.mkdir(parents=True, exist_ok=True)
    output_relative = artifact_relative(str(uuid4()), source.suffix)
    output = safe_join(root, output_relative)
    if output != root / output_relative:
        raise ValueError("Voice output cannot cross symlinks")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="voice-level-", dir=work) as private:
        pcm = Path(private) / "voice.wav"
        report = level_wave(source, pcm, check)
        processed = Path(private) / "result.mp4" if source.suffix == ".mp4" else pcm
        if source.suffix == ".mp4":
            mux_voice(source, pcm, processed, report, check)
        check()
        if source != safe_join(root, relative) or digest(source, check) != original_sha:
            raise ValueError("Voice input changed during processing")
        if output != safe_join(root, output_relative):
            raise ValueError("Voice output boundary changed")
        import os

        processed.chmod(0o600)
        os.link(processed, output)  # No overwrite, including after a lost worker acknowledgement.
    report["source_sha256"] = original_sha
    return output_relative, {"audio_leveling": report}


def pulse(executor, session, run, claim, source=None):
    last = 0.0

    def check(force=False):
        nonlocal last
        if not force and time.monotonic() - last < 0.5:
            return
        canceled = False

        def observe():
            nonlocal canceled
            cancel_expired_run(session, run.id)
            canceled = run.status == "cancel_requested"
            if source:
                checked_source(session, source["id"], source)

        if not executor._database_step(session, run, claim, observe):
            raise FinishingClaimLost
        if canceled:
            raise FinishingCanceled
        last = time.monotonic()

    return check


def finish_generated(executor, session, run, claim, output):
    """No database transaction spans CPU decoding, filters or packet copying."""
    if executor.name not in {"chatterbox", "fish_speech", "sonic_whole", "echomimic", "media_compose"}:
        return output, {}
    if executor.artifact_type == "video":
        for identity in [
            *run.parameters.get("parent_artifact_ids", []),
            run.parameters.get("canonical_audio_id"),
        ]:
            if not identity:
                continue
            source = session.get(Artifact, identity)
            receipt = source.metadata_json.get("audio_leveling") if source else None
            if (
                source
                and source.artifact_type == "audio"
                and isinstance(receipt, dict)
                and receipt.get("profile") == PROFILE
            ):
                inherited = {
                    **receipt,
                    "inherited_from_artifact_id": source.id,
                    "inherited_from_sha256": source.sha256,
                }
                session.commit()
                return output, {"audio_leveling": inherited}
    if run.parameters.get("level_volume") is not True:
        session.commit()
        return output, {}
    if run.parameters.get("audio_level_profile") != PROFILE:
        raise ValueError("The saved voice finishing profile is unavailable; inspect before retrying")
    session.commit()
    check = pulse(executor, session, run, claim)
    check(True)
    executor._database_step(
        session,
        run,
        claim,
        lambda: append_event(session, run.id, "audio.leveling.started", {"profile": PROFILE}),
    )
    result = process_output(output, run.id, check)
    check(True)
    return result


class LevelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: UUID


@router.post("/{artifact_id}/voice-level", status_code=202)
def enqueue_level(artifact_id: UUID, body: LevelRequest, session: DB):
    try:
        source, snapshot = checked_source(session, artifact_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    identity = str(uuid5(body.client_request_id, "voice-level:" + source.id))
    existing = session.get(Task, identity)
    if existing:
        if existing.metadata_json != {"voice_source": snapshot, "profile": PROFILE}:
            raise HTTPException(409, "This request already refers to different voice input")
        return run_dict(existing.runs[0])
    if (source.metadata_json.get("audio_leveling") or {}).get("profile") == PROFILE:
        raise HTTPException(409, "This recording already has even voice volume")
    task = Task(
        id=identity,
        title="Even out voice volume",
        prompt="Balance the existing spoken audio without changing its words or timing.",
        capability="audio.level",
        metadata_json={"voice_source": snapshot, "profile": PROFILE},
    )
    session.add(task)
    try:
        session.flush()
        run = create_run(
            session,
            task,
            run_type=source.artifact_type,
            capability="audio.level",
            executor_type="voice_level",
            execution_target="container",
            requested_gpu="none",
            permissions=["filesystem_read", "workspace_write"],
            retry_class="safe",
            parameters={"source": snapshot, "parent_artifact_ids": [source.id], "profile": PROFILE},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.get(Task, identity)
        if not existing or existing.metadata_json != {"voice_source": snapshot, "profile": PROFILE}:
            raise
        run = existing.runs[0]
    return run_dict(run)


class VoiceLevelExecutor(HostMediaExecutor):
    name = "voice_level"
    requires_gpu = False

    def execute(self, session, run):
        require(run.effective_permissions, "filesystem_read")
        require(run.effective_permissions, "workspace_write")
        if run.parameters.get("profile") != PROFILE:
            raise ValueError("The saved voice processing profile changed")
        claim = (run.worker_id, run.claimed_at)
        if self._cancel_before_dispatch(session, run):
            session.commit()
            return "done"
        source, snapshot = checked_source(session, run.parameters["source"]["id"], run.parameters["source"])
        filename = Path(source.original_filename).stem[:200]
        display_name = source.title or filename
        inherited = {
            k: v
            for k, v in source.metadata_json.items()
            if k
            in {
                "backend",
                "capability",
                "width",
                "height",
                "fps",
                "duration_seconds",
                "sample_rate",
                "channels",
            }
        }
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="run.started")
        append_event(session, run.id, "audio.leveling.started", {"profile": PROFILE})
        session.commit()
        check = pulse(self, session, run, claim, snapshot)
        try:
            output, metadata = process_output(snapshot["relative_path"], run.id, check, snapshot["sha256"])
            check(True)
        except FinishingClaimLost:
            return "done"
        except FinishingCanceled:
            self._database_step(
                session,
                run,
                claim,
                lambda: transition(session, run, RunStatus.CANCELED, event_type="run.canceled"),
            )
            return "done"

        def publish():
            checked_source(session, snapshot["id"], snapshot)
            if run.status == "cancel_requested":
                transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
                return
            a = adopt_existing(
                session,
                relative_path=output,
                artifact_type=snapshot["artifact_type"],
                mime_type=snapshot["mime_type"],
                original_filename=filename + "-balanced" + Path(output).suffix,
                run_id=run.id,
                parent_artifact_ids=[snapshot["id"]],
                metadata={**inherited, **metadata, "source_artifact_id": snapshot["id"]},
            )
            a.title = (display_name + " · balanced voice volume")[:200]
            run.metadata_json = {**run.metadata_json, "result_artifact_id": a.id}
            append_event(session, run.id, "audio.leveling.completed", metadata["audio_leveling"])
            transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")

        self._database_step(session, run, claim, publish)
        return "done"

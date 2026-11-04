"""Worker-only cancellation of revoked runtime preparation and managed image jobs.

No execution session, identity impersonation or machine-policy grant is issued.
Only the exact immutable owned native action can be canceled; uncertain cleanup
retains its lease/reservations and never dispatches another action.
"""

import re

from app.data_access import DataAccessError, ScopedSession
from app.events import append_event
from app.models import Run, User
from app.resources import release_run_locks
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import touch_lease, transition
from app.runtime_setup_job import cancel_payload, confirmed_gone, validate_operation
from app.state import RunStatus


def cleanup_revoked_runtime_setup(session, run, worker_id):
    if isinstance(session, ScopedSession):
        raise DataAccessError("Revoked operation cleanup requires trusted worker coordination")
    image_job = run.executor_type == "photo_pipe" and isinstance(
        run.parameters.get("managed_image_runtime"), dict
    )
    if (
        run.executor_type
        not in {
            "runtime_setup",
            "speech_setup",
            "image_setup",
            "music_setup",
            "video_setup",
            "avatar_setup",
            "effects_setup",
            "fish_setup",
            "native_llama_setup",
        }
        and not image_job
    ) or run.owner_id is None:
        return False
    inputs = run.executor_type in {
        "speech_setup",
        "image_setup",
        "music_setup",
        "video_setup",
        "avatar_setup",
        "effects_setup",
        "fish_setup",
        "native_llama_setup",
    }
    if inputs:
        from app.speech_setup_job import SpeechSetupExecutor

        if run.executor_type == "native_llama_setup":
            from app.native_llama_setup_job import NativeLlamaSetupExecutor

            input_contract = NativeLlamaSetupExecutor()
        elif run.executor_type == "fish_setup":
            from app.fish_setup_job import FishSetupExecutor

            input_contract = FishSetupExecutor()
        elif run.executor_type == "effects_setup":
            from app.effects_setup_job import EffectsSetupExecutor

            input_contract = EffectsSetupExecutor()
        elif run.executor_type == "avatar_setup":
            from app.avatar_setup_job import AvatarSetupExecutor

            input_contract = AvatarSetupExecutor()
        elif run.executor_type == "video_setup":
            from app.video_setup_job import VideoSetupExecutor

            input_contract = VideoSetupExecutor()
        elif run.executor_type == "music_setup":
            from app.music_setup_job import MusicSetupExecutor

            input_contract = MusicSetupExecutor()
        elif run.executor_type == "image_setup":
            from app.image_setup_job import ImageSetupExecutor

            input_contract = ImageSetupExecutor()
        else:
            input_contract = SpeechSetupExecutor()
    user = session.get(User, run.owner_id, populate_existing=True)
    if user is not None and user.enabled and (image_job or user.is_admin) and not user.bootstrap_pending:
        return False
    if not run.metadata_json.get("dispatch_attempted"):
        return False
    identity, owner_id = run.id, run.owner_id
    run = session.get(Run, identity, populate_existing=True, with_for_update=True)
    if (
        run is None
        or run.owner_id != owner_id
        or run.worker_id != worker_id
        or run.status
        not in {RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.CANCEL_REQUESTED}
    ):
        session.commit()
        return True
    try:
        if image_job:
            runtime = run.parameters["managed_image_runtime"]
            if (
                run.execution_target != "container"
                or run.task is None
                or run.task.owner_id != run.owner_id
                or runtime.get("profile") != "qwen-image21-cuda-linux-amd64-v1"
                or not isinstance(runtime.get("manifest_sha256"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", runtime["manifest_sha256"])
                or not {"filesystem_read", "workspace_write"} <= set(run.effective_permissions)
            ):
                raise ValueError("The managed image identity requires inspection")
        elif inputs:
            input_contract.validate(run)
        else:
            validate_operation(run)
    except ValueError:
        run.metadata_json = {
            **run.metadata_json,
            "cleanup_requires_inspection": True,
            "cancel_on_resume": True,
        }
        run.error_type = "RevokedOperationNeedsInspection"
        run.error_message = "The owned runtime preparation identity requires inspection"
        transition(session, run, RunStatus.INTERRUPTED, event_type="run.interrupted")
        session.commit()
        return True
    if run.status != RunStatus.CANCEL_REQUESTED:
        transition(session, run, RunStatus.CANCEL_REQUESTED, event_type="run.cancel_requested")
    run.metadata_json = {**run.metadata_json, "cancel_on_resume": True, "cleanup_requires_inspection": True}
    touch_lease(session, run)
    payload = None if image_job else cancel_payload(run)
    confirmed = run.metadata_json.get("process_confirmed_gone") is True
    session.commit()  # Native I/O must not hold the database transaction.
    if not confirmed:
        try:
            if image_job:
                from app.managed_image_client import ManagedImageClient

                result = ManagedImageClient(timeout=10).cancel_process(identity)
                confirmed = (
                    result.get("run_id") == identity
                    and result.get("executor") == "photo_pipe"
                    and result.get("execution_target") == "container"
                    and result.get("alive") is False
                    and not result.get("completion_pending")
                    and result.get("status") == "canceled"
                )
            else:
                client = input_contract.runner() if inputs else RunnerClient(timeout=10)
                result = client.cancel_runtime_preparation(identity, payload)
                confirmed = confirmed_gone(result, run)
        except (RunnerError, RunnerUnavailable, ValueError):
            confirmed = False  # Never persist a native daemon/configuration details or raw error.
    run = session.get(Run, identity, populate_existing=True, with_for_update=True)
    if (
        run is None
        or run.owner_id != owner_id
        or run.worker_id != worker_id
        or run.status != RunStatus.CANCEL_REQUESTED
    ):
        session.commit()
        return True
    if confirmed:
        run.metadata_json = {
            **run.metadata_json,
            "process_confirmed_gone": True,
            "cleanup_requires_inspection": False,
        }
        transition(
            session, run, RunStatus.CANCELED, event_type="run.canceled", payload={"authority_revoked": True}
        )
        release_run_locks(session, identity)
    else:
        touch_lease(session, run)
        append_event(session, identity, "recovery.cleanup_pending", {"authority_revoked": True})
    session.commit()
    return True

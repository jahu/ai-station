"""A licensed model Task may own exactly its pinned image/video prerequisite."""

from sqlalchemy.orm import object_session

from app.hub_candidates import download_candidate
from app.model_setup import INTENT, fingerprint
from app.models import Run, RunDependency


def owns_preparation(run):
    task = run.task
    saved = task.metadata_json.get("model_download") or {}
    if (
        task.intent != INTENT
        or ((saved.get("entry") or {}).get("origin"), run.executor_type)
        not in {("hub_image", "image_setup"), ("hub_video", "video_setup")}
        or task.owner_id != run.owner_id
        or saved.get("license_accepted") is not True
        or (
            (saved.get("entry") or {}).get("origin") == "hub_video"
            and saved.get("workload_accepted") is not True
        )
        or fingerprint(saved.get("entry")) != saved.get("manifest_sha256")
    ):
        return False
    entry = download_candidate(saved["entry"])
    session = object_session(run)
    parent = session.get(Run, saved.get("run_id")) if session and saved.get("run_id") else None
    return bool(
        parent
        and parent.task_id == task.id
        and parent.owner_id == run.owner_id
        and parent.executor_type == "model_download"
        and parent.parameters.get("entry") == saved["entry"]
        and parent.parameters.get("manifest_sha256") == saved["manifest_sha256"]
        and entry.prepare_engine
        and entry.setup_recipe == run.parameters.get("recipe")
        and entry.setup_manifest_sha256 == run.parameters.get("manifest_sha256")
        and session.get(RunDependency, (parent.id, run.id)) is not None
    )

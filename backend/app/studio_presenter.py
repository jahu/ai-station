"""Optional presenter stages inside the existing whole-material Task coordinator."""

from copy import deepcopy
from typing import Literal
from uuid import UUID, uuid5

from ai_station_runner.motion_contract import Presenter
from fastapi import HTTPException
from pydantic import Field, StrictInt
from sqlalchemy import select

from app.avatar_models import profile_for_request
from app.media_jobs import FullAvatarRequest, publish_avatar
from app.models import Artifact, Run
from app.studio_materials import source_snapshot
from app.studio_narration import NarrationRequest, create_narration
from app.studio_presenter_sources import portrait_snapshot
from app.studio_schema import Fields
from app.studio_soundtrack import audio_source
from app.whole_avatars import PROFILE, verify_recipe


class GeneratePresenter(Fields):
    image_artifact_id: UUID
    model_id: UUID | None = None
    seed: StrictInt = Field(default=43, ge=0, le=2147483647)
    gpu: str = Field(default="auto", pattern=r"^(auto|[0-9]{1,12})$")
    placement: Literal["auto", "right", "bottom"] = "auto"


def capture(session, settings, plan, ready, previous=None):
    if plan.audio not in {"voice", "voice_music"}:
        raise HTTPException(422, "Choose narration or narration with music to generate a speaking presenter")
    if ready.get("max_presenter_clips", 0) < 32:
        raise HTTPException(409, "Prepare the current Studio renderer before generating a presenter")
    portrait = portrait_snapshot(session, settings.image_artifact_id)
    prior = previous.parameters.get("presenter_binding") if previous else None
    if prior:
        if prior["portrait"] != portrait:
            raise ValueError("The original presenter portrait changed; start a new production")
        return prior
    profile = profile_for_request(session, settings)
    verify_recipe(profile, profile.get("recipe"))
    return {"portrait": portrait, "profile": profile}


def restore(session, previous, state):
    if not previous or not previous.parameters.get("presenter_binding"):
        return
    from app.studio_production import all_runs

    for run in all_runs(session, previous):
        if (
            run.executor_type == "sonic_whole"
            and run.status != "succeeded"
            and run.metadata_json.get("dispatch_attempted")
            and run.metadata_json.get("process_confirmed_gone") is not True
        ):
            raise HTTPException(
                409, "Inspect the previous presenter process before continuing; it may still be running"
            )
    old = previous.metadata_json.get("production_state", {})
    if old.get("revision_id") != state["revision_id"] or old.get("soundtrack_id") != state["soundtrack_id"]:
        return
    try:
        portrait = old.get("presenter_portrait")
        if not portrait:
            return
        if source_snapshot(session, portrait["artifact_id"], verify=True) != portrait:
            return
        parts = deepcopy(old["presenter_parts"])
        for part in parts:
            if audio_source(session, part["audio"]["artifact_id"], verify=True) != part["audio"]:
                return
            if part.get("video"):
                try:
                    if presenter_source(session, part["video"]["artifact_id"], verify=True) != part["video"]:
                        part.pop("video", None)
                except (ValueError, OSError):
                    part.pop("video", None)
        state.update(presenter_portrait=portrait, presenter_parts=parts)
    except (ValueError, OSError, KeyError):
        return


def presenter_source(session, identity, *, verify=False):
    result = source_snapshot(session, identity, verify=verify, complete=True, internal_role="presenter_part")
    if result["kind"] != "video":
        raise ValueError("The presenter needs complete inspected video")
    return result


def observe(session, root, state, child, pending):
    if pending["kind"] == "presenter_narration":
        if (
            child.executor_type != "studio_narration"
            or child.parameters["studio_revision_id"] != state["revision_id"]
        ):
            raise ValueError("Presenter narration belongs to another saved edit")
        if any(
            child.parameters["soundtrack"].get(key) != state["soundtrack_source"].get(key)
            for key in ("artifact_id", "relative_path", "sha256", "size_bytes")
        ):
            raise ValueError("Presenter narration changed its approved soundtrack")
        if child.parameters.get("portrait") != root.parameters["presenter_binding"]["portrait"]:
            raise ValueError("Presenter narration changed its approved portrait")
        portrait_id = child.metadata_json.get("portrait_artifact_id")
        state["presenter_portrait"] = source_snapshot(session, portrait_id, verify=True)
        result, end = [], 0
        for part in child.metadata_json["parts"]:
            if part["start_frame"] != end or not 1 <= part["duration_frames"] <= 1800:
                raise ValueError("Presenter narration intervals changed")
            source = audio_source(session, part["artifact_id"], verify=True)
            if source["samples"] != part["samples"] or source["sample_rate"] != 48000:
                raise ValueError("Presenter speech sample coverage changed")
            result.append({"start_frame": end, "duration_frames": part["duration_frames"], "audio": source})
            end += part["duration_frames"]
        if end * 1600 != child.metadata_json["samples"] or not 1 <= len(result) <= 32:
            raise ValueError("Presenter speech does not cover the complete edit")
        state["presenter_parts"] = result
    else:
        index = pending["part"]
        parts = deepcopy(state["presenter_parts"])
        part = parts[index]
        if (
            child.executor_type != "sonic_whole"
            or child.parameters.get("studio_presenter_part") != index
            or [s["artifact_id"] for s in child.parameters.get("whole_inputs", [])]
            != [state["presenter_portrait"]["artifact_id"], part["audio"]["artifact_id"]]
        ):
            raise ValueError("Presenter output changed its reviewed sources")
        outputs = list(
            session.scalars(
                select(Artifact).where(Artifact.run_id == child.id, Artifact.artifact_type == "video")
            )
        )
        if (
            len(outputs) != 1
            or child.task.metadata_json.get("media_plan", {}).get("final_artifact_id") != outputs[0].id
        ):
            raise ValueError("Presenter requires its complete adopted avatar output")
        item = outputs[0]
        # Inspect while the completed native result is public, then classify it
        # as a complete internal part bound to this closed production registry.
        part["video"] = presenter_source(session, item.id, verify=True)
        item.metadata_json = {
            **item.metadata_json,
            "internal_media": True,
            "studio_role": "presenter_part",
            "studio_production_root_id": root.id,
            "studio_presenter_part": index,
        }
        parts[index] = part
        state["presenter_parts"] = parts


def advance(session, stage, root, state, body, revision):
    """Return true only after all actual presenter clips are adopted and frozen."""
    from app.studio_production import attach, follow

    if body.presenter is None:
        return True
    binding = root.parameters["presenter_binding"]
    if portrait_snapshot(session, body.presenter.image_artifact_id, verify=True) != binding["portrait"]:
        raise ValueError("The selected presenter portrait changed before production")
    if not state.get("presenter_parts"):
        child = create_narration(
            session,
            revision.material_id,
            NarrationRequest(
                client_request_id=uuid5(UUID(root.id), "presenter-narration"),
                revision_id=revision.id,
                portrait_artifact_id=body.presenter.image_artifact_id,
            ),
        )
        attach(session, stage, root, child)
        follow(session, stage, root, {"kind": "presenter_narration", "run_id": child.id})
        return False
    if (
        source_snapshot(session, state["presenter_portrait"]["artifact_id"], verify=True)
        != state["presenter_portrait"]
    ):
        raise ValueError("The normalized presenter portrait changed")
    for index, part in enumerate(state["presenter_parts"]):
        if audio_source(session, part["audio"]["artifact_id"], verify=True) != part["audio"]:
            raise ValueError("The prepared narration part changed")
        if part.get("video"):
            if presenter_source(session, part["video"]["artifact_id"], verify=True) != part["video"]:
                raise ValueError("The frozen presenter clip changed")
            continue
        result = publish_avatar(
            session,
            FullAvatarRequest(
                client_request_id=uuid5(UUID(root.id), "presenter:" + str(index)),
                image_artifact_id=state["presenter_portrait"]["artifact_id"],
                audio_artifact_id=part["audio"]["artifact_id"],
                generation_profile=PROFILE,
                model_id=body.presenter.model_id,
                level_volume=False,
                seed=body.presenter.seed,
                gpu=body.presenter.gpu,
            ),
            observed_profile=binding["profile"],
            execution_deadline_at=root.parameters["execution_deadline_at"],
        )
        child = session.get(Run, result["whole_run_id"])
        child.parameters = {
            **child.parameters,
            "studio_presenter_part": index,
            "studio_material_id": revision.material_id,
        }
        attach(session, stage, root, child)
        follow(session, stage, root, {"kind": "presenter", "part": index, "run_id": child.id})
        return False
    return True


def render_layer(body, state):
    if body.presenter is None:
        return None
    return Presenter(
        placement=body.presenter.placement,
        clips=[
            {"media": p["video"]["artifact_id"], "duration_frames": p["duration_frames"]}
            for p in state["presenter_parts"]
        ],
    )

"""Revision reuse preserves complete, owned takes only under an exact audio contract."""

from app.models import Run
from app.studio_materials import digest, get_material, get_revision
from app.studio_render import Presenter, audio_snapshot
from app.studio_schema import Storyboard
from app.studio_soundtrack import audio_source


def audio_contract(revision):
    plan = Storyboard.model_validate(revision.storyboard)
    return storyboard_audio_contract(plan)


def storyboard_audio_contract(plan):
    return {
        "audio": plan.audio,
        "voice_direction": plan.voice_direction,
        "narration_delivery": plan.narration_delivery.model_dump(mode="json"),
        "music_brief": plan.music_brief,
        "scenes": [
            {
                "duration_frames": shot.duration_frames,
                "narration": shot.narration,
                "narration_segments": [s.model_dump(mode="json") for s in shot.narration_segments]
                if shot.narration_segments
                else [],
            }
            for shot in plan.scenes
        ],
    }


def source_render(session, identity, target):
    render = session.get(Run, str(identity))
    if not render or render.executor_type != "motion_render" or render.status != "succeeded":
        raise ValueError("Reuse requires a completed Studio export")
    row = get_material(session, render.parameters["studio_material_id"], active=True)
    target_row = get_material(session, target.material_id, active=True)
    if render.owner_id != row.owner_id or row.owner_id != target_row.owner_id:
        raise ValueError("The source export owner changed")
    revision = get_revision(session, row, render.parameters["studio_revision_id"])
    if digest(revision.storyboard) != render.parameters["revision_sha256"]:
        raise ValueError("The source export storyboard changed")
    if audio_contract(revision) != audio_contract(target):
        raise ValueError("Reuse requires unchanged narration, performance, music and scene timing")
    return render


def capture(session, identity, revision):
    render = source_render(session, identity, revision)
    soundtrack = render.parameters["soundtrack_artifact_id"]
    state = {"revision_reuse_export_id": render.id}
    if soundtrack:
        source = audio_snapshot(session, soundtrack, Storyboard.model_validate(revision.storyboard).frames)
        if source != render.parameters["sources"].get(soundtrack):
            raise ValueError("The original soundtrack changed")
        state.update(soundtrack_id=soundtrack, soundtrack_source=audio_source(session, soundtrack))
    if presenter := render.parameters.get("presenter"):
        layer = Presenter.model_validate(presenter)
        from app.studio_materials import source_snapshot

        sources = {}
        for media, _, _ in layer.segments(Storyboard.model_validate(revision.storyboard).frames):
            source = source_snapshot(session, media, complete=True, internal_role="presenter_part")
            if source != render.parameters["sources"].get(str(media)):
                raise ValueError("The original presenter clip changed")
            sources[str(media)] = source
        state.update(reused_presenter=layer.model_dump(mode="json"), reused_presenter_sources=sources)
    return state


def verify(session, state, revision):
    if identity := state.get("revision_reuse_export_id"):
        captured = capture(session, identity, revision)
        if any(state.get(key) != value for key, value in captured.items()):
            raise ValueError("The captured revision reuse contract changed")
        for media, expected in state.get("reused_presenter_sources", {}).items():
            from app.studio_materials import source_snapshot

            if (
                source_snapshot(session, media, verify=True, complete=True, internal_role="presenter_part")
                != expected
            ):
                raise ValueError("The preserved presenter clip changed")

"""Collect independent editorial and schema defects in one bounded correction."""

import json
import math
from collections import Counter

from pydantic import ValidationError

from app.studio_schema import Storyboard, spoken_word_count, validate_spoken_word_count
from app.studio_storyboard import fit_source_timing, visual_origin


def fit_plan(plan, options, catalog, *, fit_duration=True):
    return fit_source_timing(plan, options["duration_seconds"], catalog) if fit_duration else plan


def validate_storyboard(
    text,
    options,
    sources,
    catalog,
    *,
    check_words=True,
    fit_duration=True,
    existing_visuals_only=False,
    preserved_audio=None,
):
    raw = json.loads(text)
    errors, measurements = [], {}
    scenes = raw.get("scenes") if isinstance(raw, dict) else None
    if isinstance(scenes, list) and all(isinstance(scene, dict) for scene in scenes):
        measurements["scene_count"] = len(scenes)
        measurements["visual_kinds"] = dict(
            Counter(
                s.get("visual_kind")
                if s.get("visual_kind") in ("image", "video", "library", "graphics", "reuse")
                else "invalid"
                for s in scenes
            )
        )
        if all(isinstance(s.get("narration", ""), str) for s in scenes):
            count = spoken_word_count(s.get("narration", "") for s in scenes)
            measurements["spoken_words"] = count
            if check_words:
                try:
                    validate_spoken_word_count(count, options)
                except ValueError as exc:
                    errors.append(str(exc))
        if raw.get("audio") != options["audio"]:
            errors.append("Preserve the selected audio policy")
        if raw.get("audio") in {"music", "voice_music"} and isinstance(raw.get("music_brief"), str):
            if len(raw["music_brief"]) > 512:
                errors.append("Keep the instrumental music direction within 512 characters")
    try:
        plan = Storyboard.model_validate(raw)
    except ValidationError as exc:
        plan = None
        failures = exc.errors(include_url=False, include_input=False)
        for failure in failures[:10]:
            errors.append((".".join(str(x) for x in failure["loc"]) + ": " + failure["msg"])[:300])
        if len(failures) > 10:
            errors.append(f"{len(failures) - 10} additional schema errors; recheck the complete schema")
    if plan:
        if preserved_audio is not None:
            from app.studio_revision_reuse import storyboard_audio_contract

            if storyboard_audio_contract(plan) != preserved_audio:
                errors.append(
                    "Preserve the original complete soundtrack: keep prior scene timings, spoken words, phrase directions, narration delivery and music_brief exactly. Only the requested visual/caption/identity edit is authorized."
                )
        if existing_visuals_only and any(s.visual_kind in {"image", "video"} for s in plan.scenes):
            errors.append(
                "Preserve the completed visuals: select their actual Library IDs from prior_visuals/source_catalog, or reuse an earlier scene. Do not request fresh image/video generation for this edit."
            )
        for index, shot in enumerate(plan.scenes):
            ids = [i for i in [shot.source_artifact_id, *shot.reference_artifact_ids] if i]
            if any(str(i) not in sources for i in ids):
                errors.append(f"Scene {index + 1}: choose source IDs only from the supplied catalog")
            elif any(sources[str(i)]["kind"] != "image" for i in shot.reference_artifact_ids):
                errors.append(f"Scene {index + 1}: generated-shot references must be images")
        try:
            fitted = fit_plan(plan, options, catalog, fit_duration=fit_duration)
        except ValueError as exc:
            errors.append(str(exc))
        else:
            errors += source_window_errors(fitted, catalog)
    elif isinstance(scenes, list):
        # A malformed framing/title must not hide an independently impossible
        # Library window. Inspect only finite typed raw coordinates here; the
        # complete Pydantic/source/renderer boundaries still remain mandatory.
        for index, shot in enumerate(scenes[:60]):
            if not isinstance(shot, dict) or shot.get("visual_kind") != "library":
                continue
            frames, start = shot.get("duration_frames"), shot.get("media_start_seconds", 0)
            duration = catalog.get(str(shot.get("source_artifact_id")), {}).get("duration_seconds")
            if type(frames) is int and type(start) in (int, float) and math.isfinite(start) and duration:
                if frames / 30 + start > duration + 1e-9:
                    errors.append(
                        f"Scene {index + 1}: Library footage ends at {duration:g}s; its requested window ends at {frames / 30 + start:g}s. Shorten that visual beat and its spoken line; preserve the overall requested edit."
                    )
    if errors:
        report = "Proposal measurements: " + json.dumps(measurements) + ".\n" + "\n".join(errors[:20])
        raise ValueError(report[:6000])
    return plan


def source_window_errors(plan, catalog):
    errors = []
    for index, shot in enumerate(plan.scenes):
        origin = plan.scenes[visual_origin(plan, index)]
        if origin.visual_kind != "library":
            continue
        duration = catalog.get(str(origin.source_artifact_id), {}).get("duration_seconds")
        if duration and shot.duration_frames / 30 + shot.media_start_seconds > duration + 1e-9:
            errors.append(
                f"Scene {index + 1}: Library footage ends at {duration:g}s; fitted window ends at {shot.duration_frames / 30 + shot.media_start_seconds:g}s. Shorten this beat/line within the available clip; allocate longer explanations to other scenes."
            )
    return errors

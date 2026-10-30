"""Observed media work, not a publication or execution authority."""

import hashlib
import json
import math
import re
from datetime import datetime, timedelta

from sqlalchemy import select

from app.db import utcnow
from app.events import append_event
from app.models import Run
from app.state import TERMINAL

EXECUTORS = {"photo_pipe", "wan_video", "echomimic", "chatterbox", "ace_step_music", "media_compose"}
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
# tqdm's iteration display, and sd-cli's sampler display. Byte-loading bars do
# not carry either iteration-speed unit and are deliberately ignored.
SAMPLER = re.compile(
    r"(?<!\d)(\d{1,6})/(\d{1,6})\s*(?:\[[^\r\n]{0,90}?,\s*|\s*-\s*)(\d+(?:\.\d+)?)\s*(s/it|it/s)(?!\w)"
)
CHUNK = re.compile(r"^speech\.chunk\.completed (\d{1,2})/(\d{1,2})$")
STAGES = {
    "verifying selected weights": "preparing",
    "encoding instruction on GPU": "preparing",
    "encoding references on GPU": "preparing",
    "loading diffusion model on GPU": "preparing",
    "encoding prompt": "preparing",
    "preparing first frame": "preparing",
    "preparing video": "preparing",
    "loading Wan 2.2": "preparing",
    "generating image on GPU": "generating",
    "generating frames": "generating",
    "decoding image on GPU": "finishing",
    "decoding video": "finishing",
    "saving MP4": "finishing",
    "completed": "finishing",
}
ORDER = {"preparing": 0, "generating": 1, "finishing": 2}


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 < value <= 86400


def parse_line(line, run):
    line = ANSI.sub("", line).strip()
    prefixes = {"photo_pipe": ("image.stage: ",), "wan_video": ("video.stage: ",)}
    for prefix in prefixes.get(run.executor_type, ()):
        if line.startswith(prefix) and line[len(prefix) :] in STAGES:
            return {"phase": STAGES[line[len(prefix) :]]}
    if run.executor_type == "chatterbox":
        chunk = CHUNK.fullmatch(line)
        if chunk:
            completed, total = map(int, chunk.groups())
            if 2 <= total <= 20 and 0 < completed <= total:
                return {
                    "phase": "finishing" if completed == total else "generating",
                    "completed": completed,
                    "total": total,
                    "unit": "speech fragments",
                }
        # A token counter proves generation activity, but its stopping ceiling
        # is deliberately never used as a completion denominator.
        if SAMPLER.search(line):
            return {"phase": "generating"}
        return None
    if run.executor_type == "ace_step_music":
        if line == "Loading approved local music preset (no additional music LLM).":
            return {"phase": "preparing"}
        if re.fullmatch(r"Generating \d+ seconds of music locally\.", line):
            return {"phase": "generating"}
    expected = 8 if run.executor_type == "ace_step_music" else run.parameters.get("steps")
    if type(expected) is not int or not 1 <= expected <= 1000:
        return None
    sample = SAMPLER.search(line)
    if sample:
        completed, total = map(int, sample.group(1, 2))
        speed = float(sample[3])
        seconds = speed if sample[4] == "s/it" else 1 / speed if speed else 0
        if total == expected and 0 <= completed <= total and positive(seconds):
            return {
                "phase": "finishing" if completed == total else "generating",
                "completed": completed,
                "total": total,
                "unit": "sampling steps",
                "seconds_per_unit": seconds,
            }
    return None


def observe(session, run, info):
    if run.executor_type not in EXECUTORS:
        return
    metadata = dict(run.metadata_json or {})
    previous = metadata.get("generation_progress") or {}
    current = dict(previous)
    buffers = dict(metadata.get("generation_progress_buffers") or {})
    for stream in ("stdout", "stderr"):
        text = info.get(stream, "")
        ended = (
            info.get("alive") is False
            and not info.get("completion_pending")
            and not info.get(f"{stream}_more")
        )
        if not isinstance(text, str) or not text and not ended:
            continue
        # Inspection log pages are bounded by the Runner; keep only one small
        # unfinished line across pages, including CR-based terminal displays.
        text = buffers.get(stream, "") + text[-65536:]
        if ended:
            text += "\n"
        lines = re.split(r"[\r\n]", text)
        buffers[stream] = lines.pop()[-512:]
        for line in lines:
            candidate = parse_line(line, run)
            if candidate is None:
                continue
            if ORDER[candidate["phase"]] < ORDER.get(current.get("phase"), 0):
                continue
            if "completed" in candidate and "completed" in current:
                if candidate["total"] != current["total"] or candidate["completed"] < current["completed"]:
                    continue
            if "completed" not in candidate and candidate["phase"] == current.get("phase"):
                continue
            if candidate.get("completed") == current.get("completed") and candidate["phase"] == current.get(
                "phase"
            ):
                continue
            current = {**candidate, "observed_at": utcnow().isoformat()}
    if info.get("alive") is False and info.get("exit_code") == 0:
        current = {"phase": "finishing", "observed_at": utcnow().isoformat()}
    metadata["generation_progress_buffers"] = buffers
    if current != previous:
        metadata["generation_progress"] = current
        append_event(session, run.id, "generation.progress", current)
    run.metadata_json = metadata


def begin_timing(session, run, hardware):
    if run.executor_type not in EXECUTORS or run.metadata_json.get("dispatch_attempted"):
        return
    selected = run.allocated_resources.get("gpus") or [run.actual_gpu]
    devices = [
        {key: gpu.get(key) for key in ("uuid", "name", "memory_total_mib")}
        for identity in selected
        for gpu in hardware.get("gpus", [])
        if str(gpu.get("index")) == str(identity)
    ]
    # A synthetic or incomplete hardware probe cannot qualify historical ETA.
    if not devices or any(not gpu["name"] or not gpu["memory_total_mib"] for gpu in devices):
        return
    parameters = run.parameters
    fields = (
        "backend",
        "image_model",
        "width",
        "height",
        "max_side",
        "frames",
        "steps",
        "cfg",
        "mode",
        "duration_seconds",
        "memory_profile",
        "generation_profile",
        "reference_strength",
        "reference_layout",
        "grounding_px",
        "reference_relative",
        "repeats",
        "whole_recipe",
    )
    profile = {
        "version": 1,
        "executor": run.executor_type,
        "capability": run.capability,
        "parameters": {key: parameters.get(key) for key in fields},
        "reference_count": len(parameters.get("parent_artifact_ids", [])),
        "text_bucket": math.ceil(len(str(parameters.get("text", ""))) / 50),
        "devices": devices,
        "host_memory_mib": hardware.get("memory", {}).get("total_mib"),
    }
    key = hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    recent = session.scalars(
        select(Run)
        .where(
            Run.executor_type == run.executor_type,
            Run.status == "succeeded",
            Run.owner_id == run.owner_id,
            Run.finished_at >= utcnow() - timedelta(days=30),
            Run.metadata_json["generation_timing"]["profile"].as_string() == key,
        )
        .order_by(Run.finished_at.desc())
        .limit(12)
    )
    samples = []
    for prior in recent:
        # Explicit equality is also required for legacy/unscoped operator mode.
        if prior.owner_id != run.owner_id or prior.started_at is None or prior.finished_at is None:
            continue
        seconds = (prior.finished_at - prior.started_at).total_seconds()
        if positive(seconds):
            samples.append(seconds)
    value = {"profile": key}
    if len(samples) >= 3:
        value.update(
            samples=len(samples),
            lower_seconds=math.floor(min(samples) * 0.9),
            upper_seconds=math.ceil(max(samples) * 1.1),
        )
    run.metadata_json = {**run.metadata_json, "generation_timing": value}
    append_event(session, run.id, "generation.timing.prepared", value)


def projection(run, *, now=None):
    if run.executor_type not in EXECUTORS:
        return None
    now = now or utcnow()
    phase = run.status
    metadata = run.metadata_json or {}
    observation = metadata.get("generation_progress") or {}
    if not isinstance(observation, dict):
        observation = {}
    started = run.started_at
    elapsed = max(0, (now - started).total_seconds()) if started else 0
    estimate = None
    fraction = None
    if phase == "running":
        phase = observation.get("phase", "finishing" if run.executor_type == "media_compose" else "preparing")
        stamp = observation.get("observed_at")
        try:
            age = (now - datetime.fromisoformat(stamp)).total_seconds() if stamp else math.inf
        except (ValueError, TypeError):
            age = math.inf
        rate = observation.get("seconds_per_unit")
        completed, total = observation.get("completed"), observation.get("total")
        valid = (
            type(completed) is int
            and type(total) is int
            and 0 <= completed <= total
            and total > 0
            and observation.get("unit") in {"sampling steps", "speech fragments"}
        )
        fresh = 0 <= age <= max(120, rate * 3 if positive(rate) else 120)
        if valid and fresh and phase == "generating":
            fraction = {"completed": completed, "total": total, "unit": observation["unit"]}
            if completed >= 2 and positive(rate):
                remaining = (total - completed) * rate
                estimate = {
                    "lower_seconds": math.floor(remaining * 0.7),
                    "upper_seconds": math.ceil(remaining * 1.3),
                    "basis": "observed sampling speed",
                    "scope": "sampling",
                }
        if not estimate:
            timing = metadata.get("generation_timing") or {}
            upper = timing.get("upper_seconds")
            if positive(upper) and elapsed < upper:
                estimate = {
                    "lower_seconds": max(0, timing["lower_seconds"] - math.floor(elapsed)),
                    "upper_seconds": math.ceil(upper - elapsed),
                    "basis": "similar completed jobs",
                    "samples": timing["samples"],
                    "scope": "this stage",
                }
        # Once a measured counter has stalled, historical timing must not mask it.
        if valid and not fresh:
            estimate = None
    if run.status in TERMINAL or run.status == "cancel_requested":
        estimate = None
    return {
        "phase": phase,
        "fraction": fraction,
        "elapsed_seconds": math.floor(elapsed),
        "estimate": estimate,
    }


def active_progress(runs):
    """Bounded observations for existing MediaJob projections, no extra I/O."""
    candidates = [run for run in runs if run.status not in TERMINAL and run.status != "queued"]
    if not candidates:
        candidates = [run for run in runs if run.status == "queued"][:1]
    result = []
    for run in candidates[:6]:
        value = projection(run)
        if value is not None:
            result.append({"run_id": run.id, "capability": run.capability, "status": run.status, **value})
    return result

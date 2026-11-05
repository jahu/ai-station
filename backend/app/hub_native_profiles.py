"""One bounded header read selects only a matching fixed native checkpoint slot."""

from app.hub_checkpoint_headers import inspect as inspect_header
from app.runner_client import RunnerError, RunnerUnavailable


def adapters():
    from app import hub_speech_candidates, hub_video_candidates

    return (("video_profile", hub_video_candidates), ("speech_profile", hub_speech_candidates))


async def resolve_profile(observation, check, filename=None):
    matches = [
        file
        for file in observation["files"]
        if file.get("format") == "safetensors"
        and file.get("identity_available")
        and (filename is None or file["filename"] == filename)
    ]
    if len(matches) != 1:
        raise ValueError("Choose a specific complete checkpoint file to inspect its actual graph")
    file = matches[0]
    header = await inspect_header(file, check)
    errors = []
    for key, adapter in adapters():
        try:
            value = await adapter.resolve_profile(observation, check, file["filename"], _header=header)
        except (ValueError, RunnerError, RunnerUnavailable) as exc:
            errors.append(f"{key.removesuffix('_profile')}: {str(exc)[:140]}")
        else:
            return key, value
    raise ValueError("No compatible native checkpoint slot. " + "; ".join(errors))


async def candidate(observation, filename, check):
    for key, adapter in adapters():
        saved = observation.get(key)
        if saved and saved.get("source_filename") == filename:
            return adapter.refresh_plan(adapter.candidate_from_profile(observation, filename), check)
    key, profile = await resolve_profile(observation, check, filename)
    adapter = dict(adapters())[key]
    return adapter.refresh_plan(
        adapter.candidate_from_profile({**observation, key: profile}, filename), check
    )

"""Opaque prepared music identities, shared without preparation account or Run IDs."""

import re
from pathlib import Path

from ai_station_runner import music_environment
from ai_station_runner.environment_files import read_json

PROFILE = music_environment.PROFILE


def resolve(root, observation):
    if (
        not isinstance(observation, dict)
        or set(observation) != {"profile", "manifest_sha256", "operation_id"}
        or any(not isinstance(value, str) for value in observation.values())
    ):
        raise ValueError("Music requires its exact prepared environment observation")
    return music_environment.resolve(root, observation)


def public_observation(observation):
    return {
        "profile": observation["profile"],
        "manifest_sha256": observation["manifest_sha256"],
        "environment_id": music_environment.fingerprint(observation),
    }


def active(root):
    root = Path(root).resolve(strict=True)
    return resolve(root, read_json(root / "runtime/music-environments/active.json"))


def remember(root, observation):
    from ai_station_runner.runtime_install import atomic_json

    resolve(root, observation)
    public = public_observation(observation)
    folder = music_environment.directory(Path(root).resolve() / "runtime", "music-environments/identities")
    path = folder / (public["environment_id"] + ".json")
    if path.exists() or path.is_symlink():
        if read_json(path) != observation:
            raise ValueError("The managed music identity mapping changed")
    else:
        atomic_json(folder, path.name, observation)
    return public


def before_adoption(root, observation):
    # Preserve an older activated environment before replacing its active pointer.
    # Existing shared bindings can then outlive a later explicit preparation.
    try:
        previous = active(root)["observation"]
    except (OSError, ValueError, KeyError):
        previous = None
    if previous is not None:
        remember(root, previous)
    remember(root, observation)


def resolve_public(root, observation):
    if (
        not isinstance(observation, dict)
        or set(observation) != {"profile", "manifest_sha256", "environment_id"}
        or not isinstance(observation["environment_id"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", observation["environment_id"])
    ):
        raise ValueError("Music requires its exact opaque engine identity")
    root = Path(root).resolve(strict=True)
    path = root / "runtime/music-environments/identities" / (observation["environment_id"] + ".json")
    try:
        identity = read_json(path)
    except FileNotFoundError:
        # Read-only compatibility for an engine activated before opaque identities.
        selected = active(root)
        if public_observation(selected["observation"]) != observation:
            raise ValueError("The selected music environment identity is unavailable") from None
        return selected
    if public_observation(identity) != observation:
        raise ValueError("The managed music environment identity changed")
    return resolve(root, identity)

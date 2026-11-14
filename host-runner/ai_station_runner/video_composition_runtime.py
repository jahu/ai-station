"""Closed offline resolution for CPU composition, independent of the Runner API."""


def resolve_public(root, observation):
    if not isinstance(observation, dict):
        raise ValueError("Composition requires its exact prepared runtime identity")
    if observation.get("profile") == "wan22-svi-pro-q4-linux-x86-64-python312-v1":
        from ai_station_runner.svi_environment import resolve_public as resolve
    elif observation.get("profile") == "wan22-5b-linux-x86-64-python312-v1":
        from ai_station_runner.video_environment import resolve_public as resolve
    else:
        raise ValueError("Unsupported prepared composition runtime profile")
    return resolve(root, observation)
